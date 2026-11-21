"""Trace every model and tool call of a run to <moldir>/harness/trace.jsonl.

Each record names the graph node, so a run can be read step by step: which model actually answered (OpenRouter
may route a free model to different providers), tokens used, which tools were called with which arguments, and
what they returned.
"""
from __future__ import annotations

import datetime
import json
from pathlib import Path
from typing import Any

from langchain_core.callbacks import BaseCallbackHandler


def _now() -> str:
    return datetime.datetime.now(datetime.timezone.utc).isoformat(timespec="seconds")


class JsonlTracer(BaseCallbackHandler):
    def __init__(self, path: Path, node: str = ""):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.node = node

    def _write(self, rec: dict) -> None:
        rec = {"utc": _now(), "node": self.node, **rec}
        with self.path.open("a") as f:
            f.write(json.dumps(rec, default=str) + "\n")

    def on_chat_model_start(self, serialized, messages, *, run_id, **kw: Any):
        msgs = messages[0] if messages else []
        self._write({"event": "model_start", "run_id": str(run_id), "n_messages": len(msgs),
                     "chars_in": sum(len(str(m.content)) for m in msgs)})

    def on_llm_end(self, response, *, run_id, **kw: Any):
        gen = response.generations[0][0] if response.generations and response.generations[0] else None
        msg = getattr(gen, "message", None)
        meta = getattr(msg, "response_metadata", {}) or {}
        usage = getattr(msg, "usage_metadata", None) or {}
        calls = [{"name": c["name"], "args": c["args"]} for c in (getattr(msg, "tool_calls", None) or [])]
        text = getattr(msg, "text", None) if msg is not None else None
        text = text() if callable(text) else text
        self._write({"event": "model_end", "run_id": str(run_id),
                     "model": meta.get("model_name") or meta.get("model"), "provider": meta.get("provider"),
                     "finish_reason": meta.get("finish_reason"), "usage": usage, "tool_calls": calls,
                     "text": (text or "")[:2000]})

    def on_llm_error(self, error, *, run_id, **kw: Any):
        self._write({"event": "model_error", "run_id": str(run_id), "error": f"{type(error).__name__}: {error}"[:2000]})

    def on_tool_start(self, serialized, input_str, *, run_id, inputs=None, **kw: Any):
        self._write({"event": "tool_start", "run_id": str(run_id), "tool": (serialized or {}).get("name"),
                     "input": inputs if inputs is not None else input_str})

    def on_tool_end(self, output, *, run_id, **kw: Any):
        out = getattr(output, "content", output)
        self._write({"event": "tool_end", "run_id": str(run_id), "output": str(out)[:3000]})

    def on_tool_error(self, error, *, run_id, **kw: Any):
        self._write({"event": "tool_error", "run_id": str(run_id), "error": f"{type(error).__name__}: {error}"[:2000]})
