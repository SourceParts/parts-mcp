"""
Template router for the Blender render pipeline.

Maps parts to .blend templates using category + package + MPN suffix heuristics.
Every route entry defines a match predicate and a params_fn that extracts
Blender-specific parameters from the part record.
"""
import re
from collections.abc import Callable
from typing import Any

RouteMatch = dict[str, str | None]
ParamsFn = Callable[[dict[str, Any]], dict[str, Any]]


class _Route:
    __slots__ = ("match", "template", "params_fn")

    def __init__(self, match: RouteMatch, template: str, params_fn: ParamsFn):
        self.match = match
        self.template = template
        self.params_fn = params_fn


ROUTE_TABLE: list[_Route] = [
    _Route(
        match={
            "category": "Varistors",
            "suffix_pattern": r"KD(\d+)",
        },
        template="varistor_disc.blend",
        params_fn=lambda part: {
            "diameter_mm": int(re.search(r"KD(\d+)", part["mpn"]).group(1)),
            "voltage_label": part["parameters"]["voltage_rating"],
        },
    ),
]


def resolve_template(part: dict[str, Any]) -> dict[str, Any] | None:
    """Resolve a part to a Blender template and parameter set.

    Args:
        part: Part record dict with at least 'category', 'package', 'mpn',
              and 'parameters' keys.

    Returns:
        {"template": str, "blender_params": dict} or None if no route matches.
    """
    for route in ROUTE_TABLE:
        m = route.match

        if m.get("category") and m["category"] != part.get("category"):
            continue
        if m.get("package") and m["package"] != part.get("package"):
            continue
        if m.get("suffix_pattern"):
            if not re.search(m["suffix_pattern"], part.get("mpn", "")):
                continue

        return {
            "template": route.template,
            "blender_params": route.params_fn(part),
        }

    return None
