"""Thin client for Jev's three question types: choice, score, noul.

Jev is not a chat model - there is no "conversation" or "prompt" in the LLM sense.
Each call asks one narrow, typed question about a piece of state and gets back a
label/score/probability plus a calibrated confidence. Keep questions narrow: one
judgment call per request, not a multi-part task.
"""

from __future__ import annotations

from dataclasses import dataclass

import httpx

from agent.config import settings


@dataclass
class ChoiceResult:
    label: str
    confidence: float  # 0.0-1.0, calibrated in aggregate, not per-call


@dataclass
class ScoreResult:
    score: int  # within the min/max you supplied
    confidence: float


@dataclass
class NoulResult:
    probability_true: float  # 0.0-1.0


class JevClient:
    """NOTE: endpoint paths/payload shapes below are placeholders — swap them for
    TypeSafe's actual Jev API spec once you have access. The three-method shape
    (choice/score/noul) and the calibrated-confidence contract are what matters;
    wire them to whatever TypeSafe actually exposes.
    """

    def __init__(self) -> None:
        self._client = httpx.Client(
            base_url=settings.jev_base_url,
            timeout=settings.jev_timeout_seconds,
            headers={"Authorization": f"Bearer {settings.jev_api_key}"},
        )

    def choice(self, state: str, question: str, options: list[str]) -> ChoiceResult:
        """Pick exactly one of up to 255 predefined labels."""
        if not 1 <= len(options) <= 255:
            raise ValueError("choice() requires 1-255 options")
        resp = self._client.post(
            "/choice",
            json={"state": state, "question": question, "options": options},
        )
        resp.raise_for_status()
        data = resp.json()
        return ChoiceResult(label=data["label"], confidence=data["confidence"])

    def score(self, state: str, question: str, min_level: int = 2, max_level: int = 10) -> ScoreResult:
        """Place state on a min_level..max_level scale you describe in `question`."""
        resp = self._client.post(
            "/score",
            json={
                "state": state,
                "question": question,
                "min_level": min_level,
                "max_level": max_level,
            },
        )
        resp.raise_for_status()
        data = resp.json()
        return ScoreResult(score=data["score"], confidence=data["confidence"])

    def noul(self, state: str, statement: str) -> NoulResult:
        """Return the calibrated probability that `statement` is true of `state`."""
        resp = self._client.post(
            "/noul",
            json={"state": state, "statement": statement},
        )
        resp.raise_for_status()
        data = resp.json()
        return NoulResult(probability_true=data["probability_true"])

    def close(self) -> None:
        self._client.close()

    def __enter__(self) -> "JevClient":
        return self

    def __exit__(self, *exc: object) -> None:
        self.close()
