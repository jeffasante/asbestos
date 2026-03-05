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
import os
import subprocess
from pathlib import Path
from typing import Any

from config import SAFE_COMMAND_PREFIXES, AUTONOMOUS

# ── Pending confirmations store ───────────────────────────────────────
# Maps request_id → { "tool": ..., "args": ..., "description": ... }
_pending_confirmations: dict[str, dict[str, Any]] = {}


def get_pending() -> dict[str, dict[str, Any]]:
    return _pending_confirmations


def pop_pending(request_id: str) -> dict[str, Any] | None:
    return _pending_confirmations.pop(request_id, None)


# ── Safety checker ────────────────────────────────────────────────────
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


# ── Tool: shell_exec ──────────────────────────────────────────────────
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
            "message": f"⚠️  I need your approval to run this command:\n```\n{command}\n```\nReply **yes** to confirm.",
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


# ── Tool: file_rw ────────────────────────────────────────────────────
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
        try:
            text = resolved.read_text(errors="replace")
            # Truncate very large files
            if len(text) > 20_000:
                text = text[:20_000] + f"\n\n... [truncated, total {len(text)} chars]"
            return {"status": "ok", "path": str(resolved), "content": text}
        except FileNotFoundError:
            return {"status": "error", "message": f"File not found: {resolved}"}
        except Exception as e:
            return {"status": "error", "message": str(e)}

    # Write — needs confirmation
    if not AUTONOMOUS:
        conf_id = request_id or os.urandom(8).hex()
        preview = content[:500] + "..." if len(content) > 500 else content
        _pending_confirmations[conf_id] = {
            "tool": "file_rw",
            "args": {"path": path, "content": content},
            "description": f"Write to `{path}`",
        }
        return {
            "status": "confirmation_required",
            "confirmation_id": conf_id,
            "message": (
                f"⚠️  I need your approval to write to `{resolved}`:\n"
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


# ── Tool: os_action ───────────────────────────────────────────────────
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
    if action_type == "open":
        try:
            proc = await asyncio.create_subprocess_exec(
                "open", payload,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            await proc.communicate()
            return {"status": "ok", "action": "open", "target": payload}
        except Exception as e:
            return {"status": "error", "message": str(e)}

    elif action_type == "notify":
        script = (
            f'display notification "{payload}" with title "Asbestos Agent"'
        )
        try:
            proc = await asyncio.create_subprocess_exec(
                "osascript", "-e", script,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            await proc.communicate()
            return {"status": "ok", "action": "notify", "message": payload}
        except Exception as e:
            return {"status": "error", "message": str(e)}

    return {"status": "error", "message": f"Unknown action type: {action_type}"}


# ── Tool registry (OpenAI function-calling format) ────────────────────
TOOL_DEFINITIONS = [
    {
        "type": "function",
        "function": {
            "name": "shell_exec",
            "description": (
                "Execute a shell command on the local machine and return "
                "stdout, stderr, and exit code.  Use for system info, "
                "file listings, git operations, running scripts, etc."
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
                "Read or write a file.  To read, provide only 'path'.  "
                "To write, also provide 'content'.  Paths may use ~ for home."
                "Read or write a file.  When writing, missing parent directories ARE created automatically.  "
                "To read, provide only 'path'.  To write, also provide 'content'.  Paths may use ~ for home."
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
                        "description": "Content to write.  Omit to read.",
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
]


# ── Dispatcher ────────────────────────────────────────────────────────
TOOL_MAP = {
    "shell_exec": shell_exec,
    "file_rw": file_rw,
    "os_action": os_action,
}


async def execute_tool(name: str, arguments: dict[str, Any], request_id: str | None = None) -> str:
    """Dispatch a tool call and return the result as a JSON string."""
    fn = TOOL_MAP.get(name)
    if fn is None:
        return json.dumps({"status": "error", "message": f"Unknown tool: {name}"})

    # Inject request_id for confirmation tracking
    if "request_id" in fn.__code__.co_varnames:
        arguments["request_id"] = request_id

    result = await fn(**arguments)
    return json.dumps(result, ensure_ascii=False)
