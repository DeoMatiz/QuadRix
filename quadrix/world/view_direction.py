#!/usr/bin/env python3
"""[QuadRix] Native view direction and horizontal blocking-angle arithmetic.

Port of horizon/crates/horizon-world/src/view_direction.rs (Minecraft 26.3).
"""

from __future__ import annotations

import math
import struct

from quadrix.core.geometry import Vec3

__all__ = [
    "view_vector",
    "acos",
    "blocking_angle",
    "BLOCKING_FALLBACK_ANGLE",
]

DEG_TO_RAD = math.pi / 180.0


def _f32(value: float) -> float:
    return struct.unpack("<f", struct.pack("<f", float(value)))[0]


def view_vector(pitch: float, yaw: float) -> Vec3:
    """``view_vector`` (view_direction.rs:3)."""
    pitch = _f32(_f32(pitch) * _f32(DEG_TO_RAD))
    yaw = _f32(_f32(-yaw) * _f32(DEG_TO_RAD))
    cy = _f32(math.cos(float(yaw)))
    sy = _f32(math.sin(float(yaw)))
    cp = _f32(math.cos(float(pitch)))
    sp = _f32(math.sin(float(pitch)))
    return Vec3(float(_f32(sy * cp)), float(_f32(-sp)), float(_f32(cy * cp)))


def acos(value: float) -> float:
    """``view_direction::acos`` (view_direction.rs:14).

    Java ``Math.acos`` comparisons use the pinned pure-Rust implementation;
    Python's ``math.acos`` is the platform libm (close, not bit-identical for
    every input, as documented for the Rust port too).
    """
    if value > 1.0:
        value = 1.0
    elif value < -1.0:
        value = -1.0
    return math.acos(value)


def blocking_angle(source: Vec3, position: Vec3, head_yaw: float) -> float:
    """``blocking_angle`` (view_direction.rs:17)."""
    view = view_vector(0.0, head_yaw)
    delta = source.subtract(position)
    horizontal = Vec3(delta.x, 0.0, delta.z).normalize()
    return acos(horizontal.dot(view))


#: ``BLOCKING_FALLBACK_ANGLE`` — f32 PI widened to f64 (view_direction.rs:24).
BLOCKING_FALLBACK_ANGLE: float = float(_f32(math.pi))
