# Autonomous Dump Packing System (ADPS)

A research-grade system for optimizing autonomous mine truck dump spacing in dynamic dump-yard polygons. This is a submission to **Caterpillar Inc.'s Participant Evaluation Challenge**, titled **"Optimal Dump Packing."**

The system targets spacing improvement from the legacy ~7.38m pattern toward the ~3.03m human operator benchmark using DSDE (Dump Strategy Decision Engine) strategy selection, perception-driven terrain awareness, and scenario simulation.

---

## Problem Statement

| Mode | Inter-pile spacing | Dumps per 100m face | Area efficiency |
|------|-------------------|---------------------|-----------------|
| Human (staffed) | **3.03m** | ~33 | 100% |
| Autonomous (current) | **7.38m** | ~14 | ~41% |
| **Project target** | **≤3.5m** | **≥28** | **≥87%** |

The 4.35m excess gap × 200 dump cycles per shift means the autonomous system exhausts the dump polygon **2–3 weeks earlier** than a human crew for the same volume of material.

---

## Architecture Overview

ADPS uses a **three-layer architecture**:

```
┌─────────────────────────────────────────────────────────────┐
│  LAYER 3 — Research Paper                                   │
│  Argument: 7.38m → 3.03m gap requires context-aware         │
│  switching system (DSDE) with Server↔Client + P2P V2V     │
└─────────────────────────────────────────────────────────────┘
                              │
┌─────────────────────────────▼───────────────────────────────┐
│  LAYER 2 — Communication System                             │
│  Channel A: Server ↔ Client (MQTT)                          │
│  Channel B: Truck ↔ Truck P2P (WebSocket)                   │
└─────────────────────────────────────────────────────────────┘
                              │
┌─────────────────────────────▼───────────────────────────────┐
│  LAYER 1 — Simulation / Visualizer                          │
│  Real-time visualization of dump operations                  │
└─────────────────────────────────────────────────────────────┘
```

---

## Key Features

### 1. DSDE (Dump Strategy Decision Engine)
- **7 Strategies (S1-S7):** Pre-computed Grid, Polygon-Aware, Real-Time Adaptive, P2P Coordination, Safety modifiers, Degraded mode
- **30+ Input Variables:** Fleet composition, polygon fill %, terrain slope, material type, weather, system health
- **Safety First:** GPS degradation, LiDAR faults, V2V loss → automatic S7 fallback

### 2. Dynamic Material-Based Spacing
Material-specific spacing profiles based on settled behavior:

| Material | Base Target Spacing | Settled Width Ratio |
|----------|--------------------|--------------------|
| Sand | 2.8m | 0.85 |
| Coal | 3.3m | 0.92 |
| Rock | 3.5m | 0.95 |
| Ore | 3.1m | 0.88 |

### 3. Swept-Area Collision Avoidance
- Computes full reverse maneuver swept polygon before truck assignment
- Validates arc and footprint don't conflict with existing piles

### 4. MQTT Integration
- Server↔truck messaging via MQTT broker
- Topics: truck state, spot assignment, strategy updates, alerts

### 5. P2P 8-Phase Protocol (Choke Point Scenarios)
Full truck-to-truck negotiation for valley fill / narrow corridor scenarios:
1. CHOKE_APPROACH_NOTICE
2. CHOKE_STATE_RESPONSE
3. PRIORITY_RESULT
4. SAFE_ZONE_DECLARED
5. SAFE_ZONE_CONFIRMED
6. DUMP_COMPLETE_EXIT_INTENT
7. EXIT_PATH_CLEAR
8. COMM_LOST (failure handling)

---

## Directory Structure

```
caterpillar/
├── SPEC.md                           # Detailed implementation plan
├── ADPS_FINAL_MASTER_CONTEXT.md     # Complete project context
├── README.md                         # This file
│
├── backend/                         # Python FastAPI backend
│   ├── app/                        # API endpoints, dump manager
│   ├── dsde/                       # DSDE decision engine
│   │   └── decision_engine.py      # Complete strategy selection
│   ├── geometry/                   # Collision, path planning
│   │   └── collision_avoidance.py # Swept-area collision detection
│   ├── strategies_v2/             # S1-S7 strategy implementations
│   │   ├── common.py              # Dynamic spacing logic
│   │   └── s1-s7_*.py             # Individual strategies
│   ├── scenarios/configs/         # 8 scenario configurations
│   ├── agents/                    # Truck agent logic
│   ├── fleet/                     # Fleet models (Cat 793F, 789D, etc.)
│   ├── perception/               # Surface mapping, sensors
│   ├── simulation/                # Metrics, reservations
│   ├── communication/             # V2V protocol
│   ├── tests/                     # 37 passing tests
│   └── requirements.txt
│
└── frontend/                       # React + TypeScript frontend
    ├── src/
    │   ├── components/            # UI components
    │   │   ├── Dashboard.tsx      # Main dashboard
    │   │   ├── YardCanvas.tsx     # Heatmap visualization
    │   │   ├── StrategyPanel.tsx # DSDE strategy display
    │   │   ├── MessageLogPanel.tsx # Live message log
    │   │   ├── MetricsPanel.tsx  # Density trend chart
    │   │   └── ScenarioSelector.tsx # Scenario loader
    │   ├── simulation/            # Core simulation
    │   │   ├── store.ts           # Zustand state management
    │   │   ├── engine.ts         # Simulation engine
    │   │   ├── dynamicSpacing.ts # Frontend spacing logic
    │   │   └── config.ts         # Material profiles
    │   ├── communication/         # MQTT service
    │   │   └── mqttService.ts    # MQTT messaging
    │   ├── p2p/                  # P2P protocol
    │   │   └── P2PChannel.ts    # Truck-to-truck channel
    │   └── routes/               # React Router
    ├── package.json
    └── vite.config.ts
```

---

## Setup

### Backend

```bash
cd backend
python -m venv venv

# Windows
venv\Scripts\activate

# Linux/Mac
source venv/bin/activate

pip install -r requirements.txt
```

### Frontend

```bash
cd frontend
npm install
```

---

## Running the Application

### Start Backend

```bash
cd backend
python -m uvicorn app.main:app --host 127.0.0.1 --port 8000 --reload
```

### Start Frontend

```bash
cd frontend
npm run dev
```

Open the app at the URL printed by Vite (typically `http://localhost:5173`).

---

## Testing

### Backend Tests

```bash
cd backend
python -m pytest tests/ -v
```

**Current Results:** 37/37 tests passing

### Test Coverage

| Test Suite | Tests | Status |
|-------------|-------|--------|
| test_decision_engine.py | 27 | ✅ Passing |
| test_dynamic_spacing.py | 10 | ✅ Passing |

### Frontend Build

```bash
cd frontend
npm run build
```

### Frontend Lint

```bash
cd frontend
npm run lint
```

---

## The 8 Scenarios

ADPS includes 8 pre-configured scenarios for testing:

| ID | Name | Description |
|----|------|-------------|
| S01 | Monsoon Paddock | Mixed fleet, monsoon rain, pile drift |
| S02 | Flat Bench | Edge dump, wind scatter, high density ore |
| S03 | Narrow Corridor | Valley fill, choke point, P2P coordination |
| S04 | Clay Freeze | Low temperature, copper overburden |
| S05 | Mixed Fleet | Homogeneous vs heterogeneous fleet |
| S06 | GPS Degraded | S7 fallback mode testing |
| S07 | High Density Ore | Iron ore, tight spacing |
| S08 | Night Operations | Low visibility, lighting constraints |

---

## DSDE Strategy Selection Logic

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

## Implementation Changes (per ADPS_FINAL_MASTER_CONTEXT.md)

The consolidated codebase includes all 12 implementation changes from the master context:

1. ✅ **Dynamic Material-Based Spacing** - Material-specific profiles with nudge logic
2. ✅ **Swept-Area Collision Avoidance** - computeReverseSweep() with polygon intersection
3. ✅ **Complete DSDE Decision Tree** - 30+ input variables, edge dump detection, polygon analysis
4. ✅ **MQTT Integration** - Server↔truck messaging via MQTT
5. ✅ **P2P 8-Phase Protocol** - Full choke point negotiation
6. ✅ **StrategyPanel Component** - Shows active DSDE strategy
7. ✅ **MessageLogPanel Component** - Color-coded live messages (blue/green/orange/red)
8. ✅ **MetricsPanel Enhancement** - Density trend with 7.38m and 3.03m reference lines
9. ✅ **ScenarioSelector Enhancement** - 8 scenario loader
10. ✅ **ControlBar Enhancement** - Speed slider, view modes (2D/3D/Heatmap)
11. ✅ **Terrain3D Component** - 3D terrain visualization
12. ✅ **Canvas2D Component** - 2D canvas rendering

---

## Supported Truck Models

| Model | Payload (t) | Width (m) | Pile Footprint (m) | AHS Status |
|-------|-------------|-----------|-------------------|------------|
| Cat 777G | 100 | 7.4 | 5.5 × 4.5 | ✅ Proven |
| Cat 785 | 139 | 8.2 | 7.0 × 5.5 | ✅ Deployed |
| Cat 789D | 181 | 8.8 | 8.0 × 6.2 | ✅ Commercial |
| Cat 793F | 227 | 9.3 | 9.0 × 7.0 | ✅ Primary fleet |
| Cat 797F | 363 | 9.8 | 11.0 × 8.5 | ✅ Commercial |
| Cat 794 AC | 290 | 9.5 | 10.0 × 7.8 | ✅ Electric drive |

---

## Known Limitations

1. Lint baseline contains pre-existing formatting/line-ending inconsistencies (not merge-related)
2. Sensor map transport uses flattened arrays - bandwidth-heavy at high update rates
3. `avgSpacing` relies on nearest-neighbor dump record distance (not direction-weighted)
4. Risk scoring is deterministic weighted blending, not ML-learned terrain hazard modeling

---

## License

This project is submitted as part of Caterpillar Inc.'s Participant Evaluation Challenge.