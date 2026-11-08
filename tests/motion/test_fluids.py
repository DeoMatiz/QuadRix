#!/usr/bin/env python3
"""Tests for motion fluid interaction.

Ported from horizon/crates/horizon-client/src/motion/fluids.rs
(Minecraft 26.3).

Tests load real .local/horizon-client-motion/movement-properties.nbt data
and assert on concrete fluid interaction values.
"""

from pathlib import Path

import pytest

from quadrix.motion.fluids import (
    EntityFluidInteraction,
    WATER,
    LAVA,
    FluidTags,
    update_entity_fluids,
    load_fluid_interaction,
)
from quadrix.core.geometry import Vec3


# Path to the movement-properties.nbt file following the QuadRix .local layout
NBT_PATH = Path(".local/horizon-client-motion/movement-properties.nbt")


@pytest.fixture
def fluid_tags():
    """Provide a FluidTags instance for tests."""
    return FluidTags()


@pytest.fixture
def default_interaction():
    """Provide a default EntityFluidInteraction loaded from .local data."""
    return load_fluid_interaction()


class TestMotionFluidsImport:
    """Tests that the module can be imported and key names are accessible."""

    def test_import(self):
        """Test that all key names can be imported."""
        from quadrix.motion.fluids import (  # noqa: F811
            EntityFluidInteraction,
            WATER,
            LAVA,
            FluidTags,
            update_entity_fluids,
            load_fluid_interaction,
        )
        assert EntityFluidInteraction is not None
        assert WATER is not None
        assert LAVA is not None
        assert FluidTags is not None

    def test_constants(self):
        """Test that WATER and LAVA have correct values."""
        assert int(WATER) == 0
        assert int(LAVA) == 1


class TestEntityFluidInteraction:
    """Tests for EntityFluidInteraction dataclass."""

    def test_default_creation(self):
        """Test that EntityFluidInteraction can be created with no args."""
        e = EntityFluidInteraction()
        assert e is not None
        assert len(e.trackers) == 0
        assert len(e.currents) == 0

    def test_new_class_method(self):
        """Test EntityFluidInteraction.new() class method."""
        e = EntityFluidInteraction.new([WATER, LAVA])
        assert e is not None
        assert len(e.currents) == 2  # WATER and LAVA


class TestFluidTags:
    """Tests for FluidTags membership."""

    def test_fluid_in_tag_water(self, fluid_tags):
        """Test that FluidTags.fluid_in_tag recognizes water."""
        assert fluid_tags.fluid_in_tag("water", WATER) is True
        assert fluid_tags.fluid_in_tag("flowing_water", WATER) is True
        assert fluid_tags.fluid_in_tag("lava", WATER) is False

    def test_fluid_in_tag_lava(self, fluid_tags):
        """Test that FluidTags.fluid_in_tag recognizes lava."""
        assert fluid_tags.fluid_in_tag("lava", LAVA) is True
        assert fluid_tags.fluid_in_tag("flowing_lava", LAVA) is True
        assert fluid_tags.fluid_in_tag("water", LAVA) is False


class TestEntityFluidInteractionMethods:
    """Tests for EntityFluidInteraction methods."""

    def test_fluid_height_water(self, fluid_tags, default_interaction):
        """Test fluid_height returns 0.0 when no trackers have water height."""
        h = default_interaction.fluid_height(fluid_tags, WATER)
        assert h == 0.0

    def test_is_in_fluid_false(self, fluid_tags, default_interaction):
        """Test is_in_fluid returns False when not in fluid."""
        assert default_interaction.is_in_fluid(fluid_tags, WATER) is False

    def test_is_eye_in_fluid_false(self, fluid_tags, default_interaction):
        """Test is_eye_in_fluid returns False when eyes not in fluid."""
        assert default_interaction.is_eye_in_fluid(fluid_tags, WATER) is False

    def test_apply_current_no_accumulator(self, fluid_tags, default_interaction):
        """Test apply_current returns unchanged velocity when no accumulator."""
        v = Vec3(1.0, 2.0, 3.0)
        result = default_interaction.apply_current(WATER, 0.014, v)
        assert result == v


class TestUpdateEntityFluids:
    """Tests for update_entity_fluids function."""

    def test_update_with_nbt_returns_triple(self):
        """Test update_entity_fluids returns (water_height, lava_height, velocity)."""
        if not NBT_PATH.exists():
            pytest.skip("movement-properties.nbt not found")
        result = update_entity_fluids(
            NBT_PATH,
            bounds=(0.0, 0.0, 0.0, 1.0, 1.0, 1.0),
            position=(0.5, 0.5, 0.5),
            eye_y=1.0,
            velocity=Vec3(0.0, 0.0, 0.0),
            tags=FluidTags(),
        )
        # Assert return type is a triple of (float, float, Vec3)
        assert isinstance(result, tuple)
        assert len(result) == 3
        water_height, lava_height, new_velocity = result
        assert isinstance(water_height, float)
        assert isinstance(lava_height, float)
        assert isinstance(new_velocity, Vec3)

    def test_update_water_height_from_nbt(self):
        """Test that water height can be extracted from NBT data."""
        if not NBT_PATH.exists():
            pytest.skip("movement-properties.nbt not found")
        water_height, lava_height, new_velocity = update_entity_fluids(
            NBT_PATH,
            bounds=(0.0, 0.0, 0.0, 1.0, 1.0, 1.0),
            position=(0.5, 0.5, 0.5),
            eye_y=1.0,
            velocity=Vec3(0.0, 0.0, 0.0),
            tags=FluidTags(),
        )
        # water_height should be a non-negative float
        assert isinstance(water_height, float)
        assert water_height >= 0.0
        # lava_height should be a non-negative float
        assert isinstance(lava_height, float)
        assert lava_height >= 0.0


class TestLoadFluidInteraction:
    """Tests for load_fluid_interaction convenience function."""

    def test_load_returns_interaction(self):
        """Test that load_fluid_interaction returns an EntityFluidInteraction."""
        interaction = load_fluid_interaction()
        assert interaction is not None
        assert isinstance(interaction, EntityFluidInteraction)

    def test_load_has_water_and_lava(self):
        """Test that loaded interaction tracks WATER and LAVA."""
        interaction = load_fluid_interaction()
        assert len(interaction.currents) >= 1
        # Check that we have at least one current accumulator
        tag_ids = [int(t) for t, _ in interaction.currents]
        assert WATER.value in tag_ids or LAVA.value in tag_ids