#!/usr/bin/env bash
# ──────────────────────────────────────────────────────────────────────
# Asbestos CLI — explain.sh
#
# Generate pseudocode and architectural explanations for source files.
# Uses the asbestos-agent's local LLM to analyze code and produce
# human-readable logic breakdowns.
#
# Usage:
#   ./explain.sh <file_or_directory>
#   ./explain.sh ./src/main.cpp
#   ./explain.sh ./src/                   # Analyze all files in dir
#   ./explain.sh ./server.py --quiz       # Generate quiz questions
#   ./explain.sh ./server.py --recap      # "Previously on this file..."
#
# Requires: asbestos-agent running on localhost:8765
# ──────────────────────────────────────────────────────────────────────

set -euo pipefail

AGENT_URL="${ASBESTOS_AGENT_URL:-http://localhost:8765}"
BOLD='\033[1m'
DIM='\033[2m'
PURPLE='\033[0;35m'
CYAN='\033[0;36m'
GREEN='\033[0;32m'
YELLOW='\033[0;33m'
RED='\033[0;31m'
RESET='\033[0m'

# ── Usage ─────────────────────────────────────────────────────────────
usage() {
    echo -e "${BOLD}Asbestos · Project Insight CLI${RESET}"
    echo ""
    echo -e "  ${DIM}Generate pseudocode, architectural explanations,${RESET}"
    echo -e "  ${DIM}and comprehension quizzes for your source code.${RESET}"
    echo ""
    echo -e "${BOLD}Usage:${RESET}"
    echo -e "  ${GREEN}./explain.sh${RESET} <file>              ${DIM}# Analyze a single file${RESET}"
    echo -e "  ${GREEN}./explain.sh${RESET} <directory>          ${DIM}# Scan & list project files${RESET}"
    echo -e "  ${GREEN}./explain.sh${RESET} <file> ${YELLOW}--quiz${RESET}        ${DIM}# Generate comprehension quiz${RESET}"
    echo -e "  ${GREEN}./explain.sh${RESET} <file> ${YELLOW}--recap${RESET}       ${DIM}# \"Previously on this file...\"${RESET}"
    echo -e "  ${GREEN}./explain.sh${RESET} <file> ${YELLOW}--flowchart${RESET}   ${DIM}# Generate Mermaid.js flowchart${RESET}"
    echo ""
    echo -e "${BOLD}Options:${RESET}"
    echo -e "  ${YELLOW}--quiz${RESET}        Generate comprehension questions (anti-atrophy)"
    echo -e "  ${YELLOW}--recap${RESET}       Generate contextual memory summary"
    echo -e "  ${YELLOW}--flowchart${RESET}   Generate Mermaid.js logic flowchart"
    echo -e "  ${YELLOW}--help${RESET}        Show this help message"
    echo ""
    echo -e "${BOLD}Environment:${RESET}"
    echo -e "  ${CYAN}ASBESTOS_AGENT_URL${RESET}  Agent URL (default: http://localhost:8765)"
    exit 0
}

# ── Health check ──────────────────────────────────────────────────────
check_agent() {
    if ! curl -sf "${AGENT_URL}/health" > /dev/null 2>&1; then
        echo -e "${RED}✗ Cannot reach asbestos-agent at ${AGENT_URL}${RESET}"
        echo -e "${DIM}  Start it with: cd asbestos-agent && ./start.sh${RESET}"
        exit 1
    fi
}

# ── Analyze a single file ────────────────────────────────────────────
analyze_file() {
    local file_path="$1"
    local abs_path
    abs_path="$(cd "$(dirname "$file_path")" && pwd)/$(basename "$file_path")"

    echo -e "${PURPLE}🔬 Analyzing${RESET} ${BOLD}${abs_path}${RESET}"
    echo -e "${DIM}───────────────────────────────────────────────────${RESET}"
    echo ""

    local response
    response=$(curl -sf "${AGENT_URL}/insight/analyze" \
        -H "Content-Type: application/json" \
        -d "{\"file_path\": \"${abs_path}\", \"include_context\": true}" \
        2>/dev/null)

    if [ $? -ne 0 ]; then
        echo -e "${RED}✗ Failed to analyze file${RESET}"
        exit 1
    fi

    local status
    status=$(echo "$response" | python3 -c "import sys,json; print(json.load(sys.stdin).get('status','error'))" 2>/dev/null)

    if [ "$status" = "ok" ]; then
        echo "$response" | python3 -c "import sys,json; print(json.load(sys.stdin).get('insight',''))" 2>/dev/null
    else
        local error
        error=$(echo "$response" | python3 -c "import sys,json; print(json.load(sys.stdin).get('error','Unknown error'))" 2>/dev/null)
        echo -e "${RED}✗ ${error}${RESET}"
        exit 1
    fi
}

# ── Generate quiz (Interactive) ──────────────────────────────────────
generate_quiz() {
    local file_path="$1"
    local abs_path
    abs_path="$(cd "$(dirname "$file_path")" && pwd)/$(basename "$file_path")"

    echo -e "${YELLOW}🧠 Comprehension Quiz${RESET} for ${BOLD}$(basename "$file_path")${RESET}"
    echo -e "${DIM}───────────────────────────────────────────────────${RESET}"
    echo ""

    local response
    response=$(curl -sf "${AGENT_URL}/insight/quiz" \
        -H "Content-Type: application/json" \
        -d "{\"file_path\": \"${abs_path}\"}" \
        2>/dev/null)

    if [ $? -ne 0 ]; then
        echo -e "${RED}✗ Failed to generate quiz${RESET}"
        exit 1
    fi

    local quiz_text ground_truth
    quiz_text=$(echo "$response" | python3 -c "import sys,json; print(json.load(sys.stdin).get('quiz',''))" 2>/dev/null)
    ground_truth=$(echo "$response" | python3 -c "import sys,json; print(json.load(sys.stdin).get('answers',''))" 2>/dev/null)

    echo -e "${quiz_text}"
    echo ""
    echo -e "${BOLD}Your Answers (Anti-Atrophy Mode)${RESET}"
    echo -e "${DIM}───────────────────────────────────────────────────${RESET}"
    
    local ans1 ans2 ans3
    echo -ne "${CYAN}Answer 1: ${RESET}"; read -r ans1
    echo -ne "${CYAN}Answer 2: ${RESET}"; read -r ans2
    echo -ne "${CYAN}Answer 3: ${RESET}"; read -r ans3
    echo ""
    
    echo -e "${DIM}⌛ Grading via local LLM...${RESET}"

    # Prepare JSON safely
    local grade_payload
    grade_payload=$(python3 -c "
import sys, json
print(json.dumps({
    'file_path': sys.argv[1],
    'user_answers': [sys.argv[2], sys.argv[3], sys.argv[4]],
    'ground_truth': sys.argv[5]
}))
" "$abs_path" "$ans1" "$ans2" "$ans3" "$ground_truth")

    local grade_resp
    grade_resp=$(curl -sf "${AGENT_URL}/insight/grade" \
        -H "Content-Type: application/json" \
        -d "$grade_payload" \
        2>/dev/null)

    if [ $? -ne 0 ]; then
        echo -e "${RED}✗ Grading failed${RESET}"
        exit 1
    fi

    local feedback
    feedback=$(echo "$grade_resp" | python3 -c "import sys,json; print(json.load(sys.stdin).get('feedback',''))" 2>/dev/null)

    echo -e "${PURPLE}${BOLD}🎓 Tutor Review:${RESET}"
    echo -e "${feedback}"
    echo ""
}

# ── Generate recap ───────────────────────────────────────────────────
generate_recap() {
    local file_path="$1"
    local abs_path
    abs_path="$(cd "$(dirname "$file_path")" && pwd)/$(basename "$file_path")"

    echo -e "${CYAN}🔄 Previously on${RESET} ${BOLD}$(basename "$file_path")${RESET}..."
    echo -e "${DIM}───────────────────────────────────────────────────${RESET}"
    echo ""

    local response
    response=$(curl -sf "${AGENT_URL}/insight/summary" \
        -H "Content-Type: application/json" \
        -d "{\"file_path\": \"${abs_path}\"}" \
        2>/dev/null)

    if [ $? -ne 0 ]; then
        echo -e "${RED}✗ Failed to generate summary${RESET}"
        exit 1
    fi

    echo "$response" | python3 -c "import sys,json; print(json.load(sys.stdin).get('summary',''))" 2>/dev/null
}

# ── Generate flowchart ────────────────────────────────────────────
generate_flowchart() {
    local file_path="$1"
    local abs_path
    abs_path="$(cd "$(dirname "$file_path")" && pwd)/$(basename "$file_path")"

    echo -e "${PURPLE}📈 Flowchart${RESET} for ${BOLD}$(basename "$file_path")${RESET}"
    echo -e "${DIM}───────────────────────────────────────────────────${RESET}"
    echo ""

    local response
    response=$(curl -sf "${AGENT_URL}/insight/flowchart" \
        -H "Content-Type: application/json" \
        -d "{\"file_path\": \"${abs_path}\"}" \
        2>/dev/null)

    if [ $? -ne 0 ]; then
        echo -e "${RED}✗ Failed to generate flowchart${RESET}"
        exit 1
    fi

    echo -e "${DIM}\`\`\`mermaid${RESET}"
    echo "$response" | python3 -c "import sys,json; print(json.load(sys.stdin).get('flowchart',''))" 2>/dev/null
    echo -e "${DIM}\`\`\`${RESET}"
    echo ""
    echo -e "${DIM}Paste the above into https://mermaid.live to visualize${RESET}"
}

# ── Scan directory ───────────────────────────────────────────────────
scan_directory() {
    local dir_path="$1"
    local abs_path
    abs_path="$(cd "$dir_path" && pwd)"

    echo -e "${GREEN}📂 Scanning${RESET} ${BOLD}${abs_path}${RESET}"
    echo -e "${DIM}───────────────────────────────────────────────────${RESET}"
    echo ""

    local response
    response=$(curl -sf "${AGENT_URL}/insight/scan" \
        -H "Content-Type: application/json" \
        -d "{\"directory\": \"${abs_path}\"}" \
        2>/dev/null)

    if [ $? -ne 0 ]; then
        echo -e "${RED}✗ Failed to scan directory${RESET}"
        exit 1
    fi

    local count
    count=$(echo "$response" | python3 -c "import sys,json; print(json.load(sys.stdin).get('file_count', 0))" 2>/dev/null)

    echo -e "${BOLD}${count} source files found${RESET}"
    echo ""

    echo "$response" | python3 -c "
import sys, json
data = json.load(sys.stdin)
files = data.get('files', [])
current_dir = ''
for f in files:
    parts = f['relative_path'].rsplit('/', 1)
    d = parts[0] if len(parts) > 1 else '.'
    if d != current_dir:
        current_dir = d
        print(f'\033[2m  {current_dir}/\033[0m')
    name = parts[-1]
    size = f['size']
    if size < 1024:
        size_str = f'{size}B'
    elif size < 1024*1024:
        size_str = f'{size/1024:.1f}K'
    else:
        size_str = f'{size/(1024*1024):.1f}M'
    print(f'    {name:<40} {size_str:>8}')
" 2>/dev/null

    echo ""
    echo -e "${DIM}Run ${GREEN}./explain.sh <file>${RESET}${DIM} to analyze a specific file${RESET}"
}

# ── Main ──────────────────────────────────────────────────────────────
[ $# -eq 0 ] && usage
[ "$1" = "--help" ] || [ "$1" = "-h" ] && usage

TARGET="$1"
MODE="${2:-analyze}"

check_agent

if [ -d "$TARGET" ]; then
    scan_directory "$TARGET"
elif [ -f "$TARGET" ]; then
    case "$MODE" in
        --quiz)      generate_quiz "$TARGET" ;;
        --recap)     generate_recap "$TARGET" ;;
        --flowchart) generate_flowchart "$TARGET" ;;
        *)           analyze_file "$TARGET" ;;
    esac
else
    echo -e "${RED}✗ Not found: ${TARGET}${RESET}"
    exit 1
fi
