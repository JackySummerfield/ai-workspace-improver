import importlib.util
import json
import os
import sys
import tempfile
import unittest
from pathlib import Path


SCRIPT = Path(__file__).parents[1] / "scripts" / "collect_chat_history.py"
SPEC = importlib.util.spec_from_file_location("collect_chat_history", SCRIPT)
COLLECTOR = importlib.util.module_from_spec(SPEC)
assert SPEC and SPEC.loader
sys.modules[SPEC.name] = COLLECTOR
SPEC.loader.exec_module(COLLECTOR)


def write_jsonl(path: Path, events: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("".join(json.dumps(event) + "\n" for event in events), encoding="utf-8")


class CollectorTests(unittest.TestCase):
    def test_copilot_parser_bounds_redacts_and_collects_tools(self):
        with tempfile.TemporaryDirectory() as directory:
            transcript = Path(directory) / "session.jsonl"
            write_jsonl(transcript, [
                {"type": "session.start", "timestamp": "2026-07-01T10:00:00Z", "data": {"startTime": "2026-07-01T10:00:00Z"}},
                {"type": "user.message", "timestamp": "2026-07-01T10:01:00Z", "data": {"content": "api_key=super-secret-value", "toolRequests": [{"toolName": "search"}]}},
                {"type": "assistant.message", "timestamp": "2026-07-01T10:02:00Z", "data": {"content": "x" * 300}},
            ])
            session = COLLECTOR.parse_copilot_transcript(transcript, 100)
            self.assertIsNotNone(session)
            assert session
            self.assertIn("[REDACTED]", session.messages[0].content)
            self.assertNotIn("super-secret-value", session.messages[0].content)
            self.assertTrue(session.messages[1].content.endswith("chars total)"))
            self.assertEqual(session.tools_used, {"search"})

    def test_codex_parser_reads_message_items_and_ignores_tool_output(self):
        with tempfile.TemporaryDirectory() as directory:
            transcript = Path(directory) / "rollout.jsonl"
            write_jsonl(transcript, [
                {"type": "session_meta", "timestamp": "2026-07-01T10:00:00Z", "payload": {"session_id": "codex-1", "cwd": "/project", "timestamp": "2026-07-01T10:00:00Z"}},
                {"type": "response_item", "timestamp": "2026-07-01T10:01:00Z", "payload": {"type": "message", "role": "user", "content": [{"type": "input_text", "text": "sk-abcdefghijklmnopqrstuvwxyz"}]}},
                {"type": "response_item", "timestamp": "2026-07-01T10:02:00Z", "payload": {"type": "function_call", "name": "exec_command"}},
                {"type": "response_item", "timestamp": "2026-07-01T10:03:00Z", "payload": {"type": "message", "role": "assistant", "content": [{"type": "output_text", "text": "Done"}]}},
                {"type": "response_item", "timestamp": "2026-07-01T10:04:00Z", "payload": {"type": "function_call_output", "output": "must not be collected"}},
            ])
            session = COLLECTOR.parse_codex_transcript(transcript, 300)
            self.assertIsNotNone(session)
            assert session
            self.assertEqual(session.session_id, "codex-1")
            self.assertEqual(session.workspace, "/project")
            self.assertEqual([item.content for item in session.messages], ["[REDACTED_OPENAI_KEY]", "Done"])
            self.assertEqual(session.tools_used, {"exec_command"})

    def test_legacy_state_migrates_to_copilot_cursor_only(self):
        state = COLLECTOR.normalize_state({"reviewed_sessions": {"legacy": 12}, "last_review": "then"})
        self.assertEqual(state["schema_version"], 2)
        self.assertEqual(state["sources"]["copilot"]["reviewed_sessions"], {"legacy": 12})
        self.assertEqual(state["sources"]["codex"]["reviewed_sessions"], {})
        self.assertEqual(state["last_review"], "then")

    def test_marked_state_never_contains_transcript_content(self):
        with tempfile.TemporaryDirectory() as directory:
            transcript = Path(directory) / "session.jsonl"
            write_jsonl(transcript, [
                {"type": "user.message", "timestamp": "2026-07-01T10:00:00Z", "data": {"content": "private transcript sentence"}},
            ])
            session = COLLECTOR.parse_copilot_transcript(transcript, 300)
            assert session
            state = COLLECTOR.default_state()
            COLLECTOR.mark_reviewed(state, [session])
            state_file = Path(directory) / "state.json"
            COLLECTOR.save_review_state(state_file, state)
            saved = state_file.read_text(encoding="utf-8")
            self.assertNotIn("private transcript sentence", saved)
            self.assertIn("session", saved)

    def test_collect_sessions_honors_explicit_empty_codex_files(self):
        state = COLLECTOR.default_state()
        self.assertEqual(COLLECTOR.collect_sessions("codex", state, 90, 300, codex_files=[]), [])

    def test_copilot_discovery_deduplicates_session_id(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            first = root / "workspaceStorage" / "a" / "GitHub.copilot-chat" / "transcripts" / "same.jsonl"
            second = root / "workspaceStorage" / "b" / "GitHub.copilot-chat" / "transcripts" / "same.jsonl"
            write_jsonl(first, [])
            write_jsonl(second, [])
            os.utime(second, (second.stat().st_atime + 5, second.stat().st_mtime + 5))
            self.assertEqual(COLLECTOR.discover_copilot_files([root]), [second])


if __name__ == "__main__":
    unittest.main()
