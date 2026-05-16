"""
Collect un-reviewed VS Code Copilot chat history across all workspaces.

Scans JSONL transcript files, filters out already-reviewed sessions,
and outputs a structured Markdown summary to stdout.

Usage:
    python collect_chat_history.py [--state-file PATH] [--mark-reviewed]

Options:
    --state-file PATH    Path to review_state.json (default: alongside this script's parent)
    --mark-reviewed      Update review_state.json after collecting (default: false, let caller decide)
    --max-assistant-chars N  Max chars to keep from assistant messages (default: 200)
"""

import json
import os
import sys
import glob
import argparse
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import unquote, urlparse


def get_default_paths():
    """Get default paths for VS Code data on Windows."""
    appdata = os.environ.get("APPDATA", "")
    workspace_storage = os.path.join(appdata, "Code", "User", "workspaceStorage")
    global_storage = os.path.join(appdata, "Code", "User", "globalStorage")
    return workspace_storage, global_storage


def load_review_state(state_file: str) -> dict:
    """Load the review state tracking which sessions have been reviewed."""
    if os.path.exists(state_file):
        try:
            with open(state_file, "r", encoding="utf-8") as f:
                return json.load(f)
        except (json.JSONDecodeError, IOError):
            pass
    return {"reviewed_sessions": {}, "last_review": None}


def save_review_state(state_file: str, state: dict):
    """Save updated review state."""
    state["last_review"] = datetime.now(timezone.utc).isoformat()
    with open(state_file, "w", encoding="utf-8") as f:
        json.dump(state, f, indent=2, ensure_ascii=False)


def load_workspace_mapping(global_storage: str) -> dict:
    """Load workspace storage ID -> folder path mapping from storage.json."""
    storage_json = os.path.join(global_storage, "storage.json")
    mapping = {}
    if not os.path.exists(storage_json):
        return mapping

    try:
        with open(storage_json, "r", encoding="utf-8") as f:
            data = json.load(f)

        # Extract workspace folder mappings from various possible structures
        # The storage.json contains workspace URIs as keys in profileAssociations
        profile_assoc = data.get("profileAssociations", {})
        workspaces = profile_assoc.get("workspaces", {})

        # We need to find the reverse mapping: storage_id -> workspace_uri
        # This requires scanning the workspace storage folders for workspace.json
        workspace_storage_dir = os.path.join(
            os.environ.get("APPDATA", ""),
            "Code", "User", "workspaceStorage"
        )

        for storage_id in os.listdir(workspace_storage_dir):
            ws_json = os.path.join(workspace_storage_dir, storage_id, "workspace.json")
            if os.path.exists(ws_json):
                try:
                    with open(ws_json, "r", encoding="utf-8") as wf:
                        ws_data = json.load(wf)
                    # workspace.json contains "folder" key with URI
                    folder_uri = ws_data.get("folder", "")
                    if folder_uri:
                        # Convert file URI to path
                        parsed = urlparse(folder_uri)
                        folder_path = unquote(parsed.path)
                        # On Windows, strip leading / from /c:/...
                        if folder_path.startswith("/") and len(folder_path) > 2 and folder_path[2] == ":":
                            folder_path = folder_path[1:]
                        mapping[storage_id] = folder_path
                except (json.JSONDecodeError, IOError):
                    pass
    except (json.JSONDecodeError, IOError):
        pass

    return mapping


def parse_transcript(filepath: str, max_assistant_chars: int = 200, skip_lines: int = 0) -> dict | None:
    """Parse a JSONL transcript file and extract conversation summary.
    
    Args:
        skip_lines: Number of lines already reviewed. Only parse lines after this offset.
    """
    session_id = Path(filepath).stem
    events = []
    total_lines = 0

    try:
        with open(filepath, "r", encoding="utf-8") as f:
            for line_num, line in enumerate(f, 1):
                total_lines = line_num
                if line_num <= skip_lines:
                    continue
                line = line.strip()
                if not line:
                    continue
                try:
                    event = json.loads(line)
                    events.append(event)
                except json.JSONDecodeError:
                    continue  # Skip corrupted lines
    except (IOError, PermissionError) as e:
        print(f"<!-- Warning: Could not read {filepath}: {e} -->", file=sys.stderr)
        return None

    if not events:
        return None

    # Extract session metadata
    session_info = {
        "session_id": session_id,
        "file_path": filepath,
        "start_time": None,
        "end_time": None,
        "messages": [],
        "tools_used": set(),
        "topics": [],
        "total_lines": total_lines,
        "is_incremental": skip_lines > 0,
    }

    for event in events:
        event_type = event.get("type", "")
        data = event.get("data", {})
        timestamp = event.get("timestamp", "")

        if event_type == "session.start":
            session_info["start_time"] = data.get("startTime", timestamp)
        elif event_type == "user.message":
            content = data.get("content", "")
            if content:
                session_info["messages"].append({
                    "role": "user",
                    "content": content,
                    "timestamp": timestamp,
                })
        elif event_type == "assistant.message":
            content = data.get("content", "")
            if content:
                # Truncate long assistant messages
                truncated = content[:max_assistant_chars]
                if len(content) > max_assistant_chars:
                    truncated += f"... ({len(content)} chars total)"
                session_info["messages"].append({
                    "role": "assistant",
                    "content": truncated,
                    "timestamp": timestamp,
                })
            # Track tool usage
            tool_requests = data.get("toolRequests", [])
            for tr in tool_requests:
                tool_name = tr.get("toolName", "")
                if tool_name:
                    session_info["tools_used"].add(tool_name)
        elif event_type == "tool.execution_complete":
            tool_name = data.get("toolName", "")
            if tool_name:
                session_info["tools_used"].add(tool_name)

    # Update end time from last event
    if events:
        session_info["end_time"] = events[-1].get("timestamp", "")

    # Convert set to list for serialization
    session_info["tools_used"] = sorted(session_info["tools_used"])

    # Only return if there are actual messages
    if not session_info["messages"]:
        return None

    return session_info


def format_session_markdown(session: dict, workspace_name: str) -> str:
    """Format a single session as Markdown."""
    lines = []

    start = session.get("start_time", "Unknown")
    try:
        dt = datetime.fromisoformat(start.replace("Z", "+00:00"))
        start_formatted = dt.strftime("%Y-%m-%d %H:%M")
    except (ValueError, AttributeError):
        start_formatted = str(start)

    incremental_tag = " (incremental)" if session.get("is_incremental") else ""
    lines.append(f"### Session: {session['session_id'][:8]}...{incremental_tag}")
    lines.append(f"- **Time**: {start_formatted}")
    lines.append(f"- **Workspace**: {workspace_name}")

    if session["tools_used"]:
        lines.append(f"- **Tools Used**: {', '.join(session['tools_used'])}")

    msg_count = len(session["messages"])
    user_msgs = [m for m in session["messages"] if m["role"] == "user"]
    lines.append(f"- **Messages**: {msg_count} total ({len(user_msgs)} user)")

    lines.append("")
    lines.append("#### Conversation:")
    lines.append("")

    for msg in session["messages"]:
        role_label = "👤 User" if msg["role"] == "user" else "🤖 Assistant"
        content = msg["content"].replace("\n", "\n  > ")
        lines.append(f"> **{role_label}**: {content}")
        lines.append("")

    return "\n".join(lines)


def main():
    parser = argparse.ArgumentParser(description="Collect un-reviewed Copilot chat history")
    parser.add_argument(
        "--state-file",
        default=os.path.join(
            os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
            "review_state.json"
        ),
        help="Path to review_state.json"
    )
    parser.add_argument(
        "--mark-reviewed",
        action="store_true",
        help="Update review_state.json after collecting"
    )
    parser.add_argument(
        "--max-assistant-chars",
        type=int,
        default=200,
        help="Max chars to keep from assistant messages (default: 200)"
    )
    args = parser.parse_args()

    workspace_storage, global_storage = get_default_paths()

    if not os.path.exists(workspace_storage):
        print("# No Chat History Found\n\nVS Code workspace storage directory not found.", flush=True)
        sys.exit(0)

    # Load review state
    state = load_review_state(args.state_file)
    # Support both old format (list) and new format (dict with line counts)
    raw_reviewed = state.get("reviewed_sessions", {})
    if isinstance(raw_reviewed, list):
        # Migrate old format: list of IDs -> dict with 0 lines (will re-scan fully)
        reviewed_dict = {sid: 0 for sid in raw_reviewed}
    else:
        reviewed_dict = raw_reviewed

    # Load workspace mappings
    workspace_mapping = load_workspace_mapping(global_storage)

    # Find all JSONL transcript files
    transcript_pattern = os.path.join(
        workspace_storage, "*", "GitHub.copilot-chat", "transcripts", "*.jsonl"
    )
    transcript_files = glob.glob(transcript_pattern)

    if not transcript_files:
        print("# No Chat History Found\n\nNo JSONL transcript files found in any workspace.", flush=True)
        sys.exit(0)

    # Check each transcript: new sessions OR sessions with new content
    transcripts_to_review = []  # (filepath, skip_lines)
    for tf in transcript_files:
        session_id = Path(tf).stem
        if session_id not in reviewed_dict:
            # Completely new session
            transcripts_to_review.append((tf, 0))
        else:
            # Already reviewed — check if file has grown
            reviewed_lines = reviewed_dict[session_id]
            try:
                current_lines = sum(1 for _ in open(tf, "r", encoding="utf-8"))
            except (IOError, PermissionError):
                continue
            if current_lines > reviewed_lines:
                transcripts_to_review.append((tf, reviewed_lines))

    if not transcripts_to_review:
        last_review = state.get("last_review", "N/A")
        print(f"# No New Chat History\n\nAll sessions have been reviewed. Last review: {last_review}", flush=True)
        sys.exit(0)

    # Parse and group by workspace
    workspace_sessions = {}  # workspace_storage_id -> list of sessions
    new_session_ids = []  # list of (session_id, total_lines)

    for tf, skip_lines in transcripts_to_review:
        # Extract workspace storage ID from path
        parts = Path(tf).parts
        # Find the part that comes right before "GitHub.copilot-chat"
        try:
            idx = parts.index("GitHub.copilot-chat")
            ws_storage_id = parts[idx - 1]
        except (ValueError, IndexError):
            ws_storage_id = "unknown"

        session = parse_transcript(tf, max_assistant_chars=args.max_assistant_chars, skip_lines=skip_lines)
        if session:
            if ws_storage_id not in workspace_sessions:
                workspace_sessions[ws_storage_id] = []
            workspace_sessions[ws_storage_id].append(session)
            new_session_ids.append((session["session_id"], session["total_lines"]))

    if not workspace_sessions:
        print("# No New Chat History\n\nFound transcript files but no parseable messages.", flush=True)
        sys.exit(0)

    # Mark as reviewed BEFORE output (so broken pipe won't skip it)
    if args.mark_reviewed and new_session_ids:
        for sid, lines in new_session_ids:
            reviewed_dict[sid] = lines
        state["reviewed_sessions"] = reviewed_dict
        save_review_state(args.state_file, state)

    # Output Markdown summary
    total_sessions = sum(len(sessions) for sessions in workspace_sessions.values())
    total_messages = sum(
        len(s["messages"])
        for sessions in workspace_sessions.values()
        for s in sessions
    )

    print(f"# Chat History Review Summary")
    print(f"")
    print(f"- **Date**: {datetime.now().strftime('%Y-%m-%d %H:%M')}")
    print(f"- **New Sessions**: {total_sessions}")
    print(f"- **Total Messages**: {total_messages}")
    print(f"- **Workspaces**: {len(workspace_sessions)}")
    if state.get("last_review"):
        print(f"- **Last Review**: {state['last_review']}")
    print(f"")

    for ws_id, sessions in sorted(workspace_sessions.items()):
        ws_name = workspace_mapping.get(ws_id, f"Unknown Workspace ({ws_id[:8]}...)")
        # Shorten workspace name for display
        if len(ws_name) > 80:
            ws_name = "..." + ws_name[-77:]

        print(f"## Workspace: {ws_name}")
        print(f"")

        # Sort sessions by start time
        sessions.sort(key=lambda s: s.get("start_time") or "")

        for session in sessions:
            print(format_session_markdown(session, ws_name))
            print("---")
            print("")

    if args.mark_reviewed and new_session_ids:
        incremental = sum(1 for s in workspace_sessions.values() for sess in s if sess.get("is_incremental"))
        fresh = len(new_session_ids) - incremental
        parts = []
        if fresh:
            parts.append(f"{fresh} new")
        if incremental:
            parts.append(f"{incremental} incremental")
        print(f"\n<!-- Marked {' + '.join(parts)} sessions as reviewed -->", flush=True)

    sys.stdout.flush()


if __name__ == "__main__":
    main()
