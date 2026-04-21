"""Tests for the Blender template router."""
from parts_mcp.utils.template_router import resolve_template

YAGEO_471KD20TR = {
    "part_id": "sp_00a7f3e2",
    "sku": "SP-YAGEO-471KD20TR",
    "mpn": "471KD20-TR",
    "manufacturer": "YAGEO",
    "category": "Varistors",
    "package": "Disc",
    "parameters": {
        "voltage_rating": "470V",
        "diameter_mm": 20,
    },
}


def test_varistor_kd20_resolves():
    result = resolve_template(YAGEO_471KD20TR)
    assert result is not None
    assert result["template"] == "varistor_disc.blend"
    assert result["blender_params"]["diameter_mm"] == 20
    assert result["blender_params"]["voltage_label"] == "470V"


def test_varistor_kd14_resolves():
    part = {
        **YAGEO_471KD20TR,
        "mpn": "471KD14-TR",
        "parameters": {"voltage_rating": "470V", "diameter_mm": 14},
    }
    result = resolve_template(part)
    assert result is not None
    assert result["template"] == "varistor_disc.blend"
    assert result["blender_params"]["diameter_mm"] == 14


def test_unknown_category_returns_none():
    part = {
        "category": "Quantum Flux Capacitors",
        "package": "DIP-8",
        "mpn": "QFC-100",
        "parameters": {},
    }
    assert resolve_template(part) is None


def test_wrong_suffix_no_match():
    part = {
        **YAGEO_471KD20TR,
        "mpn": "471ZZ20-TR",
    }
    assert resolve_template(part) is None


def test_missing_mpn_returns_none():
    part = {
        "category": "Varistors",
        "package": "Disc",
        "parameters": {"voltage_rating": "470V"},
    }
    assert resolve_template(part) is None
