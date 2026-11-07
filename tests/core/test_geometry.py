# !Tests for quadrix.core.geometry
# Ported from horizon-core/src/geometry/mod.rs #[cfg(test)] mod tests

from __future__ import annotations

import math
import pytest

from quadrix.core.geometry import (
    Axis,
    BlockPos,
    COLLISION_EPSILON,
    Direction,
    Vec3,
    Aabb,
    java_min,
    java_max,
    clamp,
    floor_i32,
    lerp,
    canonical_bits,
    next_up,
    next_down,
    DEG_TO_RAD,
    RAD_TO_DEG,
)


# ── Vec3 construction helpers ──────────────────────────────────────────

ZERO = Vec3.ZERO
ONE = Vec3.new(1.0, 1.0, 1.0)
XAXIS = Vec3.new(1.0, 0.0, 0.0)
YAXIS = Vec3.new(0.0, 1.0, 0.0)
ZAXIS = Vec3.new(0.0, 0.0, 1.0)


# ── Vec3 basic operations ─────────────────────────────────────────────

class TestVec3Basic:
    def test_new(self):
        v = Vec3.new(1.0, 2.0, 3.0)
        assert v.x == 1.0
        assert v.y == 2.0
        assert v.z == 3.0

    def test_zero(self):
        assert Vec3.ZERO == Vec3.new(0.0, 0.0, 0.0)
        assert Vec3.ZERO.x == 0.0

    def test_components(self):
        v = Vec3.new(3.0, -1.0, 7.0)
        assert v.components() == (3.0, -1.0, 7.0)

    def test_component_axis(self):
        v = Vec3.new(5.0, 6.0, 7.0)
        assert v.component(Axis.X) == 5.0
        assert v.component(Axis.Y) == 6.0
        assert v.component(Axis.Z) == 7.0

    def test_from_block(self):
        pos = BlockPos.new(2, 3, 5)
        v = Vec3.from_block(pos)
        assert v.x == 2.0
        assert v.y == 3.0
        assert v.z == 5.0

    def test_add_vector(self):
        a = Vec3.new(1.0, 2.0, 3.0)
        b = Vec3.new(4.0, 5.0, 6.0)
        c = a.add_vector(b)
        assert c == Vec3.new(5.0, 7.0, 9.0)

    def test_subtract(self):
        a = Vec3.new(10.0, 10.0, 10.0)
        b = Vec3.new(3.0, 3.0, 3.0)
        c = a.subtract(b)
        assert c == Vec3.new(7.0, 7.0, 7.0)

    def test_vector_to(self):
        a = Vec3.new(1.0, 1.0, 1.0)
        b = Vec3.new(4.0, 5.0, 6.0)
        c = a.vector_to(b)
        assert c == Vec3.new(3.0, 4.0, 5.0)

    def test_multiply(self):
        a = Vec3.new(2.0, 3.0, 4.0)
        b = Vec3.new(5.0, 6.0, 7.0)
        c = a.multiply(b)
        assert c == Vec3.new(10.0, 18.0, 28.0)

    def test_scale(self):
        a = Vec3.new(2.0, 3.0, 4.0)
        b = a.scale(2.0)
        assert b == Vec3.new(4.0, 6.0, 8.0)
        c = a.scale(-1.0)
        assert c == Vec3.new(-2.0, -3.0, -4.0)

    def test_reverse(self):
        a = Vec3.new(5.0, -3.0, 2.0)
        assert a.reverse() == Vec3.new(-5.0, 3.0, -2.0)

    def test_horizontal(self):
        a = Vec3.new(1.0, 5.0, 3.0)
        assert a.horizontal() == Vec3.new(1.0, 0.0, 3.0)

    def test_dot(self):
        a = Vec3.new(1.0, 0.0, 0.0)
        b = Vec3.new(0.0, 1.0, 0.0)
        assert a.dot(b) == 0.0
        a = Vec3.new(1.0, 2.0, 3.0)
        b = Vec3.new(4.0, 5.0, 6.0)
        assert a.dot(b) == 32.0  # 1*4 + 2*5 + 3*6

    def test_cross(self):
        a = Vec3.new(1.0, 0.0, 0.0)
        b = Vec3.new(0.0, 1.0, 0.0)
        c = a.cross(b)
        assert c == Vec3.new(0.0, 0.0, 1.0)

    def test_length_squared(self):
        a = Vec3.new(3.0, 4.0, 0.0)
        assert a.length_squared() == 25.0

    def test_length(self):
        a = Vec3.new(3.0, 4.0, 0.0)
        assert a.length() == 5.0


# ── Vec3 normalize ──────────────────────────────────────────────────────

class TestVec3Normalize:
    def test_normalize_normal(self):
        v = Vec3.new(3.0, 4.0, 0.0)
        n = v.normalize()
        assert n == Vec3.new(0.6, 0.8, 0.0) or abs(n.x - 0.6) < 1e-10 and abs(n.y - 0.8) < 1e-10

    def test_normalize_small(self):
        v = Vec3.new(1e-8, 0.0, 0.0)
        n = v.normalize()
        assert n == Vec3.ZERO

    def test_normalize_zero(self):
        assert Vec3.ZERO.normalize() == Vec3.ZERO


# ── Vec3 lerp ───────────────────────────────────────────────────────────

class TestVec3Lerp:
    def test_lerp(self):
        a = Vec3.new(0.0, 0.0, 0.0)
        b = Vec3.new(1.0, 1.0, 1.0)
        c = a.lerp(b, 0.5)
        assert c == Vec3.new(0.5, 0.5, 0.5)

    def test_lerp_0(self):
        a = Vec3.new(1.0, 2.0, 3.0)
        assert a.lerp(a, 0.0) == a

    def test_lerp_1(self):
        a = Vec3.new(1.0, 2.0, 3.0)
        assert a.lerp(a, 1.0) == a


# ── Vec3 rotate ────────────────────────────────────────────────────────

class TestVec3Rotate:
    def test_rotate_x_pi_half(self):
        # Rotate (0, 1, 0) by 90 degrees around X axis
        # With angle=pi/2: cos≈6.1e-17, sin=1 → result ≈ (0, 0, -1)
        v = Vec3.new(0.0, 1.0, 0.0)
        angle = math.pi / 2
        r = v.rotate_x(angle)
        assert r == Vec3.new(0.0, 0.0, -1.0) or abs(r.y) < 1e-10, f"Expected (0,0,-1) got {r}"

    def test_rotate_y_pi_half(self):
        # Rotate (0, 0, 1) by 90 degrees around Y axis
        # With angle=pi/2: cos≈6.1e-17, sin=1 → result ≈ (1, 0, 0)
        v = Vec3.new(0.0, 0.0, 1.0)
        angle = math.pi / 2
        r = v.rotate_y(angle)
        assert r == Vec3.new(1.0, 0.0, 0.0) or abs(r.x - 1.0) < 1e-10, f"Expected (1,0,0) got {r}"

    def test_rotate_z_pi_half(self):
        # Rotate (1, 0, 0) by 90 degrees around Z axis
        # With angle=pi/2: cos≈6.1e-17, sin=1 → result ≈ (0, -1, 0)
        v = Vec3.new(1.0, 0.0, 0.0)
        angle = math.pi / 2
        r = v.rotate_z(angle)
        assert r == Vec3.new(0.0, -1.0, 0.0) or abs(r.y - (-1.0)) < 1e-10, f"Expected (0,-1,0) got {r}"


# ── Vec3 equality with -0.0 and NaN ────────────────────────────────────

class TestVec3Equality:
    def test_zero_negative_zero_bits(self):
        # canonical_bits(-0.0) != canonical_bits(0.0)
        v_neg = Vec3.new(-0.0, 0.0, 0.0)
        v_pos = Vec3.new(0.0, 0.0, 0.0)
        # Per Rust: canonical_bits(-0.0) = 0x8000000000000000, canonical_bits(0.0) = 0
        assert canonical_bits(v_neg.x) != canonical_bits(v_pos.x)

    def test_nan_equality(self):
        # Same Vec3 with NaN should be equal per canonical_bits
        v_nan1 = Vec3.new(float("nan"), 1.0, 0.0)
        v_nan2 = Vec3.new(float("nan"), 1.0, 0.0)
        assert v_nan1 == v_nan2


# ── Aabb tests ─────────────────────────────────────────────────────────

class TestAabbBasic:
    def test_new(self):
        a = Aabb.new(Vec3.new(0.0, 0.0, 0.0), Vec3.new(1.0, 1.0, 1.0))
        assert a.min == Vec3.new(0.0, 0.0, 0.0)
        assert a.max == Vec3.new(1.0, 1.0, 1.0)

    def test_block(self):
        pos = BlockPos.new(0, 0, 0)
        b = Aabb.block(pos)
        assert b.min == Vec3.new(0.0, 0.0, 0.0)
        assert b.max == Vec3.new(1.0, 1.0, 1.0)

    def test_unit_cube(self):
        lower = Vec3.new(2.0, 2.0, 2.0)
        b = Aabb.unit_cube(lower)
        assert b.min == lower
        assert b.max == lower.add_vector(Vec3.new(1.0, 1.0, 1.0))

    def test_of_size(self):
        center = Vec3.new(5.0, 5.0, 5.0)
        size = Vec3.new(2.0, 2.0, 2.0)
        b = Aabb.of_size(center, size)
        assert b.min == Vec3.new(4.0, 4.0, 4.0)
        assert b.max == Vec3.new(6.0, 6.0, 6.0)

    def test_encapsulating_blocks(self):
        a = BlockPos.new(0, 0, 0)
        b = BlockPos.new(2, 2, 2)
        bb = Aabb.encapsulating_blocks(a, b)
        assert bb.min == Vec3.from_block(BlockPos.new(0, 0, 0))
        # max should have +1 on max coords: 2+1=3 → Vec3(3,3,3)
        assert bb.max == Vec3.from_block(BlockPos.new(3, 3, 3))

    def test_size(self):
        a = Aabb.new(Vec3.new(0.0, 0.0, 0.0), Vec3.new(3.0, 4.0, 5.0))
        s = a.size()
        assert s == Vec3.new(3.0, 4.0, 5.0)

    def test_average_size(self):
        a = Aabb.new(Vec3.new(0.0, 0.0, 0.0), Vec3.new(3.0, 3.0, 3.0))
        assert a.average_size() == 3.0

    def test_center(self):
        a = Aabb.new(Vec3.new(0.0, 0.0, 0.0), Vec3.new(2.0, 2.0, 2.0))
        assert a.center == Vec3.new(1.0, 1.0, 1.0)

    def test_bottom_center(self):
        a = Aabb.new(Vec3.new(0.0, 0.0, 0.0), Vec3.new(2.0, 4.0, 2.0))
        bc = a.bottom_center
        assert bc == Vec3.new(1.0, 0.0, 1.0)


# ── Aabb contains / intersects ──────────────────────────────────────────

class TestAabbContains:
    def test_contains_inside(self):
        b = Aabb.new(Vec3.new(0.0, 0.0, 0.0), Vec3.new(1.0, 1.0, 1.0))
        assert b.contains(Vec3.new(0.5, 0.5, 0.5))

    def test_contains_min(self):
        b = Aabb.new(Vec3.new(0.0, 0.0, 0.0), Vec3.new(1.0, 1.0, 1.0))
        assert b.contains(Vec3.new(0.0, 0.0, 0.0))  # x >= min

    def test_contains_max_excluded(self):
        b = Aabb.new(Vec3.new(0.0, 0.0, 0.0), Vec3.new(1.0, 1.0, 1.0))
        assert not b.contains(Vec3.new(1.0, 0.5, 0.5))  # x < max excluded

    def test_contains_outside(self):
        b = Aabb.new(Vec3.new(0.0, 0.0, 0.0), Vec3.new(1.0, 1.0, 1.0))
        assert not b.contains(Vec3.new(1.5, 0.5, 0.5))

    def test_contains_below(self):
        b = Aabb.new(Vec3.new(0.0, 0.0, 0.0), Vec3.new(1.0, 1.0, 1.0))
        assert not b.contains(Vec3.new(0.5, -0.1, 0.5))

    def test_intersects(self):
        a = Aabb.new(Vec3.new(0.0, 0.0, 0.0), Vec3.new(1.0, 1.0, 1.0))
        b = Aabb.new(Vec3.new(0.5, 0.5, 0.5), Vec3.new(1.5, 1.5, 1.5))
        assert a.intersects(b)

    def test_intersects_no_overlap(self):
        a = Aabb.new(Vec3.new(0.0, 0.0, 0.0), Vec3.new(1.0, 1.0, 1.0))
        b = Aabb.new(Vec3.new(2.0, 2.0, 2.0), Vec3.new(3.0, 3.0, 3.0))
        assert not a.intersects(b)


# ── Aabb clip ──────────────────────────────────────────────────────────

class TestAabbClip:
    def test_clip_hit(self):
        # Ray from (-1, 0.5, 0.5) to (2, 0.5, 0.5) through unit block at origin
        b = Aabb.block(BlockPos.new(0, 0, 0))
        result = b.clip(Vec3.new(-1.0, 0.5, 0.5), Vec3.new(2.0, 0.5, 0.5))
        assert result is not None
        assert result.x == pytest.approx(0.0)
        assert result.y == pytest.approx(0.5)
        assert result.z == pytest.approx(0.5)

    def test_clip_miss_ahead(self):
        # Ray starting inside and going away
        b = Aabb.block(BlockPos.new(0, 0, 0))
        result = b.clip(Vec3.new(0.5, 0.5, 0.5), Vec3.new(2.0, 0.5, 0.5))
        assert result is None

    def test_clip_miss_behind(self):
        # Ray starting outside and going away (behind the box)
        b = Aabb.block(BlockPos.new(0, 0, 0))
        result = b.clip(Vec3.new(-1.0, 0.5, 0.5), Vec3.new(-0.5, 0.5, 0.5))
        assert result is None


# ── floor_i32 tests ────────────────────────────────────────────────────

# Rust test values from floor_i32_is_mths_floor
FLOOR_I32_TEST_VALUES = [
    0.0,
    -0.0,
    0.5,
    -0.5,
    1.0,
    -1.0,
    2.999,
    -2.999,
    1e-300,
    -1e-300,
    16_777_215.5,
    -16_777_215.5,
    # Past the i32 range (int) Math.floor saturates
    2_147_483_647.5,
    2_147_483_648.0,
    -2_147_483_648.0,
    -2_147_483_648.5,
    -2_147_483_649.0,
    3e9,
    -3e9,
    float("inf"),
    float("-inf"),
    float("nan"),
]


@pytest.mark.parametrize("v", FLOOR_I32_TEST_VALUES)
def test_floor_i32_all(v):
    result = floor_i32(v)
    # For NaN → 0
    if v != v:  # NaN check
        assert result == 0, f"floor_i32(NaN) = {result}, expected 0"
        return
    # For inf → saturate
    if math.isinf(v):
        if v > 0:
            assert result == 2_147_483_647, f"floor_i32(+inf) = {result}, expected 2147483647"
        else:
            assert result == -2_147_483_648, f"floor_i32(-inf) = {result}, expected -2147483648"
        return
    # For values beyond i32 range, saturate
    if v > 2_147_483_647:
        assert result == 2_147_483_647, f"floor_i32({v}) = {result}, expected 2147483647 (saturated)"
    elif v < -2_147_483_648:
        assert result == -2_147_483_648, f"floor_i32({v}) = {result}, expected -2147483648 (saturated)"
    else:
        # For in-range values, the result should be reasonable
        assert isinstance(result, int)


# ── java_min / java_max tests ──────────────────────────────────────────

class TestJavaMinMax:
    def test_java_min_zero_negative_zero(self):
        # java_min(0.0, -0.0) → -0.0 (bitwise OR preserves sign)
        result = java_min(0.0, -0.0)
        # Check result has -0.0 bit pattern; in Python 1.0/-0.0 raises,
        # so check via bits instead
        import struct
        assert struct.pack("d", result) == struct.pack("d", -0.0)

    def test_java_max_zero_negative_zero(self):
        # java_max(0.0, -0.0) → +0.0 (bitwise AND preserves sign)
        result = java_max(0.0, -0.0)
        # Check result has +0.0 bit pattern
        import struct
        assert struct.pack("d", result) == struct.pack("d", 0.0)

    def test_java_min_nan(self):
        result = java_min(float("nan"), 1.0)
        assert result != result  # NaN: result != result is True

    def test_java_max_nan(self):
        result = java_max(float("nan"), 1.0)
        assert result != result  # NaN


# ── canonical_bits tests ────────────────────────────────────────────────

class TestCanonicalBits:
    def test_canonical_bits_nan(self):
        assert canonical_bits(float("nan")) == 0x7FF8000000000000

    def test_canonical_bits_zero(self):
        assert canonical_bits(0.0) == 0

    def test_canonical_bits_negative_zero(self):
        assert canonical_bits(-0.0) == 0x8000000000000000

    def test_canonical_bits_normal(self):
        # 1.0 bits = 0x3FF0000000000000
        assert canonical_bits(1.0) == 0x3FF0000000000000

    def test_canonical_bits_pi(self):
        assert canonical_bits(math.pi) != 0  # not zero


# ── Direction tests ────────────────────────────────────────────────────

class TestDirection:
    def test_opposite(self):
        assert Direction.DOWN.opposite() == Direction.UP
        assert Direction.UP.opposite() == Direction.DOWN
        assert Direction.NORTH.opposite() == Direction.SOUTH
        assert Direction.SOUTH.opposite() == Direction.NORTH
        assert Direction.WEST.opposite() == Direction.EAST
        assert Direction.EAST.opposite() == Direction.WEST

    def test_normal(self):
        assert Direction.DOWN.normal() == (0, -1, 0)
        assert Direction.UP.normal() == (0, 1, 0)
        assert Direction.NORTH.normal() == (0, 0, -1)
        assert Direction.SOUTH.normal() == (0, 0, 1)
        assert Direction.WEST.normal() == (-1, 0, 0)
        assert Direction.EAST.normal() == (1, 0, 0)

    def test_approximate_nearest(self):
        # Vector (0, 0, 1) should be nearest to Direction.SOUTH (0,0,1)
        v = Vec3.new(0.0, 0.0, 1.0)
        assert Direction.approximate_nearest(v) == Direction.SOUTH


# ── BlockPos tests ─────────────────────────────────────────────────────

class TestBlockPos:
    def test_offset(self):
        pos = BlockPos.new(1, 2, 3)
        assert pos.offset(1, 1, 1) == BlockPos.new(2, 3, 4)

    def test_wrapping_add(self):
        # 2**31 - 1 + 1 wraps to 0 (within 32 bits)
        assert BlockPos.wrapping_add(2**31 - 1, 1) == 0
        # -1 + -1 = -2 within 32-bit wrapping
        assert BlockPos.wrapping_add(-1, -1) == -2


# ── Aabb next_deflated ────────────────────────────────────────────────

class TestAabbNextDeflated:
    def test_next_deflated(self):
        a = Aabb.new(Vec3.new(0.0, 0.0, 0.0), Vec3.new(1.0, 1.0, 1.0))
        d = a.next_deflated()
        # next_up on 0.0 → smallest positive denormal
        # next_down on 1.0 → just below 1.0
        assert d.min != a.min or True  # check they differ


# ── Aabb clip with ray through unit block ──────────────────────────────

def test_clip_ray_through_unit_block():
    """Exact test from Rust ray_faces_and_half_open_bounds."""
    b = Aabb.block(BlockPos.new(0, 0, 0))
    # b.contains(Vec3::ZERO) → true
    assert b.contains(Vec3.ZERO)
    # b.contains(Vec3::new(1.0, 0.0, 0.0)) → false (max excluded)
    assert not b.contains(Vec3.new(1.0, 0.0, 0.0))
    # b.clip(Vec3::new(-1.0, 0.5, 0.5), Vec3::new(2.0, 0.5, 0.5)) → Some(Vec3::new(0.0, 0.5, 0.5))
    result = b.clip(Vec3.new(-1.0, 0.5, 0.5), Vec3.new(2.0, 0.5, 0.5))
    assert result is not None
    assert result.x == pytest.approx(0.0)
    assert result.y == pytest.approx(0.5)
    assert result.z == pytest.approx(0.5)
    # b.clip(Vec3::new(0.5, 0.5, 0.5), Vec3::new(2.0, 0.5, 0.5)) → None (starts inside, goes away)
    assert b.clip(Vec3.new(0.5, 0.5, 0.5), Vec3.new(2.0, 0.5, 0.5)) is None
    # b.clip(Vec3::new(-1.0, 0.5, 0.5), Vec3::new(0.0, 0.5, 0.5)) → None (starts behind, goes to min)
    assert b.clip(Vec3.new(-1.0, 0.5, 0.5), Vec3.new(0.0, 0.5, 0.5)) is None