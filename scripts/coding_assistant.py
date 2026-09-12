"""
Coding Assistant — Cursor-like Code Intelligence (Phase 5.2)
=============================================================
Provides code-aware tools for the agent loop, enabling Cursor/Codex-style
coding workflows:

1. read_repo — Read and understand a repository's structure
2. search_code — Semantic/grep code search across the repo
3. read_file — Read a specific file with line numbers
4. edit_file — Apply targeted edits to a file (find & replace)
5. run_tests — Execute the project's test suite
6. git_commit — Stage and commit changes with conventional commit format
7. git_diff — Show uncommitted changes
8. git_status — Show working tree status

These tools complement the existing MCP GitHub tools (which handle remote
repo operations) by providing local file system and git operations.

Usage:
    from coding_assistant import get_coding_tools, handle_coding_tool
    tools = get_coding_tools()
    result = await handle_coding_tool("read_repo", {"path": "/opt/vinifera"})
"""

from __future__ import annotations

import asyncio
import json
import os
import re
import subprocess
from datetime import datetime, timezone
from typing import Optional


# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

MAX_FILE_READ_LINES = 200       # Max lines to return from read_file
MAX_SEARCH_RESULTS = 20         # Max search results to return
MAX_EDIT_SIZE = 50000           # Max chars for edit operations
SHELL_TIMEOUT = 120             # Timeout for shell commands (tests, builds)
CODING_OUTPUT_LIMIT = 3000      # Max chars for coding tool output


# ---------------------------------------------------------------------------
# Tool definitions (OpenAI function-calling format)
# ---------------------------------------------------------------------------

def get_coding_tools() -> list[dict]:
    """Return the coding assistant tool definitions for the LLM."""
    return [
        {
            "type": "function",
            "function": {
                "name": "read_repo",
                "description": (
                    "Read and understand a repository's structure. Returns a tree "
                    "of the directory structure, key files (README, package.json, "
                    "tsconfig, etc.), and a summary of the project. Use this FIRST "
                    "when starting work on a coding task to understand the codebase."
                ),
                "parameters": {
                    "type": "object",
                    "properties": {
                        "path": {
                            "type": "string",
                            "description": "Path to the repository root directory",
                        },
                        "depth": {
                            "type": "integer",
                            "description": "Directory tree depth (default 3, max 5)",
                        },
                    },
                    "required": ["path"],
                },
            },
        },
        {
            "type": "function",
            "function": {
                "name": "search_code",
                "description": (
                    "Search for code patterns in a repository using grep. "
                    "Returns matching lines with file paths and line numbers. "
                    "Use for finding function definitions, imports, usages, etc."
                ),
                "parameters": {
                    "type": "object",
                    "properties": {
                        "pattern": {
                            "type": "string",
                            "description": "The search pattern (regex supported)",
                        },
                        "path": {
                            "type": "string",
                            "description": "Root directory to search in",
                        },
                        "file_pattern": {
                            "type": "string",
                            "description": "File pattern to search (e.g., '*.ts', '*.py'). Default: all files",
                        },
                        "case_sensitive": {
                            "type": "boolean",
                            "description": "Whether search is case-sensitive (default: false)",
                        },
                    },
                    "required": ["pattern", "path"],
                },
            },
        },
        {
            "type": "function",
            "function": {
                "name": "read_file_lines",
                "description": (
                    "Read a specific file with line numbers. Returns the file "
                    "content with line number prefixes. Useful for reading source "
                    "code before making edits."
                ),
                "parameters": {
                    "type": "object",
                    "properties": {
                        "path": {
                            "type": "string",
                            "description": "Absolute path to the file",
                        },
                        "start_line": {
                            "type": "integer",
                            "description": "Starting line number (1-based, default 1)",
                        },
                        "end_line": {
                            "type": "integer",
                            "description": "Ending line number (default: start+200)",
                        },
                    },
                    "required": ["path"],
                },
            },
        },
        {
            "type": "function",
            "function": {
                "name": "edit_file",
                "description": (
                    "Apply a targeted edit to a file using find-and-replace. "
                    "The old_text must match exactly (including whitespace) for "
                    "the edit to succeed. Use read_file_lines first to see the "
                    "exact content before editing."
                ),
                "parameters": {
                    "type": "object",
                    "properties": {
                        "path": {
                            "type": "string",
                            "description": "Absolute path to the file to edit",
                        },
                        "old_text": {
                            "type": "string",
                            "description": "The exact text to find in the file (must match exactly)",
                        },
                        "new_text": {
                            "type": "string",
                            "description": "The replacement text",
                        },
                    },
                    "required": ["path", "old_text", "new_text"],
                },
            },
        },
        {
            "type": "function",
            "function": {
                "name": "write_file_content",
                "description": (
                    "Write content to a new file or completely overwrite an existing file. "
                    "Use for creating new files or replacing entire file contents. "
                    "For targeted edits, use edit_file instead."
                ),
                "parameters": {
                    "type": "object",
                    "properties": {
                        "path": {
                            "type": "string",
                            "description": "Absolute path to the file",
                        },
                        "content": {
                            "type": "string",
                            "description": "The full content to write",
                        },
                    },
                    "required": ["path", "content"],
                },
            },
        },
        {
            "type": "function",
            "function": {
                "name": "run_tests",
                "description": (
                    "Execute the project's test suite. Auto-detects the test "
                    "runner (npm test, pytest, cargo test, go test, etc.) based "
                    "on the project configuration files."
                ),
                "parameters": {
                    "type": "object",
                    "properties": {
                        "path": {
                            "type": "string",
                            "description": "Path to the project root directory",
                        },
                        "command": {
                            "type": "string",
                            "description": "Optional: override the test command (e.g., 'npm run test:unit')",
                        },
                    },
                    "required": ["path"],
                },
            },
        },
        {
            "type": "function",
            "function": {
                "name": "git_status",
                "description": (
                    "Show the git working tree status for a repository. "
                    "Returns staged, modified, and untracked files."
                ),
                "parameters": {
                    "type": "object",
                    "properties": {
                        "path": {
                            "type": "string",
                            "description": "Path to the git repository",
                        },
                    },
                    "required": ["path"],
                },
            },
        },
        {
            "type": "function",
            "function": {
                "name": "git_diff",
                "description": (
                    "Show uncommitted changes in a git repository. "
                    "Returns the diff of staged and unstaged changes."
                ),
                "parameters": {
                    "type": "object",
                    "properties": {
                        "path": {
                            "type": "string",
                            "description": "Path to the git repository",
                        },
                        "staged": {
                            "type": "boolean",
                            "description": "If true, show only staged changes (default: false = all changes)",
                        },
                    },
                    "required": ["path"],
                },
            },
        },
        {
            "type": "function",
            "function": {
                "name": "git_commit",
                "description": (
                    "Stage and commit changes in a git repository using conventional "
                    "commit format. The commit message should follow the format: "
                    "type(scope): description (e.g., 'feat(auth): add login validation'). "
                    "NEVER commits .env files. The bot will ask for confirmation before committing."
                ),
                "parameters": {
                    "type": "object",
                    "properties": {
                        "path": {
                            "type": "string",
                            "description": "Path to the git repository",
                        },
                        "message": {
                            "type": "string",
                            "description": "The commit message (conventional commit format)",
                        },
                        "files": {
                            "type": "string",
                            "description": "Optional: specific files to stage (comma-separated). Default: all modified files",
                        },
                    },
                    "required": ["path", "message"],
                },
            },
        },
    ]


# ---------------------------------------------------------------------------
# Tool handlers
# ---------------------------------------------------------------------------

async def handle_coding_tool(
    tool_name: str,
    args: dict,
    project_workdir: str = "",
) -> str:
    """
    Route a coding tool call to the appropriate handler.

    Args:
        tool_name: The name of the coding tool
        args: Tool arguments from the LLM
        project_workdir: The project's working directory (for relative path resolution)

    Returns:
        Result string for the LLM
    """
    handler = _HANDLERS.get(tool_name)
    if handler is None:
        return f"Error: unknown coding tool '{tool_name}'"

    try:
        return await handler(args, project_workdir)
    except Exception as e:
        return f"Error in {tool_name}: {e}"


# ---------------------------------------------------------------------------
# read_repo — understand repository structure
# ---------------------------------------------------------------------------

async def _handle_read_repo(args: dict, workdir: str) -> str:
    """Read and summarize a repository's structure."""
    path = args.get("path") or workdir
    depth = min(args.get("depth", 3), 5)

    if not os.path.isdir(path):
        return f"Error: directory '{path}' does not exist"

    # Build directory tree
    tree = _build_dir_tree(path, max_depth=depth)

    # Find key files
    key_files = _find_key_files(path)

    # Get project type
    project_type = _detect_project_type(path)

    result_parts = [
        f"Repository: {path}",
        f"Project type: {project_type}",
        "",
        "Key files:",
        *key_files,
        "",
        "Directory structure:",
        tree,
    ]

    result = "\n".join(result_parts)
    if len(result) > CODING_OUTPUT_LIMIT:
        result = result[:CODING_OUTPUT_LIMIT] + "\n... (truncated)"
    return result


def _build_dir_tree(path: str, max_depth: int = 3, prefix: str = "", current_depth: int = 0) -> str:
    """Build a text-based directory tree."""
    if current_depth >= max_depth:
        return ""

    # Skip common non-essential directories
    skip_dirs = {".git", "node_modules", ".venv", "venv", "__pycache__", ".next",
                 "dist", "build", ".cache", "vendor", ".gradle", "target",
                 "*.egg-info", ".idea", ".vscode"}

    try:
        entries = sorted(os.listdir(path))
    except PermissionError:
        return f"{prefix}[permission denied]"

    dirs = [e for e in entries if os.path.isdir(os.path.join(path, e)) and e not in skip_dirs]
    files = [e for e in entries if not os.path.isdir(os.path.join(path, e)) and not e.startswith(".")]

    # Limit number of entries shown
    dirs = dirs[:15]
    files = files[:15]

    lines = []
    all_items = dirs + files
    for i, item in enumerate(all_items):
        is_last = (i == len(all_items) - 1)
        connector = "└── " if is_last else "├── "
        item_path = os.path.join(path, item)

        if os.path.isdir(item_path):
            lines.append(f"{prefix}{connector}{item}/")
            extension = "    " if is_last else "│   "
            subtree = _build_dir_tree(item_path, max_depth, prefix + extension, current_depth + 1)
            if subtree:
                lines.append(subtree)
        else:
            size = os.path.getsize(item_path)
            size_str = f" ({_format_size(size)})" if size > 1000 else ""
            lines.append(f"{prefix}{connector}{item}{size_str}")

    return "\n".join(lines)


def _format_size(size: int) -> str:
    """Format byte size human-readably."""
    for unit in ["B", "KB", "MB", "GB"]:
        if size < 1024:
            return f"{size:.0f}{unit}"
        size /= 1024
    return f"{size:.1f}TB"


def _find_key_files(path: str) -> list[str]:
    """Find and summarize key project files."""
    key_names = [
        "README.md", "README.txt", "readme.md",
        "package.json", "pyproject.toml", "setup.py", "requirements.txt",
        "Cargo.toml", "go.mod", "pom.xml", "build.gradle",
        "tsconfig.json", "jsconfig.json", "vite.config.ts", "vite.config.js",
        "wrangler.jsonc", "wrangler.toml", "docker-compose.yml", "Dockerfile",
        ".env.example", "AGENTS.md", "CLAUDE.md", "CONTINUITY_BRIEF.md",
        "Makefile", "CMakeLists.txt",
    ]

    found = []
    for name in key_names:
        full_path = os.path.join(path, name)
        if os.path.isfile(full_path):
            size = os.path.getsize(full_path)
            found.append(f"  ✓ {name} ({_format_size(size)})")

    return found if found else ["  (no key files found)"]


def _detect_project_type(path: str) -> str:
    """Detect the project type from config files."""
    checks = [
        ("package.json", "Node.js"),
        ("pyproject.toml", "Python (pyproject)"),
        ("setup.py", "Python (setup.py)"),
        ("requirements.txt", "Python (pip)"),
        ("Cargo.toml", "Rust"),
        ("go.mod", "Go"),
        ("pom.xml", "Java (Maven)"),
        ("build.gradle", "Java (Gradle)"),
        ("tsconfig.json", "TypeScript"),
        ("vite.config.ts", "Vite + TypeScript"),
        ("wrangler.jsonc", "Cloudflare Workers"),
        ("docker-compose.yml", "Docker Compose"),
        ("Dockerfile", "Docker"),
        ("Makefile", "Make-based"),
    ]

    types = []
    for filename, ptype in checks:
        if os.path.isfile(os.path.join(path, filename)):
            types.append(ptype)

    return ", ".join(types) if types else "Unknown"


# ---------------------------------------------------------------------------
# search_code — grep-based code search
# ---------------------------------------------------------------------------

async def _handle_search_code(args: dict, workdir: str) -> str:
    """Search for code patterns using grep."""
    pattern = args.get("pattern", "")
    path = args.get("path") or workdir
    file_pattern = args.get("file_pattern", "")
    case_sensitive = args.get("case_sensitive", False)

    if not pattern:
        return "Error: search pattern is required"
    if not os.path.isdir(path):
        return f"Error: directory '{path}' does not exist"

    cmd = ["grep", "-rn", "--include=" + (file_pattern or "*")]
    if not case_sensitive:
        cmd.append("-i")
    cmd.extend([pattern, path])

    try:
        result = subprocess.run(
            cmd, capture_output=True, text=True, timeout=30,
        )
        output = result.stdout
    except subprocess.TimeoutExpired:
        return "Error: search timed out (30s)"
    except Exception as e:
        return f"Error: {e}"

    if not output:
        return f"No matches found for '{pattern}' in {path}"

    lines = output.strip().split("\n")
    if len(lines) > MAX_SEARCH_RESULTS:
        lines = lines[:MAX_SEARCH_RESULTS]
        output = "\n".join(lines) + f"\n... ({len(lines)} of {len(output.strip().split(chr(10)))} results shown)"

    if len(output) > CODING_OUTPUT_LIMIT:
        output = output[:CODING_OUTPUT_LIMIT] + "\n... (truncated)"

    return output


# ---------------------------------------------------------------------------
# read_file_lines — read a file with line numbers
# ---------------------------------------------------------------------------

async def _handle_read_file_lines(args: dict, workdir: str) -> str:
    """Read a file with line number prefixes."""
    path = args.get("path", "")
    start_line = max(1, args.get("start_line", 1))
    end_line = args.get("end_line", start_line + MAX_FILE_READ_LINES)

    if not path:
        return "Error: file path is required"
    if not os.path.isfile(path):
        return f"Error: file '{path}' does not exist"

    try:
        with open(path, "r", encoding="utf-8", errors="replace") as f:
            all_lines = f.readlines()
    except Exception as e:
        return f"Error reading file: {e}"

    total_lines = len(all_lines)
    end_line = min(end_line, total_lines)

    selected = all_lines[start_line - 1:end_line]
    numbered = []
    for i, line in enumerate(selected, start=start_line):
        # Strip trailing newline for consistent formatting
        content = line.rstrip("\n").rstrip("\r")
        numbered.append(f"{i:5d} | {content}")

    result = "\n".join(numbered)
    header = f"File: {path} (lines {start_line}-{end_line} of {total_lines})\n\n"
    result = header + result

    if len(result) > CODING_OUTPUT_LIMIT:
        result = result[:CODING_OUTPUT_LIMIT] + "\n... (truncated)"

    return result


# ---------------------------------------------------------------------------
# edit_file — find-and-replace editing
# ---------------------------------------------------------------------------

async def _handle_edit_file(args: dict, workdir: str) -> str:
    """Apply a targeted find-and-replace edit to a file."""
    path = args.get("path", "")
    old_text = args.get("old_text", "")
    new_text = args.get("new_text", "")

    if not path or not old_text:
        return "Error: path and old_text are required"
    if not os.path.isfile(path):
        return f"Error: file '{path}' does not exist"
    if len(new_text) > MAX_EDIT_SIZE:
        return f"Error: new_text too large (max {MAX_EDIT_SIZE} chars)"

    try:
        with open(path, "r", encoding="utf-8", errors="replace") as f:
            content = f.read()
    except Exception as e:
        return f"Error reading file: {e}"

    # Check if old_text exists
    count = content.count(old_text)
    if count == 0:
        # Try with normalized whitespace
        old_normalized = old_text.strip()
        if old_normalized and old_normalized in content:
            return (f"Error: exact match not found, but a stripped version exists. "
                    f"Try using the exact text including leading/trailing whitespace.")
        return f"Error: old_text not found in file. The text must match exactly (including whitespace and indentation)."

    if count > 1:
        return (f"Error: old_text appears {count} times in the file. "
                f"Please provide a more specific (longer) match to avoid ambiguity.")

    # Apply the edit
    new_content = content.replace(old_text, new_text, 1)

    try:
        with open(path, "w", encoding="utf-8") as f:
            f.write(new_content)
    except Exception as e:
        return f"Error writing file: {e}"

    # Return a diff-like preview
    old_lines = old_text.split("\n")
    new_lines = new_text.split("\n")
    diff_preview = []
    for line in old_lines[:5]:
        diff_preview.append(f"- {line}")
    for line in new_lines[:5]:
        diff_preview.append(f"+ {line}")

    return f"Successfully edited {path}\n\nChanges:\n" + "\n".join(diff_preview)


# ---------------------------------------------------------------------------
# write_file_content — write a new file or overwrite
# ---------------------------------------------------------------------------

async def _handle_write_file_content(args: dict, workdir: str) -> str:
    """Write content to a file."""
    path = args.get("path", "")
    content = args.get("content", "")

    if not path:
        return "Error: file path is required"
    if len(content) > MAX_EDIT_SIZE:
        return f"Error: content too large (max {MAX_EDIT_SIZE} chars)"

    # Block writing to protected files
    protected = [".env", "AGENTS.md", "CLAUDE.md"]
    basename = os.path.basename(path)
    if basename in protected:
        return f"BLOCKED: Cannot write to {basename} — this file is protected."

    try:
        parent = os.path.dirname(path)
        if parent:
            os.makedirs(parent, exist_ok=True)
        with open(path, "w", encoding="utf-8") as f:
            f.write(content)
        return f"Successfully wrote {len(content)} bytes to {path}"
    except Exception as e:
        return f"Error writing file: {e}"


# ---------------------------------------------------------------------------
# run_tests — execute the project's test suite
# ---------------------------------------------------------------------------

async def _handle_run_tests(args: dict, workdir: str) -> str:
    """Run the project's test suite with auto-detection."""
    path = args.get("path") or workdir
    override_cmd = args.get("command", "")

    if not os.path.isdir(path):
        return f"Error: directory '{path}' does not exist"

    # Determine the test command
    if override_cmd:
        cmd = override_cmd
    else:
        cmd = _detect_test_command(path)

    if not cmd:
        return (f"Error: could not detect test command for {path}. "
                f"Please specify a command explicitly.")

    try:
        result = subprocess.run(
            cmd, shell=True, capture_output=True, text=True,
            timeout=SHELL_TIMEOUT, cwd=path,
        )
        output = f"Command: {cmd}\nExit code: {result.returncode}\n\n"
        if result.stdout:
            output += f"stdout:\n{result.stdout}\n"
        if result.stderr:
            output += f"stderr:\n{result.stderr}\n"
    except subprocess.TimeoutExpired:
        return f"Error: test command timed out after {SHELL_TIMEOUT}s\nCommand: {cmd}"
    except Exception as e:
        return f"Error running tests: {e}"

    if len(output) > CODING_OUTPUT_LIMIT:
        output = output[:CODING_OUTPUT_LIMIT] + "\n... (truncated)"

    return output


def _detect_test_command(path: str) -> str:
    """Auto-detect the test command based on project files."""
    if os.path.isfile(os.path.join(path, "package.json")):
        # Check for specific test scripts
        try:
            with open(os.path.join(path, "package.json"), "r") as f:
                pkg = json.load(f)
            scripts = pkg.get("scripts", {})
            if "test" in scripts:
                return "npm test"
            if "test:unit" in scripts:
                return "npm run test:unit"
        except (json.JSONDecodeError, IOError):
            pass
        return "npm test"

    if os.path.isfile(os.path.join(path, "pytest.ini")) or \
       os.path.isfile(os.path.join(path, "pyproject.toml")) or \
       os.path.isfile(os.path.join(path, "setup.py")):
        return "python -m pytest"

    if os.path.isfile(os.path.join(path, "go.mod")):
        return "go test ./..."

    if os.path.isfile(os.path.join(path, "Cargo.toml")):
        return "cargo test"

    if os.path.isfile(os.path.join(path, "pom.xml")):
        return "mvn test"

    if os.path.isfile(os.path.join(path, "build.gradle")):
        return "./gradlew test"

    return ""


# ---------------------------------------------------------------------------
# Git operations
# ---------------------------------------------------------------------------

async def _handle_git_status(args: dict, workdir: str) -> str:
    """Show git working tree status."""
    path = args.get("path") or workdir
    if not os.path.isdir(os.path.join(path, ".git")):
        return f"Error: '{path}' is not a git repository"

    try:
        result = subprocess.run(
            ["git", "status", "--short"],
            capture_output=True, text=True, timeout=10, cwd=path,
        )
        output = result.stdout.strip()
        if not output:
            return "Working tree clean — no changes."
        return f"Git status for {path}:\n\n{output}"
    except Exception as e:
        return f"Error: {e}"


async def _handle_git_diff(args: dict, workdir: str) -> str:
    """Show git diff."""
    path = args.get("path") or workdir
    staged = args.get("staged", False)

    if not os.path.isdir(os.path.join(path, ".git")):
        return f"Error: '{path}' is not a git repository"

    cmd = ["git", "diff", "--staged"] if staged else ["git", "diff"]
    try:
        result = subprocess.run(
            cmd, capture_output=True, text=True, timeout=30, cwd=path,
        )
        output = result.stdout.strip()
        if not output:
            return "No changes to show."
        if len(output) > CODING_OUTPUT_LIMIT:
            output = output[:CODING_OUTPUT_LIMIT] + "\n... (truncated)"
        return output
    except Exception as e:
        return f"Error: {e}"


async def _handle_git_commit(args: dict, workdir: str) -> str:
    """Stage and commit changes."""
    path = args.get("path") or workdir
    message = args.get("message", "")
    files = args.get("files", "")

    if not message:
        return "Error: commit message is required"
    if not os.path.isdir(os.path.join(path, ".git")):
        return f"Error: '{path}' is not a git repository"

    # Stage files
    if files:
        file_list = [f.strip() for f in files.split(",")]
        for f in file_list:
            # Never stage .env files
            if f.endswith(".env") or ".env." in f:
                return f"BLOCKED: Cannot stage {f} — .env files are protected"
            try:
                subprocess.run(
                    ["git", "add", f],
                    capture_output=True, text=True, timeout=10, cwd=path,
                )
            except Exception:
                pass
    else:
        # Stage all modified files (excluding .env)
        try:
            result = subprocess.run(
                ["git", "status", "--porcelain"],
                capture_output=True, text=True, timeout=10, cwd=path,
            )
            for line in result.stdout.strip().split("\n"):
                if line:
                    filepath = line[3:].strip()
                    if not filepath.endswith(".env") and ".env." not in filepath:
                        subprocess.run(
                            ["git", "add", filepath],
                            capture_output=True, text=True, timeout=10, cwd=path,
                        )
        except Exception:
            pass

    # Commit
    try:
        result = subprocess.run(
            ["git", "commit", "-m", message],
            capture_output=True, text=True, timeout=30, cwd=path,
        )
        if result.returncode == 0:
            # Get the commit hash
            hash_result = subprocess.run(
                ["git", "rev-parse", "HEAD"],
                capture_output=True, text=True, timeout=5, cwd=path,
            )
            commit_hash = hash_result.stdout.strip()[:7]
            return f"✅ Committed successfully: {commit_hash}\nMessage: {message}\n\n{result.stdout}"
        else:
            return f"❌ Commit failed (exit {result.returncode}):\n{result.stderr}"
    except Exception as e:
        return f"Error committing: {e}"


# ---------------------------------------------------------------------------
# Coding-aware system prompt addition
# ---------------------------------------------------------------------------

CODING_PROMPT_ADDITION = """

## Coding Assistant Mode (Phase 5.2)
You have access to a full coding toolkit that enables Cursor-like workflows:

### Available Coding Tools
- **read_repo**: Read and understand a repository's structure. ALWAYS use this FIRST when starting a coding task.
- **search_code**: Search for patterns in the codebase using grep (regex supported).
- **read_file_lines**: Read a specific file with line numbers before editing.
- **edit_file**: Apply targeted find-and-replace edits. The old_text must match EXACTLY.
- **write_file_content**: Create new files or overwrite entire file contents.
- **run_tests**: Execute the project's test suite (auto-detects test runner).
- **git_status**: Show the working tree status.
- **git_diff**: Show uncommitted changes.
- **git_commit**: Stage and commit changes with conventional commit format.

### Coding Workflow
When asked to make code changes, follow this workflow:
1. **Understand** — Use `read_repo` to see the project structure
2. **Locate** — Use `search_code` to find the relevant files
3. **Read** — Use `read_file_lines` to see the exact content before editing
4. **Edit** — Use `edit_file` for targeted changes or `write_file_content` for new files
5. **Verify** — Use `run_tests` to verify the changes work
6. **Review** — Use `git_diff` to review the changes
7. **Commit** — Use `git_commit` with a conventional commit message

### Conventional Commit Format
- `feat(scope): description` — new feature
- `fix(scope): description` — bug fix
- `refactor(scope): description` — code refactoring
- `docs(scope): description` — documentation
- `test(scope): description` — tests
- `perf(scope): description` — performance

### Rules
- NEVER edit .env files or AGENTS.md
- ALWAYS read a file before editing it
- ALWAYS run tests after making changes when a test suite exists
- Use conventional commit format for all commits
- Explain what you're changing and why before making edits
"""


# ---------------------------------------------------------------------------
# Handler registry
# ---------------------------------------------------------------------------

_HANDLERS = {
    "read_repo": _handle_read_repo,
    "search_code": _handle_search_code,
    "read_file_lines": _handle_read_file_lines,
    "edit_file": _handle_edit_file,
    "write_file_content": _handle_write_file_content,
    "run_tests": _handle_run_tests,
    "git_status": _handle_git_status,
    "git_diff": _handle_git_diff,
    "git_commit": _handle_git_commit,
}


def is_coding_tool(tool_name: str) -> bool:
    """Check if a tool name is a coding assistant tool."""
    return tool_name in _HANDLERS
