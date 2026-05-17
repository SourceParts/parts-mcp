"""
Unit tests for the local paths of parts_mcp/tools/sch_repair.py:
ERC report categorization + pin-position math.

The HTTP-backed tools (sch_check_structure, sch_remove_wires,
sch_libsync) aren't covered here — they need integration tests
against a live API.
"""
from __future__ import annotations

import json

import pytest

from parts_mcp.tools.sch_repair import (
    _categorize_erc,
    _compute_pin_position,
)


class TestCategorizeERC:
    def test_groups_by_type_with_uuid_lists(self):
        report = json.dumps(
            {
                "violations": [
                    {
                        "type": "unconnected_wire_endpoint",
                        "description": "Wire endpoint is not connected",
                        "items": [
                            {"uuid": "u1"},
                            {"uuid": "u2"},
                        ],
                    },
                    {
                        "type": "endpoint_off_grid",
                        "description": "Wire endpoint off grid",
                        "items": [{"uuid": "u3"}],
                    },
                ]
            }
        ).encode("utf-8")
        r = _categorize_erc(report)
        assert r["total"] == 3
        assert r["by_type"]["unconnected_wire_endpoint"]["count"] == 2
        assert set(r["by_type"]["unconnected_wire_endpoint"]["uuids"]) == {"u1", "u2"}
        assert r["by_type"]["endpoint_off_grid"]["count"] == 1
        assert r["by_type"]["endpoint_off_grid"]["sample_description"] == "Wire endpoint off grid"

    def test_empty_report(self):
        report = b'{"violations": []}'
        r = _categorize_erc(report)
        assert r["total"] == 0
        assert r["by_type"] == {}

    def test_items_without_uuid_dont_count(self):
        report = json.dumps(
            {
                "violations": [
                    {
                        "type": "unknown",
                        "items": [{"no_uuid": "x"}, {"uuid": "real"}],
                    }
                ]
            }
        ).encode("utf-8")
        r = _categorize_erc(report)
        assert r["total"] == 1
        assert r["by_type"]["unknown"]["uuids"] == ["real"]


class TestPinPosition:
    """The cases that cost multiple debugging sessions per the RFC.
    These tests pin down the formula so it doesn't have to be
    re-derived. Tolerances are 1e-9 (exact arithmetic at 90° steps)."""

    def test_zero_rotation_identity(self):
        # sym at origin, no rotation, pin at lib (1, 0)
        # → expected: (1, 0) because negate_Y on (1,0) = (1,0)
        x, y = _compute_pin_position(0, 0, 0, 1, 0)
        assert x == pytest.approx(1.0)
        assert y == pytest.approx(0.0)

    def test_180_rotation_inverts_x(self):
        # RFC example: sym=(17.78, 93.98, 180°), pin_lib=(-0.254, 0)
        # → negate_Y → (-0.254, 0) → CW180° → (0.254, 0) → +sym → (18.034, 93.98)
        x, y = _compute_pin_position(17.78, 93.98, 180, -0.254, 0)
        assert x == pytest.approx(18.034)
        assert y == pytest.approx(93.98)

    def test_90_cw_rotation(self):
        # sym at (10, 10), 90° CW, pin_lib at (1, 0)
        # negate_Y: (1, 0) → CW90°: (x,y) → (x·cos90 + y·sin90, -x·sin90 + y·cos90)
        #                       = (0·1 + 0·1, -1·1 + 0·1) wait that's wrong
        # CW90 by formula: (x, y) → (y, -x) so (1, 0) → (0, -1)
        # → + (10, 10) = (10, 9)
        x, y = _compute_pin_position(10, 10, 90, 1, 0)
        assert x == pytest.approx(10.0)
        assert y == pytest.approx(9.0)

    def test_270_cw_rotation(self):
        # sym at origin, 270° CW = 90° CCW, pin_lib (1, 0)
        # negate_Y: (1, 0) → CW270°: (x,y) → (x·cos270 + y·sin270, -x·sin270 + y·cos270)
        #                       = (0 - 1, 1 + 0) = (-1·-1, ... ) — easier check:
        # CW270 of (1,0) is (0, 1)
        x, y = _compute_pin_position(0, 0, 270, 1, 0)
        assert x == pytest.approx(0.0)
        assert y == pytest.approx(1.0)

    def test_pin_with_nonzero_y(self):
        # pin_lib at (0, 2), no sym rotation
        # negate_Y → (0, -2) → no rotation → (0, -2)
        x, y = _compute_pin_position(0, 0, 0, 0, 2)
        assert x == pytest.approx(0.0)
        assert y == pytest.approx(-2.0)
