def detect_limitation_warnings(user_input: str) -> str:
    """
    Analyze user input for patterns that match known Architect bot limitations.
    Returns a warning string to inject into the agent context, or empty string.

    The Architect has five documented capability gaps. This function detects
    when a user request is likely to hit one and returns a clear explanation
    so the LLM can proactively warn the user before attempting the task.
    """
    text = user_input.lower()
    warnings = []

    # 1. No surgical file editing
    surgical_patterns = [
        "replace this function", "replace the function", "change this method",
        "modify this part", "edit this section", "update this function",
        "replace this class", "change this line", "modify this block",
        "swap this", "patch this function", "rewrite this function",
        "update just the", "change just the", "modify just the",
        "replace just the", "edit just the",
    ]
    large_file_patterns = [
        "schubert-bot-v2.py", "schubert-bot.py", "architect-bot.py",
        "memory_store.py", "coding_assistant.py", "webhook_handler.py",
        "scheduler.py", "context_builder.py", "session_manager.py",
    ]
    mentions_surgical = any(p in text for p in surgical_patterns)
    mentions_large_file = any(p in text for p in large_file_patterns)
    if mentions_surgical or (mentions_large_file and any(w in text for w in ["edit", "modify", "change", "update", "replace", "patch"])):
        warnings.append(
            "**Surgical Editing Limitation**: My `deploy_file` tool writes entire file contents - "
            "there is no find-and-replace or surgical edit capability. To change one function in a "
            "large file (e.g., schubert-bot-v2.py at 136KB), I would need to regenerate and output "
            "the entire file, which is token-expensive and error-prone. For surgical edits to large "
            "files, consider using WRITER Agent (which has a `str_replace` tool), or ask me to make "
            "the change via a shell command using `sed` or a Python patch script instead."
        )

    # 2. No binary file deployment
    binary_patterns = [
        "binary", ".png", ".jpg", ".jpeg", ".gif", ".pdf", ".zip", ".tar",
        ".gz", ".mp3", ".mp4", ".wav", ".woff", ".woff2", ".ico",
        "image file", "deploy image", "upload binary",
    ]
    if any(p in text for p in binary_patterns):
        warnings.append(
            "**Binary Deployment Limitation**: My `deploy_file` tool uses text-mode file writing "
            "(`open(path, 'w')`). It cannot reliably deploy binary files (images, PDFs, archives, "
            "fonts) or files containing non-UTF-8 content. Binary data may be corrupted during "
            "deployment. For binary file deployment, use WRITER Agent's binary file writer or "
            "transfer the file via `scp`/`wget`/`curl` through a shell command instead."
        )

    # 3. No structured planning
    planning_patterns = [
        "multi-phase", "multiple phases", "step by step", "step-by-step",
        "migration", "migrate", "refactor the entire", "rewrite the whole",
        "multiple steps", "sequential steps", "phase 1", "phase 2",
        "first do", "then do", "after that", "multi-step",
        "complex change", "large change", "big change", "major change",
        "overhaul", "restructure",
    ]
    if any(p in text for p in planning_patterns):
        warnings.append(
            "**Structured Planning Limitation**: I run a single conversational agent loop with "
            "no task dependencies, plan tracking, or progress visibility. For complex multi-phase "
            "work (e.g., a database migration with 7 sequential steps and verification at each "
            "stage), you will need to drive the workflow manually in the conversation - I cannot "
            "track progress or show you what step I am on. WRITER Agent has structured planning "
            "with task tracking and dependency management for this type of work."
        )

    # 4. No subagent delegation
    parallel_patterns = [
        "in parallel", "parallel", "simultaneously", "at the same time",
        "multiple tasks", "several tasks", "delegate", "subagent",
        "spawn", "concurrent", "while also",
    ]
    if any(p in text for p in parallel_patterns):
        warnings.append(
            "**Subagent Delegation Limitation**: I run a single agent loop and cannot spawn "
            "parallel child agents for independent subtasks. If you need multiple independent "
            "tasks done simultaneously, I will handle them sequentially. WRITER Agent can delegate "
            "to parallel child agents for concurrent work."
        )

    # 5. Hardcoded test suites
    test_patterns = [
        "run test", "run a test", "test suite", "run the test",
        "verify with", "verify by running", "run this script",
        "run this python", "execute this python", "run custom test",
        "run a custom", "run verification", "run the verification",
        "custom test", "custom verification", "verify the",
    ]
    if any(p in text for p in test_patterns):
        if not any(s in text for s in ["v2_init", "phase3", "phase 3"]):
            warnings.append(
                "**Test Suite Limitation**: My `run_test` tool only supports two hardcoded test "
                "suites: `v2_init` and `phase3`. I cannot run arbitrary Python verification scripts "
                "through this tool. For custom verification scripts, I can try to execute them via "
                "a shell command or an MCP shell tool, but the dedicated `run_test` tool is limited "
                "to the two built-in suites."
            )

    if not warnings:
        return ""

    header = (
        "\n\n## Capability Limitation Warning\n"
        "The following limitations may affect this task. Consider whether WRITER Agent "
        "(which has surgical editing, binary deployment, structured planning, and subagent "
        "delegation) would be better suited, or whether I can work around these limitations.\n\n"
    )
    return header + "\n\n".join(warnings)
