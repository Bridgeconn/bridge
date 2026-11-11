"""#475: the price table matches what the provider billed on #469 (2026-11-05/06,
read off the usage dashboard CSV: sol $5.00 / $0.50 / $20.00, terra $2.50 /
$0.25 / $12.00 per million input / cached input / output). A wrong row
mis-states the AI tab's cost line and the lifetime counter in the same
direction on every call."""
from __future__ import annotations

from tc_ai_bridge.model_router import DEFAULT_PRICES, cheapest_model, estimate_cost

M = 1_000_000


def test_sol_and_terra_rows_match_the_469_measurement():
    assert DEFAULT_PRICES["gpt-5.6-sol"] == {"input": 5.00, "cached_input": 0.50, "output": 20.00}
    assert DEFAULT_PRICES["gpt-5.6"] == DEFAULT_PRICES["gpt-5.6-sol"]  # billed as sol
    assert DEFAULT_PRICES["gpt-5.6-terra"] == {"input": 2.50, "cached_input": 0.25, "output": 12.00}


def test_estimate_cost_prices_cached_input_at_the_cached_rate():
    assert estimate_cost("gpt-5.6-sol", M, M) == 25.00
    assert estimate_cost("gpt-5.6-terra", M, 0, cached_input_tokens=M) == 0.25
    assert estimate_cost("gpt-5.6-terra", M, M, cached_input_tokens=M // 2) == 1.25 + 0.125 + 12.00
    assert estimate_cost("unknown-model", M, 0) == 5.00  # falls back to the sol row
    assert cheapest_model() == "gpt-5.6-luna"
