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


def codex_segment(session_id: str, timestamp: str, text: str, tool: str = "") -> list[dict]:
    events = [
        {"type": "session_meta", "timestamp": timestamp, "payload": {"session_id": session_id, "cwd": "/project", "timestamp": timestamp}},
        {"type": "response_item", "timestamp": timestamp, "payload": {"type": "message", "role": "user", "content": [{"type": "input_text", "text": text}]}},
    ]
    if tool:
        events.append({"type": "response_item", "timestamp": timestamp, "payload": {"type": "function_call", "name": tool}})
    return events


class CollectorTests(unittest.TestCase):
    def test_copilot_parser_bounds_redacts_and_collects_tools(self):
        with tempfile.TemporaryDirectory() as directory:
            transcript = Path(directory) / "session.jsonl"
            write_jsonl(transcript, [
                {"type": "session.start", "timestamp": "2026-07-01T10:00:00Z", "data": {"startTime": "2026-07-01T10:00:00Z"}},
                {"type": "user.message", "timestamp": "2026-07-01T10:01:00Z", "data": {"content": "api_key=super-secret-value", "toolRequests": [{"toolName": "search"}]}},
                {"type": "assistant.message", "timestamp": "2026-07-01T10:02:00Z", "data": {"content": "x" * 300}},
            ])
            segment = COLLECTOR.parse_copilot_transcript(transcript, 100)
            self.assertIsNotNone(segment)
            assert segment
            self.assertIn("[REDACTED]", segment.messages[0].content)
            self.assertNotIn("super-secret-value", segment.messages[0].content)
            self.assertTrue(segment.messages[1].content.endswith("chars total)"))
            self.assertEqual(segment.tools_used, {"search"})

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
            segment = COLLECTOR.parse_codex_transcript(transcript, 300)
            self.assertIsNotNone(segment)
            assert segment
            self.assertEqual(segment.session_id, "codex-1")
            self.assertTrue(segment.identity_known)
            self.assertEqual(segment.workspace, "/project")
            self.assertEqual([item.content for item in segment.messages], ["[REDACTED_OPENAI_KEY]", "Done"])
            self.assertEqual(segment.tools_used, {"exec_command"})

    def test_same_codex_identity_merges_segments_once(self):
        with tempfile.TemporaryDirectory() as directory:
            first = Path(directory) / "part-one.jsonl"
            second = Path(directory) / "part-two.jsonl"
            write_jsonl(first, codex_segment("codex-1", "2026-07-01T10:00:00Z", "first", "search"))
            write_jsonl(second, codex_segment("codex-1", "2026-07-01T10:01:00Z", "second", "exec"))
            reviews = COLLECTOR.collect_sessions("codex", COLLECTOR.default_state(), 90, 300, codex_files=[second, first])
            self.assertEqual(len(reviews), 1)
            review = reviews[0]
            self.assertEqual(review.session_id, "codex-1")
            self.assertEqual(review.segment_count, 2)
            self.assertEqual([item.content for item in review.messages], ["first", "second"])
            self.assertEqual(review.tools_used, {"search", "exec"})
            self.assertEqual(review.start_time, "2026-07-01T10:00:00Z")
            self.assertEqual(review.end_time, "2026-07-01T10:01:00Z")

    def test_marking_reviewed_advances_each_segment_without_chat_content(self):
        with tempfile.TemporaryDirectory() as directory:
            first = Path(directory) / "part-one.jsonl"
            second = Path(directory) / "part-two.jsonl"
            write_jsonl(first, codex_segment("codex-1", "2026-07-01T10:00:00Z", "private first"))
            write_jsonl(second, codex_segment("codex-1", "2026-07-01T10:01:00Z", "private second"))
            state = COLLECTOR.default_state()
            reviews = COLLECTOR.collect_sessions("codex", state, 90, 300, codex_files=[first, second])
            COLLECTOR.mark_reviewed(state, reviews)
            source_state = state["sources"]["codex"]
            self.assertEqual(set(source_state["reviewed_segments"]), {"part-one", "part-two"})
            self.assertEqual(set(source_state["segment_sessions"].values()), {"codex-1"})
            state_file = Path(directory) / "state.json"
            COLLECTOR.save_review_state(state_file, state)
            saved = state_file.read_text(encoding="utf-8")
            self.assertNotIn("private first", saved)
            self.assertNotIn("private second", saved)

    def test_incremental_codex_segment_recovers_persisted_identity(self):
        with tempfile.TemporaryDirectory() as directory:
            transcript = Path(directory) / "rollout.jsonl"
            write_jsonl(transcript, codex_segment("codex-1", "2026-07-01T10:00:00Z", "original"))
            initial_state = COLLECTOR.default_state()
            initial_review = COLLECTOR.collect_sessions("codex", initial_state, 90, 300, codex_files=[transcript])
            COLLECTOR.mark_reviewed(initial_state, initial_review)
            with transcript.open("a", encoding="utf-8") as handle:
                handle.write(json.dumps({"type": "response_item", "timestamp": "2026-07-01T10:02:00Z", "payload": {"type": "message", "role": "assistant", "content": [{"type": "output_text", "text": "incremental"}]}}) + "\n")
            incremental = COLLECTOR.collect_sessions("codex", initial_state, 90, 300, codex_files=[transcript])
            self.assertEqual(len(incremental), 1)
            self.assertTrue(incremental[0].identity_known)
            self.assertEqual(incremental[0].session_id, "codex-1")
            self.assertEqual([item.content for item in incremental[0].messages], ["incremental"])

    def test_incremental_codex_segment_without_mapping_stays_unknown(self):
        with tempfile.TemporaryDirectory() as directory:
            transcript = Path(directory) / "rollout.jsonl"
            write_jsonl(transcript, [
                {"type": "session_meta", "timestamp": "2026-07-01T10:00:00Z", "payload": {"session_id": "codex-1"}},
                {"type": "response_item", "timestamp": "2026-07-01T10:01:00Z", "payload": {"type": "message", "role": "user", "content": [{"type": "input_text", "text": "new"}]}},
            ])
            state = COLLECTOR.default_state()
            state["sources"]["codex"]["reviewed_segments"]["rollout"] = 1
            review = COLLECTOR.collect_sessions("codex", state, 90, 300, codex_files=[transcript])[0]
            self.assertFalse(review.identity_known)
            self.assertEqual(review.session_id, "unknown:rollout")

    def test_v2_and_legacy_state_migrate_to_segment_cursors(self):
        v2 = COLLECTOR.normalize_state({"schema_version": 2, "sources": {"codex": {"reviewed_sessions": {"old": 12}}}})
        legacy = COLLECTOR.normalize_state({"reviewed_sessions": {"legacy": 8}, "last_review": "then"})
        self.assertEqual(v2["schema_version"], 3)
        self.assertEqual(v2["sources"]["codex"]["reviewed_segments"], {"old": 12})
        self.assertEqual(v2["sources"]["codex"]["segment_sessions"], {})
        self.assertEqual(legacy["sources"]["copilot"]["reviewed_segments"], {"legacy": 8})
        self.assertEqual(legacy["last_review"], "then")

    def test_collect_sessions_honors_explicit_empty_codex_files(self):
        self.assertEqual(COLLECTOR.collect_sessions("codex", COLLECTOR.default_state(), 90, 300, codex_files=[]), [])

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
