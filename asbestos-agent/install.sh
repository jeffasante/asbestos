#!/bin/bash
# ────────────────────────────────────────────────────────────────
#  Asbestos Agent — Installation Script
#  Installs dependencies, tools (like cloudflared), and models
# ────────────────────────────────────────────────────────────────

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
cd "$SCRIPT_DIR"

# Colors
GREEN='\033[0;32m'
CYAN='\033[0;36m'
YELLOW='\033[1;33m'
RED='\033[0;31m'
NC='\033[0m'

echo -e "${CYAN}"
echo "  ╔══════════════════════════════════════════════╗"
echo "  ║          🧶 Asbestos Agent Install           ║"
echo "  ╚══════════════════════════════════════════════╝"
echo -e "${NC}"

if ! command -v curl &> /dev/null; then
    echo -e "${RED}Error: 'curl' is required to download models.${NC}"
    exit 1
fi

if ! command -v python3 &> /dev/null; then
    echo -e "${RED}Error: 'python3' is required.${NC}"
    exit 1
fi

# 1. Check/Download the LLaMA model
MODEL_FILENAME="Qwen_Qwen3.5-0.8B-Q8_0.gguf"
MODEL_URL="https://huggingface.co/bartowski/Qwen_Qwen3.5-0.8B-GGUF/resolve/main/${MODEL_FILENAME}"
PARENT_MODEL_PATH="../${MODEL_FILENAME}"

if [ -f "$PARENT_MODEL_PATH" ]; then
    echo -e "${GREEN}✓ Model already exists in parent directory: $MODEL_FILENAME${NC}"
elif [ -f "$MODEL_FILENAME" ]; then
    echo -e "${GREEN}✓ Model already exists in agent directory: $MODEL_FILENAME${NC}"
else
    echo -e "${YELLOW}Downloading Model: $MODEL_FILENAME (~800MB)...${NC}"
    curl -L "$MODEL_URL" -o "../$MODEL_FILENAME"
    echo -e "${GREEN}✓ Model downloaded to project root${NC}"
fi

# 1b. Check/Download the multimodal projection model (vision)
MMPROJ_FILENAME="mmproj-Qwen_Qwen3.5-0.8B-bf16.gguf"
MMPROJ_URL="https://huggingface.co/bartowski/Qwen_Qwen3.5-0.8B-GGUF/resolve/main/mmproj-Qwen_Qwen3.5-0.8B-bf16.gguf?download=true"
PARENT_MMPROJ_PATH="../${MMPROJ_FILENAME}"

if [ -f "$PARENT_MMPROJ_PATH" ]; then
    echo -e "${GREEN}✓ Vision model already exists in parent directory: $MMPROJ_FILENAME${NC}"
elif [ -f "$MMPROJ_FILENAME" ]; then
    echo -e "${GREEN}✓ Vision model already exists in agent directory: $MMPROJ_FILENAME${NC}"
else
    echo -e "${YELLOW}Downloading Vision Model: $MMPROJ_FILENAME (~200MB)...${NC}"
    curl -L "$MMPROJ_URL" -o "../$MMPROJ_FILENAME"
    echo -e "${GREEN}✓ Vision model downloaded to project root${NC}"
fi

# 2. Setup Python environment
echo -e "\n${YELLOW}Setting up Python virtual environment...${NC}"
if [ ! -d ".venv" ]; then
    python3 -m venv .venv
fi
source .venv/bin/activate
pip install --upgrade pip -q
pip install -r requirements.txt -q
echo -e "${GREEN}✓ Python dependencies installed${NC}"

# 3. Check / Install Cloudflare Tunnel
echo -e "\n${YELLOW}Checking tunneling tools...${NC}"
if ! command -v cloudflared &> /dev/null; then
    if command -v brew &> /dev/null; then
        echo -e "${CYAN}Installing cloudflared via Homebrew...${NC}"
        brew install cloudflared
        echo -e "${GREEN}✓ cloudflared installed${NC}"
    else
        echo -e "${YELLOW}⚠ cloudflared not found and Homebrew is missing.${NC}"
        echo -e "If you want to use the Cloudflare tunnel, install it from:"
        echo -e "https://developers.cloudflare.com/cloudflare-one/connections/connect-networks/downloads/"
    fi
else
    echo -e "${GREEN}✓ cloudflared is already installed${NC}"
fi

# Make start script executable
chmod +x start.sh

echo -e "\n${GREEN}────────────────────────────────────────────"
echo -e "🎉 Installation Complete!"
echo -e "────────────────────────────────────────────${NC}"
echo -e "To start the agent and get a public URL, run:\n"
echo -e "  ${CYAN}./start.sh --tunnel cloudflare${NC}"
echo ""
