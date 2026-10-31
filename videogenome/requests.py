"""Shared request contracts for Studio, MCP and rendering entry points."""
from __future__ import annotations

import json
import math

from jsonschema import Draft202012Validator

from videogenome.compiler import ProductionError

IDENTIFIER = {"type": "string", "minLength": 1, "maxLength": 200}
BRIEF = {"type": "string", "maxLength": 12000}
NAME = {"type": "string", "minLength": 1, "maxLength": 120}
FORMATS = {"type": "array", "minItems": 1, "maxItems": 8, "uniqueItems": True,
           "items": {"type": "string", "pattern": "^(all|[1-9][0-9]?[x:][1-9][0-9]?)$"},
           "description": "Delivery formats to render (aspect ids from the template's formats, e.g. 9x16, "
                          "or 'all'); default: the template's main format"}
RENDER_PROPERTIES = {
    "size": {"type": "string", "pattern": "^[0-9]{2,4}x[0-9]{2,4}$"},
    "fps": {"type": "integer", "minimum": 1, "maximum": 120},
    "duration": {"type": "number", "minimum": 0.05, "maximum": 600},
    "seed": {"type": "integer", "minimum": 0, "maximum": 4294967295},
    "params": {"type": "object"},
}
COPY_PROPERTIES = {"template": IDENTIFIER, "inputs": {"type": "object"}, "brief": BRIEF, "formats": FORMATS}
PREVIEW_PROPERTIES = {"recipe": IDENTIFIER, "preset": {"type": "string", "maxLength": 200}, **RENDER_PROPERTIES}
CAPTURE_PROPERTIES = {
    "html": {"type": "string", "minLength": 1, "maxLength": 4 * 1024 * 1024},
    **RENDER_PROPERTIES, "click": {"type": "boolean"}, "audio": {"type": "boolean"}, "name": NAME,
}


def object_schema(properties: dict, required: tuple[str, ...] = ()) -> dict:
    return {"type": "object", "properties": properties, "required": list(required),
            "additionalProperties": False}


def parse_request(text: str | bytes) -> object:
    def reject(value: str) -> None:
        raise ValueError(f"Invalid JSON number: {value}")
    return json.loads(text, parse_constant=reject)


def validate_request(value: object, schema: dict) -> None:
    """Reject invalid types, undeclared controls and non-finite numbers before work starts."""
    pending = [(value, 0)]
    while pending:
        item, depth = pending.pop()
        if depth > 64:
            raise ProductionError("Request nesting exceeds 64 levels")
        if isinstance(item, float) and not math.isfinite(item):
            raise ProductionError("Request numbers must be finite")
        if isinstance(item, str):
            try:
                item.encode("utf-8")
            except UnicodeEncodeError as exc:
                raise ProductionError("Request text must contain valid Unicode") from exc
        if isinstance(item, dict):
            if any(not isinstance(key, str) for key in item):
                raise ProductionError("Request object keys must be strings")
            pending.extend((key, depth + 1) for key in item)
            pending.extend((child, depth + 1) for child in item.values())
        elif isinstance(item, list):
            pending.extend((child, depth + 1) for child in item)
    error = next(Draft202012Validator(schema).iter_errors(value), None)
    if error is not None:
        path = "/" + "/".join(map(str, error.absolute_path))
        raise ProductionError(f"Invalid request at {path}: {error.message[:500]}")
