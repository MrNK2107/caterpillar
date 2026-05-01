import pytest
from dsde.decision_engine import DSDEDecisionEngine, DSDEState

def test_default_homogeneous_fleet_s1():
    engine = DSDEDecisionEngine()
    state = {
        "fleet_composition": {"Cat_797F": 5},
        "polygon_fill_percent": 50.0,
        "terrain_slope": 0.1,
    }
    result = engine.evaluate(state)
    assert result.strategy == "S1"

def test_default_heterogeneous_fleet_s2():
    """According to SPEC: Mixed fleet + regular polygon = S3 (not S2)"""
    engine = DSDEDecisionEngine()
    state = {
        "fleet_composition": {"Cat_797F": 5, "Cat_777G": 2},
        "polygon_fill_percent": 50.0,
        "terrain_slope": 0.1,
    }
    result = engine.evaluate(state)
    assert result.strategy == "S3"

def test_gps_degraded_accuracy_s7():
    engine = DSDEDecisionEngine()
    state = {
        "system_health": {"gps": "ok", "gps_accuracy_m": 0.6},
    }
    result = engine.evaluate(state)
    assert result.strategy == "S7"

def test_gps_degraded_status_s7():
    engine = DSDEDecisionEngine()
    state = {
        "system_health": {"gps": "lost"},
    }
    result = engine.evaluate(state)
    assert result.strategy == "S7"

def test_lidar_degraded_s7():
    engine = DSDEDecisionEngine()
    state = {
        "system_health": {"lidar": "fault"},
    }
    result = engine.evaluate(state)
    assert result.strategy == "S7"

def test_v2v_lost_s7():
    engine = DSDEDecisionEngine()
    state = {
        "system_health": {"v2v": "lost"},
    }
    result = engine.evaluate(state)
    assert result.strategy == "S7"

def test_heavy_rain_s6():
    engine = DSDEDecisionEngine()
    state = {
        "weather_conditions": {"rain_intensity": 25.0},
    }
    result = engine.evaluate(state)
    assert result.strategy == "S6"

def test_extreme_slope_s6():
    engine = DSDEDecisionEngine()
    state = {
        "terrain_slope": 0.7,
    }
    result = engine.evaluate(state)
    assert result.strategy == "S6"

def test_choke_point_s5():
    engine = DSDEDecisionEngine()
    state = {
        "choke_point_presence": True,
    }
    result = engine.evaluate(state)
    assert result.strategy == "S5"

def test_fill_80_homogeneous_s3():
    engine = DSDEDecisionEngine()
    state = {
        "polygon_fill_percent": 82.0,
        "fleet_composition": {"Cat_797F": 5},
    }
    result = engine.evaluate(state)
    assert result.strategy == "S3"

def test_fill_80_heterogeneous_s4():
    engine = DSDEDecisionEngine()
    state = {
        "polygon_fill_percent": 82.0,
        "fleet_composition": {"Cat_797F": 5, "Cat_777G": 2},
    }
    result = engine.evaluate(state)
    assert result.strategy == "S4"

def test_fill_70_s6():
    engine = DSDEDecisionEngine()
    state = {
        "polygon_fill_percent": 75.0,
    }
    result = engine.evaluate(state)
    assert result.strategy == "S6"

def test_clay_freeze_modifier_applied():
    engine = DSDEDecisionEngine()
    state = {
        "material_type": "COPPER_OVERBURDEN",
        "weather_conditions": {"temperature_c": 5.0},
    }
    result = engine.evaluate(state)
    assert "CLAY_FREEZE" in result.modifiers

def test_clay_freeze_modifier_not_applied_temp():
    engine = DSDEDecisionEngine()
    state = {
        "material_type": "COPPER_OVERBURDEN",
        "weather_conditions": {"temperature_c": 10.0},
    }
    result = engine.evaluate(state)
    assert "CLAY_FREEZE" not in result.modifiers

def test_clay_freeze_modifier_not_applied_material():
    engine = DSDEDecisionEngine()
    state = {
        "material_type": "ROCK",
        "weather_conditions": {"temperature_c": 5.0},
    }
    result = engine.evaluate(state)
    assert "CLAY_FREEZE" not in result.modifiers

def test_heavy_rain_modifier_applied():
    engine = DSDEDecisionEngine()
    state = {
        "weather_conditions": {"rain_intensity": 25.0},
    }
    result = engine.evaluate(state)
    assert "HEAVY_RAIN" in result.modifiers
    assert "SOFT_GROUND" in result.modifiers

def test_steep_slope_modifier_applied():
    engine = DSDEDecisionEngine()
    state = {
        "terrain_slope": 0.7,
    }
    result = engine.evaluate(state)
    assert "STEEP_SLOPE" in result.modifiers
    assert "SOFT_GROUND" in result.modifiers

def test_low_visibility_modifier_applied():
    engine = DSDEDecisionEngine()
    state = {
        "weather_conditions": {"visibility_m": 200.0},
    }
    result = engine.evaluate(state)
    assert "LOW_VISIBILITY" in result.modifiers

def test_lidar_degraded_modifier_applied():
    engine = DSDEDecisionEngine()
    state = {
        "system_health": {"lidar": "degraded"},
    }
    result = engine.evaluate(state)
    assert "LIDAR_DEGRADED" in result.modifiers
    assert result.strategy == "S7"

def test_v2v_degraded_modifier_applied():
    engine = DSDEDecisionEngine()
    state = {
        "system_health": {"v2v": "lost"},
    }
    result = engine.evaluate(state)
    assert "V2V_DEGRADED" in result.modifiers
    assert result.strategy == "S7"

# NEW TESTS for complete DSDE coverage

def test_edge_dump_forces_s3():
    """Edge dump requires real-time adaptive strategy."""
    engine = DSDEDecisionEngine()
    state = {
        "edge_dump_active": True,
        "fleet_composition": {"Cat_797F": 5},
        "polygon_fill_percent": 30.0,
    }
    result = engine.evaluate(state)
    assert result.strategy == "S3"

def test_irregular_polygon_s2_homogeneous():
    """Irregular polygon with homogeneous fleet uses S2."""
    engine = DSDEDecisionEngine()
    state = {
        "polygon_shape": "IRREGULAR",
        "fleet_composition": {"Cat_797F": 5},
        "polygon_fill_percent": 30.0,
    }
    result = engine.evaluate(state)
    assert result.strategy == "S2"

def test_irregular_polygon_s4_mixed():
    """Irregular polygon with mixed fleet uses S4."""
    engine = DSDEDecisionEngine()
    state = {
        "polygon_shape": "NON_CONVEX",
        "fleet_composition": {"Cat_797F": 3, "Cat_777G": 2},
        "polygon_fill_percent": 30.0,
    }
    result = engine.evaluate(state)
    assert result.strategy == "S4"

def test_mixed_fleet_regular_polygon_s3():
    """Mixed fleet with regular polygon uses S3."""
    engine = DSDEDecisionEngine()
    state = {
        "polygon_shape": "RECTANGULAR",
        "fleet_composition": {"Cat_797F": 3, "Cat_777G": 2},
        "polygon_fill_percent": 50.0,
    }
    result = engine.evaluate(state)
    assert result.strategy == "S3"

def test_wind_scatter_modifier():
    """Wind scatter buffer applied on edge dump with high wind."""
    engine = DSDEDecisionEngine()
    state = {
        "edge_dump_active": True,
        "weather_conditions": {"wind_speed": 12.0},
        "material_type": "IRON_ORE",
        "fleet_composition": {"Cat_797F": 5},
    }
    result = engine.evaluate(state)
    # Should have wind scatter modifier
    modifiers_str = " ".join(result.modifiers)
    assert "WIND_SCATTER" in modifiers_str

def test_low_spot_priority_wet_material():
    """Low spot priority on wet material."""
    engine = DSDEDecisionEngine()
    state = {
        "material_type": "COAL_OVERBURDEN",
        "weather_conditions": {"rain_intensity": 10.0},
    }
    result = engine.evaluate(state)
    assert "LOW_SPOT_PRIORITY" in result.modifiers

def test_low_spot_priority_high_moisture():
    """Low spot priority on high moisture content."""
    engine = DSDEDecisionEngine()
    state = {
        "material_type": "COAL_OVERBURDEN",
        "moisture_content_pct": 20.0,
    }
    result = engine.evaluate(state)
    assert "LOW_SPOT_PRIORITY" in result.modifiers

def test_fill_80_mixed_fleet_s4():
    """Fill above 80% with mixed fleet uses S4."""
    engine = DSDEDecisionEngine()
    state = {
        "polygon_fill_percent": 85.0,
        "fleet_composition": {"Cat_797F": 3, "Cat_777G": 2},
    }
    result = engine.evaluate(state)
    assert result.strategy == "S4"

def test_fill_70_above_triggers_s6():
    """Fill above 70% triggers S6."""
    engine = DSDEDecisionEngine()
    state = {
        "polygon_fill_percent": 72.0,
    }
    result = engine.evaluate(state)
    assert result.strategy == "S6"
