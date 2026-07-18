"""Read optional local token telemetry without installing external software.

The adapter intentionally invokes only an already-installed ``ccusage`` binary.
It never runs package managers and returns coverage metadata when exact session
usage is unavailable.
"""

from __future__ import annotations

import argparse
import json
import shutil
import subprocess
from typing import Any, Callable


INSTALL_HINT = "Install ccusage manually, review its release, then rerun this adapter; automatic installation is disabled."


def _records(payload: Any) -> list[dict[str, Any]]:
    if isinstance(payload, list):
        return [item for item in payload if isinstance(item, dict)]
    if not isinstance(payload, dict):
        return []
    for key in ("sessions", "data", "records", "items"):
        if isinstance(payload.get(key), list):
            return [item for item in payload[key] if isinstance(item, dict)]
    return []


def _usage(record: dict[str, Any]) -> dict[str, Any]:
    usage = record.get("usage", record.get("token_usage", record))
    return usage if isinstance(usage, dict) else {}


def normalize_ccusage(payload: Any) -> dict[str, Any]:
    """Normalize only explicit session IDs; never infer an attribution."""
    sessions = []
    unattributed = 0
    for record in _records(payload):
        usage = _usage(record)
        session_id = next((record.get(key) for key in ("session_id", "sessionId", "id", "thread_id") if record.get(key)), "")
        metrics = {
            "input_tokens": usage.get("input_tokens", usage.get("inputTokens")),
            "cached_input_tokens": usage.get("cached_input_tokens", usage.get("cachedInputTokens")),
            "output_tokens": usage.get("output_tokens", usage.get("outputTokens")),
            "reasoning_tokens": usage.get("reasoning_tokens", usage.get("reasoningTokens")),
            "total_tokens": usage.get("total_tokens", usage.get("totalTokens")),
            "cost_usd": usage.get("cost_usd", usage.get("cost")),
        }
        if not session_id:
            unattributed += 1
            continue
        sessions.append({"session_id": str(session_id), "model": record.get("model", usage.get("model", "")), "metrics": metrics})
    return {
        "provider": "ccusage",
        "available": True,
        "exact_session_records": sessions,
        "unattributed_records": unattributed,
        "coverage": "exact-session" if sessions else "aggregate-or-unavailable",
    }


def collect_ccusage(runner: Callable[..., subprocess.CompletedProcess[str]] = subprocess.run) -> dict[str, Any]:
    executable = shutil.which("ccusage")
    if not executable:
        return {"provider": "ccusage", "available": False, "coverage": "unavailable", "install_hint": INSTALL_HINT}
    result = runner([executable, "codex", "session", "--json"], text=True, capture_output=True)
    if result.returncode:
        return {"provider": "ccusage", "available": True, "coverage": "unavailable", "error": "ccusage command failed"}
    try:
        return normalize_ccusage(json.loads(result.stdout))
    except json.JSONDecodeError:
        return {"provider": "ccusage", "available": True, "coverage": "unavailable", "error": "ccusage returned invalid JSON"}


def main() -> int:
    parser = argparse.ArgumentParser(description="Collect optional local ccusage token telemetry")
    parser.add_argument("--json", action="store_true", help="Emit structured telemetry")
    args = parser.parse_args()
    result = collect_ccusage()
    if args.json:
        print(json.dumps(result, ensure_ascii=False))
    else:
        print(f"ccusage: {result['coverage']}")
        if result.get("install_hint"):
            print(result["install_hint"])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
