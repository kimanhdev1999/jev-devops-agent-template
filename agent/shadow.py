"""Shadow-mode logging: record what Jev would have decided without acting on it.

Run this for 1-2 weeks against real traffic before trusting any auto-routing, then
compare `label`/`action` against what actually happened (human decision, downstream
outcome) to measure real-world agreement before automating.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

LOG_PATH = Path("logs/shadow.jsonl")


def log_decision(input_summary: str, label: str, confidence: float, would_do: str) -> None:
    LOG_PATH.parent.mkdir(parents=True, exist_ok=True)
    record = {
        "ts": datetime.now(timezone.utc).isoformat(),
        "input_summary": input_summary,
        "label": label,
        "confidence": confidence,
        "would_do": would_do,
    }
    with LOG_PATH.open("a") as f:
        f.write(json.dumps(record) + "\n")
