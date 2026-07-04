"""Anthropic wrapper: model slots, structured output, prompt caching, usage counter.

Caching layout (the big cost lever on agent loops): the system prompt is a
stable prefix with a cache breakpoint; volatile content (snapshots, step
results) always comes after it in messages. A second top-level breakpoint
caches the growing conversation on tool loops.
"""

import re
from pathlib import Path

from groundhog import config

SMART = config.SMART_MODEL
FAST = config.FAST_MODEL

PROMPTS = Path(__file__).parent / "prompts"

_usage = {"calls": 0, "input_tokens": 0, "output_tokens": 0, "cache_read_input_tokens": 0}
_client = None


def _anthropic():
    global _client
    if _client is None:
        import anthropic

        _client = anthropic.Anthropic(api_key=config.ANTHROPIC_API_KEY)
    return _client


def usage_snapshot() -> dict | None:
    """Token spend for this process — None when no LLM call was made, so reports
    can assert 'fully static run' honestly."""
    return dict(_usage) if _usage["calls"] else None


def _record(usage) -> None:
    _usage["calls"] += 1
    _usage["input_tokens"] += usage.input_tokens
    _usage["output_tokens"] += usage.output_tokens
    _usage["cache_read_input_tokens"] += usage.cache_read_input_tokens or 0


def prompt(name: str, **slots: str) -> str:
    """Load llm/prompts/<name>.md and fill its {{slot}} placeholders."""
    text = (PROMPTS / f"{name}.md").read_text()
    return re.sub(r"\{\{(\w+)\}\}", lambda m: slots.get(m.group(1), ""), text)


def _system_block(system: str) -> list[dict]:
    return [{"type": "text", "text": system, "cache_control": {"type": "ephemeral"}}]


def parse(user: str, output_model, system: str, model: str = FAST, max_tokens: int = 4096):
    """One structured-output call; the SDK validates against the Pydantic model.
    One retry on transient failures."""
    import anthropic

    last = None
    for _ in range(2):
        try:
            resp = _anthropic().messages.parse(
                model=model,
                max_tokens=max_tokens,
                system=_system_block(system),
                messages=[{"role": "user", "content": user}],
                output_format=output_model,
            )
            _record(resp.usage)
            return resp.parsed_output
        except (anthropic.APIConnectionError, anthropic.RateLimitError, anthropic.InternalServerError) as e:
            last = e
    raise last


def message(messages: list[dict], system: str, tools: list[dict] | None = None,
            model: str = FAST, max_tokens: int = 2048):
    """One raw call for tool loops; caller owns the conversation. The top-level
    cache_control caches the growing message prefix between loop turns."""
    resp = _anthropic().messages.create(
        model=model,
        max_tokens=max_tokens,
        system=_system_block(system),
        messages=messages,
        tools=tools or [],
        cache_control={"type": "ephemeral"},
    )
    _record(resp.usage)
    return resp
