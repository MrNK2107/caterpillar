# Project Context Dossier - ADPS (Autonomous Dump Planning System)

This dossier documents the current code state of the repository at `c:\Users\nanda\desktop\optimaldumping`, including all recently implemented systems, backend optimizations, and architectural modules.

---

## 1) Project Overview

ADPS is a full-stack dump-yard simulation and dispatch platform.

- **Purpose:** optimize autonomous dump placement and routing under geometric, kinematic, safety, and environmental constraints.
- **Frontend role:** run simulation loop, render 2D/3D state, collect operational metrics, provide dynamic scenario controls, and visualize AHS execution.
- **Backend role:** allocate dump spots, plan routes, maintain perception layers, execute local truck-agent policies, enforce reservation constraints, handle timeline events, and expose simulation APIs.

---

## 2) Runtime Modes

Frontend simulation store (`frontend/src/simulation/store.ts`) supports two modes:

1. `DEMO_LOOP_MODE = true` — frontend-only demo loop (when enabled).
- Local frontend target assignment and movement behavior.
- Backend APIs are bypassed for the core assignment loop.
- Useful for fast visualization/demo continuity.
- **Note**: Most advanced backend systems (DSDE, V2V, reservation-aware Hybrid A*, Scenario Engine) are bypassed in this mode.

2. `DEMO_LOOP_MODE = false` — backend orchestration active.
- Backend endpoints are exercised and return authoritative assignments/routes and metrics snapshots, including:
  - `/api/init_yard`
  - `/api/trucks`
  - `/api/assign_dump`
  - `/api/complete_dump`
  - `/api/release_reservation`
  - `/api/metrics`
  - `/api/step` (central simulation clock)
  - `/api/scenarios` (fetch available configurations)
  - `/api/load_scenario/{id}` (hot-swap environment configurations)

**Note:** The repository defaults to `DEMO_LOOP_MODE = false` to leverage the full backend AI architecture.

---

## 3) Major Implemented Systems

### 3.1 Scenario Control and Timeline Engine (NEW)

Files:
- `backend/scenarios/__init__.py`
- `backend/scenarios/configs/*.json`
- `frontend/src/components/ScenarioSelector.tsx`

Capabilities:
- **Dynamic Configuration:** JSON-based setup of fleet composition, weather arrays, material types, and initial polygon boundaries.
- **Verified Scenarios (S01-S08):** 8 pre-configured AHS test environments, including:
  - S01: Monsoon Valley (Heavy Rain)
  - S02: Flat Bench (Baseline)
  - S03: Narrow Corridor (Choke point testing)
  - S04: Clay Freeze
  - S05: Mixed Fleet
  - S06: GPS Degraded (Sensor fallback testing)
  - S07: High Density Ore
  - S08: Night Ops
- **Event Timeline:** A deterministic timeline engine shifts environment properties (e.g. dropping visibility or increasing rain intensity) mid-simulation at specific `time_sec` marks.
- **Frontend UI:** Integrated Scenario Selector modal that interfaces with the backend to hot-swap scenarios and trigger a clean reset of the fleet and yard.

### 3.2 Perception Layer

Files:
- `backend/perception/surface_map.py`

Capabilities:
- Occupancy grid (0.5m resolution) with values: `EMPTY`, `PARTIAL`, `FILLED`.
- Height map (`float` array) for material depth.
- Core operations: `update_after_dump`, `get_cell_height`, `mark_cells_filled`.
- Height increment uses radial falloff with material-specific spread factors.

### 3.3 Dynamic Strategic Decision Engine (DSDE)

Files:
- `backend/dsde/decision_engine.py`

Purpose:
- Acts as the "brain" of the system, evaluating high-level environment and fleet state to select the optimal dumping strategy.

Evaluation Criteria:
- **Fleet Composition**: Homogeneous vs. Heterogeneous.
- **Polygon Fill Percent**: Adjusts strategy as the yard fills up (e.g., >70%, >80%).
- **Terrain Slope**: Detects steep or soft ground.
- **Weather Conditions**: Monitors rain intensity and visibility (often driven by the Scenario Timeline Engine).
- **Choke Point Presence**: Detects congestion at entry/exit points.
- **System Health**: Checks for GPS/Lidar degradation or V2V failures.

### 3.4 Strategies V2 Architecture

Files:
- `backend/strategies_v2/`
- `backend/strategies_v2/registry.py`

The system supports 7 distinct strategies:
- **S1 (Grid Strategy)**: Standard grid-based placement for homogeneous fleets.
- **S2 (Polygon-Aware Grid)**: Optimized grid for mixed fleets within complex polygons.
- **S3 (Adaptive Strategy)**: Dynamic spacing and orientation for high-density filling.
- **S4 (Constrained Adaptive)**: Tight boundary enforcement for near-capacity zones.
- **S5 (P2P Coordination)**: Focuses on avoiding choke points and managing traffic.
- **S6 (Safety Modifier)**: Overrides placements during high-risk conditions (heavy rain/slope).
- **S7 (Fallback)**: Degraded-mode operations (e.g., GPS loss).

### 3.5 Reachability Validation

Files:
- `backend/geometry/reachability.py`

Behavior:
- BFS from entry gate over traversable cells.
- Rejects candidates that would "orphan" remaining empty space (preventing islands).

### 3.6 Space-Time Reservation System

Files:
- `backend/simulation/reservation_system.py`

Model & Optimizations:
- Reserves (x, y, time_window) for both paths and dump footprints.
- **Continuous Time-Sweeps:** Uses exact convex hull unions of truck footprints moving along A* segment vectors to guarantee collision-free reservations. This avoids false-positive bounding box inflation and ensures dense traffic flow at choke points.

### 3.7 Path Planning (Hybrid A*)

Files:
- `backend/geometry/path_planner.py`

Planner & Optimizations:
- Hybrid A* accounting for truck turning radius (`turning_radius_m`).
- Supports reverse motion and avoids `FILLED` cells/reservations.
- **Geometric Hashing:** Employs `shapely.prepared.prep(polygon)` for spatial indexing, accelerating A* boundary validation `_is_valid_cell` by ~100x, allowing real-time multi-agent routing.
- **Deterministic Tie-Breaking:** Uses explicit `__lt__` operator methods on `HybridState` dataclass instances to guarantee stable `heapq` resolution when path costs are identical.

### 3.8 Truck-to-Truck Communication (V2V) & Local Behavior

Files:
- `backend/communication/v2v_protocol.py`
- `backend/agents/truck_agent.py`

Protocol & Rules:
- In-memory pub/sub (`InMemoryV2VProtocol`).
- Agents publish position, state, and reserved cells.
- P2P negotiation at choke points; yield logic based on vehicle size, eta, and distance.
- Dynamic speed multipliers based on weather visibility and surface stability.

### 3.9 Deadlock Detection and Resolution

- Triggered if a truck is `waiting` > 20 steps.
- Resolution involves releasing reservations and re-requesting assignments with updated state.
- Fallback paths are generated if A* fails to locate a complex candidate.

### 3.10 Metrics Tracking + Baseline Comparison

Files:
- `backend/simulation/metrics.py`

KPIs:
- Packing density, average spacing, throughput, collision count.
- Compares "New System" performance against a "Baseline" (simple circular union).

---

## 4) Backend Architecture

### 4.1 Core Manager (`DumpManager`)

File: `backend/app/dump_manager.py`

Responsibilities:
- **Strategy Control**: Periodic (30s) or event-driven re-evaluation via DSDE.
- **Transition Management**: Ensures smooth strategy swaps (waiting for active dumps to clear).
- **Simulation Clock**: `step_simulation()` drives the state of all agents, environment, and applies timeline events.
- **Unified Reservation**: Single source of truth for `reserved_spots`.

### 4.2 API Surface (`main.py`)

- `POST /api/init_yard`: Sets polygon and scenario.
- `POST /api/assign_dump`: Entry point for strategy-driven assignment.
- `POST /api/step`: Advances the simulation state.
- `GET /api/metrics`: Quantitative evaluation output.
- `GET /api/scenarios`: Returns available scenario configurations.
- `POST /api/load_scenario/{id}`: Loads and resets the backend to a specific scenario configuration.

---

## 5) Fleet Management

Files:
- `backend/fleet/truck_models.py`

Supported Models:
- **Cat 777G, 785, 789D** (Small)
- **Cat 793F, 794 AC, 797F** (Large)

Attributes:
- Payload tonnes, turning radius, width/length, and footprint dimensions (`pile_length_m`, `pile_width_m`).

---

## 6) Data Contracts

### 6.1 Backend Models (`backend/app/models.py`)
- `ScenarioConfig`: Weather, Material, Slope Limits, Timeline Events.
- `AssignDumpRequest`: Truck ID and current position.

### 6.2 Frontend Types (`frontend/src/simulation/types.ts`)
- `TruckState`: `idle`, `requesting_dump`, `moving_to_dump`, `dumping`, `returning`, `waiting`.

---

## 7) Operational Commands

Backend:
```bash
cd backend
python -m venv venv
venv\Scripts\activate
pip install -r requirements.txt
uvicorn main:app --host 127.0.0.1 --port 8000 --reload
```

Frontend:
```bash
cd frontend
npm install
npm run dev
```

---

## 8) Important Notes and Known Edges

1. **Strategy Transitions**: When DSDE switches strategies, trucks in `REQUESTING_DUMP` may wait until in-flight movements (`MOVING_TO_DUMP`, `DUMPING`) complete to ensure consistency.
2. **Legacy Endpoints**: `/api/zones` in `main.py` is currently broken (calls missing `manager.add_zone`).
3. **Collision Logic**: Collision count is tracked but relies on agent-level reporting during `advance_along_path`.

---

## 9) Detailed File Map

### Backend
- `dsde/`: Decision Engine and State Evaluation.
- `strategies_v2/`: Implementation of S1-S7 strategies.
- `fleet/`: Truck model definitions and registry.
- `perception/`: Occupancy and height maps.
- `geometry/`: Path planning (Hybrid A* with shapely prep) and reachability.
- `agents/`: Autonomous truck agent logic.
- `simulation/`: Metrics and exact continuous-sweep reservation systems.
- `scenarios/`: JSON configurations (S01-S08) and scenario timeline engine.
- `app/`: FastAPI endpoints and `DumpManager`.

### Frontend
- `src/simulation/store.ts`: Central state and simulation loop.
- `src/components/`:
  - `Canvas2D.tsx` / `Terrain3D.tsx`: Visualizers.
  - `MetricsPanel.tsx`: KPI display and fleet configuration.
  - `ControlBar.tsx`: Sim controls and yard drawing.
  - `ScenarioSelector.tsx`: Scenario hot-swapping UI.
