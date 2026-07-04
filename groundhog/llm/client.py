"""Anthropic wrapper: model slots, structured output, prompt caching, usage counter."""

_usage = {"calls": 0, "input_tokens": 0, "output_tokens": 0, "cache_read_input_tokens": 0}


def usage_snapshot() -> dict | None:
    """Token spend for this process — None when no LLM call was made, so reports
    can assert 'fully static run' honestly."""
    return dict(_usage) if _usage["calls"] else None
