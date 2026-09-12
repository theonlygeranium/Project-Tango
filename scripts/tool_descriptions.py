def describe_tool_call(tool_name: str, tool_args: dict) -> str:
    """
    Translate a tool name + arguments into a brief, human-readable description
    for live progress display in Discord.

    Returns a short string like:
        "📖 Reading /opt/Project-Tango/scripts/schubert-bot-v2.py (lines 100-150)"
        "🔍 Searching for 'def run_agent' in /opt/Project-Tango/scripts"
        "📝 Deploying /opt/Project-Tango/scripts/memory_store.py (40KB)"
        "🔄 Restarting schubert-bot.service"
        "📋 Viewing logs for schubert-bot.service (30 lines)"

    Falls back to the raw tool name if no specific handler exists.
    """

    # --- Dev tools ---

    if tool_name == "read_code":
        path = tool_args.get("path", "?")
        # Shorten common paths for display
        short_path = path.replace("/opt/Project-Tango/scripts/", "") if path else "?"
        start = tool_args.get("start_line", 1)
        end = tool_args.get("end_line", 50)
        return f"📖 Reading {short_path} (lines {start}-{end})"

    if tool_name == "search_code":
        pattern = tool_args.get("pattern", "?")
        path = tool_args.get("path", "/opt/Project-Tango/scripts")
        short_path = path.replace("/opt/Project-Tango/scripts/", ".../") if path else "?"
        return f"🔍 Searching for '{pattern}' in {short_path}"

    if tool_name == "deploy_file":
        path = tool_args.get("path", "?")
        content = tool_args.get("content", "")
        size_str = f"{len(content)//1024}KB" if len(content) > 1024 else f"{len(content)}B"
        short_path = path.replace("/opt/Project-Tango/scripts/", "") if path else "?"
        return f"📝 Deploying {short_path} ({size_str})"

    if tool_name == "restart_service":
        service = tool_args.get("service", "?")
        return f"🔄 Restarting {service}"

    if tool_name == "view_logs":
        service = tool_args.get("service", "schubert-bot.service")
        lines = tool_args.get("lines", 30)
        return f"📋 Viewing logs for {service} ({lines} lines)"

    if tool_name == "run_test":
        suite = tool_args.get("suite", "v2_init")
        return f"🧪 Running test suite: {suite}"

    if tool_name == "service_status":
        return "📊 Checking all service statuses"

    if tool_name == "web_search":
        query = tool_args.get("query", "?")
        return f"🌐 Searching web: '{query[:60]}'"

    if tool_name == "query_memory":
        action = tool_args.get("action", tool_args.get("type", "search"))
        query = tool_args.get("query", tool_args.get("name", ""))
        if query:
            return f"🧠 Memory {action}: '{query[:50]}'"
        return f"🧠 Memory {action}"

    if tool_name == "cloudflare":
        action = tool_args.get("action", "?")
        return f"☁️ Cloudflare: {action}"

    if tool_name == "create_poll":
        question = tool_args.get("question", "?")
        num_answers = len(tool_args.get("answers", []))
        duration = tool_args.get("duration_hours", 24)
        return f"📊 Creating poll: '{question[:50]}' ({num_answers} options, {duration}h)"

    # --- MeetScribe tools ---

    if tool_name == "query_meetings":
        question = tool_args.get("question", "?")
        return f"📝 Querying meetings: '{question[:60]}'"

    if tool_name == "search_meetings":
        query = tool_args.get("query", "?")
        return f"🔍 Searching meetings: '{query[:60]}'"

    if tool_name == "list_recent_meetings":
        limit = tool_args.get("limit", 10)
        return f"📋 Listing recent meetings ({limit})"

    if tool_name == "get_meeting_notes":
        session_id = tool_args.get("session_id", "?")
        return f"📝 Fetching notes for session #{session_id}"

    if tool_name == "get_meeting_transcript":
        session_id = tool_args.get("session_id", "?")
        return f"💬 Fetching transcript for session #{session_id}"

    if tool_name == "get_meetscribe_status":
        return "📊 Checking MeetScribe memory index"

    # --- MCP tools (namespaced as server__tool) ---

    if "__" in tool_name:
        parts = tool_name.split("__", 1)
        server = parts[0]
        tool = parts[1] if len(parts) > 1 else ""

        # Common MCP tool descriptions
        mcp_descriptions = {
            # Schubert Nexus
            "schubert_run_command": lambda a: f"💻 Shell: {a.get('command', '?')[:80]}",
            "schubert_read_file": lambda a: f"📖 Reading {a.get('path', '?')}",
            "schubert_write_file": lambda a: f"📝 Writing {a.get('path', '?')}",
            "schubert_write_file_binary": lambda a: f"📝 Deploying {a.get('path', '?')} (binary)",
            "schubert_list_directory": lambda a: f"📂 Listing {a.get('path', '?')}",
            "schubert_get_network_status": lambda a: "🌐 Checking network status",
            # GitHub
            "github_get_file_contents": lambda a: f"📄 GitHub: {a.get('path', '?')} in {a.get('repo', '?')}",
            "github_search_code": lambda a: f"🔍 GitHub code search: '{a.get('q', '?')[:60]}'",
            "github_create_issue": lambda a: f"🐛 GitHub issue in {a.get('repo', '?')}: {a.get('title', '?')[:50]}",
            "github_list_issues": lambda a: f"📋 GitHub issues in {a.get('repo', '?')}",
            "github_create_pull_request": lambda a: f"🔀 GitHub PR in {a.get('repo', '?')}: {a.get('title', '?')[:50]}",
            "github_get_pull_request": lambda a: f"🔀 GitHub PR #{a.get('pull_number', '?')} in {a.get('repo', '?')}",
            "github_merge_pull_request": lambda a: f"🔀 Merging PR #{a.get('pull_number', '?')} in {a.get('repo', '?')}",
            "github_create_commit": lambda a: f"📦 GitHub commit to {a.get('repo', '?')}",
            "github_get_commit": lambda a: f"📦 GitHub commit {a.get('sha', '?')[:8]} in {a.get('repo', '?')}",
            "github_list_branches": lambda a: f"🌿 GitHub branches in {a.get('repo', '?')}",
            "github_create_branch": lambda a: f"🌿 GitHub branch {a.get('branch', '?')} in {a.get('repo', '?')}",
            # Gmail
            "gmail_send_email": lambda a: f"📧 Sending email to {a.get('to', '?')}",
            "gmail_list_messages": lambda a: "📧 Listing Gmail messages",
            "gmail_get_message": lambda a: f"📧 Reading Gmail message {a.get('message_id', '?')[:20]}",
            # PostgreSQL
            "postgres_mcp_query": lambda a: f"🗄️ SQL query: {a.get('query', '?')[:80]}",
            # Redis
            "redis_mcp_query": lambda a: f"🗄️ Redis: {a.get('command', '?')[:80]}",
            # Ollama
            "ollama_list_models": lambda a: "🤖 Listing Ollama models",
            "ollama_generate": lambda a: f"🤖 Ollama generate: {a.get('model', '?')}",
        }

        desc_func = mcp_descriptions.get(tool)
        if desc_func:
            try:
                return desc_func(tool_args)
            except Exception:
                pass

        # Generic MCP tool description
        return f"🔗 [{server}] {tool}"

    return tool_name


def describe_tool_thinking(tool_name: str, tool_args: dict) -> str:
    """
    Generate a brief 'thinking' status for the progress embed.
    This is the one-line status shown at the top of the embed.
    """
    desc = describe_tool_call(tool_name, tool_args)
    # Remove emoji prefix for the thinking line (it's in the tool calls list already)
    if desc and desc[0] in "📖🔍📝🔄📋🧪📊🌐🧠☁️💻📂📄🐛📋🔀📦🌿📧🗄️🤖🔗":
        desc = desc[1:].strip()
    return desc
