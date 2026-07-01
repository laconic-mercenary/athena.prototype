"""Tests for shared utility functions."""

import pytest

from athena.utils import extract_json


def test_bare_json_object() -> None:
    assert extract_json('{"target": "host", "notes": "ok"}') == {"target": "host", "notes": "ok"}


def test_bare_json_array() -> None:
    assert extract_json('[{"a": 1}, {"b": 2}]') == [{"a": 1}, {"b": 2}]


def test_strips_markdown_json_fence() -> None:
    text = '```json\n{"key": "value"}\n```'
    assert extract_json(text) == {"key": "value"}


def test_strips_plain_markdown_fence() -> None:
    text = '```\n{"key": "value"}\n```'
    assert extract_json(text) == {"key": "value"}


def test_extracts_from_surrounding_prose() -> None:
    text = 'Here is the result:\n{"target": "host", "notes": "done"}\nThat is all.'
    assert extract_json(text) == {"target": "host", "notes": "done"}


def test_extracts_array_from_prose() -> None:
    text = 'My findings:\n[{"command": "nmap", "command_output": "open"}]\nEnd.'
    assert extract_json(text) == [{"command": "nmap", "command_output": "open"}]


def test_raises_on_no_json() -> None:
    with pytest.raises(ValueError, match="No valid JSON"):
        extract_json("This is just plain text with no JSON at all.")


def test_raises_on_empty_string() -> None:
    with pytest.raises(ValueError, match="No valid JSON"):
        extract_json("")


def test_nested_object_preserved() -> None:
    data = {"observations": [{"specialist_id": "abc", "classification": "signal_info"}], "summary": "done"}
    import json
    assert extract_json(json.dumps(data)) == data
