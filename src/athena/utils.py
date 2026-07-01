"""Shared utility functions."""

from __future__ import annotations

import json
import re
from typing import Any
from uuid import uuid4


def new_id() -> str:
    return str(uuid4())


def new_short_id() -> str:
    return uuid4().hex[:8]


def extract_json(text: str) -> Any:
    """Parse JSON from LLM output that may contain prose or markdown code fences.

    Tries three strategies in order:
      1. Direct parse (model followed instructions and returned bare JSON).
      2. Strip ```json ... ``` or ``` ... ``` fences.
      3. Slice from the first { or [ to the last matching closer.

    Raises ValueError if no valid JSON is found.
    """
    text = text.strip()

    try:
        return json.loads(text)
    except json.JSONDecodeError:
        pass

    fence = re.search(r"```(?:json)?\s*\n?([\s\S]*?)\n?```", text)
    if fence:
        try:
            return json.loads(fence.group(1).strip())
        except json.JSONDecodeError:
            pass

    # Pick whichever delimiter appears first so that '[{...}]' extracts the array,
    # not the inner object.
    first_brace = text.find("{")
    first_bracket = text.find("[")
    if first_brace == -1 and first_bracket == -1:
        raise ValueError(f"No valid JSON found in model output: {text[:300]!r}")
    if first_brace == -1 or (first_bracket != -1 and first_bracket < first_brace):
        pairs = [("[", "]"), ("{", "}")]
    else:
        pairs = [("{", "}"), ("[", "]")]
    for opener, closer in pairs:
        start = text.find(opener)
        end = text.rfind(closer)
        if start != -1 and end > start:
            try:
                return json.loads(text[start : end + 1])
            except json.JSONDecodeError:
                pass

    raise ValueError(f"No valid JSON found in model output: {text[:300]!r}")
