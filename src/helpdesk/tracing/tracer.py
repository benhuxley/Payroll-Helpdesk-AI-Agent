"""One JSONL trace file per conversation.

Every event (user message, guardrail decision, model call, tool call, reply) is one JSON line, written
immediately so nothing is lost if the process dies. Everything passes through the Redactor first:
personal data never reaches the disk.

Event types: conversation_start, user_message, guardrail, model_call, tool_call, assistant_reply,
escalation_backstop, error, conversation_end.
"""

import json
from datetime import UTC, datetime
from pathlib import Path

from helpdesk.guardrails.redaction import Redactor


class Tracer:
    def __init__(self, conversation_id: str, traces_dir: Path | None, redactor: Redactor | None = None):
        self.conversation_id = conversation_id
        self.redactor = redactor or Redactor()
        self.events: list[dict] = []
        self.path = None
        if traces_dir is not None:
            traces_dir.mkdir(parents=True, exist_ok=True)
            self.path = traces_dir / f"{conversation_id}.jsonl"

    def log(self, event_type: str, **data) -> dict:
        record = {
            "ts": datetime.now(UTC).isoformat(timespec="milliseconds"),
            "seq": len(self.events) + 1,
            "conversation_id": self.conversation_id,
            "type": event_type,
            **self.redactor.value(data),
        }
        self.events.append(record)
        if self.path is not None:
            with self.path.open("a", encoding="utf-8") as f:
                f.write(json.dumps(record, ensure_ascii=False, default=str) + "\n")
        return record
