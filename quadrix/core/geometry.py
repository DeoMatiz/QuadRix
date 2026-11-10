# !Double-precision simulation geometry for the pinned Java Edition target.
# !
# !Operation order and Java floating-point edge cases are deliberate. These are
# !simulation coordinates; rendering may use a separate camera-relative format.

from __future__ import annotations

import math
from dataclasses import dataclass
from enum import Enum, auto
from typing import Optional, Tuple, List, Sequence


# ── BlockPos stub (only needed for Vec3::from_block, Aabb::block,
# ── Aabb::encapsulating_blocks, BlockHit.block) ──────────────────────
@dataclass(frozen=True)
class BlockPos:
    x: int
    y: int
    z: int

    def __post_init__(self):
        object.__setattr__(self, "x", int(self.x))
        object.__setattr__(self, "y", int(self.y))
        object.__setattr__(self, "z", int(self.z))

    def offset(self, dx: int, dy: int, dz: int) -> BlockPos:
        return BlockPos(self.x + dx, self.y + dy, self.z + dz)

    @staticmethod
    def new(x: int, y: int, z: int) -> BlockPos:
        return BlockPos(x, y, z)

    @staticmethod
    def wrapping_add(a: int, b: int, width: int = 2**31) -> int:
        # i32 wrapping: positive overflow wraps modulo width, negative values pass through
        result = a + b
        if result > width - 1:
            result = result % width
        return result


# ── Trig stub (used only in Vec3 rotate / direction_from_rotation / rotation) ─
# Match Rust behaviour: `trig::cos(angle as f64)` where angle is f32,
# so in Python cast to float and call math.cos / math.sin.
DEG_TO_RAD = math.pi / 180.0
RAD_TO_DEG = 180.0 / math.pi


def cos_angle(angle: float) -> float:
    return math.cos(float(angle))


def sin_angle(angle: float) -> float:
    return math.sin(float(angle))


# ── Axis ──────────────────────────────────────────────────────────────
class Axis(Enum):
    X = 0
    Y = 1
    Z = 2

    @staticmethod
    def step_order(movement: "Vec3") -> "Tuple[Axis, ...]":
        if abs(movement.x) < abs(movement.z):
            return Axis.Y, Axis.Z, Axis.X
        return Axis.Y, Axis.X, Axis.Z


#: All axis values in X, Y, Z order.
Axis.ALL: Tuple[Axis, ...] = (Axis.X, Axis.Y, Axis.Z)


# ── Direction ─────────────────────────────────────────────────────────
class Direction(Enum):
    DOWN = 0
    UP = 1
    NORTH = 2
    SOUTH = 3
    WEST = 4
    EAST = 5

    def opposite(self) -> Direction:
        match self:
            case Direction.DOWN:
                return Direction.UP
            case Direction.UP:
                return Direction.DOWN
            case Direction.NORTH:
                return Direction.SOUTH
            case Direction.SOUTH:
                return Direction.NORTH
            case Direction.WEST:
                return Direction.EAST
            case Direction.EAST:
                return Direction.WEST

    def normal(self) -> Tuple[int, int, int]:
        match self:
            case Direction.DOWN:
                return (0, -1, 0)
            case Direction.UP:
                return (0, 1, 0)
            case Direction.NORTH:
                return (0, 0, -1)
            case Direction.SOUTH:
                return (0, 0, 1)
            case Direction.WEST:
                return (-1, 0, 0)
            case Direction.EAST:
                return (1, 0, 0)

    @staticmethod
    def approximate_nearest(vector: "Vec3") -> Direction:
        # Find direction with max dot product with vector components
        best: float = float("-inf")
        result = Direction.NORTH
        for direction in Direction.ALL:
            nx, ny, nz = direction.normal()
            dot = vector.x * nx + vector.y * ny + vector.z * nz  # type: ignore[operator]
            if dot > best:
                best = dot
                result = direction
        return result


#: All direction values in defined order.
Direction.ALL: Tuple[Direction, ...] = (
    Direction.DOWN,
    Direction.UP,
    Direction.NORTH,
    Direction.SOUTH,
    Direction.WEST,
    Direction.EAST,
)


# ── Free functions (definitions before Vec3 so methods can reference them) ──────────────────────────

COLLISION_EPSILON: float = 1.0e-7


def java_min(a: float, b: float) -> float:
    """Java-style f64 minimum with NaN and -0.0 handling."""
    import struct

    # If a is NaN, return a (NaN propagates)
    if a != a:  # NaN check
        return a
    # If b is NaN, return b
    if b != b:
        return b

    # If both are zero (including -0.0), use bitwise OR to preserve sign
    if a == 0.0 and b == 0.0:
        # Java: f64::from_bits(a.to_bits() | b.to_bits())
        a_i = struct.unpack("q", struct.pack("d", a))[0]
        b_i = struct.unpack("q", struct.pack("d", b))[0]
        result_i = a_i | b_i
        return struct.unpack("d", struct.pack("q", result_i))[0]

    # Normal comparison
    if a <= b:
        return a
    return b


def java_max(a: float, b: float) -> float:
    """Java-style f64 maximum with NaN and -0.0 handling."""
    import struct

    # If a is NaN, return a
    if a != a:  # NaN check
        return a
    # If b is NaN, return b
    if b != b:
        return b

    # If both are zero (including -0.0), use bitwise AND to preserve sign
    if a == 0.0 and b == 0.0:
        # Java: f64::from_bits(a.to_bits() & b.to_bits())
        a_i = struct.unpack("q", struct.pack("d", a))[0]
        b_i = struct.unpack("q", struct.pack("d", b))[0]
        result_i = a_i & b_i
        return struct.unpack("d", struct.pack("q", result_i))[0]

    # Normal comparison
    if a >= b:
        return a
    return b


def clamp(value: float, min_: float, max_: float) -> float:
    if value < min_:
        return min_
    return java_min(value, max_)


def floor_i32(value: float) -> int:
    # Rust: let truncated = value as i32; if value < f64::from(truncated) { truncated.saturating_sub(1) } else { truncated }
    # Handle NaN and infinity first
    if value != value:  # NaN
        return 0
    if value == float("inf"):
        return 2_147_483_647  # i32::MAX
    if value == float("-inf"):
        return -2_147_483_648  # i32::MIN
    # Python's int() truncates toward zero same as C f64 truncation.
    truncated = int(value)
    # Saturate to i32 range [MIN, MAX]
    if truncated > 2_147_483_647:
        return 2_147_483_647
    if truncated < -2_147_483_648:
        return -2_147_483_648
    # Compare value < f64::from(truncated)
    if value < float(truncated):
        # Step down, but saturate at i32::MIN = -2**31
        return max(truncated - 1, -2**31)
    return truncated


def lerp(amount: float, start: float, end: float) -> float:
    return start + amount * (end - start)


def canonical_bits(value: float) -> int:
    """Return bits for Java Double.compare equality.
    NaN maps to 0x7ff8000000000000; otherwise return raw bits as unsigned."""
    import struct

    if math.isnan(value):
        return 0x7FF8000000000000
    return struct.unpack("Q", struct.pack("d", value))[0]


def next_up(value: float) -> float:
    """Return next representable float64 above value (toward +inf)."""
    import struct

    if math.isnan(value) or value == float("inf"):
        return value
    if value == 0.0:
        # Smallest positive denormal: 2^-1074
        return float.fromhex("0x1p-1074")
    if value > 0.0:
        # Add 1 to the mantissa bits
        a_i = struct.unpack("q", struct.pack("d", value))[0]
        result_i = a_i + 1
        return struct.unpack("d", struct.pack("q", result_i))[0]
    else:
        # For negative values, "up" means toward zero (less negative)
        # So we add 1 to bits (which makes it less negative = larger)
        a_i = struct.unpack("q", struct.pack("d", value))[0]
        result_i = a_i + 1  # adding 1 to negative bits moves toward zero
        return struct.unpack("d", struct.pack("q", result_i))[0]


def next_down(value: float) -> float:
    """Return next representable float64 below value (toward -inf)."""
    return -next_up(-value)


# ── Vec3 ──────────────────────────────────────────────────────────────
# Component equality follows Java Double.compare, including NaNs and -0.0.
# canonical_bits maps NaN → 0x7ff8_0000_0000_0000

@dataclass(frozen=True, eq=False)
class Vec3:
    x: float = 0.0
    y: float = 0.0
    z: float = 0.0

    def __post_init__(self):
        object.__setattr__(self, "x", float(self.x))
        object.__setattr__(self, "y", float(self.y))
        object.__setattr__(self, "z", float(self.z))

    @staticmethod
    def new(x: float, y: float, z: float) -> "Vec3":
        return Vec3(x, y, z)

    def components(self) -> Tuple[float, float, float]:
        return (self.x, self.y, self.z)

    def component(self, axis: Axis) -> float:
        return self.components()[axis.value]

    @staticmethod
    def from_block(pos: BlockPos) -> "Vec3":
        return Vec3(float(pos.x), float(pos.y), float(pos.z))

    def add_vector(self, other: "Vec3") -> "Vec3":
        return Vec3(self.x + other.x, self.y + other.y, self.z + other.z)

    def subtract(self, other: "Vec3") -> "Vec3":
        return self.add_vector(Vec3.new(-other.x, -other.y, -other.z))

    def vector_to(self, other: "Vec3") -> "Vec3":
        return Vec3(other.x - self.x, other.y - self.y, other.z - self.z)

    def multiply(self, other: "Vec3") -> "Vec3":
        return Vec3(self.x * other.x, self.y * other.y, self.z * other.z)

    def scale(self, scale: float) -> "Vec3":
        return self.multiply(Vec3.new(scale, scale, scale))

    def reverse(self) -> "Vec3":
        return self.scale(-1.0)

    def horizontal(self) -> "Vec3":
        return Vec3(self.x, 0.0, self.z)

    def dot(self, other: "Vec3") -> float:
        return self.x * other.x + self.y * other.y + self.z * other.z

    def cross(self, other: "Vec3") -> "Vec3":
        return Vec3(
            self.y * other.z - self.z * other.y,
            self.z * other.x - self.x * other.z,
            self.x * other.y - self.y * other.x,
        )

    def length_squared(self) -> float:
        return self.x * self.x + self.y * self.y + self.z * self.z

    def length(self) -> float:
        return math.sqrt(self.length_squared())

    def horizontal_distance_squared(self) -> float:
        return self.x * self.x + self.z * self.z

    def horizontal_distance(self) -> float:
        return self.horizontal_distance_squared().sqrt()

    def distance_squared(self, other: "Vec3") -> float:
        dx = self.x - other.x
        dy = self.y - other.y
        dz = self.z - other.z
        return dx * dx + dy * dy + dz * dz

    def distance(self, other: "Vec3") -> float:
        return self.distance_squared(other).sqrt()

    def normalize(self) -> "Vec3":
        length = self.length()
        if length < 9.999999747378752e-6:
            return Vec3.ZERO
        else:
            return Vec3.new(self.x / length, self.y / length, self.z / length)

    def lerp(self, other: "Vec3", amount: float) -> "Vec3":
        return Vec3(
            lerp(amount, self.x, other.x),
            lerp(amount, self.y, other.y),
            lerp(amount, self.z, other.z),
        )

    def projected_on(self, other: "Vec3") -> "Vec3":
        if other.length_squared() == 0.0:
            return other
        else:
            return other.scale(self.dot(other)).scale(1.0 / other.length_squared())

    def closer_than(self, other: "Vec3", distance: float) -> bool:
        return self.distance_squared(other) < distance * distance

    def is_finite(self) -> bool:
        return (
            math.isfinite(self.x)
            and math.isfinite(self.y)
            and math.isfinite(self.z)
        )

    def with_component(self, axis: Axis, value: float) -> "Vec3":
        coords = list(self.components())
        coords[axis.value] = value
        return Vec3.new(coords[0], coords[1], coords[2])

    def align(self, axes: Tuple[bool, bool, bool]) -> "Vec3":
        from .geometry import floor_i32  # local stub

        coords = [
            floor_i32(self.components()[i]) if axes[i] else self.components()[i]
            for i in range(3)
        ]
        return Vec3.new(float(coords[0]), float(coords[1]), float(coords[2]))

    def relative(self, direction: Direction, distance: float) -> "Vec3":
        normal = direction.normal()
        return Vec3.new(
            self.x + distance * float(normal[0]),
            self.y + distance * float(normal[1]),
            self.z + distance * float(normal[2]),
        )

    def rotate_x(self, angle: float) -> "Vec3":
        c = cos_angle(angle)
        s = sin_angle(angle)
        return Vec3.new(self.x, self.y * c + self.z * s, self.z * c - self.y * s)

    def rotate_y(self, angle: float) -> "Vec3":
        c = cos_angle(angle)
        s = sin_angle(angle)
        return Vec3.new(self.x * c + self.z * s, self.y, self.z * c - self.x * s)

    def rotate_z(self, angle: float) -> "Vec3":
        c = cos_angle(angle)
        s = sin_angle(angle)
        return Vec3.new(self.x * c + self.y * s, self.y * c - self.x * s, self.z)

    def rotate_clockwise_90(self) -> "Vec3":
        return Vec3.new(-self.z, self.y, self.x)

    def direction_from_rotation(self, pitch: float, yaw: float) -> "Vec3":
        yaw_radians = -yaw * DEG_TO_RAD - math.pi
        cy = cos_angle(yaw_radians)
        sy = sin_angle(yaw_radians)
        pitch_radians = -pitch * DEG_TO_RAD
        cp = -cos_angle(pitch_radians)
        sp = sin_angle(pitch_radians)
        return Vec3.new(sy * cp, sp, cy * cp)

    def rotation(self) -> Tuple[float, float]:
        yaw = ((-self.x).atan2(self.z) * RAD_TO_DEG)  # type: ignore[operator]
        pitch = ((-self.y / self.length()).asin() * RAD_TO_DEG)  # type: ignore[operator]
        return (pitch, yaw)

    # Java Double.compare-based equality via canonical_bits
    def __eq__(self, other: object) -> bool:
        if not isinstance(other, Vec3):
            return NotImplemented
        return (
            canonical_bits(self.x) == canonical_bits(other.x)
            and canonical_bits(self.y) == canonical_bits(other.y)
            and canonical_bits(self.z) == canonical_bits(other.z)
        )

    def __hash__(self) -> int:
        # Hash based on canonical bits for NaN safety
        return hash((canonical_bits(self.x), canonical_bits(self.y), canonical_bits(self.z)))


#: Zero vector.
Vec3.ZERO = Vec3.new(0.0, 0.0, 0.0)


# ── Aabb ──────────────────────────────────────────────────────────────
@dataclass(frozen=True, eq=False)
class Aabb:
    min: Vec3
    max: Vec3

    def __post_init__(self):
        object.__setattr__(self, "min", self.min)
        object.__setattr__(self, "max", self.max)

    @staticmethod
    def new(min: Vec3, max: Vec3) -> "Aabb":
        # java_min/java_max for min/max clamping so that NaN propagates correctly
        lo = Vec3(
            java_min(min.x, max.x),
            java_min(min.y, max.y),
            java_min(min.z, max.z),
        )
        hi = Vec3(
            java_max(min.x, max.x),
            java_max(min.y, max.y),
            java_max(min.z, max.z),
        )
        return Aabb(lo, hi)

    @staticmethod
    def block(pos: BlockPos) -> "Aabb":
        return Aabb.new(Vec3.from_block(pos), Vec3.from_block(pos.offset(1, 1, 1)))

    @staticmethod
    def unit_cube(lower: Vec3) -> "Aabb":
        return Aabb.new(lower, lower.add_vector(Vec3.new(1.0, 1.0, 1.0)))

    @staticmethod
    def of_size(center: Vec3, size: Vec3) -> "Aabb":
        return Aabb.new(
            Vec3.new(
                center.x - size.x / 2.0,
                center.y - size.y / 2.0,
                center.z - size.z / 2.0,
            ),
            Vec3.new(
                center.x + size.x / 2.0,
                center.y + size.y / 2.0,
                center.z + size.z / 2.0,
            ),
        )

    @staticmethod
    def encapsulating_blocks(a: BlockPos, b: BlockPos) -> "Aabb":
        return Aabb.new(
            Vec3.from_block(
                BlockPos.new(
                    min(a.x, b.x),
                    min(a.y, b.y),
                    min(a.z, b.z),
                )
            ),
            Vec3.from_block(
                BlockPos.new(
                    max(a.x, b.x) + 1,
                    max(a.y, b.y) + 1,
                    max(a.z, b.z) + 1,
                )
            ),
        )

    @property
    def min_position(self) -> Vec3:
        return self.min

    @property
    def max_position(self) -> Vec3:
        return self.max

    def get_min(self, axis: Axis) -> float:
        return self.min.component(axis)

    def get_max(self, axis: Axis) -> float:
        return self.max.component(axis)

    def with_min(self, axis: Axis, value: float) -> "Aabb":
        a = self.min.components()
        a[axis.value] = value
        return Aabb.new(Vec3.new(a[0], a[1], a[2]), self.max)

    def with_max(self, axis: Axis, value: float) -> "Aabb":
        a = self.max.components()
        a[axis.value] = value
        return Aabb.new(self.min, Vec3.new(a[0], a[1], a[2]))

    def size(self) -> Vec3:
        return self.min.vector_to(self.max)

    def average_size(self) -> float:
        v = self.size()
        return (v.x + v.y + v.z) / 3.0

    @property
    def center(self) -> Vec3:
        return self.min.lerp(self.max, 0.5)

    @property
    def bottom_center(self) -> Vec3:
        v = self.center
        return Vec3.new(v.x, self.min.y, v.z)

    def move_by(self, offset: Vec3) -> "Aabb":
        return Aabb.new(
            Vec3.new(
                self.min.x + offset.x,
                self.min.y + offset.y,
                self.min.z + offset.z,
            ),
            Vec3.new(
                self.max.x + offset.x,
                self.max.y + offset.y,
                self.max.z + offset.z,
            ),
        )

    def inflate(self, amount: Vec3) -> "Aabb":
        return Aabb.new(
            Vec3.new(
                self.min.x - amount.x,
                self.min.y - amount.y,
                self.min.z - amount.z,
            ),
            self.max.add_vector(amount),
        )

    def deflate(self, amount: Vec3) -> "Aabb":
        return self.inflate(amount.reverse())

    def expand_towards(self, amount: Vec3) -> "Aabb":
        return self.change_extent(amount, False)

    def contract(self, amount: Vec3) -> "Aabb":
        return self.change_extent(amount, True)

    def change_extent(self, amount: Vec3, contract: bool) -> "Aabb":
        min_c = self.min.components()
        max_c = self.max.components()
        for i, v in enumerate(amount.components()):
            if v < 0.0:
                min_c[i] = min_c[i] - v if contract else min_c[i] + v
            elif v > 0.0:
                max_c[i] = max_c[i] - v if contract else max_c[i] + v
        return Aabb.new(
            Vec3.new(min_c[0], min_c[1], min_c[2]),
            Vec3.new(max_c[0], max_c[1], max_c[2]),
        )

    def intersect(self, other: "Aabb") -> "Aabb":
        return Aabb.new(
            Vec3.new(
                java_max(self.min.x, other.min.x),
                java_max(self.min.y, other.min.y),
                java_max(self.min.z, other.min.z),
            ),
            Vec3.new(
                java_min(self.max.x, other.max.x),
                java_min(self.max.y, other.max.y),
                java_min(self.max.z, other.max.z),
            ),
        )

    def union_bounds(self, other: "Aabb") -> "Aabb":
        return Aabb.new(
            Vec3.new(
                java_min(self.min.x, other.min.x),
                java_min(self.min.y, other.min.y),
                java_min(self.min.z, other.min.z),
            ),
            Vec3.new(
                java_max(self.max.x, other.max.x),
                java_max(self.max.y, other.max.y),
                java_max(self.max.z, other.max.z),
            ),
        )

    def intersects_corners(self, min: Vec3, max: Vec3) -> bool:
        return (
            self.min.x < max.x
            and self.max.x > min.x
            and self.min.y < max.y
            and self.max.y > min.y
            and self.min.z < max.z
            and self.max.z > min.z
        )

    def intersects(self, other: "Aabb") -> bool:
        return (
            self.min.x < other.max.x
            and self.max.x > other.min.x
            and self.min.y < other.max.y
            and self.max.y > other.min.y
            and self.min.z < other.max.z
            and self.max.z > other.min.z
        )

    def contains(self, point: Vec3) -> bool:
        return (
            point.x >= self.min.x
            and point.x < self.max.x
            and point.y >= self.min.y
            and point.y < self.max.y
            and point.z >= self.min.z
            and point.z < self.max.z
        )

    def has_nan(self) -> bool:
        return (
            self.min.x.is_nan()
            or self.min.y.is_nan()
            or self.min.z.is_nan()
            or self.max.x.is_nan()
            or self.max.y.is_nan()
            or self.max.z.is_nan()
        )

    def distance_squared_to_point(self, point: Vec3) -> float:
        distances = [
            java_max(
                java_max(
                    self.get_min(axis) - point.component(axis),
                    point.component(axis) - self.get_max(axis),
                ),
                0.0,
            )
            for axis in Axis.ALL
        ]
        return distances[0] * distances[0] + distances[1] * distances[1] + distances[2] * distances[2]

    def distance_squared_to_box(self, other: "Aabb") -> float:
        distances = [
            java_max(
                java_max(self.min(a) - other.max(a), other.min(a) - self.max(a)),
                0.0,
            )
            for a in Axis.ALL
        ]
        return distances[0] * distances[0] + distances[1] * distances[1] + distances[2] * distances[2]

    def next_deflated(self) -> "Aabb":
        lo = [next_up(c) for c in self.min.components()]
        hi = [next_down(c) for c in self.max.components()]
        return Aabb.new(
            Vec3.new(float(lo[0]), float(lo[1]), float(lo[2])),
            Vec3.new(float(hi[0]), float(hi[1]), float(hi[2])),
        )

    def clip(self, start: Vec3, end: Vec3) -> Optional[Vec3]:
        delta = start.vector_to(end)
        best_holder = [1.0]
        face = self.clip_direction(start, delta, best_holder)
        if face is None:
            return None
        t = best_holder[0]
        return start.add_vector(delta.scale(t))

    def clip_direction(
        self, start: Vec3, delta: Vec3, best: List[float]
    ) -> Optional[Direction]:
        result: Optional[Direction] = None
        for axis in Axis.ALL:
            i = axis.value
            j = (i + 1) % 3
            k = (i + 2) % 3
            ds = delta.components()
            origins = start.components()
            if ds[i] > COLLISION_EPSILON:
                plane = self.get_min(axis)
                face = [Direction.WEST, Direction.DOWN, Direction.NORTH][i]
            elif ds[i] < -COLLISION_EPSILON:
                plane = self.get_max(axis)
                face = [Direction.EAST, Direction.UP, Direction.SOUTH][i]
            else:
                continue
            t = (plane - origins[i]) / ds[i]
            u = origins[j] + t * ds[j]
            v = origins[k] + t * ds[k]
            if (
                0.0 < t
                and t < best[0]
                and self.min.components()[j] - COLLISION_EPSILON < u
                and u < self.max.components()[j] + COLLISION_EPSILON
                and self.min.components()[k] - COLLISION_EPSILON < v
                and v < self.max.components()[k] + COLLISION_EPSILON
            ):
                best[0] = t
                result = face
        return result

    def clip_boxes(
        self,
        boxes: Sequence["Aabb"],
        start: Vec3,
        end: Vec3,
        block: BlockPos,
    ) -> Optional["BlockHit"]:
        delta = start.vector_to(end)
        best_holder = [1.0]
        direction: Optional[Direction] = None
        for aabb in boxes:
            moved = aabb.move_by(Vec3.from_block(block))
            if (face := moved.clip_direction(start, delta, best_holder)) is not None:
                direction = face
        return BlockHit(
            location=start.add_vector(delta.scale(best_holder[0])),
            direction=direction,
            block=block,
            inside=False,
        )

    def collided_along_vector(self, movement: Vec3, boxes: Sequence["Aabb"]) -> bool:
        start = self.center()
        end = start.add_vector(movement)
        amount = self.size().scale(0.5).subtract(Vec3.new(COLLISION_EPSILON, COLLISION_EPSILON, COLLISION_EPSILON))
        return any(
            b.inflate(amount).contains(end)
            or b.inflate(amount).contains(start)
            or b.inflate(amount).clip(start, end) is not None
            for b in boxes
        )


# ── BlockHit ──────────────────────────────────────────────────────────
@dataclass(frozen=True, eq=False)
class BlockHit:
    location: Vec3
    direction: Direction
    block: BlockPos
    inside: bool


# ── End of geometry module ────────────────────────────────────────────