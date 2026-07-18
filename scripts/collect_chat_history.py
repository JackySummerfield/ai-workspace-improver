"""Collect bounded local Copilot and Codex history for review.

The collector separates physical JSONL transcript segments from logical review
sessions. State stores only per-segment cursors and Codex identity mappings; it
never stores chat content.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Iterable


STATE_VERSION = 5
SOURCES = ("copilot", "codex")
DEFAULT_MAX_MESSAGE_CHARS = 300


@dataclass
class Message:
    role: str
    content: str
    timestamp: str = ""


@dataclass(frozen=True)
class RuntimeIncident:
    """A privacy-safe classification of tool friction, never raw tool output."""

    category: str
    recovered: bool = False


@dataclass
class Session:
    """One physical JSONL transcript segment and its bounded contents."""

    source: str
    session_id: str
    file_path: Path
    identity_known: bool
    start_time: str = ""
    end_time: str = ""
    workspace: str = ""
    messages: list[Message] = field(default_factory=list)
    tools_used: set[str] = field(default_factory=set)
    runtime_incidents: list[RuntimeIncident] = field(default_factory=list)
    total_lines: int = 0
    skip_lines: int = 0

    @property
    def state_key(self) -> str:
        """Stable cursor key for the physical segment, not its logical session."""
        return self.file_path.stem

    @property
    def is_incremental(self) -> bool:
        return self.skip_lines > 0


@dataclass
class ReviewSession:
    """One logical review unit formed from one or more transcript segments."""

    source: str
    session_id: str
    identity_known: bool
    segments: list[Session]
    start_time: str
    end_time: str
    workspace: str
    messages: list[Message]
    tools_used: set[str]
    runtime_incidents: list[RuntimeIncident]

    @property
    def segment_count(self) -> int:
        return len(self.segments)

    @property
    def is_incremental(self) -> bool:
        return any(segment.is_incremental for segment in self.segments)


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


def timestamp_sort_key(value: str) -> tuple[int, datetime]:
    parsed = parse_time(value)
    return (0, parsed) if parsed else (1, datetime.max.replace(tzinfo=timezone.utc))


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
    return text if len(text) <= limit else text[:limit] + f"... ({len(text)} chars total)"


def content_to_text(content: Any) -> str:
    """Extract Codex message text without retaining tool output."""
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        return "\n".join(filter(None, (content_to_text(item) for item in content)))
    if isinstance(content, dict):
        for key in ("text", "input_text", "output_text", "output", "error", "message", "result"):
            if isinstance(content.get(key), str):
                return content[key]
    return ""


def classify_runtime_incidents(value: Any) -> list[RuntimeIncident]:
    """Classify known tool failures without retaining commands or error text."""
    if not isinstance(value, (str, dict, list)):
        return []
    text = redact_text(content_to_text(value) if isinstance(value, dict) else str(value)).lower()
    if not text:
        return []
    incidents: list[RuntimeIncident] = []
    if any(marker in text for marker in ("operation not permitted", "permission denied", "sandbox")):
        incidents.append(RuntimeIncident("sandbox_permission"))
    if any(marker in text for marker in ("fetch failed", "dns", "network is unreachable", "could not resolve", "connection refused")):
        incidents.append(RuntimeIncident("network"))
    if "require_escalated" in text or ("approval" in text and "permission" in text):
        incidents.append(RuntimeIncident("permission_escalation", recovered=True))
    if any(marker in text for marker in ("exit code", "non-zero", "command failed")):
        incidents.append(RuntimeIncident("tool_failure"))
    return incidents


def default_source_state() -> dict[str, dict[str, int] | dict[str, str]]:
    return {"reviewed_segments": {}, "segment_sessions": {}}


def default_state() -> dict[str, Any]:
    return {
        "schema_version": STATE_VERSION,
        "sources": {source: default_source_state() for source in SOURCES},
        "last_review": None,
        "pending_reviews": {},
        "completed_reviews": 0,
        "last_deep_audit_review": 0,
    }


def normalize_state(raw: dict[str, Any] | None) -> dict[str, Any]:
    """Migrate v1/v2 cursor state to v3 physical-segment cursor state."""
    state = default_state()
    raw = raw or {}
    if isinstance(raw.get("sources"), dict):
        for source in SOURCES:
            source_state = raw["sources"].get(source, {})
            if not isinstance(source_state, dict):
                continue
            reviewed = source_state.get("reviewed_segments", source_state.get("reviewed_sessions", {}))
            if isinstance(reviewed, dict):
                state["sources"][source]["reviewed_segments"] = reviewed
            identities = source_state.get("segment_sessions", {})
            if isinstance(identities, dict):
                state["sources"][source]["segment_sessions"] = identities
    else:
        reviewed = raw.get("reviewed_sessions", {})
        if isinstance(reviewed, list):
            reviewed = {session_id: 0 for session_id in reviewed}
        if isinstance(reviewed, dict):
            state["sources"]["copilot"]["reviewed_segments"] = reviewed
    state["last_review"] = raw.get("last_review")
    if isinstance(raw.get("pending_reviews"), dict):
        state["pending_reviews"] = raw["pending_reviews"]
    if isinstance(raw.get("completed_reviews"), int):
        state["completed_reviews"] = raw["completed_reviews"]
    if isinstance(raw.get("last_deep_audit_review"), int):
        state["last_deep_audit_review"] = raw["last_deep_audit_review"]
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
    if appdata := os.environ.get("APPDATA"):
        roots.append(Path(appdata) / "Code" / "User")
    return [root for root in roots if root.exists()]


def get_default_paths() -> tuple[str, str]:
    """Compatibility helper retained for former Copilot-only callers."""
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
    segment = Session("copilot", path.stem, path, True, workspace=workspace, total_lines=total_lines, skip_lines=skip_lines)
    for event in events:
        data = event.get("data", {})
        event_type = event.get("type", "")
        timestamp = str(event.get("timestamp", ""))
        if event_type == "session.start":
            segment.start_time = str(data.get("startTime", timestamp))
        elif event_type in {"user.message", "assistant.message"}:
            content = bound_text(data.get("content", ""), max_message_chars)
            if content:
                segment.messages.append(Message("user" if event_type == "user.message" else "assistant", content, timestamp))
            for request in data.get("toolRequests", []):
                if request.get("toolName"):
                    segment.tools_used.add(str(request["toolName"]))
        elif event_type == "tool.execution_complete" and data.get("toolName"):
            segment.tools_used.add(str(data["toolName"]))
            segment.runtime_incidents.extend(classify_runtime_incidents(data.get("result", data.get("error", ""))))
        segment.end_time = timestamp or segment.end_time
    return segment if segment.messages else None


def parse_codex_transcript(path: Path, max_message_chars: int, skip_lines: int = 0) -> Session | None:
    events, total_lines = read_jsonl(path, skip_lines)
    if not events:
        return None
    segment = Session("codex", "", path, False, total_lines=total_lines, skip_lines=skip_lines)
    primary_messages: list[Message] = []
    fallback_messages: list[Message] = []
    for event in events:
        payload = event.get("payload", {})
        if not isinstance(payload, dict):
            continue
        event_type = event.get("type", "")
        timestamp = str(event.get("timestamp", ""))
        if event_type == "session_meta":
            session_id = payload.get("session_id")
            if session_id:
                segment.session_id = str(session_id)
                segment.identity_known = True
            segment.start_time = str(payload.get("timestamp", timestamp))
            segment.workspace = str(payload.get("cwd", ""))
        elif event_type == "response_item":
            item_type = payload.get("type")
            if item_type == "message" and payload.get("role") in {"user", "assistant"}:
                content = bound_text(content_to_text(payload.get("content")), max_message_chars)
                if content:
                    primary_messages.append(Message(str(payload["role"]), content, timestamp))
            elif item_type in {"function_call", "custom_tool_call"} and payload.get("name"):
                segment.tools_used.add(str(payload["name"]))
            elif item_type in {"function_call_output", "custom_tool_call_output"}:
                segment.runtime_incidents.extend(classify_runtime_incidents(payload.get("output", payload.get("content", ""))))
        elif event_type == "event_msg":
            item_type = payload.get("type")
            if item_type in {"user_message", "agent_message"}:
                content = bound_text(payload.get("message", ""), max_message_chars)
                if content:
                    fallback_messages.append(Message("user" if item_type == "user_message" else "assistant", content, timestamp))
            elif isinstance(item_type, str) and item_type.endswith("_tool_call"):
                segment.tools_used.add(item_type)
            elif item_type in {"tool_result", "tool_error", "command_error"}:
                segment.runtime_incidents.extend(classify_runtime_incidents(payload.get("message", payload.get("output", payload.get("error", "")))))
        segment.end_time = timestamp or segment.end_time
    segment.messages = primary_messages or fallback_messages
    return segment if segment.messages else None


def parse_transcript(filepath: str, max_assistant_chars: int = DEFAULT_MAX_MESSAGE_CHARS, skip_lines: int = 0) -> dict[str, Any] | None:
    """Backward-compatible Copilot parser used by older integrations."""
    segment = parse_copilot_transcript(Path(filepath), max_assistant_chars, skip_lines)
    return session_to_legacy_dict(segment) if segment else None


def session_to_legacy_dict(segment: Session) -> dict[str, Any]:
    return {
        "session_id": segment.session_id,
        "file_path": str(segment.file_path),
        "start_time": segment.start_time,
        "end_time": segment.end_time,
        "messages": [{"role": item.role, "content": item.content, "timestamp": item.timestamp} for item in segment.messages],
        "tools_used": sorted(segment.tools_used),
        "total_lines": segment.total_lines,
        "is_incremental": segment.is_incremental,
    }


def in_lookback_window(path: Path, lookback_days: int) -> bool:
    return datetime.fromtimestamp(path.stat().st_mtime, timezone.utc) >= utc_now() - timedelta(days=lookback_days)


def hydrate_segment_identity(segment: Session, identities: dict[str, str]) -> None:
    """Recover a Codex logical identity when an incremental read skipped metadata."""
    if not segment.identity_known and (session_id := identities.get(segment.state_key)):
        segment.session_id = session_id
        segment.identity_known = True


def aggregate_segments(segments: Iterable[Session]) -> list[ReviewSession]:
    """Group physical segments into logical sessions without joining unknown IDs."""
    groups: dict[tuple[str, str], list[Session]] = {}
    for segment in segments:
        identity = segment.session_id if segment.identity_known else f"unknown:{segment.state_key}"
        groups.setdefault((segment.source, identity), []).append(segment)

    reviews: list[ReviewSession] = []
    for (source, identity), group in groups.items():
        ordered_segments = sorted(group, key=lambda item: timestamp_sort_key(item.start_time or item.end_time))
        ordered_messages = sorted(
            (message for segment in ordered_segments for message in segment.messages),
            key=lambda item: timestamp_sort_key(item.timestamp),
        )
        messages: list[Message] = []
        seen_messages: set[tuple[str, str, str]] = set()
        for message in ordered_messages:
            fingerprint = (message.role, message.timestamp, message.content)
            if fingerprint not in seen_messages:
                seen_messages.add(fingerprint)
                messages.append(message)
        start_values = [segment.start_time for segment in ordered_segments if segment.start_time]
        end_values = [segment.end_time for segment in ordered_segments if segment.end_time]
        reviews.append(ReviewSession(
            source=source,
            session_id=identity,
            identity_known=not identity.startswith("unknown:"),
            segments=ordered_segments,
            start_time=min(start_values, key=timestamp_sort_key) if start_values else "",
            end_time=max(end_values, key=timestamp_sort_key) if end_values else "",
            workspace=next((segment.workspace for segment in ordered_segments if segment.workspace), ""),
            messages=messages,
            tools_used=set().union(*(segment.tools_used for segment in ordered_segments)),
            runtime_incidents=[incident for segment in ordered_segments for incident in segment.runtime_incidents],
        ))
    return sorted(reviews, key=lambda item: (timestamp_sort_key(item.start_time), item.source, item.session_id))


def collect_sessions(
    source: str,
    state: dict[str, Any],
    lookback_days: int,
    max_message_chars: int,
    copilot_roots: Iterable[Path] | None = None,
    codex_files: Iterable[Path] | None = None,
) -> list[ReviewSession]:
    selected = SOURCES if source == "all" else (source,)
    segments: list[Session] = []
    roots = list(copilot_roots) if copilot_roots is not None else copilot_storage_roots()
    workspace_maps = {root: load_workspace_mapping(root / "globalStorage") for root in roots}
    for provider in selected:
        files = discover_copilot_files(roots) if provider == "copilot" else list(codex_files if codex_files is not None else discover_codex_files())
        source_state = state["sources"][provider]
        reviewed = source_state["reviewed_segments"]
        identities = source_state["segment_sessions"]
        for path in files:
            skip_lines = int(reviewed.get(path.stem, 0))
            if not skip_lines and not in_lookback_window(path, lookback_days):
                continue
            if provider == "copilot":
                try:
                    workspace_id = path.parents[2].name
                    workspace = next((mapping.get(workspace_id, "") for mapping in workspace_maps.values()), "")
                except IndexError:
                    workspace = ""
                segment = parse_copilot_transcript(path, max_message_chars, skip_lines, workspace)
            else:
                segment = parse_codex_transcript(path, max_message_chars, skip_lines)
            if segment:
                hydrate_segment_identity(segment, identities)
                segments.append(segment)
    return aggregate_segments(segments)


def mark_reviewed(state: dict[str, Any], sessions: Iterable[ReviewSession]) -> None:
    for review in sessions:
        source_state = state["sources"][review.source]
        for segment in review.segments:
            source_state["reviewed_segments"][segment.state_key] = segment.total_lines
            if segment.identity_known:
                source_state["segment_sessions"][segment.state_key] = segment.session_id


def create_review_snapshot(state: dict[str, Any], sessions: Iterable[ReviewSession]) -> str:
    """Store only cursor ceilings so delivery can finish in a later turn."""
    captured = [
        {
            "source": review.source,
            "session_id": review.session_id if review.identity_known else "",
            "segments": [
                {"key": segment.state_key, "lines": segment.total_lines, "session_id": segment.session_id if segment.identity_known else ""}
                for segment in review.segments
            ],
        }
        for review in sessions
    ]
    digest = hashlib.sha256(json.dumps(captured, sort_keys=True).encode()).hexdigest()[:12]
    review_id = f"review-{utc_now().strftime('%Y%m%d%H%M%S')}-{digest}"
    state["pending_reviews"][review_id] = {"created_at": utc_now().isoformat(), "sessions": captured}
    return review_id


def finalize_review_snapshot(state: dict[str, Any], review_id: str) -> bool:
    snapshot = state["pending_reviews"].pop(review_id, None)
    if not isinstance(snapshot, dict):
        return False
    for review in snapshot.get("sessions", []):
        if not isinstance(review, dict) or review.get("source") not in SOURCES:
            continue
        source_state = state["sources"][review["source"]]
        for segment in review.get("segments", []):
            if not isinstance(segment, dict) or not isinstance(segment.get("key"), str):
                continue
            previous = int(source_state["reviewed_segments"].get(segment["key"], 0))
            source_state["reviewed_segments"][segment["key"]] = max(previous, int(segment.get("lines", 0)))
            if segment.get("session_id"):
                source_state["segment_sessions"][segment["key"]] = segment["session_id"]
    state["completed_reviews"] += 1
    return True


def deep_audit_status(state: dict[str, Any], include_current_review: bool = True) -> dict[str, int | bool]:
    completed = int(state.get("completed_reviews", 0)) + int(include_current_review)
    last_deep = int(state.get("last_deep_audit_review", 0))
    return {"due": completed - last_deep >= 5, "completed_reviews": completed, "last_deep_audit_review": last_deep}


def record_deep_audit(state: dict[str, Any]) -> None:
    state["last_deep_audit_review"] = int(state.get("completed_reviews", 0))


def format_session_markdown(session: ReviewSession, workspace_name: str | None = None) -> str:
    start = parse_time(session.start_time)
    formatted = start.strftime("%Y-%m-%d %H:%M") if start else (session.start_time or "Unknown")
    incremental = " (incremental)" if session.is_incremental else ""
    identity = f"{session.session_id[:8]}..." if session.identity_known else "identity unavailable"
    lines = [
        f"### {session.source.title()} session: {identity}{incremental}",
        f"- **Time**: {formatted}",
        f"- **Workspace**: {workspace_name or session.workspace or 'Unknown'}",
        f"- **Transcript segments**: {session.segment_count}",
        f"- **Messages**: {len(session.messages)} total ({sum(item.role == 'user' for item in session.messages)} user)",
    ]
    if session.tools_used:
        lines.append(f"- **Tools Used**: {', '.join(sorted(session.tools_used))}")
    if session.runtime_incidents:
        counts: dict[str, int] = {}
        for incident in session.runtime_incidents:
            counts[incident.category] = counts.get(incident.category, 0) + 1
        lines.append("- **Runtime incidents**: " + ", ".join(f"{name} ×{count}" for name, count in sorted(counts.items())))
    lines.extend(["", "#### Bounded transcript excerpt", ""])
    for item in session.messages:
        label = "User" if item.role == "user" else "Assistant"
        lines.extend([f"> **{label}**: {item.content.replace(chr(10), chr(10) + '  > ')}", ""])
    return "\n".join(lines)


def main() -> int:
    parser = argparse.ArgumentParser(description="Collect bounded logical Copilot and Codex review sessions")
    parser.add_argument("--state-file", default=str(Path(__file__).resolve().parents[1] / "review_state.json"))
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--mark-reviewed", action="store_true", help="Legacy: immediately advance cursors for collected segments")
    mode.add_argument("--prepare-review", action="store_true", help="Create a delivery snapshot without advancing cursors")
    mode.add_argument("--finalize-review", metavar="REVIEW_ID", help="Advance only the cursor ceilings stored in a delivery snapshot")
    parser.add_argument("--deep-audit-status", action="store_true", help="Print whether the current review is due for a deep asset audit")
    parser.add_argument("--record-deep-audit", action="store_true", help="Record that the current deep asset audit has completed")
    parser.add_argument("--source", choices=("all", *SOURCES), default="all")
    parser.add_argument("--lookback-days", type=int, default=90, help="Initial-history window; later runs are incremental")
    parser.add_argument("--max-message-chars", type=int, default=DEFAULT_MAX_MESSAGE_CHARS)
    parser.add_argument("--max-assistant-chars", type=int, dest="legacy_message_chars", help="Compatibility alias for --max-message-chars")
    args = parser.parse_args()
    if args.lookback_days < 1 or args.max_message_chars < 1:
        parser.error("lookback and message limits must be positive")
    state = load_review_state(args.state_file)
    if args.deep_audit_status:
        print(json.dumps(deep_audit_status(state), ensure_ascii=False))
        return 0
    if args.record_deep_audit:
        record_deep_audit(state)
        save_review_state(args.state_file, state)
        print("<!-- Recorded deep asset audit -->")
        return 0
    if args.finalize_review:
        if not finalize_review_snapshot(state, args.finalize_review):
            parser.error(f"unknown review snapshot: {args.finalize_review}")
        save_review_state(args.state_file, state)
        print(f"<!-- Finalized review snapshot {args.finalize_review} -->")
        return 0
    sessions = collect_sessions(args.source, state, args.lookback_days, args.legacy_message_chars or args.max_message_chars)
    if not sessions:
        print("# No New Chat History\n\nNo unreviewed Copilot or Codex sessions were found in the selected window.")
        return 0
    print("# Chat History Review Summary\n")
    print(f"- **Date**: {utc_now().strftime('%Y-%m-%d %H:%M UTC')}")
    print(f"- **Sources**: {', '.join(sorted({item.source for item in sessions}))}")
    print(f"- **Logical sessions**: {len(sessions)}")
    print(f"- **Transcript segments**: {sum(item.segment_count for item in sessions)}")
    print(f"- **Messages**: {sum(len(item.messages) for item in sessions)}")
    print("- **Privacy**: bounded and redacted excerpts; raw transcripts are not persisted\n")
    for session in sessions:
        print(format_session_markdown(session))
        print("---\n")
    if args.mark_reviewed:
        mark_reviewed(state, sessions)
        save_review_state(args.state_file, state)
        print("<!-- Marked collected transcript segments as reviewed -->")
    elif args.prepare_review:
        review_id = create_review_snapshot(state, sessions)
        save_review_state(args.state_file, state)
        print(f"<!-- Prepared review snapshot {review_id}; finalize only after the report has been delivered -->")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
