"""Mask PII and secrets in log text before it leaves the analyzer (Slack, Jira, Bedrock)."""

from __future__ import annotations

import re

_RULES: list[tuple[re.Pattern, str]] = [
    (re.compile(r"\bxox[abposr]-[A-Za-z0-9-]+"), "<SLACK_TOKEN>"),
    (re.compile(r"\b(AKIA|ASIA)[A-Z0-9]{16}\b"), "<AWS_KEY>"),
    (re.compile(r"(?i)\b(bearer|token|password|passwd|secret|api[_-]?key)\s*[=:]\s*\S+"), r"\1=<SECRET>"),
    (re.compile(r"\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}\b"), "<EMAIL>"),
    (re.compile(r"\b(?:\d{1,3}\.){3}\d{1,3}\b"), "<IP>"),
    (re.compile(r"\b[A-Za-z0-9+/_-]{32,}={0,2}"), "<BLOB>"),
    (re.compile(r"\b\d{5,}\b"), "<NUM>"),
]


def mask(text: str) -> str:
    for pattern, repl in _RULES:
        text = pattern.sub(repl, text)
    return text
