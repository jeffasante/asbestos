#!/bin/bash
# ────────────────────────────────────────────────────────────────
#  Asbestos Agent — Start Script
#
#  Starts the agent server which auto-launches llama-server.
#
#  Tunneling options (pick one):
#    --tunnel cloudflare    Use cloudflared (free, no account needed)
#    --tunnel vscode        Use VS Code port forwarding (manual)
#    --tunnel ngrok         Use ngrok (requires account)
#
#  Other flags:
#    --autonomous           Skip confirmation for destructive commands
# ────────────────────────────────────────────────────────────────

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
cd "$SCRIPT_DIR"

# Cleanup old processes
pkill -f "cloudflared tunnel --url" 2>/dev/null || true
lsof -t -i:8765 | xargs kill -9 2>/dev/null || true
lsof -t -i:8776 | xargs kill -9 2>/dev/null || true

# Colors
GREEN='\033[0;32m'
CYAN='\033[0;36m'
YELLOW='\033[1;33m'
RED='\033[0;31m'
BOLD='\033[1m'
NC='\033[0m'

AGENT_PORT=${AGENT_PORT:-8765}
AUTONOMOUS="false"
TUNNEL_MODE=""

# Parse flags
while [[ $# -gt 0 ]]; do
    case $1 in
        --autonomous)
            AUTONOMOUS="true"
            shift
            ;;
        --tunnel)
            TUNNEL_MODE="$2"
            shift 2
            ;;
        --port)
            AGENT_PORT="$2"
            shift 2
            ;;
        *)
            echo "Unknown option: $1"
            exit 1
            ;;
    esac
done

echo -e "${CYAN}"
echo "  ╔══════════════════════════════════════════════╗"
echo "  ║          🧶 Asbestos Agent v0.1              ║"
echo "  ║    Local AI + Tool Execution + Web Access    ║"
echo "  ╚══════════════════════════════════════════════╝"
echo -e "${NC}"

# Check Python
if ! command -v python3 &> /dev/null; then
    echo -e "${RED}Error: python3 not found${NC}"
    exit 1
fi

# Create venv if needed
if [ ! -d ".venv" ]; then
    echo -e "${YELLOW}Creating virtual environment...${NC}"
    python3 -m venv .venv
fi

source .venv/bin/activate

# Install deps
echo -e "${YELLOW}Installing dependencies...${NC}"
pip install -q -r requirements.txt

# ── Tunnel setup ──────────────────────────────────────────────────
TUNNEL_PID=""

cleanup() {
    if [ -n "$TUNNEL_PID" ]; then
        echo -e "\n${YELLOW}Stopping tunnel (pid $TUNNEL_PID)...${NC}"
        kill "$TUNNEL_PID" 2>/dev/null || true
    fi
    exit 0
}
trap cleanup SIGINT SIGTERM

start_tunnel() {
    case "$TUNNEL_MODE" in
        cloudflare|cf)
            if ! command -v cloudflared &> /dev/null; then
                echo -e "${YELLOW}Installing cloudflared...${NC}"
                if command -v brew &> /dev/null; then
                    brew install cloudflared
                else
                    echo -e "${RED}Please install cloudflared: https://developers.cloudflare.com/cloudflare-one/connections/connect-networks/downloads/${NC}"
                    exit 1
                fi
            fi
            echo -e "${GREEN}Starting Cloudflare tunnel...${NC}"
            > .cf_tunnel.log # clear log
            cloudflared tunnel --url "http://localhost:${AGENT_PORT}" 2> .cf_tunnel.log &
            TUNNEL_PID=$!
            
            # Extract and display the URL clearly
            (
                echo -en "${CYAN}→ Establishing secure mobile connection...${NC} "
                
                # Check very frequently for low latency response
                for i in {1..300}; do
                    if [ -f .cf_tunnel.log ] && grep -q "\.trycloudflare\.com" .cf_tunnel.log; then
                        URL=$(grep -a -oE 'https://[a-zA-Z0-9.-]+\.trycloudflare\.com' .cf_tunnel.log | head -1)
                        if [ -n "$URL" ]; then
                            echo -e "${GREEN}✓ Ready!${NC}"
                            echo -e "\n${RED}${BOLD}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"
                            echo -e "${RED}${BOLD}🚀 YOUR PUBLIC AGENT URL IS READY!${NC}"
                            echo -e "${BOLD}   Access the UI from your phone or anywhere at:${NC}"
                            echo -e "${GREEN}${BOLD}   ${URL}/chat${NC}"
                            echo -e "${RED}${BOLD}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}\n"
                            
                            # Save to a persistent file
                            echo "$URL/chat" > URL.txt
                            # Trigger a notification if on macOS
                            if command -v osascript &> /dev/null; then
                                osascript -e "display notification \"Asbestos Agent is ready at $URL/chat\" with title \"Agent Ready\"" 2>/dev/null || true
                            fi
                            break
                        fi
                    fi
                    
                    # Print a dot every 2 seconds (20 * 0.1s) to show life without spam
                    if (( i % 20 == 0 )); then
                        echo -n "."
                    fi
                    
                    if [ $i -eq 150 ]; then
                        echo -en "\n${YELLOW}→ Still waiting... Cloudflare is being a bit slow.${NC} "
                    fi
                    
                    sleep 0.1
                done
            ) &
            ;;

        ngrok)
            if ! command -v ngrok &> /dev/null; then
                echo -e "${RED}ngrok not found. Install: https://ngrok.com/download${NC}"
                exit 1
            fi
            echo -e "${GREEN}Starting ngrok tunnel...${NC}"
            ngrok http "$AGENT_PORT" --log=stdout &
            TUNNEL_PID=$!
            echo -e "${CYAN}→ Check the ngrok dashboard at http://localhost:4040${NC}"
            ;;

        vscode|vs)
            echo -e "${CYAN}${BOLD}VS Code Tunnel Instructions:${NC}"
            echo -e "${CYAN}  1. Open the Ports panel in VS Code (Ctrl+Shift+P → Ports)${NC}"
            echo -e "${CYAN}  2. Forward port ${AGENT_PORT}${NC}"
            echo -e "${CYAN}  3. Set visibility to Public${NC}"
            echo -e "${CYAN}  4. Use the generated *.devtunnels.ms URL${NC}"
            echo ""
            ;;

        "")
            # No tunnel requested
            ;;

        *)
            echo -e "${RED}Unknown tunnel mode: ${TUNNEL_MODE}${NC}"
            echo "Options: cloudflare, ngrok, vscode"
            exit 1
            ;;
    esac
}

# ── Start ─────────────────────────────────────────────────────────
echo ""
echo -e "${GREEN}Starting agent server on http://0.0.0.0:${AGENT_PORT}${NC}"
echo -e "${CYAN}→ Chat UI:  http://localhost:${AGENT_PORT}/chat${NC}"
echo -e "${CYAN}→ API:      http://localhost:${AGENT_PORT}/v1/chat/completions${NC}"

if [ -n "$TUNNEL_MODE" ]; then
    echo -e "${CYAN}→ Tunnel:   ${TUNNEL_MODE}${NC}"
fi

if [ "$AUTONOMOUS" = "true" ]; then
    echo -e "${YELLOW}⚠  AUTONOMOUS MODE — all commands execute without confirmation${NC}"
fi

echo ""

# Start tunnel (if requested) after a brief delay to let server start
if [ -n "$TUNNEL_MODE" ] && [ "$TUNNEL_MODE" != "vscode" ] && [ "$TUNNEL_MODE" != "vs" ]; then
    (sleep 3 && start_tunnel) &
else
    start_tunnel
fi

AUTONOMOUS=$AUTONOMOUS AGENT_PORT=$AGENT_PORT python3 server.py
