"""The visible cache metric accounts for every measured prompt, including misses."""
import json

import pytest

from bridge.core import analytics


@pytest.mark.parametrize('prompts, expected', [
    ([], None),
    ([(100, 0)], 0),
    ([(100, 100), (300, 0)], 25),
    ([(100, 100), (300, 150)], 62),
])
def test_cache_hit_percentage_weights_all_prompt_tokens(tmp_path, monkeypatch, prompts, expected):
    monkeypatch.setattr(analytics, 'ROOT', tmp_path)
    monkeypatch.setattr(analytics, '_analytics_pruned', False)
    for index, (input_tokens, cached_tokens) in enumerate(prompts):
        analytics.log_turn('direct' if index % 2 else 'agent', 'fixture-model',
                           input_tokens, 10, cached_tokens, 20, 0.5)
    payload = json.loads(analytics.api_analytics().body)
    assert 'error' not in payload
    assert payload['cache_hit_pct'] == expected
    assert payload['turns_today'] == len(prompts)
    assert payload['tokens_today'] == 10 * len(prompts)
