"""Collect bounded, unreviewed Copilot and Codex chat history.

The collector deliberately reads local transcripts only.  It writes no chat
content: the optional review state contains source/session cursors only.

Usage:
    python collect_chat_history.py --source all --lookback-days 90
    python collect_chat_history.py --source codex --mark-reviewed
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Iterable


STATE_VERSION = 2
SOURCES = ("copilot", "codex")
DEFAULT_MAX_MESSAGE_CHARS = 300


@dataclass
class Message:
    role: str
    content: str
    timestamp: str = ""


@dataclass
class Session:
    source: str
    session_id: str
    file_path: Path
    start_time: str = ""
    end_time: str = ""
    workspace: str = ""
    messages: list[Message] = field(default_factory=list)
    tools_used: set[str] = field(default_factory=set)
    total_lines: int = 0
    skip_lines: int = 0

    @property
    def state_key(self) -> str:
        # Cursor keys must match discovery before Codex replaces the display ID
        # with the session_meta identifier.
        return self.file_path.stem

    @property
    def is_incremental(self) -> bool:
        return self.skip_lines > 0


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


def parse_time(value: str) -> datetime | None:
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)


def redact_text(value: str) -> str:
    """Remove common credentials before transcript text reaches an LLM or report."""
    value = re.sub(
        r"(?i)(\b(?:api[_-]?key|access[_-]?token|secret|password)\s*[=:]\s*)([^\s'\"]+)",
        r"\1[REDACTED]",
        value,
    )
    value = re.sub(r"\bsk-[A-Za-z0-9_-]{16,}\b", "[REDACTED_OPENAI_KEY]", value)
    value = re.sub(r"\bgh[pousr]_[A-Za-z0-9_]{20,}\b", "[REDACTED_GITHUB_TOKEN]", value)
    value = re.sub(r"\bAKIA[0-9A-Z]{16}\b", "[REDACTED_AWS_KEY]", value)
    return value


def bound_text(value: Any, limit: int) -> str:
    text = redact_text(str(value or "")).strip()
    if len(text) <= limit:
        return text
    return text[:limit] + f"... ({len(text)} chars total)"


def content_to_text(content: Any) -> str:
    """Extract text from Codex response content without retaining tool output."""
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        return "\n".join(filter(None, (content_to_text(item) for item in content)))
    if isinstance(content, dict):
        for key in ("text", "input_text", "output_text"):
            if isinstance(content.get(key), str):
                return content[key]
    return ""


def default_state() -> dict[str, Any]:
    return {
        "schema_version": STATE_VERSION,
        "sources": {source: {"reviewed_sessions": {}} for source in SOURCES},
        "last_review": None,
    }


def normalize_state(raw: dict[str, Any] | None) -> dict[str, Any]:
    """Migrate the original Copilot-only state shape without losing cursors."""
    state = default_state()
    raw = raw or {}
    if isinstance(raw.get("sources"), dict):
        for source in SOURCES:
            source_state = raw["sources"].get(source, {})
            reviewed = source_state.get("reviewed_sessions", {}) if isinstance(source_state, dict) else {}
            if isinstance(reviewed, dict):
                state["sources"][source]["reviewed_sessions"] = reviewed
    else:
        reviewed = raw.get("reviewed_sessions", {})
        if isinstance(reviewed, list):
            reviewed = {session_id: 0 for session_id in reviewed}
        if isinstance(reviewed, dict):
            state["sources"]["copilot"]["reviewed_sessions"] = reviewed
    state["last_review"] = raw.get("last_review")
    return state


def load_review_state(state_file: str | Path) -> dict[str, Any]:
    try:
        with Path(state_file).open(encoding="utf-8") as handle:
            return normalize_state(json.load(handle))
    except (OSError, json.JSONDecodeError):
        return default_state()


def save_review_state(state_file: str | Path, state: dict[str, Any]) -> None:
    path = Path(state_file)
    path.parent.mkdir(parents=True, exist_ok=True)
    state["schema_version"] = STATE_VERSION
    state["last_review"] = utc_now().isoformat()
    path.write_text(json.dumps(state, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


def copilot_storage_roots(home: Path | None = None) -> list[Path]:
    home = home or Path.home()
    roots = [
        home / "Library" / "Application Support" / "Code" / "User",
        home / ".config" / "Code" / "User",
    ]
    appdata = os.environ.get("APPDATA")
    if appdata:
        roots.append(Path(appdata) / "Code" / "User")
    return [root for root in roots if root.exists()]


def get_default_paths() -> tuple[str, str]:
    """Compatibility helper retained for callers of the former Copilot collector."""
    root = next(iter(copilot_storage_roots()), Path(os.environ.get("APPDATA", "")) / "Code" / "User")
    return str(root / "workspaceStorage"), str(root / "globalStorage")


def load_workspace_mapping(global_storage: Path) -> dict[str, str]:
    mapping: dict[str, str] = {}
    workspace_storage = global_storage.parent / "workspaceStorage"
    if not workspace_storage.exists():
        return mapping
    for workspace_json in workspace_storage.glob("*/workspace.json"):
        try:
            data = json.loads(workspace_json.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        folder = data.get("folder", "")
        if folder.startswith("file://"):
            folder = folder.removeprefix("file://")
            if len(folder) > 2 and folder[0] == "/" and folder[2:3] == ":":
                folder = folder[1:]
        if folder:
            mapping[workspace_json.parent.name] = folder
    return mapping


def discover_copilot_files(roots: Iterable[Path]) -> list[Path]:
    candidates: dict[str, Path] = {}
    for root in roots:
        for path in (root / "workspaceStorage").glob("*/GitHub.copilot-chat/transcripts/*.jsonl"):
            previous = candidates.get(path.stem)
            if previous is None or path.stat().st_mtime > previous.stat().st_mtime:
                candidates[path.stem] = path
    return sorted(candidates.values())


def discover_codex_files(home: Path | None = None) -> list[Path]:
    home = home or Path.home()
    roots = [home / ".codex" / "sessions", home / ".codex" / "archived_sessions"]
    candidates: dict[str, Path] = {}
    for root in roots:
        if not root.exists():
            continue
        for path in root.rglob("*.jsonl"):
            key = str(path.relative_to(root))
            previous = candidates.get(key)
            if previous is None or path.stat().st_mtime > previous.stat().st_mtime:
                candidates[key] = path
    return sorted(candidates.values())


def read_jsonl(path: Path, skip_lines: int = 0) -> tuple[list[dict[str, Any]], int]:
    events: list[dict[str, Any]] = []
    total_lines = 0
    try:
        with path.open(encoding="utf-8") as handle:
            for total_lines, line in enumerate(handle, 1):
                if total_lines <= skip_lines or not line.strip():
                    continue
                try:
                    events.append(json.loads(line))
                except json.JSONDecodeError:
                    continue
    except (OSError, UnicodeDecodeError):
        return [], 0
    return events, total_lines


def parse_copilot_transcript(path: Path, max_message_chars: int, skip_lines: int = 0, workspace: str = "") -> Session | None:
    events, total_lines = read_jsonl(path, skip_lines)
    if not events:
        return None
    session = Session("copilot", path.stem, path, workspace=workspace, total_lines=total_lines, skip_lines=skip_lines)
    for event in events:
        data = event.get("data", {})
        event_type = event.get("type", "")
        timestamp = str(event.get("timestamp", ""))
        if event_type == "session.start":
            session.start_time = str(data.get("startTime", timestamp))
        elif event_type in {"user.message", "assistant.message"}:
            content = bound_text(data.get("content", ""), max_message_chars)
            if content:
                role = "user" if event_type == "user.message" else "assistant"
                session.messages.append(Message(role, content, timestamp))
            for request in data.get("toolRequests", []):
                if request.get("toolName"):
                    session.tools_used.add(str(request["toolName"]))
        elif event_type == "tool.execution_complete" and data.get("toolName"):
            session.tools_used.add(str(data["toolName"]))
        session.end_time = timestamp or session.end_time
    return session if session.messages else None


def parse_codex_transcript(path: Path, max_message_chars: int, skip_lines: int = 0) -> Session | None:
    events, total_lines = read_jsonl(path, skip_lines)
    if not events:
        return None
    session = Session("codex", path.stem, path, total_lines=total_lines, skip_lines=skip_lines)
    primary_messages: list[Message] = []
    fallback_messages: list[Message] = []
    for event in events:
        payload = event.get("payload", {})
        if not isinstance(payload, dict):
            continue
        event_type = event.get("type", "")
        timestamp = str(event.get("timestamp", ""))
        if event_type == "session_meta":
            session.session_id = str(payload.get("session_id") or session.session_id)
            session.start_time = str(payload.get("timestamp", timestamp))
            session.workspace = str(payload.get("cwd", ""))
        elif event_type == "response_item":
            item_type = payload.get("type")
            if item_type == "message" and payload.get("role") in {"user", "assistant"}:
                content = bound_text(content_to_text(payload.get("content")), max_message_chars)
                if content:
                    primary_messages.append(Message(str(payload["role"]), content, timestamp))
            elif item_type in {"function_call", "custom_tool_call"} and payload.get("name"):
                session.tools_used.add(str(payload["name"]))
        elif event_type == "event_msg":
            item_type = payload.get("type")
            if item_type in {"user_message", "agent_message"}:
                content = bound_text(payload.get("message", ""), max_message_chars)
                if content:
                    role = "user" if item_type == "user_message" else "assistant"
                    fallback_messages.append(Message(role, content, timestamp))
            elif isinstance(item_type, str) and item_type.endswith("_tool_call"):
                session.tools_used.add(item_type)
        session.end_time = timestamp or session.end_time
    session.messages = primary_messages or fallback_messages
    return session if session.messages else None


def parse_transcript(filepath: str, max_assistant_chars: int = DEFAULT_MAX_MESSAGE_CHARS, skip_lines: int = 0) -> dict[str, Any] | None:
    """Backward-compatible Copilot parser used by older integrations."""
    session = parse_copilot_transcript(Path(filepath), max_assistant_chars, skip_lines)
    if not session:
        return None
    return session_to_legacy_dict(session)


def session_to_legacy_dict(session: Session) -> dict[str, Any]:
    return {
        "session_id": session.session_id,
        "file_path": str(session.file_path),
        "start_time": session.start_time,
        "end_time": session.end_time,
        "messages": [{"role": item.role, "content": item.content, "timestamp": item.timestamp} for item in session.messages],
        "tools_used": sorted(session.tools_used),
        "total_lines": session.total_lines,
        "is_incremental": session.is_incremental,
    }


def in_lookback_window(path: Path, lookback_days: int) -> bool:
    cutoff = utc_now() - timedelta(days=lookback_days)
    return datetime.fromtimestamp(path.stat().st_mtime, timezone.utc) >= cutoff


def collect_sessions(
    source: str,
    state: dict[str, Any],
    lookback_days: int,
    max_message_chars: int,
    copilot_roots: Iterable[Path] | None = None,
    codex_files: Iterable[Path] | None = None,
) -> list[Session]:
    selected = SOURCES if source == "all" else (source,)
    collected: list[Session] = []
    roots = list(copilot_roots) if copilot_roots is not None else copilot_storage_roots()
    workspace_maps = {root: load_workspace_mapping(root / "globalStorage") for root in roots}
    for provider in selected:
        files = discover_copilot_files(roots) if provider == "copilot" else list(codex_files if codex_files is not None else discover_codex_files())
        reviewed = state["sources"][provider]["reviewed_sessions"]
        for path in files:
            session_id = path.stem
            skip_lines = int(reviewed.get(session_id, 0))
            if not skip_lines and not in_lookback_window(path, lookback_days):
                continue
            workspace = ""
            if provider == "copilot":
                try:
                    workspace_id = path.parents[2].name
                    workspace = next((mapping.get(workspace_id, "") for mapping in workspace_maps.values()), "")
                except IndexError:
                    pass
                parsed = parse_copilot_transcript(path, max_message_chars, skip_lines, workspace)
            else:
                parsed = parse_codex_transcript(path, max_message_chars, skip_lines)
            if parsed:
                collected.append(parsed)
    return sorted(collected, key=lambda item: (item.start_time, item.source, item.session_id))


def mark_reviewed(state: dict[str, Any], sessions: Iterable[Session]) -> None:
    for session in sessions:
        state["sources"][session.source]["reviewed_sessions"][session.state_key] = session.total_lines


def format_session_markdown(session: Session, workspace_name: str | None = None) -> str:
    start = parse_time(session.start_time)
    formatted = start.strftime("%Y-%m-%d %H:%M") if start else (session.start_time or "Unknown")
    incremental = " (incremental)" if session.is_incremental else ""
    lines = [
        f"### {session.source.title()} session: {session.session_id[:8]}...{incremental}",
        f"- **Time**: {formatted}",
        f"- **Workspace**: {workspace_name or session.workspace or 'Unknown'}",
        f"- **Messages**: {len(session.messages)} total ({sum(item.role == 'user' for item in session.messages)} user)",
    ]
    if session.tools_used:
        lines.append(f"- **Tools Used**: {', '.join(sorted(session.tools_used))}")
    lines.extend(["", "#### Bounded transcript excerpt", ""])
    for item in session.messages:
        label = "User" if item.role == "user" else "Assistant"
        lines.extend([f"> **{label}**: {item.content.replace(chr(10), chr(10) + '  > ')}", ""])
    return "\n".join(lines)


def main() -> int:
    parser = argparse.ArgumentParser(description="Collect bounded, unreviewed Copilot and Codex chat history")
    parser.add_argument("--state-file", default=str(Path(__file__).resolve().parents[1] / "review_state.json"))
    parser.add_argument("--mark-reviewed", action="store_true", help="Advance cursors after printing the collected sessions")
    parser.add_argument("--source", choices=("all", *SOURCES), default="all")
    parser.add_argument("--lookback-days", type=int, default=90, help="Initial-history window; later runs are incremental")
    parser.add_argument("--max-message-chars", type=int, default=DEFAULT_MAX_MESSAGE_CHARS)
    parser.add_argument("--max-assistant-chars", type=int, dest="legacy_message_chars", help="Compatibility alias for --max-message-chars")
    args = parser.parse_args()
    if args.lookback_days < 1 or args.max_message_chars < 1:
        parser.error("lookback and message limits must be positive")
    max_chars = args.legacy_message_chars or args.max_message_chars
    state = load_review_state(args.state_file)
    sessions = collect_sessions(args.source, state, args.lookback_days, max_chars)
    if not sessions:
        print("# No New Chat History\n\nNo unreviewed Copilot or Codex sessions were found in the selected window.")
        return 0
    print("# Chat History Review Summary\n")
    print(f"- **Date**: {utc_now().strftime('%Y-%m-%d %H:%M UTC')}")
    print(f"- **Sources**: {', '.join(sorted({item.source for item in sessions}))}")
    print(f"- **Sessions**: {len(sessions)}")
    print(f"- **Messages**: {sum(len(item.messages) for item in sessions)}")
    print("- **Privacy**: bounded and redacted excerpts; raw transcripts are not persisted\n")
    for session in sessions:
        print(format_session_markdown(session))
        print("---\n")
    if args.mark_reviewed:
        mark_reviewed(state, sessions)
        save_review_state(args.state_file, state)
        print("<!-- Marked collected sessions as reviewed -->")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
