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
from typing import Any, AsyncGenerator

import httpx

from config import LLAMA_HOST, LLAMA_PORT, MAX_AGENT_LOOPS, LLAMA_N_PREDICT
from tools import TOOL_DEFINITIONS, execute_tool

logger = logging.getLogger("asbestos.agent")

LLAMA_BASE = f"http://{LLAMA_HOST}:{LLAMA_PORT}"

SYSTEM_PROMPT = """\
You are Asbestos, a secure and highly capable local AI agent running on macOS.
You have direct access to tools: shell_exec, file_rw, and os_action.

CORE OBJECTIVES:
1. BE PROACTIVE: If the user asks for information (disk, specs, files), EXECUTE a tool. Do NOT guess or just explain how.
2. BE ACCURATE: Always fact-check your responses against tool outputs.
3. BE HELPFUL: You are a personal assistant. You can write stories, take notes, and manage the local workspace.

SAFETY & CONSTRAINTS:
- NEVER delete files or directories. `rm` and `rmdir` are strictly forbidden.
- Always ask for confirmation before overwriting important-looking files.
- If a command fails, analyze the error and try a different approach.

HARDWARE & SYSTEM FACT-CHECKING:
- To get system specs, call: `shell_exec(command="sysctl hw.model machdep.cpu.brand_string hw.memsize && sw_vers")`.
- hw.memsize is in BYTES. Calculate GB: (bytes / 1024^3). Ensure you report the correct M-series chip (M1, M2, M3, M4).
- To check disk space, call: `shell_exec(command="df -h")`.

VISION CAPABILITIES:
- You have multimodal support. When images are provided, analyze them carefully to answer questions or perform tasks based on visual input.

PERSONAL TASKS & USE CASES:
- SMART HOME & FAMILY: You can act as a Home Project Manager—researching topics, managing tasks, or sending roundup notifications via `os_action`.
- CREATIVE: Help with writing poems, stories, meal planning (creating Notion-style lists), drafting family newsletters, or creating fun activities like dynamic MadLibs for kids.
- PRODUCTIVITY: Help with developer tasks, summarizing local files, or organizing workspace folders.
- PERSISTENCE: To "remember" things across sessions, write notes to a specific `~/asbestos_knowledge/` folder using `file_rw`.

Environment: macOS
"""


async def _call_llama(
    messages: list[dict],
    stream: bool = False,
) -> httpx.Response:
    """Make a request to the local llama-server."""
    async with httpx.AsyncClient(timeout=120.0) as client:
        payload: dict[str, Any] = {
            "model": "local",
            "messages": messages,
            "tools": TOOL_DEFINITIONS,
            "max_tokens": LLAMA_N_PREDICT,
            "temperature": 0.7,
            "stream": stream,
        }
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

    while loops < MAX_AGENT_LOOPS:
        loops += 1
        t0 = time.time()

        try:
            resp = await _call_llama(messages, stream=False)
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

        # ── Model wants to call tool(s) ───────────────────────────────
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

    while loops < MAX_AGENT_LOOPS:
        loops += 1

        try:
            resp = await _call_llama(messages, stream=False)
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
                    # Directly yield the confirmation message and finish the stream
                    yield _sse_chunk(result_data["message"])
                    yield "data: [DONE]\n\n"
                    return

                messages.append({
                    "role": "tool",
                    "tool_call_id": tc["id"],
                    "content": result_str,
                })

            continue

        # Final text response
        content = msg.get("content", "")
        yield _sse_chunk(content)
        yield "data: [DONE]\n\n"
        return

    yield _sse_chunk("Maximum tool-calling iterations reached.")
    yield "data: [DONE]\n\n"


# ── Helpers ───────────────────────────────────────────────────────────

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
