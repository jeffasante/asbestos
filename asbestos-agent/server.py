"""
Asbestos Agent — HTTP Server

OpenAI-compatible API served via FastAPI.
Designed to sit behind a VS Code Dev Tunnel for remote access.

Endpoints:
  POST /v1/chat/completions   — main chat endpoint (streaming & non-streaming)
  GET  /v1/models             — list available models
  GET  /health                — server health check
  POST /confirm/{id}          — approve a pending destructive action
  GET  /pending               — list pending confirmations
"""

from __future__ import annotations

import json
import logging
import os
import signal
import subprocess
import sys
import time
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any

from fastapi import FastAPI, HTTPException, Request
from fastapi.staticfiles import StaticFiles
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse, JSONResponse, HTMLResponse, FileResponse
from pydantic import BaseModel, Field

from config import (
    AGENT_HOST,
    AGENT_PORT,
    LLAMA_HOST,
    LLAMA_PORT,
    LLAMA_CTX_SIZE,
    LLAMA_SERVER_BIN,
    LLAMA_LIB_DIR,
    MODEL_PATH,
    MMPROJ_PATH,
)
from agent import run_agent_loop, run_agent_loop_streaming
from tools import get_pending, pop_pending, execute_tool

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(name)-20s  %(levelname)-7s  %(message)s",
)
logger = logging.getLogger("asbestos.server")

# ── llama-server child process ────────────────────────────────────────
_llama_proc: subprocess.Popen | None = None


def _start_llama_server() -> subprocess.Popen:
    """Launch the llama-server as a child process."""
    if not LLAMA_SERVER_BIN.exists():
        logger.error("llama-server binary not found at %s", LLAMA_SERVER_BIN)
        sys.exit(1)
    if not MODEL_PATH.exists():
        logger.error("Model not found at %s", MODEL_PATH)
        sys.exit(1)

    env = os.environ.copy()
    env["DYLD_LIBRARY_PATH"] = str(LLAMA_LIB_DIR)

    cmd = [
        str(LLAMA_SERVER_BIN),
        "-m", str(MODEL_PATH),
        "--host", LLAMA_HOST,
        "--port", str(LLAMA_PORT),
        "-c", str(LLAMA_CTX_SIZE),
        "-n", str(1024),
        "--flash-attn", "auto",
    ]
    
    if MMPROJ_PATH.exists():
        cmd.extend(["--mmproj", str(MMPROJ_PATH)])

    logger.info("Starting llama-server: %s", " ".join(cmd))
    proc = subprocess.Popen(
        cmd,
        env=env,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
    )
    return proc


def _stop_llama_server():
    global _llama_proc
    if _llama_proc and _llama_proc.poll() is None:
        logger.info("Stopping llama-server (pid %d)...", _llama_proc.pid)
        _llama_proc.terminate()
        try:
            _llama_proc.wait(timeout=10)
        except subprocess.TimeoutExpired:
            _llama_proc.kill()
    _llama_proc = None


async def _wait_for_llama(timeout: float = 60):
    """Poll the health endpoint until llama-server is ready."""
    import httpx

    start = time.time()
    url = f"http://{LLAMA_HOST}:{LLAMA_PORT}/health"
    async with httpx.AsyncClient() as client:
        while time.time() - start < timeout:
            try:
                r = await client.get(url, timeout=2)
                if r.status_code == 200:
                    data = r.json()
                    if data.get("status") == "ok":
                        logger.info("llama-server is ready ✓")
                        return
            except Exception:
                pass
            import asyncio
            await asyncio.sleep(1)
    raise RuntimeError("llama-server failed to start within timeout")


# ── FastAPI app ───────────────────────────────────────────────────────

@asynccontextmanager
async def lifespan(app: FastAPI):
    global _llama_proc
    _llama_proc = _start_llama_server()
    try:
        await _wait_for_llama()
    except RuntimeError as e:
        logger.error(str(e))
        _stop_llama_server()
        sys.exit(1)
    yield
    _stop_llama_server()


app = FastAPI(
    title="Asbestos Agent",
    description="Local AI agent with tool execution, OpenAI-compatible API.",
    version="0.1.0",
    lifespan=lifespan,
)

# Serve static files (chat UI)
STATIC_DIR = Path(__file__).parent / "static"
if STATIC_DIR.exists():
    app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# ── Models ────────────────────────────────────────────────────────────

class ChatMessage(BaseModel):
    role: str
    content: str | list[Any] | None = None
    tool_calls: list[Any] | None = None
    tool_call_id: str | None = None


class ChatRequest(BaseModel):
    model: str = "asbestos-local"
    messages: list[ChatMessage]
    stream: bool = False
    temperature: float | None = None
    max_tokens: int | None = None
    tools: list[Any] | None = None  # ignored — we use our own


# ── Routes ────────────────────────────────────────────────────────────

@app.get("/chat")
async def chat_ui():
    """Serve the built-in chat interface."""
    chat_file = Path(__file__).parent / "static" / "chat.html"
    if not chat_file.exists():
        raise HTTPException(404, "Chat UI not found")
    return FileResponse(str(chat_file), media_type="text/html")


@app.get("/health")
async def health():
    return {"status": "ok", "agent": "asbestos", "timestamp": int(time.time())}


@app.get("/v1/models")
async def list_models():
    return {
        "object": "list",
        "data": [
            {
                "id": "asbestos-local",
                "object": "model",
                "owned_by": "local",
                "created": int(time.time()),
            }
        ],
    }


@app.post("/v1/chat/completions")
async def chat_completions(req: ChatRequest):
    messages = [m.model_dump(exclude_none=True) for m in req.messages]
    request_id = f"req-{int(time.time() * 1000)}"

    if req.stream:
        return StreamingResponse(
            run_agent_loop_streaming(messages, request_id),
            media_type="text/event-stream",
            headers={
                "Cache-Control": "no-cache",
                "Connection": "keep-alive",
                "X-Accel-Buffering": "no",
            },
        )

    result = await run_agent_loop(messages, request_id)
    return JSONResponse(result)


@app.get("/pending")
async def list_pending():
    """List all pending tool-call confirmations."""
    pending = get_pending()
    return {
        "count": len(pending),
        "pending": {
            k: {"description": v["description"], "tool": v["tool"]}
            for k, v in pending.items()
        },
    }


@app.post("/confirm/{confirmation_id}")
async def confirm_action(confirmation_id: str):
    """Approve a pending destructive action."""
    entry = pop_pending(confirmation_id)
    if entry is None:
        raise HTTPException(404, f"No pending confirmation with id '{confirmation_id}'")

    from config import AUTONOMOUS as _
    # Temporarily force execution by calling the tool directly
    import tools
    original = tools.AUTONOMOUS
    tools.AUTONOMOUS = True
    try:
        result_str = await execute_tool(
            entry["tool"],
            entry["args"],
        )
    finally:
        tools.AUTONOMOUS = original

    return JSONResponse(json.loads(result_str))


# ── Entry point ───────────────────────────────────────────────────────

if __name__ == "__main__":
    import uvicorn

    logger.info("Starting Asbestos Agent on %s:%d", AGENT_HOST, AGENT_PORT)
    logger.info("Forward this port in VS Code to get a public URL!")
    uvicorn.run(
        "server:app",
        host=AGENT_HOST,
        port=AGENT_PORT,
        log_level="warning",
    )
