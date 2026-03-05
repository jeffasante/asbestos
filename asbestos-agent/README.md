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
     ├── Agent Loop (multi-turn tool calling)
     │     └── llama-server (localhost:8776)
     │
     └── Tool Executor
           ├── shell_exec  — run terminal commands
           ├── file_rw     — read/write files
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

When a destructive action is needed, the agent will ask you in the chat:

> ⚠️ I need your approval to run: `rm -rf /tmp/old`. Reply **yes** to confirm.

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
