"""
Asbestos Agent — Configuration
"""

import os
from pathlib import Path

# ── Paths ──────────────────────────────────────────────────────────────
PROJECT_ROOT = Path(__file__).resolve().parent.parent          # asbestos/
LLAMA_CPP_DIR = PROJECT_ROOT / "llama.cpp"
LLAMA_SERVER_BIN = LLAMA_CPP_DIR / "build" / "bin" / "llama-server"
LLAMA_LIB_DIR = LLAMA_CPP_DIR / "build" / "bin"               # for DYLD_LIBRARY_PATH

MODEL_PATH = PROJECT_ROOT / "Qwen_Qwen3.5-0.8B-Q8_0.gguf"
MMPROJ_PATH = PROJECT_ROOT / "mmproj-Qwen_Qwen3.5-0.8B-bf16.gguf"

# ── Llama-server settings ─────────────────────────────────────────────
LLAMA_HOST = os.getenv("LLAMA_HOST", "127.0.0.1")
LLAMA_PORT = int(os.getenv("LLAMA_PORT", "8776"))              # internal port
LLAMA_CTX_SIZE = int(os.getenv("LLAMA_CTX_SIZE", "4096"))
LLAMA_N_PREDICT = int(os.getenv("LLAMA_N_PREDICT", "1024"))

# ── Agent HTTP server ────────────────────────────────────────────────
AGENT_HOST = os.getenv("AGENT_HOST", "0.0.0.0")
AGENT_PORT = int(os.getenv("AGENT_PORT", "8765"))              # VS Code tunnel target

# ── Safety ────────────────────────────────────────────────────────────
# Commands matching any of these patterns are considered read-only (auto-approved)
SAFE_COMMAND_PREFIXES = [
    "ls", "cat", "head", "tail", "wc", "echo", "pwd", "whoami",
    "date", "uptime", "df", "du", "file", "find", "grep", "which",
    "env", "printenv", "uname", "sw_vers", "sysctl", "ps", "top -l1",
    "lsof", "stat", "md5", "shasum", "xxd", "hexdump",
]

# Max agent loop iterations (prevents infinite tool-calling loops)
MAX_AGENT_LOOPS = int(os.getenv("MAX_AGENT_LOOPS", "10"))

# Autonomous mode — if True, all commands run without confirmation
AUTONOMOUS = os.getenv("AUTONOMOUS", "false").lower() == "true"
