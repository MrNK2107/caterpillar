# ADPS Project Consolidation & Implementation Plan

**Project:** Autonomous Dump Packing System (ADPS)  
**Purpose:** Merge multiple codebases into a single, fully-functional application  
**Date:** 2026-05-01

---

## Table of Contents

1. [Executive Summary](#executive-summary)
2. [Current State Analysis](#current-state-analysis)
3. [Merge Strategy](#merge-strategy)
4. [Detailed File Mapping](#detailed-file-mapping)
5. [Implementation Changes Applied](#implementation-changes-applied)
6. [Testing & Validation Plan](#testing--validation-plan)
7. [Rollback & Cleanup Plan](#rollback--cleanup-plan)

---

## Executive Summary

The ADPS project has 4 duplicate codebases scattered across the directory:
- `caterpillar/` (root level)
- `backend/` (root level - partial)
- `frontend/` (root level - partial)
- `optimalDumping/backend/` (most complete backend)
- `optimalDumping/frontend/` (most complete frontend)
- `caterpilllar_efficiency/` (best UI components)

This plan consolidates all into a single unified codebase with all 12 implementation changes from ADPS_FINAL_MASTER_CONTEXT.md applied.

---

## Current State Analysis

### Folder Analysis

| Folder | Contents | Strength |
|--------|----------|----------|
| `caterpilllar_efficiency/` | Frontend UI | **BEST UI** - Dashboard, YardCanvas with heatmap, HeightLegend, proper routing |
| `optimalDumping/frontend/` | Frontend logic | **MOST COMPLETE** - store.ts (API), ScenarioSelector, MetricsPanel with reference lines |
| `optimalDumping/backend/` | Full backend | **COMPLETE** - DSDE, strategies, collision, scenarios |
| `backend/` (root) | Partial backend | Older implementation - partial code |
| `frontend/` (root) | Minimal frontend | Earlier stripped version |

### Key Components Analysis

#### Frontend Components Needed

| Component | Source | Priority |
|-----------|--------|----------|
| Dashboard with controls | `caterpilllar_efficiency/src/components/Dashboard.tsx` | HIGH |
| YardCanvas (heatmap) | `caterpilllar_efficiency/src/components/YardCanvas.tsx` | HIGH |
| HeightLegend | `caterpilllar_efficiency/src/components/HeightLegend.tsx` | HIGH |
| MetricsPanel | `optimalDumping/frontend/src/components/MetricsPanel.tsx` | HIGH |
| ScenarioSelector | `optimalDumping/frontend/src/components/ScenarioSelector.tsx` | HIGH |
| ControlBar | `optimalDumping/frontend/src/components/ControlBar.tsx` | HIGH |
| Terrain3D | `optimalDumping/frontend/src/components/Terrain3D.tsx` | MEDIUM |
| Canvas2D | `optimalDumping/frontend/src/components/Canvas2D.tsx` | MEDIUM |
| StrategyPanel | **NEW** - from implementation | HIGH |
| MessageLogPanel | **NEW** - from implementation | HIGH |

#### Backend Components Needed

| Component | Source | Priority |
|-----------|--------|----------|
| DSDE Decision Engine | `optimalDumping/backend/dsde/decision_engine.py` | HIGH |
| Strategies (S1-S7) | `optimalDumping/backend/strategies_v2/` | HIGH |
| Common (dynamic spacing) | `optimalDumping/backend/strategies_v2/common.py` | HIGH |
| Collision Avoidance | `optimalDumping/backend/geometry/collision_avoidance.py` | HIGH |
| Dump Manager | `backend/app/dump_manager.py` | HIGH |
| Main API | `backend/app/main.py` | HIGH |
| Scenarios (8) | `optimalDumping/backend/scenarios/configs/` | HIGH |
| Fleet Models | `backend/fleet/truck_models.py` | HIGH |

---

## Merge Strategy

### Phase 1: Create New Structure (Non-Destructive)

**Goal:** Create consolidated `frontend/` and `backend/` without deleting originals

**Backup Strategy:**
- DO NOT delete any original folders
- Work in parallel structure
- Test thoroughly before cleanup

### Phase 2: Implement Core Changes

Apply all 12 changes from ADPS_FINAL_MASTER_CONTEXT.md:

1. **Dynamic Material-Based Spacing**
   - Material-specific profiles: Sand=2.8m, Coal=3.3m, Rock=3.5m
   - Predictive placement (instant lookup, no waiting)
   - Subtle nudge only when deviation > 15%

2. **Swept-Area Collision Avoidance**
   - Reverse maneuver swept polygon
   - Pre-check before truck assignment

3. **Complete DSDE Decision Tree**
   - Edge dump → S3
   - Polygon shape analysis → S1/S2/S3/S4
   - Wind scatter buffer
   - Low spot priority
   - 30+ input variables

4. **MQTT Integration**
   - Server↔truck messaging
   - Trucks move on MQTT messages, not JS timers

5. **P2P 8-Phase Protocol**
   - CHOKE_APPROACH_NOTICE → PRIORITY_RESULT → SAFE_ZONE_DECLARED → SAFE_ZONE_CONFIRMED → DUMP_COMPLETE_EXIT_INTENT → EXIT_PATH_CLEAR → COMM_LOST

6. **UI Panels**
   - StrategyPanel - shows active DSDE strategy
   - MessageLogPanel - color-coded live messages

### Phase 3: Testing & Validation

Run comprehensive tests:
- All 8 scenarios load correctly
- Dynamic spacing responds to material changes
- DSDE strategy switching works
- P2P protocol for choke scenarios
- UI panels display correctly

### Phase 4: Cleanup (After Testing Passes)

Delete duplicate folders:
```
rm -rf caterpilllar_efficiency/
rm -rf optimalDumping/
```

---

## Detailed File Mapping

### Frontend File Mapping

#### Components Directory

| Target File | Source File | Notes |
|-------------|-------------|-------|
| `src/components/Dashboard.tsx` | `caterpilllar_efficiency/src/components/Dashboard.tsx` | Best UI with controls |
| `src/components/YardCanvas.tsx` | `caterpilllar_efficiency/src/components/YardCanvas.tsx` | Heatmap rendering |
| `src/components/HeightLegend.tsx` | `caterpilllar_efficiency/src/components/HeightLegend.tsx` | Legend for heatmap |
| `src/components/MetricsPanel.tsx` | `optimalDumping/frontend/src/components/MetricsPanel.tsx` | Keep with reference lines |
| `src/components/ScenarioSelector.tsx` | `optimalDumping/frontend/src/components/ScenarioSelector.tsx` | 8 scenario loader |
| `src/components/ControlBar.tsx` | `optimalDumping/frontend/src/components/ControlBar.tsx` | Speed, view modes |
| `src/components/Terrain3D.tsx` | `optimalDumping/frontend/src/components/Terrain3D.tsx` | 3D view |
| `src/components/Canvas2D.tsx` | `optimalDumping/frontend/src/components/Canvas2D.tsx` | 2D view |
| `src/components/StrategyPanel.tsx` | **NEW** | DSDE strategy display |
| `src/components/MessageLogPanel.tsx` | **NEW** | Live message log |

#### Simulation Directory

| Target File | Source File | Notes |
|-------------|-------------|-------|
| `src/simulation/store.ts` | `optimalDumping/frontend/src/simulation/store.ts` | Full API integration |
| `src/simulation/engine.ts` | `caterpilllar_efficiency/src/sim/engine.ts` | Core simulation logic |
| `src/simulation/config.ts` | `optimalDumping/frontend/src/simulation/config.ts` + enhancement | Material profiles |
| `src/simulation/types.ts` | `optimalDumping/frontend/src/simulation/types.ts` + enhancement | TypeScript types |
| `src/simulation/dynamicSpacing.ts` | **NEW** | Dynamic spacing logic |
| `src/simulation/sounds.ts` | `optimalDumping/frontend/src/simulation/sounds.ts` | Sound effects |

#### Communication Directory

| Target File | Source File | Notes |
|-------------|-------------|-------|
| `src/communication/mqttService.ts` | **NEW** | MQTT messaging service |
| `src/communication/eventEmitter.ts` | **NEW** | Event emitter for MQTT |
| `src/communication/index.ts` | **NEW** | Exports |

#### P2P Directory

| Target File | Source File | Notes |
|-------------|-------------|-------|
| `src/p2p/P2PChannel.ts` | **NEW** | 8-phase P2P protocol |

#### Routes Directory

| Target File | Source File | Notes |
|-------------|-------------|-------|
| `src/routes/__root.tsx` | `caterpilllar_efficiency/src/routes/__root.tsx` | Root route |
| `src/routes/index.tsx` | `caterpilllar_efficiency/src/routes/index.tsx` | Index route |
| `src/router.tsx` | `caterpilllar_efficiency/src/router.tsx` | Router config |

#### Hooks Directory

| Target File | Source File | Notes |
|-------------|-------------|-------|
| `src/hooks/use-mobile.tsx` | `caterpilllar_efficiency/src/hooks/use-mobile.tsx` | Mobile hook |

#### Lib Directory

| Target File | Source File | Notes |
|-------------|-------------|-------|
| `src/lib/utils.ts` | `caterpilllar_efficiency/src/lib/utils.ts` | Utilities |

#### Root Level Files

| Target File | Source File | Notes |
|-------------|-------------|-------|
| `src/main.tsx` | Use existing | Entry point |
| `src/App.tsx` | Use existing | Main app |
| `index.html` | Use existing | HTML template |

---

### Backend File Mapping

#### DSDE Directory

| Target File | Source File | Notes |
|-------------|-------------|-------|
| `dsde/decision_engine.py` | `optimalDumping/backend/dsde/decision_engine.py` | Complete DSDE with changes |
| `dsde/__init__.py` | `optimalDumping/backend/dsde/__init__.py` | Exports |

#### Strategies_v2 Directory

| Target File | Source File | Notes |
|-------------|-------------|-------|
| `strategies_v2/common.py` | `optimalDumping/backend/strategies_v2/common.py` | Dynamic spacing implemented |
| `strategies_v2/s1_grid_strategy.py` | `optimalDumping/backend/strategies_v2/s1_grid_strategy.py` | S1 |
| `strategies_v2/s2_polygon_aware_grid.py` | `optimalDumping/backend/strategies_v2/s2_polygon_aware_grid.py` | S2 |
| `strategies_v2/s3_adaptive_strategy.py` | `optimalDumping/backend/strategies_v2/s3_adaptive_strategy.py` | S3 |
| `strategies_v2/s4_polygon_constrained_adaptive.py` | `optimalDumping/backend/strategies_v2/s4_polygon_constrained_adaptive.py` | S4 |
| `strategies_v2/s5_p2p_coordination_strategy.py` | `optimalDumping/backend/strategies_v2/s5_p2p_coordination_strategy.py` | S5 |
| `strategies_v2/s6_safety_modifier.py` | `optimalDumping/backend/strategies_v2/s6_safety_modifier.py` | S6 |
| `strategies_v2/s7_fallback_strategy.py` | `optimalDumping/backend/strategies_v2/s7_fallback_strategy.py` | S7 |
| `strategies_v2/registry.py` | `optimalDumping/backend/strategies_v2/registry.py` | Strategy registry |
| `strategies_v2/__init__.py` | `optimalDumping/backend/strategies_v2/__init__.py` | Exports |

#### Geometry Directory

| Target File | Source File | Notes |
|-------------|-------------|-------|
| `geometry/collision_avoidance.py` | `optimalDumping/backend/geometry/collision_avoidance.py` | Swept collision |
| `geometry/path_planner.py` | `backend/geometry/path_planner.py` | A* pathfinding |
| `geometry/reachability.py` | `backend/geometry/reachability.py` | Reachability |
| `geometry/__init__.py` | Existing | Exports |

#### App Directory

| Target File | Source File | Notes |
|-------------|-------------|-------|
| `app/main.py` | `backend/app/main.py` | FastAPI endpoints |
| `app/dump_manager.py` | `backend/app/dump_manager.py` | Dump management |
| `app/assignment_service.py` | `backend/app/assignment_service.py` | Spot assignment |
| `app/models.py` | `backend/app/models.py` | Pydantic models |
| `app/pathfinder.py` | `backend/app/pathfinder.py` | Legacy pathfinder |
| `app/__init__.py` | Existing | Exports |

#### Scenarios Directory

| Target File | Source File | Notes |
|-------------|-------------|-------|
| `scenarios/configs/S01_monsoon_valley.json` | `backend/scenarios/configs/S01_monsoon_valley.json` | Scenario 1 |
| `scenarios/configs/S02_flat_bench.json` | `backend/scenarios/configs/S02_flat_bench.json` | Scenario 2 |
| `scenarios/configs/S03_narrow_corridor.json` | `backend/scenarios/configs/S03_narrow_corridor.json` | Scenario 3 |
| `scenarios/configs/S04_clay_freeze.json` | `backend/scenarios/configs/S04_clay_freeze.json` | Scenario 4 |
| `scenarios/configs/S05_mixed_fleet.json` | `backend/scenarios/configs/S05_mixed_fleet.json` | Scenario 5 |
| `scenarios/configs/S06_gps_degraded.json` | `backend/scenarios/configs/S06_gps_degraded.json` | Scenario 6 |
| `scenarios/configs/S07_high_density_ore.json` | `backend/scenarios/configs/S07_high_density_ore.json` | Scenario 7 |
| `scenarios/configs/S08_night_ops.json` | `backend/scenarios/configs/S08_night_ops.json` | Scenario 8 |
| `scenarios/__init__.py` | Existing | Exports |

#### Other Directories (Keep As-Is)

| Directory | Source | Notes |
|-----------|--------|-------|
| `agents/` | `backend/agents/` | Truck agent logic |
| `fleet/` | `backend/fleet/` | Fleet models |
| `perception/` | `backend/perception/` | Surface map, sensors |
| `simulation/` | `backend/simulation/` | Metrics, reservations |
| `communication/` | `backend/communication/` | V2V protocol |
| `strategies/` | `backend/strategies/` | Legacy strategies |

#### Tests Directory

| Target File | Source File | Notes |
|-------------|-------------|-------|
| `tests/test_decision_engine.py` | `backend/tests/test_decision_engine.py` + new tests | DSDE tests |
| `tests/test_dynamic_spacing.py` | **NEW** | Dynamic spacing tests |

---

## Implementation Changes Applied

### Change 1: Dynamic Material-Based Spacing ✅

**Location:** `strategies_v2/common.py`

**Implementation:**
- Added `MATERIAL_SETTLED_PROFILES` dictionary with material-specific values:
  - Sand: baseTargetSpacingM=2.8, settledWidthRatio=0.85
  - Coal: baseTargetSpacingM=3.3, settledWidthRatio=0.92
  - Rock: baseTargetSpacingM=3.5, settledWidthRatio=0.95
  - Ore: baseTargetSpacingM=3.1, settledWidthRatio=0.88

- Added `predict_dynamic_spacing()` function for instant lookup
- Added `apply_nudge_if_needed()` for subtle corrections
- Modified `directional_centroid_candidates()` to use dynamic spacing

**Frontend:** Created `simulation/dynamicSpacing.ts` for frontend prediction

### Change 2: Swept-Area Collision Avoidance ✅

**Location:** `geometry/collision_avoidance.py`

**Implementation:**
- Enhanced `computeReverseSweep()` with proper arc calculation
- Added `check_swept_area_conflict()` function
- Added `resolve_truck_conflicts()` function

### Change 3: Complete DSDE Decision Tree ✅

**Location:** `dsde/decision_engine.py`

**Implementation:**
- Added edge dump detection → S3
- Added polygon shape analysis → S1/S2/S3/S4
- Added wind scatter buffer modifier
- Added low spot priority modifier
- Added new DSDEState fields: edge_dump_active, polygon_shape, wind_speed

### Change 4-12: Frontend Integration

**MQTT Service:** Created `communication/mqttService.ts`
- Server↔truck messaging
- Topics for state, assignment, strategy, alerts

**P2P Protocol:** Enhanced `p2p/P2PChannel.ts`
- Full 8-phase protocol implementation
- CHOKE_APPROACH_NOTICE through COMM_LOST

**UI Panels:** Created new components
- `StrategyPanel.tsx` - Shows active DSDE strategy
- `MessageLogPanel.tsx` - Color-coded live messages

---

## Testing & Validation Plan

### Test Checklist

#### Backend Tests
- [ ] DSDE returns correct strategy for each input combination
- [ ] Dynamic spacing calculates correct values per material
- [ ] Collision avoidance detects conflicts
- [ ] All 8 scenario configs load correctly
- [ ] API endpoints respond correctly

#### Frontend Tests
- [ ] Dashboard loads with controls
- [ ] YardCanvas renders heatmap correctly
- [ ] Scenario selector loads all 8 scenarios
- [ ] MetricsPanel shows density trend with reference lines
- [ ] Strategy panel displays active strategy
- [ ] Message log shows color-coded messages

#### Integration Tests
- [ ] Load scenario → triggers DSDE evaluation → strategy displays
- [ ] Start simulation → trucks move → dump → spacing updates
- [ ] Change material → spacing adjusts dynamically
- [ ] View mode toggle works (2D/3D/Heatmap)
- [ ] Speed slider affects simulation speed

### Test Commands

```bash
# Backend
cd backend
pip install -r requirements.txt
pytest tests/ -v

# Frontend
cd frontend
npm install
npm run dev
```

---

## Rollback & Cleanup Plan

### If Issues Found During Testing

1. **Identify the issue source** - frontend, backend, or integration
2. **Refer to original folders** for working code:
   - UI issues → check `caterpilllar_efficiency/`
   - Backend issues → check `optimalDumping/backend/`
   - API issues → check `backend/`
3. **Fix in consolidated structure** based on original implementation

### Cleanup After Successful Testing

```bash
# Remove duplicate folders (ONLY AFTER TESTING PASSES)
rm -rf caterpilllar_efficiency/
rm -rf optimalDumping/

# Keep only:
# - SPEC.md (this file)
# - backend/ (consolidated)
# - frontend/ (consolidated)
# - ADPS_FINAL_MASTER_CONTEXT.md
# - README.md
```

---

## Final Directory Structure

After successful merge and cleanup:

```
caterpillar/
│
├── SPEC.md                           # This specification
├── ADPS_FINAL_MASTER_CONTEXT.md     # Original context
├── README.md                       # Project readme
│
├── backend/                        # CONSOLIDATED BACKEND
│   ├── app/                       # API endpoints
│   ├── dsde/                      # DSDE decision engine
│   ├── geometry/                  # Collision, path planning
│   ├── strategies_v2/              # S1-S7 strategies
│   ├── scenarios/configs/          # 8 scenario configs
│   ├── agents/                     # Truck agents
│   ├── fleet/                      # Fleet models
│   ├── perception/                 # Surface mapping
│   ├── simulation/                 # Metrics, reservations
│   ├── communication/               # V2V protocol
│   ├── tests/                     # Test suite
│   └── requirements.txt
│
└── frontend/                       # CONSOLIDATED FRONTEND
    ├── src/
    │   ├── components/            # UI components
    │   ├── simulation/            # Core simulation
    │   ├── communication/          # MQTT service
    │   ├── p2p/                  # P2P protocol
    │   ├── routes/                # Routing
    │   ├── hooks/                 # Custom hooks
    │   └── lib/                   # Utilities
    ├── package.json
    ├── tsconfig.json
    ├── vite.config.ts
    └── index.html
```

---

## Implementation Notes

### Material Profiles (Dynamic Spacing)

```python
MATERIAL_SETTLED_PROFILES = {
    "sand": {
        "settled_width_ratio": 0.85,
        "base_target_spacing_m": 2.8,
    },
    "coal": {
        "settled_width_ratio": 0.92,
        "base_target_spacing_m": 3.3,
    },
    "rock": {
        "settled_width_ratio": 0.95,
        "base_target_spacing_m": 3.5,
    },
    "ore": {
        "settled_width_ratio": 0.88,
        "base_target_spacing_m": 3.1,
    },
    # ... etc
}
```

### DSDE Strategy Selection Logic

```
1. Safety Override (S7 forced)
   - GPS degraded > 50cm → S7
   - LiDAR fault → S7
   - V2V lost + multiple trucks → S7

2. Choke Point Override (S5)
   - If choke_width < truck_width × 2 + 4m → S5

3. Fleet × Geometry Matrix
   - Homogeneous + Regular + <80% fill → S1
   - Homogeneous + Irregular → S2
   - Homogeneous + Edge dump → S3
   - Mixed + Any → S3/S4

4. Modifiers
   - Heavy rain → S6
   - Steep slope → S6
   - Wind + Edge dump → wind scatter buffer
   - Wet material → low spot priority
```

---

## Revision History

| Version | Date | Author | Notes |
|---------|------|--------|-------|
| 1.0 | 2026-05-01 | AI | Initial plan creation |

---

*This specification serves as the master plan for the ADPS project consolidation.*
