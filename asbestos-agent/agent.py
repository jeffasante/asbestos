"""
Asbestos Agent — Agent Loop

Implements the multi-turn tool-calling agent loop:
  1. Send user message + tool defs to llama-server (OpenAI-compatible)
  2. If model returns tool_calls → execute them → append results → loop
  3. If model returns text → return final answer
"""

from __future__ import annotations

import json
import logging
import time
import platform
import getpass
from pathlib import Path
from typing import Any, AsyncGenerator

import httpx

from config import LLAMA_HOST, LLAMA_PORT, MAX_AGENT_LOOPS, LLAMA_N_PREDICT
from tools import TOOL_DEFINITIONS, execute_tool

logger = logging.getLogger("asbestos.agent")

LLAMA_BASE = f"http://{LLAMA_HOST}:{LLAMA_PORT}"
SYSTEM_PROMPT = f"""\
You are Asbestos, a helpful AI assistant on {platform.system()} (User: {getpass.getuser()}, Home: {Path.home()}).

RULE 1: When the user asks a question about their machine (files, uptime, disk, etc.), use shell_exec to get the answer, then REPLY WITH THE RESULT AS TEXT. Do NOT write results to files.
RULE 2: Only use file_rw to write a file if the user explicitly says "create a file", "save to", or "write a file".
RULE 3: For general knowledge questions (trivia, coding help, poems), answer directly without tools.
RULE 4: Never delete files. Never use rm or rmdir.

COMMANDS (use these exact commands):
- Desktop files: shell_exec(command="ls -la {Path.home()}/Desktop")
- Uptime: shell_exec(command="uptime")
- System specs: shell_exec(command="sysctl hw.model machdep.cpu.brand_string hw.memsize && sw_vers")
- Disk space: shell_exec(command="df -h /")
- Open URL: os_action(action_type="open", payload="https://example.com")
- Notification: os_action(action_type="notify", payload="Your message")
- Asbestos repo: os_action(action_type="open", payload="https://github.com/jeffasante/asbestos/tree/main/asbestos-agent")
"""

# Keywords that indicate the user wants a LOCAL system action (tools needed).
# If none of these appear in the latest user message, we skip sending tools
# entirely — the small model can't reliably decide on its own.

# Unambiguous keywords — if ANY of these appear, tools are needed.
_STRONG_TOOL_KEYWORDS = {
    # filesystem (unambiguous)
    "folder", "directory", "path", "rename", "ls", "cat",
    # system / hardware
    "disk", "storage", "ram", "cpu", "chip", "specs", "hardware",
    "process", "port", "network", "wifi", "bluetooth",
    # commands / actions
    "execute", "install", "brew", "pip", "npm", "git", "command",
    "terminal", "shell", "script", "scan", "monitor", "kill",
    # app-level
    "notification", "notify", "alert", "screenshot", "clipboard",
    "volume", "brightness", "battery",
    # explicit tool references
    "shell_exec", "file_rw", "os_action",
}

# Ambiguous keywords — only count if paired with a system-context word.
_WEAK_TOOL_KEYWORDS = {"file", "files", "write", "read", "save", "create",
                       "open", "copy", "move", "find", "check", "run", "list",
                       "memory", "system", "remind", "tool"}
_SYSTEM_CONTEXT_WORDS = {"file", "files", "folder", "disk", "directory",
                         "system", "server", "code", "log", "config", "txt",
                         "json", "csv", "py", "sh", "home", "desktop",
                         "downloads", "documents", "~/", "/"}


def _needs_tools(messages: list[dict]) -> bool:
    """Decide if the latest user message looks like it needs local tools.

    Uses a two-tier keyword system:
    - Strong keywords always trigger tools (e.g. "disk", "install", "terminal")
    - Weak keywords only trigger tools if accompanied by system-context words
      (e.g. "write" alone could mean "write a poem", but "write" + "file" = tools)
    """
    # Find the last user message
    last_user_text = ""
    for msg in reversed(messages):
        if msg.get("role") == "user":
            content = msg.get("content", "")
            if isinstance(content, str):
                last_user_text = content
            elif isinstance(content, list):
                last_user_text = " ".join(
                    p.get("text", "") for p in content
                    if isinstance(p, dict) and p.get("type") == "text"
                )
            break

    words = set(last_user_text.lower().split())
    text_lower = last_user_text.lower()

    # Strong match — always needs tools
    if words & _STRONG_TOOL_KEYWORDS:
        return True

    # File path detected — always needs tools
    # Catches "save it to /Users/jeff/..." or "write to ~/notes.txt"
    if any(w.startswith('/') or w.startswith('~/') for w in words):
        return True
    if any(ext in text_lower for ext in ['.txt', '.py', '.sh', '.json', '.csv', '.md', '.log']):
        return True

    # Weak match — only if system-context words are also present
    if words & _WEAK_TOOL_KEYWORDS and words & _SYSTEM_CONTEXT_WORDS:
        return True

    return False


async def _call_llama(
    messages: list[dict],
    stream: bool = False,
    use_tools: bool = True,
) -> httpx.Response:
    """Make a request to the local llama-server."""
    # Detect if any message contains image content.
    # llama-server doesn't support tools + images in the same request,
    # so we omit tools when images are present (vision-only mode).
    has_images = False
    for msg in messages:
        content = msg.get("content")
        if isinstance(content, list):
            for part in content:
                if isinstance(part, dict) and part.get("type") == "image_url":
                    has_images = True
                    break
        if has_images:
            break

    async with httpx.AsyncClient(timeout=120.0) as client:
        payload: dict[str, Any] = {
            "model": "local",
            "messages": messages,
            "max_tokens": LLAMA_N_PREDICT,
            "temperature": 0.7,
            "stream": stream,
        }
        if use_tools and not has_images:
            payload["tools"] = TOOL_DEFINITIONS

        return await client.post(
            f"{LLAMA_BASE}/v1/chat/completions",
            json=payload,
        )


async def run_agent_loop(
    messages: list[dict],
    request_id: str | None = None,
) -> dict[str, Any]:
    """
    Run the synchronous (non-streaming) agent loop.

    Returns an OpenAI-compatible response dict with the final assistant message,
    plus metadata about tool calls that were executed.
    """
    # Ensure system prompt is first
    if not messages or messages[0].get("role") != "system":
        messages = [{"role": "system", "content": SYSTEM_PROMPT}] + messages

    tool_trace: list[dict] = []
    loops = 0
    use_tools = _needs_tools(messages)
    logger.info("Tool gate: %s (use_tools=%s)", request_id, use_tools)

    while loops < MAX_AGENT_LOOPS:
        loops += 1
        t0 = time.time()

        try:
            resp = await _call_llama(messages, stream=False, use_tools=use_tools)
            resp.raise_for_status()
        except httpx.HTTPError as e:
            logger.error("llama-server request failed: %s", e)
            return _error_response(f"Inference backend error: {e}")

        data = resp.json()
        choice = data.get("choices", [{}])[0]
        msg = choice.get("message", {})
        finish = choice.get("finish_reason")

        elapsed = time.time() - t0
        logger.info("Loop %d  finish_reason=%s  (%.1fs)", loops, finish, elapsed)

        # ── Model wants to call tool(s) 
        tool_calls = msg.get("tool_calls")
        if tool_calls:
            # Append assistant message with tool calls
            messages.append(msg)

            for tc in tool_calls:
                fn_name = tc["function"]["name"]
                try:
                    fn_args = json.loads(tc["function"]["arguments"])
                except json.JSONDecodeError:
                    fn_args = {"_raw": tc["function"]["arguments"]}

                logger.info("  → tool: %s(%s)", fn_name, json.dumps(fn_args)[:200])

                result_str = await execute_tool(fn_name, fn_args, request_id)
                result_data = json.loads(result_str)

                tool_trace.append({
                    "tool": fn_name,
                    "args": fn_args,
                    "result": result_data,
                })

                # If confirmation required, break the loop early
                if result_data.get("status") == "confirmation_required":
                    # For small models, relaying the confirmation request often fails or returns empty content.
                    # We'll return the tool's message directly to ensure the user sees it.
                    return _build_response(
                        {"role": "assistant", "content": result_data["message"]},
                        tool_trace,
                    )

                # Append tool result
                messages.append({
                    "role": "tool",
                    "tool_call_id": tc["id"],
                    "content": result_str,
                })

            continue  # Next loop iteration

        # ── Model returned a text response — we're done ──────────────
        return _build_response(msg, tool_trace)

    # Max loops exceeded
    return _build_response(
        {
            "role": "assistant",
            "content": "I hit the maximum number of tool-calling iterations. "
                       "Here's what I've done so far — please let me know how to proceed.",
        },
        tool_trace,
    )


async def run_agent_loop_streaming(
    messages: list[dict],
    request_id: str | None = None,
) -> AsyncGenerator[str, None]:
    """
    Streaming variant — yields SSE-formatted chunks compatible with the
    OpenAI streaming protocol.  Tool call iterations are reported as
    status messages in the stream.
    """
    if not messages or messages[0].get("role") != "system":
        messages = [{"role": "system", "content": SYSTEM_PROMPT}] + messages

    loops = 0
    use_tools = _needs_tools(messages)

    while loops < MAX_AGENT_LOOPS:
        loops += 1

        try:
            resp = await _call_llama(messages, stream=False, use_tools=use_tools)
            resp.raise_for_status()
        except httpx.HTTPError as e:
            yield _sse_chunk(f"Error contacting inference backend: {e}")
            yield "data: [DONE]\n\n"
            return

        data = resp.json()
        choice = data.get("choices", [{}])[0]
        msg = choice.get("message", {})

        tool_calls = msg.get("tool_calls")
        if tool_calls:
            messages.append(msg)

            for tc in tool_calls:
                fn_name = tc["function"]["name"]
                try:
                    fn_args = json.loads(tc["function"]["arguments"])
                except json.JSONDecodeError:
                    fn_args = {"_raw": tc["function"]["arguments"]}

                # Stream a status update to the client
                yield _sse_chunk(f"Calling `{fn_name}({json.dumps(fn_args)[:120]})`...\n\n")

                result_str = await execute_tool(fn_name, fn_args, request_id)
                result_data = json.loads(result_str)

                if result_data.get("status") == "confirmation_required":
                    # Yield a special confirmation event so the client captures the ID
                    conf_id = result_data.get("confirmation_id", "")
                    conf_payload = json.dumps({
                        "type": "confirmation",
                        "id": conf_id,
                        "message": result_data["message"],
                    })
                    yield f"event: confirmation\ndata: {conf_payload}\n\n"
                    yield "data: [DONE]\n\n"
                    return

                messages.append({
                    "role": "tool",
                    "tool_call_id": tc["id"],
                    "content": result_str,
                })

            continue

        # Final text response — stream word-by-word for typing effect
        content = msg.get("content", "")
        words = content.split(' ')
        for i, word in enumerate(words):
            token = word if i == 0 else ' ' + word
            yield _sse_chunk(token)
        yield "data: [DONE]\n\n"
        return

    yield _sse_chunk("Maximum tool-calling iterations reached.")
    yield "data: [DONE]\n\n"


# ── Helpers ────────────────────────────

def _build_response(msg: dict, tool_trace: list[dict]) -> dict:
    return {
        "id": f"asbestos-{int(time.time())}",
        "object": "chat.completion",
        "model": "asbestos-local",
        "choices": [
            {
                "index": 0,
                "message": {
                    "role": msg.get("role", "assistant"),
                    "content": msg.get("content", ""),
                },
                "finish_reason": "stop",
            }
        ],
        "usage": {"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0},
        "_tool_trace": tool_trace,
    }


def _error_response(message: str) -> dict:
    return _build_response({"role": "assistant", "content": message}, [])


def _sse_chunk(content: str) -> str:
    """Format a single SSE data line in OpenAI-compatible format."""
    chunk = {
        "choices": [
            {
                "index": 0,
                "delta": {"content": content},
                "finish_reason": None,
            }
        ]
    }
    return f"data: {json.dumps(chunk)}\n\n"
