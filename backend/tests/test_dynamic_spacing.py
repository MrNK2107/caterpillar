import pytest
from strategies_v2.common import (
    predict_dynamic_spacing,
    get_material_settled_profile,
    apply_nudge_if_needed,
)


def test_sand_material_base_spacing():
    """Sand should have tighter base spacing (2.8m)."""
    spacing = predict_dynamic_spacing("sand", 4.5, 5.5)
    assert spacing <= 3.0  # Sand spreads more, can place closer
    assert spacing >= 2.5


def test_coal_material_base_spacing():
    """Coal should have moderate base spacing (~3.3m)."""
    spacing = predict_dynamic_spacing("coal", 6.2, 8.0)
    assert spacing >= 3.0
    assert spacing <= 3.8


def test_rock_material_base_spacing():
    """Rock should have conservative spacing (3.5m)."""
    spacing = predict_dynamic_spacing("rock", 4.5, 5.5)
    assert spacing >= 3.2
    assert spacing <= 4.0


def test_ore_material_base_spacing():
    """Ore should have spacing close to target (~3.1m)."""
    spacing = predict_dynamic_spacing("ore", 6.2, 7.0)
    assert spacing >= 2.8
    assert spacing <= 3.5


def test_unknown_material_fallback():
    """Unknown material should fallback to ore profile."""
    spacing = predict_dynamic_spacing("unknown_material", 4.5, 5.5)
    # Should use ore defaults
    assert spacing >= 2.0
    assert spacing <= 5.0


def test_apply_nudge_threshold_not_met():
    """No nudge when deviation is below threshold."""
    new_spacing, nudge = apply_nudge_if_needed(
        "ore",
        3.0,        # current spacing
        3.1,        # measured gap (3.3% deviation - below 15%)
        3,           # enough samples
    )
    assert new_spacing == 3.0
    assert nudge == 0.0


def test_apply_nudge_threshold_met():
    """Nudge should be applied when deviation exceeds 15%."""
    new_spacing, nudge = apply_nudge_if_needed(
        "sand",
        2.8,        # current spacing
        3.5,        # measured gap (~25% deviation)
        3,           # enough samples
    )
    # Should have adjusted
    assert new_spacing != 2.8 or nudge != 0.0


def test_apply_nudge_not_enough_samples():
    """No nudge with insufficient samples."""
    new_spacing, nudge = apply_nudge_if_needed(
        "ore",
        3.0,
        4.0,
        1,   # only 1 sample
    )
    assert new_spacing == 3.0
    assert nudge == 0.0