"""
Asbestos Agent — Project Insight Engine

Generates pseudocode, architectural explanations, and contextual memory
for source files. Designed as the "antidote to atrophy" — forces
developers to engage with logic rather than blindly consuming code.

Three output sections per file:
  1. Architectural Intent  — what the file's singular purpose is
  2. Logical Pseudocode    — language-agnostic breakdown of the algorithm
  3. Contextual Memory     — how this file relates to the rest of the project
"""

from __future__ import annotations

import json
import logging
import os
import asyncio
from pathlib import Path
from typing import Any

import httpx
import config

logger = logging.getLogger("asbestos.insight")

LLAMA_BASE = f"http://{config.LLAMA_HOST}:{config.LLAMA_PORT}"

# ── System Prompts (optimized for small models like Qwen 0.8B) ────────
#
# Design rules for small-model prompts:
#   - Short, imperative sentences
#   - Explicit output format with exact section headers
#   - No open-ended instructions — constrain the output shape
#   - Use examples where possible
#   - Limit scope per prompt (one job, one output)

ARCHITECT_SYSTEM_PROMPT = """\
You are a software architect. Analyze the code and output Markdown with these exact sections:

## 📋 Summary
- **Goal**: One sentence — what this file does.
- **Key Logic**: The main algorithm or pattern.
- **Dependencies**: Files or libraries it uses.

## 🏗️ Why This File Exists
One paragraph: the file's purpose in the project. Mention specific technologies (e.g. FastAPI = HTTP server, Metal = GPU, JNI = native bridge) and WHY they are used.

## 📝 Pseudocode
Write pseudocode for the main logic. Rules:
- Keep it under 15 lines. **DO NOT REPEAT YOURSELF.**
- Use plain English, not code syntax.
- Show key IF/ELSE decisions only. DO NOT list every parameter check.
- Use arrows → for flow.

Example format:
```
FUNCTION handle_request(input):
  validate input
  IF input is valid → process data
  ELSE → return error
  result → send to client
```

## 🔗 Connections
List: what imports this file, what this file imports, what breaks if removed.

Be concise. No source code. Pseudocode only."""

QUIZ_SYSTEM_PROMPT = """\
Generate exactly 3 quiz questions about this code.

Format:
1. 🤔 [Short question about edge case]
2. 🤔 [Short question about logic]
3. 🤔 [Short question about purpose]

---

### 💡 Answers
1. [Correct logic answer]
2. [Correct logic answer]
3. [Correct logic answer]

**CRITICAL RULES**:
- DO NOT include any answers in the questions section.
- DO NOT repeat the examples above; be specific to the code provided.
- Use exactly one sentence per question and one sentence per answer."""

DIFF_SUMMARY_PROMPT = """\
Write a quick summary to help a developer who hasn't seen this file in a week. Use this exact format:

## 🔄 Previously on `{filename}`...

**What it does**: [One sentence]

**Remember**:
- [Key detail 1]
- [Key detail 2]
- [Key detail 3]

**Watch out for**:
- [One gotcha or subtle behavior]

Be brief — max 8 lines total."""

FLOWCHART_SYSTEM_PROMPT = """\
Generate a Mermaid.js flowchart for the main logic in this code.

Rules:
- Use `graph TD` (top-down direction)
- Node IDs must be simple: A, B, C, D, etc.
- Label nodes with short descriptions in square brackets: A["Start server"]
- Use --> for normal flow, -->|"label"| for conditional branches
- Show the MAIN flow only (5-15 nodes max)
- For IF/ELSE, use a diamond node: C{"Is valid?"}
- Output ONLY the mermaid code block, no explanation before or after

Example:
```mermaid
graph TD
    A["Start"] --> B["Load config"]
    B --> C{"Config valid?"}
    C -->|"Yes"| D["Start server"]
    C -->|"No"| E["Show error"]
    D --> F["Listen for requests"]
```

Output only the ```mermaid block. Nothing else."""

# ── File type detection ───────────────────────────────────────────────
SOURCE_EXTENSIONS = {
    ".py", ".js", ".ts", ".jsx", ".tsx", ".c", ".cpp", ".h", ".hpp",
    ".java", ".kt", ".kts", ".swift", ".go", ".rs", ".rb", ".php",
    ".cs", ".m", ".mm", ".sh", ".bash", ".zsh", ".lua", ".r",
    ".scala", ".dart", ".zig", ".v", ".nim", ".ml", ".hs",
    ".html", ".css", ".scss", ".sass", ".less",
    ".sql", ".graphql", ".proto",
    ".yaml", ".yml", ".toml", ".json", ".xml", ".plist",
    ".md", ".rst", ".txt",
    ".dockerfile", ".makefile", ".cmake",
}

GRADER_SYSTEM_PROMPT = """\
Evaluate the USER ANSWERS by comparing them to the REFERENCE ANSWERS.
Be strict and clinical.

FORMAT YOUR RESPONSE AS:
**Review**:
- Q1: [Correct | Incorrect: precisely one sentence error]
- Q2: [Correct | Incorrect: precisely one sentence error]
- Q3: [Correct | Incorrect: precisely one sentence error]

**Score**: [Sum/3]

**Mentor Tip**: One clinical sentence.

CRITICAL: The **Score** MUST match the count of 'Correct' markings in the Review. If 0 are Correct, score is [0/3]. If 1 is Correct, score is [1/3]. 
DOUBLE CHECK THE SUM."""

IGNORED_DIRS = {
    ".git", ".svn", ".hg",
    "__pycache__", ".cache", ".venv", "venv", "env",
    "node_modules", ".next", "dist", "build", "target",
    ".DS_Store", ".idea", ".vscode",
    "llama.cpp",  # Large vendored dependency
}

MAX_FILE_SIZE = 50_000  # Skip files larger than 50KB

def get_raw_code(file_path: str) -> dict:
    """Read and return the raw source code for a file."""
    try:
        path = Path(file_path).resolve()
        
        # Security check (ensure it's not trying to read things outside of what's sensible?)
        # For now we'll just check size and existence.
        if not path.exists():
            return {"error": "File not found"}
        
        if path.is_dir():
            return {"error": "Path is a directory"}
            
        stats = path.stat()
        if stats.st_size > MAX_FILE_SIZE:
             return {"error": f"File too large ({stats.st_size} bytes)"}
             
        # Detect extension
        ext_str: str = str(path.suffix).lower()
        # Use removeprefix to avoid Pyre slicing issues
        lang = ext_str.removeprefix('.') if ext_str.startswith('.') else 'text'

        with open(path, 'r', encoding='utf-8', errors='replace') as f:
            content = f.read()
            
        return {
            "path": str(path),
            "name": path.name,
            "content": content,
            "language": lang
        }
    except Exception as e:
        return {"error": str(e)}


def is_source_file(path: Path) -> bool:
    """Check if a file is a source code file worth analyzing."""
    if path.name.startswith("."):
        return False
    suffix = path.suffix.lower()
    # Also match Makefile, Dockerfile, etc.
    if path.name.lower() in {"makefile", "dockerfile", "cmakelists.txt", "gemfile", "rakefile"}:
        return True
    return suffix in SOURCE_EXTENSIONS


def scan_directory(directory: str | Path, max_files: int = 200) -> list[dict]:
    """
    Recursively scan a directory and return a tree of source files.
    
    Returns a list of dicts: { "path": str, "name": str, "size": int, "extension": str }
    """
    directory = Path(directory).resolve()
    if not directory.exists() or not directory.is_dir():
        return []
    
    files = []
    
    for root, dirs, filenames in os.walk(directory):
        # Filter out ignored directories
        to_remove: list[str] = [d for d in dirs if d in IGNORED_DIRS]
        for d in to_remove:
            dirs.remove(d)
        dirs.sort()
        
        for fname in sorted(filenames):
            if len(files) >= max_files:
                break
            
            fpath = Path(root) / fname
            if not is_source_file(fpath):
                continue
            
            try:
                size = fpath.stat().st_size
                if size > MAX_FILE_SIZE or size == 0:
                    continue
                
                files.append({
                    "path": str(fpath),
                    "relative_path": str(fpath.relative_to(directory)),
                    "name": fname,
                    "size": size,
                    "extension": fpath.suffix.lower(),
                })
            except (OSError, ValueError):
                continue
    
    return files


def build_project_tree(files: list[dict], root_dir: str) -> dict:
    """
    Build a nested tree structure from a flat list of files.
    Returns a hierarchical dict suitable for rendering a tree view.
    """
    tree: dict[str, Any] = {"name": Path(root_dir).name, "type": "directory", "children": {}}
    
    for f in files:
        parts = Path(f["relative_path"]).parts
        current = tree["children"]
        
        for i, part in enumerate(parts):
            if i == len(parts) - 1:
                # It's a file
                current[part] = {
                    "name": part,
                    "type": "file",
                    "path": f["path"],
                    "size": f["size"],
                    "extension": f["extension"],
                }
            else:
                # It's a directory
                if part not in current:
                    current[part] = {
                        "name": part,
                        "type": "directory",
                        "children": {},
                    }
                current = current[part]["children"]
    
    return tree


async def _call_llama_insight(
    system_prompt: str,
    user_prompt: str,
    max_tokens: int = 2048,
) -> str:
    """Call the local llama-server for insight generation (no tools)."""
    messages = [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": user_prompt},
    ]
    
    async with httpx.AsyncClient(timeout=180.0) as client:
        try:
            resp = await client.post(
                f"{LLAMA_BASE}/v1/chat/completions",
                json={
                    "model": "local",
                    "messages": messages,
                    "max_tokens": max_tokens,
                    "temperature": 0.1,  # Ultra-low temp to prevent loops
                    "stream": False,
                },
            )
            resp.raise_for_status()
            data = resp.json()
            content = data.get("choices", [{}])[0].get("message", {}).get("content", "")
            return content.strip()
        except Exception as e:
            logger.error("Insight LLM call failed: %s", e)
            return f"Error generating insight: {e}"


async def analyze_file(file_path: str, project_context: str = "") -> dict:
    """
    Generate a full insight analysis for a single file.
    
    Returns:
        {
            "path": str,
            "name": str,
            "insight": str,        # The full markdown analysis
            "status": "ok" | "error",
            "error": str | None,
        }
    """
    path = Path(file_path).resolve()
    
    if not path.exists():
        return {"path": str(path), "name": path.name, "insight": "", "status": "error", "error": "File not found"}
    
    try:
        code = path.read_text(errors="replace")
        if len(code) > MAX_FILE_SIZE:
            code = code[:MAX_FILE_SIZE] + "\n\n... [truncated]"
    except Exception as e:
        return {"path": str(path), "name": path.name, "insight": "", "status": "error", "error": str(e)}
    
    # Build the user prompt with optional project context
    user_prompt = f"**File**: `{path.name}` (path: `{file_path}`)\n"
    if path.suffix:
        user_prompt += f"**Language**: {path.suffix.lstrip('.')}\n"
    if project_context:
        user_prompt += f"\n**Project Context**:\n{project_context}\n"
    user_prompt += f"\n**Source Code**:\n```\n{code}\n```"
    
    insight = await _call_llama_insight(ARCHITECT_SYSTEM_PROMPT, user_prompt)
    
    return {
        "path": str(path),
        "name": path.name,
        "insight": insight,
        "status": "ok",
        "error": None,
    }


async def generate_quiz(file_path: str) -> dict:
    """
    Generate comprehension quiz questions for a file.
    The "Rubber Duck" interactive — anti-atrophy mechanic.
    """
    path = Path(file_path).resolve()
    
    if not path.exists():
        return {"path": str(path), "quiz": "", "status": "error", "error": "File not found"}
    
    try:
        code = path.read_text(errors="replace")
        if len(code) > MAX_FILE_SIZE:
            code = code[:MAX_FILE_SIZE] + "\n\n... [truncated]"
    except Exception as e:
        return {"path": str(path), "quiz": "", "status": "error", "error": str(e)}
    
    user_prompt = f"**File**: `{path.name}`\n\n```\n{code}\n```"
    raw = await _call_llama_insight(QUIZ_SYSTEM_PROMPT, user_prompt, max_tokens=1024)
    
    # Robust split for small models that might miss the '---'
    if "---" in raw:
        parts = raw.split('---', 1)
        questions = parts[0].strip()
        answers = parts[1].strip()
    elif "### 💡 Answers" in raw:
        parts = raw.split("### 💡 Answers", 1)
        questions = parts[0].strip()
        answers = f"### 💡 Answers\n{parts[1].strip()}"
    else:
        questions = raw.strip()
        answers = ""

    return {
        "path": str(path),
        "name": path.name,
        "quiz": questions,
        "answers": answers,
        "status": "ok",
        "error": None,
    }


async def generate_diff_summary(file_path: str) -> dict:
    """
    Generate a "Previously on this file..." contextual memory summary.
    Helps developers rebuild context after time away.
    """
    path = Path(file_path).resolve()
    
    if not path.exists():
        return {"path": str(path), "summary": "", "status": "error", "error": "File not found"}
    
    try:
        code = path.read_text(errors="replace")
        if len(code) > MAX_FILE_SIZE:
            code = code[:MAX_FILE_SIZE] + "\n\n... [truncated]"
    except Exception as e:
        return {"path": str(path), "summary": "", "status": "error", "error": str(e)}
    
    prompt = DIFF_SUMMARY_PROMPT.replace("{filename}", path.name)
    user_prompt = f"**File**: `{path.name}`\n\n```\n{code}\n```"
    
    summary = await _call_llama_insight(prompt, user_prompt, max_tokens=512)
    
    return {
        "path": str(path),
        "name": path.name,
        "summary": summary,
        "status": "ok",
        "error": None,
    }


async def generate_flowchart(file_path: str) -> dict:
    """
    Generate a Mermaid.js flowchart for a file's main logic.
    Visual scaffolding — helps memory retention better than text.
    """
    path = Path(file_path).resolve()
    
    if not path.exists():
        return {"path": str(path), "flowchart": "", "status": "error", "error": "File not found"}
    
    try:
        code = path.read_text(errors="replace")
        if len(code) > MAX_FILE_SIZE:
            code = code[:MAX_FILE_SIZE] + "\n\n... [truncated]"
    except Exception as e:
        return {"path": str(path), "flowchart": "", "status": "error", "error": str(e)}
    
    user_prompt = f"**File**: `{path.name}`\n\n```\n{code}\n```"
    raw = await _call_llama_insight(FLOWCHART_SYSTEM_PROMPT, user_prompt, max_tokens=1024)
    
    # Robust extraction of mermaid code
    mermaid_code = raw.strip()
    
    # 1. Look for ```mermaid ... ```
    if "```mermaid" in mermaid_code:
        try:
            start_marker = "```mermaid"
            start = mermaid_code.index(start_marker) + len(start_marker)
            if "```" in mermaid_code[start:]:
                end = mermaid_code.index("```", start)
                mermaid_code = mermaid_code[start:end].strip()
            else:
                mermaid_code = mermaid_code[start:].strip()
        except ValueError:
            pass
            
    # 2. If no fence but contains 'graph TD', try to isolate just the graph
    elif "graph TD" in mermaid_code:
        try:
            start = mermaid_code.index("graph TD")
            lines = mermaid_code[start:].split("\n")
            valid_lines = []
            for line in lines:
                if "```" in line or "Explanation:" in line:
                    break
                valid_lines.append(line)
            mermaid_code = "\n".join(valid_lines).strip()
        except ValueError:
            pass

    # 3. Final cleanup: strip generic fences if they still exist
    if mermaid_code.startswith("```"):
        mermaid_code = mermaid_code.split("\n", 1)[-1]
    if mermaid_code.endswith("```"):
        mermaid_code = mermaid_code.rsplit("\n", 1)[0]
    
    mermaid_code = mermaid_code.strip()

    # Validation: If it doesn't look like a graph, it's probably an error message
    if not mermaid_code.startswith("graph ") and "-->" not in mermaid_code:
        return {
            "path": str(path),
            "name": path.name,
            "flowchart": "",
            "status": "error",
            "error": f"Invalid flowchart generated: {mermaid_code[:100]}..."
        }
    
    return {
        "path": str(path),
        "name": path.name,
        "flowchart": mermaid_code,
        "status": "ok",
        "error": None,
    }


def get_project_context(directory: str | Path) -> str:
    """
    Build a brief project context string from a directory scan.
    This gives the LLM awareness of what other files exist in the project.
    """
    files = scan_directory(directory, max_files=100)
    if not files:
        return ""
    
    # Group files by directory
    dirs: dict[str, list[str]] = {}
    for f in files:
        parent = str(Path(f["relative_path"]).parent)
        if parent == ".":
            parent = "(root)"
        if parent not in dirs:
            dirs[parent] = []
        dirs[parent].append(f["name"])
    
    lines = ["This file is part of a project with the following structure:"]
    for dir_name, filenames_raw in sorted(dirs.items()):
        # Show up to 10 files per directory to avoid context bloating
        file_list: list[str] = list(filenames_raw)
        lines.append(f"  {dir_name}/: {', '.join(file_list[:10])}")
        if len(file_list) > 10:
            lines.append(f"    ... and {len(file_list) - 10} more files")
    
    return "\n".join(lines)


async def grade_quiz(file_path: str, user_answers: list[str], ground_truth: str) -> dict:
    """
    Grade a user's quiz attempts against the actual logic.
    Provides the "Correction" phase of the learning loop.
    """
    path = Path(file_path).resolve()
    
    if not path.exists():
        return {"status": "error", "error": "File not found"}
    
    try:
        code = path.read_text(errors="replace")
        if len(code) > 100000: # Use common MAX_FILE_SIZE logic or hardcode for safety
            code = code[:100000] + "\n\n... [truncated]"
    except Exception as e:
        return {"status": "error", "error": str(e)}

    # Format the payload for the grader
    attempts_str = "\n".join([f"User Answer {i+1}: {ans}" for i, ans in enumerate(user_answers)])
    
    user_prompt = f"""
**File**: `{path.name}`
**Source Code**:
```
{code}
```

**Correct Answers (Reference)**:
{ground_truth}

**User's Attempts**:
{attempts_str}
""".strip()

    feedback = await _call_llama_insight(GRADER_SYSTEM_PROMPT, user_prompt, max_tokens=1024)
    
    return {
        "path": str(path),
        "name": path.name,
        "feedback": feedback,
        "status": "ok",
    }
