from __future__ import annotations

# USD per million tokens, kept in one place; there is no settings override.
# Source (#475): the #469 measurement of 2026-11-05/06, Hindi IRV GEN 1 on a
# real key, read off the OpenAI usage dashboard's per-model CSV: cache-write
# tokens x input price + cached tokens x cached price + output tokens x output
# price reproduced each run's spend movement to the cent. gpt-5.6 is billed as
# gpt-5.6-sol. The earlier table (sol output $30, terra input $2.00) over-priced
# gpt-5.6 and under-priced terra. Re-check against the dashboard after a price
# change by the provider; the luna row is unmeasured and kept as it was.
DEFAULT_PRICES = {
    'gpt-5.6-sol': {'input': 5.00, 'cached_input': 0.50, 'output': 20.00},
    'gpt-5.6': {'input': 5.00, 'cached_input': 0.50, 'output': 20.00},
    'gpt-5.6-terra': {'input': 2.50, 'cached_input': 0.25, 'output': 12.00},
    'gpt-5.6-luna': {'input': 0.20, 'cached_input': 0.02, 'output': 1.20},
}

# #473: the AI tasks a model and a reasoning effort can be chosen for. The
# `ModelRouter` class that used to live here (severity-based routing with
# economy/balanced/quality profiles) was never instantiated outside its own
# tests and is deleted; the per-task choice is a setting
# (`AppSettings.ai_tasks`), and the defaults below are what it starts from.
AI_TASKS = ('review', 'alignment', 'triage')
REASONING_EFFORTS = ('low', 'medium', 'high', 'xhigh')
# Today's behaviour, kept as the default: one configured model, medium
# reasoning, for every task. Switching it off in Settings > AI exposes the
# per-task rows. The review row's blank model means "the configured model";
# the review tier itself is not changed here (that waits on the #469
# comparison).
DEFAULT_USE_ONE_MODEL = True


def cheapest_model(prices: dict | None = None) -> str:
    """The cheapest tier of the price table by input price: the default for
    the alignment and triage tasks when the per-task rows are in use."""
    table = prices or DEFAULT_PRICES
    return min(table, key=lambda name: (table[name]['input'], table[name]['output'], name))


def default_task_models() -> dict[str, dict[str, str]]:
    cheap = cheapest_model()
    return {
        'review': {'model': '', 'reasoningEffort': 'medium'},
        'alignment': {'model': cheap, 'reasoningEffort': 'low'},
        'triage': {'model': cheap, 'reasoningEffort': 'low'},
    }


def estimate_cost(model:str,input_tokens:int,output_tokens:int,cached_input_tokens:int=0,prices=None) -> float:
    prices=prices or DEFAULT_PRICES; p=prices.get(model) or prices.get('gpt-5.6-sol')
    fresh=max(0,input_tokens-cached_input_tokens)
    return (fresh*p['input'] + cached_input_tokens*p['cached_input'] + output_tokens*p['output'])/1_000_000.0
