# 🧶 Asbestos Agent

A local AI agent with tool execution, accessible from anywhere via tunneled HTTPS.

Runs **llama.cpp** inference entirely on your machine while exposing an **OpenAI-compatible API** that you can reach from your phone, browser, or any chat frontend via a public tunnel.

## Architecture

```
[You, anywhere]
     │
     ▼
Public Tunnel (cloudflared / VS Code / ngrok)
     │  HTTPS
     ▼
asbestos-agent (FastAPI)  ←── http://localhost:8765
     │
     ├── Agent Loop (multi-turn tool calling + VLM)
     │     └── llama-server (localhost:8776)
     │
     └── Tool Executor
           ├── shell_exec  — run terminal commands
           ├── file_rw     — read/write files (smart mkdir -p)
           └── os_action   — open URLs, send notifications
```

## Installation & Quick Start

```bash
# 1. Enter the agent directory
cd asbestos-agent

# 2. Run the install script (downloads model, sets up python venv, installs cloudflared)
./install.sh

# 3. Start the agent with a public tunnel (pick one):
./start.sh --tunnel cloudflare   # Free, no account needed (recommended)
./start.sh --tunnel ngrok        # Requires ngrok account
./start.sh --tunnel vscode       # Shows VS Code instructions
```

Fully autonomous mode (skips confirmation for destructive commands):

```bash
./start.sh --autonomous
```

Then visit **http://localhost:8765/chat** for the built-in chat UI.

## API

The agent exposes a standard **OpenAI `/v1/chat/completions`** endpoint:

```bash
curl http://localhost:8765/v1/chat/completions \
  -H "Content-Type: application/json" \
  -d '{
    "model": "asbestos-local",
    "messages": [{"role": "user", "content": "What files are on my Desktop?"}]
  }'
```

This means you can use it with **any OpenAI-compatible client** — just set the base URL to your tunnel address.

### Multimodal (VLM) Support

The agent supports **image analysis**. You can send images via the OpenAI-compatible API using `image_url` content blocks, or simply drag-and-drop an image into the built-in Chat UI.

### Smart File Writing

The `file_rw` tool is designed for autonomous resilience:

- **Auto-mkdir**: Missing parent directories are created automatically (`mkdir -p`) during write operations.
- **Smart Feedback**: If you try to read a non-existent file, the agent receives a hint to "create it first," preventing loops.
- **Directory Listing**: If `file_rw` is called on a directory, it returns a listing of the contents instead of an error.

### Endpoints

| Method | Path                   | Description                                  |
| ------ | ---------------------- | -------------------------------------------- |
| `POST` | `/v1/chat/completions` | Chat completions (streaming & non-streaming) |
| `GET`  | `/v1/models`           | List available models                        |
| `GET`  | `/chat`                | Built-in chat web UI                         |
| `GET`  | `/health`              | Server health check                          |
| `GET`  | `/pending`             | List pending confirmations                   |
| `POST` | `/confirm/{id}`        | Approve a destructive action                 |
| `GET`  | `/docs`                | Interactive API docs (Swagger)               |

## Safety

By default, the agent uses **human-in-the-loop** safety:

- **Read-only commands** (`ls`, `cat`, `df`, `ps`, etc.) execute automatically
- **Destructive commands** (`rm`, `kill`, `git push`, etc.) require your confirmation
- **File writes** require your confirmation

### Confirmation System

When a destructive action or file-write is requested, the server:

1. Returns a `confirmation_required` status with a unique `confirmation_id`.
2. Includes a preview of the changes in the tool result.
3. The Chat UI intercepts this and prompts you for approval.
4. Replying **yes** in the Chat UI automatically triggers a `POST /confirm/{id}` call to execute the action.

To disable safety (use at your own risk):

```bash
./start.sh --autonomous
```

## Tunneling Options

| Option                  | Account Needed     | Install                    |
| ----------------------- | ------------------ | -------------------------- |
| **Cloudflare Tunnel**   | ❌ No              | `brew install cloudflared` |
| **VS Code Dev Tunnels** | GitHub account     | Built into VS Code         |
| **ngrok**               | ✅ Yes (free tier) | `brew install ngrok`       |

## Configuration

Environment variables (all optional):

| Variable          | Default | Description                           |
| ----------------- | ------- | ------------------------------------- |
| `AGENT_PORT`      | `8765`  | Port for the agent HTTP server        |
| `LLAMA_PORT`      | `8776`  | Internal port for llama-server        |
| `LLAMA_CTX_SIZE`  | `4096`  | Context window size                   |
| `MAX_AGENT_LOOPS` | `10`    | Max tool-calling iterations           |
| `AUTONOMOUS`      | `false` | Skip destructive action confirmations |

## File Structure

```
asbestos-agent/
├── install.sh         # Installation script (models, dependencies, cloudflared)
├── start.sh           # Entry point — starts everything including the tunnel
├── server.py          # FastAPI HTTP server + llama-server lifecycle
├── agent.py           # Agent loop (tool calling + LLM orchestration)
├── tools.py           # Tool definitions & executors
├── config.py          # Configuration & safety settings
├── requirements.txt   # Python dependencies
└── static/
    └── chat.html      # Built-in web chat UI
```
