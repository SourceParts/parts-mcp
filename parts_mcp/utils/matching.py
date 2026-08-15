"""MPN match verification.

search_parts is fuzzy by design; every tool that takes its top hit and acts
on it (pricing, availability, BOM costing) must be able to tell an exact
part-number match from a fuzzy suggestion. Field test 2026-08-08: 13 of 26
BOM rows silently matched a different component (8 clearly wrong — a 5.1k
resistor priced as an inductor, a TI LDO swapped for a different TI LDO),
and the response carried no signal automation could gate on.

Verification is deliberately strict: the normalized query must equal a
normalized identifier of the candidate. A suffix variant (BSS138 vs
BSS138LT1G) is NOT verified — for costing, "almost the right part" is the
failure mode, not a success.
"""
import re
from typing import Any

_NON_ALNUM = re.compile(r"[^A-Z0-9]+")

# Whole-string identifiers on a search result / product dict.
_IDENTIFIER_FIELDS = ("part_number", "mpn", "model", "model_name", "sku", "sp_sku")
_METADATA_FIELDS = ("manufacturer_part_number", "external_id", "source_sku")
# Fields where the identifier appears as one token among others
# (e.g. name: "TECH PUBLIC TS3USB221RSER-TP").
_TOKEN_FIELDS = ("name",)


def normalize_mpn(value: Any) -> str:
    """Uppercase and strip everything but letters/digits.

    ERJ-3RQJR47V and ERJ 3RQJR47V normalize identically; ERA50V2200M16X30
    stays distinct.
    """
    if not value:
        return ""
    return _NON_ALNUM.sub("", str(value).upper())


def verify_mpn_match(query: str, candidate: dict[str, Any] | None) -> bool:
    """True when the candidate is an exact (normalized) hit for the query."""
    q = normalize_mpn(query)
    if not q or not isinstance(candidate, dict):
        return False

    metadata = candidate.get("metadata") or {}
    for field in _IDENTIFIER_FIELDS:
        if normalize_mpn(candidate.get(field)) == q:
            return True
    for field in _METADATA_FIELDS:
        if normalize_mpn(metadata.get(field)) == q:
            return True
    for field in _TOKEN_FIELDS:
        value = candidate.get(field)
        if value and any(normalize_mpn(tok) == q for tok in str(value).split()):
            return True
    return False


def describe_candidate(candidate: dict[str, Any]) -> dict[str, Any]:
    """Compact identity of a candidate, for 'closest match was …' messages."""
    metadata = candidate.get("metadata") or {}
    return {
        "sku": candidate.get("sku"),
        "part_number": candidate.get("part_number")
        or metadata.get("manufacturer_part_number")
        or candidate.get("name"),
        "manufacturer": candidate.get("manufacturer"),
    }
