"""The triage prompt + a single-issue call returning structured fields."""
from __future__ import annotations
from .providers import Provider, parse_response
from .taxonomy import CATEGORIES

SYSTEM = (
    "You are a maintainer triaging incoming GitHub issues for a software project. "
    "You assign exactly one category, a priority, and decide whether the issue is "
    "likely a duplicate of an existing one. You are decisive and consistent. "
    "Respond with a single JSON object and nothing else."
)

USER_TEMPLATE = """Repository: {repo}

Issue #{number}
Title: {title}

Body:
{body}

Classify this issue. Respond as JSON:
{{
  "category": one of {categories},
  "priority": one of ["high","medium","low"],
  "is_duplicate": true or false (true only if the text itself indicates it repeats a known/existing issue),
  "confidence": a float 0.0-1.0 (1.0 = completely certain, 0.5 = could go either way, 0.0 = guessing),
  "rationale": one short sentence
}}"""


def triage_issue(provider: Provider, rec: dict) -> dict:
    body = (rec.get("body") or "").strip() or "(no description provided)"
    user = USER_TEMPLATE.format(
        repo=rec["repo"], number=rec["number"], title=rec["title"],
        body=body[:6000], categories=CATEGORIES,
    )
    if getattr(provider, "name", "") == "mock":
        raw, input_tokens, output_tokens = provider.complete(SYSTEM, f"{rec['title']}\n\n{body}")
    else:
        raw, input_tokens, output_tokens = provider.complete(SYSTEM, user)
    pred = parse_response(raw)
    pred["number"] = rec["number"]
    pred["input_tokens"] = input_tokens
    pred["output_tokens"] = output_tokens
    return pred
