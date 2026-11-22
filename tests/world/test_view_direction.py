#!/usr/bin/env python3
"""[QuadRix] Tests for quadrix/world/view_direction.py.

Port of horizon-world/src/view_direction.rs.
"""

from __future__ import annotations

import math

import pytest

from quadrix.core.geometry import Vec3
from quadrix.world.view_direction import (
    BLOCKING_FALLBACK_ANGLE,
    acos,
    blocking_angle,
    view_vector,
)


def test_view_vector_cardinal_directions():
    def close(vector: Vec3, expected: Vec3) -> bool:
        # ``close`` is reused for the straight-up/down cases too.
        return (
            abs(vector.x - expected.x) < 1e-6
            and abs(vector.y - expected.y) < 1e-6
            and abs(vector.z - expected.z) < 1e-6
        )

    assert close(view_vector(0.0, 0.0), Vec3(0.0, 0.0, 1.0))

    # Looking straight up: pitch -90.
    assert close(view_vector(-90.0, 0.0), Vec3(0.0, 1.0, 0.0))
    # Looking straight down: pitch +90.
    assert close(view_vector(90.0, 0.0), Vec3(0.0, -1.0, 0.0))
    # Yaw 90 faces -X in Minecraft's left-handed convention.
    west = view_vector(0.0, 90.0)
    assert west.x == pytest.approx(-1.0, abs=1e-6)
    assert west.z == pytest.approx(0.0, abs=1e-6)


def test_view_vector_is_unit_length():
    for pitch, yaw in ((0.0, 0.0), (37.0, -120.0), (-61.5, 245.0)):
        length = view_vector(pitch, yaw).length()
        assert length == pytest.approx(1.0, abs=1e-5)


def test_acos_clamps_out_of_range_inputs():
    assert acos(2.0) == 0.0
    assert acos(-2.0) == pytest.approx(math.pi)
    assert acos(0.5) == pytest.approx(math.pi / 3.0)


def test_blocking_angle_in_front_and_behind():
    position = Vec3(0.0, 0.0, 0.0)
    # Source straight ahead, facing +Z.
    assert blocking_angle(Vec3(0.0, 0.0, 3.0), position, 0.0) == pytest.approx(0.0)
    # Source directly behind.
    behind = blocking_angle(Vec3(0.0, 0.0, -3.0), position, 0.0)
    assert behind == pytest.approx(math.pi)
    # Source to the left/right => 90 degrees.
    side = blocking_angle(Vec3(3.0, 0.0, 0.0), position, 0.0)
    assert side == pytest.approx(math.pi / 2.0, abs=1e-6)


def test_blocking_angle_ignores_vertical_offset():
    position = Vec3(0.0, 0.0, 0.0)
    flat = blocking_angle(Vec3(0.0, 0.0, 3.0), position, 0.0)
    raised = blocking_angle(Vec3(0.0, 50.0, 3.0), position, 0.0)
    assert raised == pytest.approx(flat)


def test_blocking_angle_same_position_falls_back_to_right_angle():
    origin = Vec3(1.0, 2.0, 3.0)
    assert blocking_angle(origin, origin, 45.0) == pytest.approx(math.pi / 2.0)


def test_blocking_fallback_angle_is_f32_pi():
    assert BLOCKING_FALLBACK_ANGLE == pytest.approx(math.pi, abs=1e-6)
    assert BLOCKING_FALLBACK_ANGLE != math.pi