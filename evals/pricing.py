"""Cost from recorded token usage. USD per million tokens (Anthropic list prices, Oct 2026).

Cost is always computed from the API's own `usage` numbers and the model that served the request,
never estimated from text length.
"""

PRICES = {
    # model: (input, output, cache write 5m, cache read)
    "claude-opus-5-5": (4.00, 20.00, 5.00, 0.20),
    "claude-sonnet-5-5": (2.00, 10.00, 2.50, 0.20),
    # Haiku 5.5 cache rates assumed at the usual 1.25x / 0.1x multipliers
    "claude-haiku-5-5": (0.10, 0.50, 0.125, 0.01),
}


def cost_usd(model: str, usage: dict) -> float:
    if model not in PRICES:
        return 0.0
    p_in, p_out, p_write, p_read = PRICES[model]
    return (usage.get("input_tokens", 0) * p_in + usage.get("output_tokens", 0) * p_out
            + usage.get("cache_creation_input_tokens", 0) * p_write
            + usage.get("cache_read_input_tokens", 0) * p_read) / 1_000_000
