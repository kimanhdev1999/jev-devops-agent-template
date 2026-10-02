"""Optional fallback for the minority of cases Jev can't or shouldn't handle:
generating prose (e.g. an incident summary) or reasoning that needs a real LLM.

Keep this path rare by design - if it's getting hit often, your Jev
question/labels probably need tuning, not a bigger LLM budget.
"""

from __future__ import annotations

import anthropic

from agent.config import settings


def summarize_incident(context: str) -> str:
    client = anthropic.Anthropic(api_key=settings.llm_api_key)
    message = client.messages.create(
        model=settings.llm_model,
        max_tokens=512,
        messages=[
            {
                "role": "user",
                "content": f"Summarize this incident for an on-call handoff:\n\n{context}",
            }
        ],
    )
    return message.content[0].text
