"""Anthropic wrapper: one structured-output call plus a usage counter.

Only used for text Jev can't produce: field values the intent doesn't spell
out, and flow composition. Browser decisions go through groundhog.jev.
"""

from groundhog import config

_usage = {"calls": 0, "input_tokens": 0, "output_tokens": 0, "cache_read_input_tokens": 0}
_client = None


def _anthropic():
    global _client
    if not config.ANTHROPIC_API_KEY:
        # Every Anthropic caller routes through here, so one guard turns a raw
        # SDK 401 into the message the CLI already knows how to print.
        raise RuntimeError("ANTHROPIC_API_KEY is not set — add it to .env "
                           "(it unlocks `flow new` and field values the intent doesn't spell out)")
    if _client is None:
        import anthropic

        # The SDK retries connection errors, 429s and 5xx itself; 5 attempts so a
        # flaky call mid-authoring doesn't kill a long agent loop.
        _client = anthropic.Anthropic(api_key=config.ANTHROPIC_API_KEY, max_retries=5)
    return _client


def usage_snapshot() -> dict | None:
    """Token spend for this process, None when no call was made, so reports can
    say 'fully static run' honestly."""
    return dict(_usage) if _usage["calls"] else None


def parse(user: str, output_model, system: str, max_tokens: int = 4096):
    """One structured-output call; the SDK validates against the Pydantic model."""
    resp = _anthropic().messages.parse(
        model=config.ANTHROPIC_MODEL,
        max_tokens=max_tokens,
        system=[{"type": "text", "text": system, "cache_control": {"type": "ephemeral"}}],
        messages=[{"role": "user", "content": user}],
        output_format=output_model,
    )
    _usage["calls"] += 1
    _usage["input_tokens"] += resp.usage.input_tokens
    _usage["output_tokens"] += resp.usage.output_tokens
    _usage["cache_read_input_tokens"] += resp.usage.cache_read_input_tokens or 0
    return resp.parsed_output
