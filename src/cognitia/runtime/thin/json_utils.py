"""Json Utils module."""

from __future__ import annotations


def find_json_object_boundaries(text: str, start: int = 0) -> tuple[int, int] | None:
    """Find json object boundaries."""
    obj_start = text.find("{", start)
    if obj_start == -1:
        return None

    depth = 0
    in_string = False
    escape = False

    for idx in range(obj_start, len(text)):
        ch = text[idx]

        if in_string:
            if escape:
                escape = False
            elif ch == "\\":
                escape = True
            elif ch == '"':
                in_string = False
            continue

        if ch == '"':
            in_string = True
            continue

        if ch == "{":
            depth += 1
        elif ch == "}":
            depth -= 1
            if depth == 0:
                return (obj_start, idx + 1)

    return None
