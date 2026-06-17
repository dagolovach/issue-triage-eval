"""One interface over Claude, OpenAI, and a free offline mock.

The mock is deliberately decent-but-imperfect: it keyword-classifies so the whole
pipeline (and the scoring numbers) work end-to-end with no API key and no cost.
That means anyone who clones the repo can reproduce the mechanics for free, and you
can debug scoring without burning tokens.
"""
from __future__ import annotations
import json
import os
import re
from typing import Protocol

from .env import load_env

load_env()  # populate os.environ from .env before any key is read


MODEL_COSTS: dict[str, dict[str, float]] = {
    "claude-sonnet-4-6":       {"input": 3.00,  "output": 15.00},
    "claude-opus-4":           {"input": 15.00, "output": 75.00},
    "claude-haiku-3-5":        {"input": 0.80,  "output": 4.00},
    "gpt-4o":                  {"input": 2.50,  "output": 10.00},
    "gpt-4o-mini":             {"input": 0.15,  "output": 0.60},
    "gpt-4-turbo":             {"input": 10.00, "output": 30.00},
}


def cost_usd(model: str, input_tokens: int, output_tokens: int) -> float:
    rates = MODEL_COSTS.get(model, {"input": 0.0, "output": 0.0})
    return (input_tokens * rates["input"] + output_tokens * rates["output"]) / 1_000_000


class Provider(Protocol):
    name: str
    def complete(self, system: str, user: str) -> tuple[str, int, int]: ...


def _extract_json(text: str) -> dict:
    """Pull the first JSON object out of a model response, tolerant of prose/fences."""
    text = re.sub(r"^```(?:json)?|```$", "", text.strip(), flags=re.M).strip()
    start = text.find("{")
    if start == -1:
        return {}
    depth = 0
    for i in range(start, len(text)):
        if text[i] == "{":
            depth += 1
        elif text[i] == "}":
            depth -= 1
            if depth == 0:
                try:
                    return json.loads(text[start : i + 1])
                except json.JSONDecodeError:
                    return {}
    return {}


class ClaudeProvider:
    name = "claude"

    def __init__(self, model: str = "claude-sonnet-4-6"):
        import anthropic  # lazy import so mock mode needs no SDK
        self.model = model
        self.client = anthropic.Anthropic(api_key=os.environ["ANTHROPIC_API_KEY"])

    def complete(self, system: str, user: str) -> tuple[str, int, int]:
        resp = self.client.messages.create(
            model=self.model, max_tokens=512, system=system,
            messages=[{"role": "user", "content": user}],
        )
        text = "".join(b.text for b in resp.content if b.type == "text")
        return text, resp.usage.input_tokens, resp.usage.output_tokens


class OpenAIProvider:
    name = "openai"

    def __init__(self, model: str = "gpt-4o"):
        from openai import OpenAI
        self.model = model
        self.client = OpenAI(
            api_key=os.environ["OPENAI_API_KEY"],
            base_url=os.environ.get("OPENAI_BASE_URL"),  # optional, for compatibles
        )

    def complete(self, system: str, user: str) -> tuple[str, int, int]:
        resp = self.client.chat.completions.create(
            model=self.model, max_tokens=512,
            messages=[{"role": "system", "content": system},
                      {"role": "user", "content": user}],
        )
        text = resp.choices[0].message.content or ""
        usage = resp.usage
        return text, usage.prompt_tokens, usage.completion_tokens


class MockProvider:
    """Free, deterministic, offline. Keyword heuristics -> a believable baseline."""
    name = "mock"

    def __init__(self, model: str = "mock"):
        self.model = model

    def complete(self, system: str, user: str) -> tuple[str, int, int]:
        t = user.lower()
        if re.search(r"vulnerab|security|cve|exploit", t):
            cat = "security"
        elif re.search(r"crash|error|broken|fail|regression|panic|exception", t):
            cat = "bug"
        elif re.search(r"add |support for|would be nice|feature|request|proposal", t):
            cat = "feature"
        elif re.search(r"how (do|can|to)|why does|question|\?", t):
            cat = "question"
        elif re.search(r"docs?|documentation|readme|typo", t):
            cat = "docs"
        elif re.search(r"\bci\b|build|test|flaky|pipeline", t):
            cat = "ci/build"
        else:
            cat = "other"
        pri = "high" if re.search(r"crash|data loss|security|urgent|production", t) else "medium"
        dup = bool(re.search(r"same as|already reported|duplicate", t))
        text = json.dumps({"category": cat, "priority": pri,
                           "is_duplicate": dup, "rationale": "mock heuristic"})
        return text, 0, 0


def get_provider(name: str, model: str | None) -> Provider:
    if name == "claude":
        return ClaudeProvider(model or "claude-sonnet-4-6")
    if name == "openai":
        return OpenAIProvider(model or "gpt-4o")
    if name == "mock":
        return MockProvider()
    raise ValueError(f"unknown provider: {name}")


def parse_response(text: str) -> dict:
    """Public helper used by triage.py to read a model response into fields."""
    data = _extract_json(text)
    raw_conf = data.get("confidence")
    try:
        confidence = max(0.0, min(1.0, float(raw_conf))) if raw_conf is not None else None
    except (TypeError, ValueError):
        confidence = None
    return {
        "category": str(data.get("category", "other")).lower().strip(),
        "priority": (str(data["priority"]).lower().strip()
                     if data.get("priority") else None),
        "is_duplicate": bool(data.get("is_duplicate", False)),
        "confidence": confidence,
        "rationale": data.get("rationale", ""),
    }
