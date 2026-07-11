"""Anthropic wrapper: model slots, structured output, prompt caching, usage counter.

Caching layout (the big cost lever on agent loops): the system prompt is a
stable prefix with a cache breakpoint; volatile content (snapshots, step
results) always comes after it in messages. A second top-level breakpoint
caches the growing conversation on tool loops.
"""

from pathlib import Path

from groundhog import config
from groundhog.cases.store import render

SMART = config.SMART_MODEL
FAST = config.FAST_MODEL

PROMPTS = Path(__file__).parent / "prompts"

_usage = {"calls": 0, "input_tokens": 0, "output_tokens": 0, "cache_read_input_tokens": 0}
_client = None


def _anthropic():
    global _client
    if _client is None:
        import anthropic

        # SDK-native resilience: the client already retries connection errors,
        # 429s and 5xx (incl. 529 overloaded) with exponential backoff on
        # every call, honoring retry-after — raised from the default 2 to 5
        # so a flaky call mid-authoring doesn't kill a long agent loop.
        _client = anthropic.Anthropic(api_key=config.ANTHROPIC_API_KEY, max_retries=5)
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
    """Load llm/prompts/<name>.md and fill its {{slot}} placeholders — with the
    same render() cases use, so illustrative {{var}} examples in prompt prose
    stay literal instead of being blanked out of the text the model sees."""
    return render((PROMPTS / f"{name}.md").read_text(), slots)


def _system_block(system: str) -> list[dict]:
    return [{"type": "text", "text": system, "cache_control": {"type": "ephemeral"}}]


def parse(user: str, output_model, system: str, model: str = FAST, max_tokens: int = 4096):
    """One structured-output call; the SDK validates against the Pydantic model.
    Transient failures are retried by the SDK client itself."""
    resp = _anthropic().messages.parse(
        model=model,
        max_tokens=max_tokens,
        system=_system_block(system),
        messages=[{"role": "user", "content": user}],
        output_format=output_model,
    )
    _record(resp.usage)
    return resp.parsed_output


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
