"""
Asbestos Agent — Tool Definitions & Executor

Three tools available to the LLM:
  1. shell_exec   — run a shell command, return stdout/stderr
  2. file_rw      — read or write a file
  3. os_action    — open URLs/apps, send notifications
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import subprocess
from pathlib import Path
from typing import Any

from config import SAFE_COMMAND_PREFIXES, AUTONOMOUS
from insight import analyze_file, get_project_context

# ── Pending confirmations store
# Maps request_id → { "tool": ..., "args": ..., "description": ... }
_pending_confirmations: dict[str, dict[str, Any]] = {}


def get_pending() -> dict[str, dict[str, Any]]:
    return _pending_confirmations


def pop_pending(request_id: str) -> dict[str, Any] | None:
    return _pending_confirmations.pop(request_id, None)


# ── Safety checker
def _is_safe_command(cmd: str) -> bool:
    """Return True if the command is considered read-only."""
    if AUTONOMOUS:
        return True
    
    stripped = cmd.strip().lower()
    
    # Hard Blacklist (triggers confirmation even if prefixed with something "safe")
    blacklist = ["rm ", "rmdir ", "mkfs", "dd ", "> /", "mv "]
    for bad in blacklist:
        if bad in stripped:
            return False

    # Whitelist check
    for prefix in SAFE_COMMAND_PREFIXES:
        if stripped == prefix or stripped.startswith(prefix + " "):
            return True
            
    return False


# ── Tool: shell_exec 
async def shell_exec(command: str, request_id: str | None = None) -> dict[str, Any]:
    """
    Execute a shell command.  If the command looks destructive and we are
    not in autonomous mode, return a confirmation request instead.
    """
    if not _is_safe_command(command):
        # Needs human confirmation
        conf_id = request_id or os.urandom(8).hex()
        _pending_confirmations[conf_id] = {
            "tool": "shell_exec",
            "args": {"command": command},
            "description": f"Run: `{command}`",
        }
        return {
            "status": "confirmation_required",
            "confirmation_id": conf_id,
            "message": f"I need your approval to run this command:\n```\n{command}\n```\nReply **yes** to confirm.",
        }

    try:
        proc = await asyncio.create_subprocess_shell(
            command,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            cwd=str(Path.home()),
        )
        stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=30)
        return {
            "status": "ok",
            "exit_code": proc.returncode,
            "stdout": stdout.decode(errors="replace")[:8000],
            "stderr": stderr.decode(errors="replace")[:2000],
        }
    except asyncio.TimeoutError:
        return {"status": "error", "message": "Command timed out after 30 seconds."}
    except Exception as e:
        return {"status": "error", "message": str(e)}


# ── Tool: file_rw
async def file_rw(
    path: str,
    content: str | None = None,
    request_id: str | None = None,
) -> dict[str, Any]:
    """
    Read a file (content=None) or write to a file (content=string).
    Writes require confirmation unless in autonomous mode.
    """
    resolved = Path(path).expanduser().resolve()

    # Read
    if content is None:
        if not resolved.exists():
            return {
                "status": "ok",
                "path": str(resolved),
                "type": "not_found",
                "content": f"Path does not exist yet. To create it, call file_rw again with path='{path}' and content='your content here'.",
            }

        if resolved.is_dir():
            files = [f.name + ("/" if f.is_dir() else "") for f in resolved.iterdir()]
            return {
                "status": "ok",
                "path": str(resolved),
                "type": "directory",
                "content": "\n".join(files) if files else "(empty directory)",
            }

        try:
            text = resolved.read_text(errors="replace")
            if len(text) > 20_000:
                text = text[:20_000] + f"\n\n... [truncated, total {len(text)} chars]"
            return {"status": "ok", "path": str(resolved), "type": "file", "content": text}
        except Exception as e:
            return {"status": "error", "message": f"Could not read {resolved}: {e}"}

    # Write — reject if target is an existing directory
    if resolved.is_dir():
        return {
            "status": "error",
            "message": f"Cannot write to '{resolved}': it is a directory, not a file. To list its contents, call file_rw without 'content', or use shell_exec with 'ls -la {resolved}'.",
        }

    # Write — needs confirmation
    if not AUTONOMOUS:
        conf_id = request_id or os.urandom(8).hex()
        
        # Guard against non-string content (hallucinations)
        if not isinstance(content, str):
            content = json.dumps(content, indent=2)

        preview = content[:500] + ("..." if len(content) > 500 else "")
        _pending_confirmations[conf_id] = {
            "tool": "file_rw",
            "args": {"path": path, "content": content},
            "description": f"Write to `{path}`",
        }
        return {
            "status": "confirmation_required",
            "confirmation_id": conf_id,
            "message": (
                f"I need your approval to write to `{resolved}`:\n"
                f"```\n{preview}\n```\n"
                f"Reply **yes** to confirm."
            ),
        }

    try:
        resolved.parent.mkdir(parents=True, exist_ok=True)
        resolved.write_text(content)
        return {"status": "ok", "path": str(resolved), "bytes_written": len(content)}
    except Exception as e:
        return {"status": "error", "message": str(e)}


# ── Tool: os_action 
async def os_action(
    action_type: str,
    payload: str = "",
    request_id: str | None = None,
) -> dict[str, Any]:
    """
    OS-level actions:
      - "open"   : open a URL or file with the default handler
      - "notify" : send a macOS notification
    """
    logger = logging.getLogger("asbestos.tools")

    if action_type == "open":
        try:
            logger.info("os_action open: %s", payload)
            proc = await asyncio.create_subprocess_exec(
                "open", payload,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=10)
            if proc.returncode != 0:
                err = stderr.decode(errors="replace").strip()
                logger.error("os_action open failed (rc=%d): %s", proc.returncode, err)
                return {"status": "error", "message": f"open failed: {err}"}
            return {"status": "ok", "action": "open", "target": payload}
        except asyncio.TimeoutError:
            return {"status": "error", "message": "open command timed out."}
        except Exception as e:
            return {"status": "error", "message": str(e)}

    elif action_type == "notify":
        # Sanitize payload to prevent AppleScript injection
        safe_payload = payload.replace('"', '\\"').replace("'", "\\'")
        script = (
            f'display notification "{safe_payload}" with title "Asbestos Agent"'
        )
        try:
            logger.info("os_action notify: %s", payload)
            proc = await asyncio.create_subprocess_exec(
                "osascript", "-e", script,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=10)
            if proc.returncode != 0:
                err = stderr.decode(errors="replace").strip()
                logger.error("os_action notify failed (rc=%d): %s", proc.returncode, err)
                return {"status": "error", "message": f"Notification failed: {err}"}
            return {"status": "ok", "action": "notify", "message": payload}
        except asyncio.TimeoutError:
            return {"status": "error", "message": "Notification command timed out."}
        except Exception as e:
            return {"status": "error", "message": str(e)}

    return {"status": "error", "message": f"Unknown action type: {action_type}"}


# ── Tool: project_insight
async def project_insight(
    file_path: str,
    request_id: str | None = None,
) -> dict[str, Any]:
    """
    Generate pseudocode and architectural explanation for a source file.
    Returns structured insight with intent, pseudocode, and context.
    """
    logger = logging.getLogger("asbestos.tools")
    logger.info("project_insight: analyzing %s", file_path)
    
    # Get project context from the file's parent directory
    from pathlib import Path as _Path
    parent = _Path(file_path).resolve().parent
    context = get_project_context(parent)
    
    result = await analyze_file(file_path, project_context=context)
    
    if result["status"] == "ok":
        return {
            "status": "ok",
            "file": result["name"],
            "insight": result["insight"],
        }
    return {
        "status": "error",
        "message": result.get("error", "Unknown error analyzing file"),
    }


# ── Tool registry (OpenAI function-calling format) 
TOOL_DEFINITIONS = [
    {
        "type": "function",
        "function": {
            "name": "shell_exec",
            "description": (
                "Execute a shell command on the local machine and return "
                "stdout, stderr, and exit code. "
                "Examples: 'ls -la ~/Desktop' (list desktop files), "
                "'uptime' (system uptime), 'df -h /' (disk space), "
                "'date' (current time), 'ps aux | head -20' (processes). "
                "Do NOT use this to write or save files — use file_rw instead."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "command": {
                        "type": "string",
                        "description": "The shell command to execute.",
                    },
                },
                "required": ["command"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "file_rw",
            "description": (
                "Read or write a file. ALWAYS use this to save content to a file. "
                "To read: provide only 'path'. "
                "To write/save: provide both 'path' and 'content'. "
                "Missing parent directories are created automatically."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "path": {
                        "type": "string",
                        "description": "Absolute or ~-relative file path.",
                    },
                    "content": {
                        "type": "string",
                        "description": "Content to write. Omit to read.",
                    },
                },
                "required": ["path"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "os_action",
            "description": (
                "Perform an OS-level action.  Supported types: "
                "'open' (open URL/file/app), 'notify' (macOS notification)."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "action_type": {
                        "type": "string",
                        "enum": ["open", "notify"],
                        "description": "The type of action to perform.",
                    },
                    "payload": {
                        "type": "string",
                        "description": "URL/path for 'open', message text for 'notify'.",
                    },
                },
                "required": ["action_type", "payload"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "project_insight",
            "description": (
                "Analyze a source code file and generate pseudocode, "
                "architectural explanation, and contextual memory. "
                "Use this when the user asks to 'explain', 'understand', "
                "'analyze', or 'document' a file or code."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "file_path": {
                        "type": "string",
                        "description": "Absolute path to the source file to analyze.",
                    },
                },
                "required": ["file_path"],
            },
        },
    },
]


# ── Dispatcher────
TOOL_MAP = {
    "shell_exec": shell_exec,
    "file_rw": file_rw,
    "os_action": os_action,
    "project_insight": project_insight,
}


async def execute_tool(name: str, arguments: dict[str, Any], request_id: str | None = None) -> str:
    """Dispatch a tool call and return the result as a JSON string."""
    fn = TOOL_MAP.get(name)
    if fn is None:
        return json.dumps({"status": "error", "message": f"Unknown tool: {name}"})

    try:
        # Filter arguments to match function signature
        obj = fn
        if hasattr(fn, "__wrapped__"): # handle wrappers
            obj = fn.__wrapped__
        
        valid_args = obj.__code__.co_varnames[:obj.__code__.co_argcount]
        filtered_args = {k: v for k, v in arguments.items() if k in valid_args}

        # Inject request_id for confirmation tracking if needed
        if "request_id" in valid_args:
            filtered_args["request_id"] = request_id

        result = await fn(**filtered_args)
        return json.dumps(result, ensure_ascii=False)
    except Exception as e:
        logger.error(f"Error executing tool {name}: {e}", exc_info=True)
        return json.dumps({
            "status": "error", 
            "message": f"Execution error in {name}: {str(e)}"
        })
