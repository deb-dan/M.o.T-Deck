"""Malformed guard policy must not retain broad allows while losing denies."""
import importlib.util
from pathlib import Path

import pytest


@pytest.fixture
def guard():
    path = Path(__file__).resolve().parents[2] / 'guards/motdeck-path-guard/__init__.py'
    spec = importlib.util.spec_from_file_location('guard_policy_truth', path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.mark.parametrize('policy', [
    'allow:\n  - /Users/person\ndeny: [unterminated',
    'allow:\n  - /Users/person\ndeny: /Users/person/.ssh',
    'allow:\n  - /Users/person\ndeny:\n  - {path: /Users/person/.ssh}',
])
def test_invalid_policy_never_retains_allows(guard, policy):
    assert guard.parse_policy_text(policy)['allow'] == []


def test_minimal_parser_keeps_hash_inside_quoted_path(guard):
    assert guard._mini_parse('allow:\n  - "/work/#project" # comment\ndeny:\n  - "/work/#project/private"')['deny'] == ['/work/#project/private']


def test_minimal_parser_rejects_partial_invalid_policy(guard):
    assert guard._mini_parse('allow:\n  - /work\ndeny: [unterminated')['allow'] == []
