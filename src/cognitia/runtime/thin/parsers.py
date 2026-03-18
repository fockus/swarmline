"""Parsers module."""

from __future__ import annotations

import json
from typing import Any

from pydantic import ValidationError

from cognitia.runtime.thin.json_utils import find_json_object_boundaries
from cognitia.runtime.thin.schemas import ActionEnvelope, PlanSchema


def strip_markdown_fences(raw: str) -> str:
    """Strip markdown fences."""
    cleaned = raw.strip()
    if not cleaned.startswith("```"):
        return cleaned

    lines = cleaned.split("\n")
    inner_lines: list[str] = []
    started = False
    for line in lines:
        if line.strip().startswith("```") and not started:
            started = True
            continue
        if line.strip() == "```" and started:
            break
        if started:
            inner_lines.append(line)
    return "\n".join(inner_lines).strip()


def extract_first_json_object(text: str) -> str | None:
    """Extract first json object."""
    bounds = find_json_object_boundaries(text)
    if bounds is None:
        return None
    return text[bounds[0] : bounds[1]]


def parse_json_dict(raw: str) -> dict[str, Any] | None:
    """Parse json dict."""
    cleaned = strip_markdown_fences(raw)


    try:
        data = json.loads(cleaned)
        if isinstance(data, dict):
            return data
    except json.JSONDecodeError:
        pass


    extracted = extract_first_json_object(cleaned)
    if not extracted:
        return None
    try:
        data = json.loads(extracted)
        if isinstance(data, dict):
            return data
    except json.JSONDecodeError:
        return None
    return None


def parse_envelope(raw: str) -> ActionEnvelope | None:
    """Parse envelope."""
    try:
        data = parse_json_dict(raw)
        if data is None:
            return None
        return ActionEnvelope.model_validate(data)
    except (json.JSONDecodeError, ValidationError):
        return None


def parse_plan(raw: str) -> PlanSchema | None:
    """Parse plan."""
    try:
        data = parse_json_dict(raw)
        if data is None:
            return None
        return PlanSchema.model_validate(data)
    except (json.JSONDecodeError, ValidationError):
        return None


def extract_text_fallback(raw: str) -> str:
    """Extract text fallback."""
    text = strip_markdown_fences(raw).strip()
    if not text:
        return ""

    if text.startswith("{") and text.endswith("}"):
        return ""
    if len(text) > 2000:
        return f"{text[:2000]}..."
    return text
