# ADPS — Autonomous Dump Packing System
## Complete Project Context Transfer — Final Master Document
### Everything discussed, decided, corrected, designed, and planned — nothing omitted

---

> **Purpose:** This is the single source of truth for the entire ADPS project.
> It captures every conversation, every correction, every design decision, and the
> complete build plan for the agentic IDE (Antigravity / Cursor / GitHub Copilot Workspace).
>
> **Existing prototype:** https://optimaldumping.onrender.com
> The prototype is live. It uses a modified A* approach and unit cell matrices.
> The enhancements described in this document have NOT yet been built.
>
> **Agentic IDE target:** Antigravity (Google's agentic IDE)
> The GitHub repository link will be shared separately.
> The agent must READ the existing code before making any changes.
> The agent must NOT rebuild what already exists.

---

# CHAPTER 1 — THE PROBLEM

## 1.1 What This Project Is

This is a submission to Caterpillar Inc.'s **Participant Evaluation Challenge**, titled
**"Optimal Dump Packing."** The goal is to close the efficiency gap between how
autonomous mining trucks dump material versus how human operators do it.

The deliverable is **both** — a research paper AND a working prototype.
- The paper argues the architecture
- The prototype proves it

## 1.2 The Core Gap

| Mode | Inter-pile spacing | Dumps per 100m face | Area efficiency |
|---|---|---|---|
| Human (staffed) | **3.03m** | ~33 | 100% |
| Autonomous (current) | **7.38m** | ~14 | ~41% |
| **Project target** | **≤3.5m** | **≥28** | **≥87%** |

The 4.35m excess gap × 200 dump cycles per shift means the autonomous system
exhausts the dump polygon **2–3 weeks earlier** than a human crew for the same
volume of material. Across a large mine, this translates to millions of rupees in
additional dump area acquisition costs per year.

## 1.3 Why Autonomous Trucks Can't Just "Drive Closer" — Three Barriers

**Barrier 1 — Obstacle Classification Conflict**
The truck's LiDAR classifies all objects above a threshold height as collision
obstacles. A previous dump pile looks identical to a parked truck. The safety
system triggers an emergency stop at 7+ meters distance. The solution is semantic
segmentation — teaching the system to distinguish a pile (approach-safe) from a
hard obstacle (stop).

**Barrier 2 — Load Cell Calibration Constraint**
Autonomous trucks cannot perform partial dumps. The bed-mounted load cell
calibrates to zero assuming the bed is fully emptied each cycle. Residual
material corrupts subsequent payload readings. Every dump is all-or-nothing,
demanding precise spatial pre-planning.

**Barrier 3 — Fixed Spot Point Inflexibility**
Pre-defined GPS spot points cannot adapt to pile drift (monsoon-induced slumping),
surface deformation, or mixed-fleet pile size variation. A spot designed for a
Cat 793F (pile footprint 9m × 7m) creates a significant low spot when a Cat 789D
(8m × 6.2m pile) uses the same coordinates.

## 1.4 Dump Site Types Reference

| Dump Type | Geometry | Entry/Exit | Primary Risks |
|---|---|---|---|
| Internal Paddock / Backfill | Flat void, 3 pit walls | Single open face | Water pooling, slope creep, low spots |
| External Edge Dump | Linear cliff edge, drop below | Linear road | Truck over-edge, bench collapse |
| Valley Fill | Funnel, narrows at base | Single road = in AND out | Deadlock at choke, mass slide, terrace failure |
| Heaped Fill | Radial mound on flat ground | Open all sides | Boundary violation, isolated sections |
| Sidehill Fill | Slope-following, one open face | Road along slope | Toe failure, lateral spreading |
| ROM Stockpile | Organized windrows for crusher | Multiple access lanes | Grade contamination, reclaim access blocked |

## 1.5 Material Properties — Pile Behavior Reference

| Material | Bulk density dry (t/m³) | Bulk density wet (t/m³) | Repose angle dry | Repose angle wet | Notes |
|---|---|---|---|---|---|
| Coal overburden | 1.35–1.55 | 1.65–1.85 | 35–40° | 22–28° | Slumps significantly when wet |
| Iron ore (hematite) | 2.4–2.8 | 2.6–3.0 | 38–45° | 32–38° | Dense, tall piles, high LiDAR reflectivity |
| Limestone | 1.5–1.8 | 1.7–1.95 | 35–42° | 28–35° | Moderate spread, angular fragments |
| Bauxite | 1.2–1.5 | 1.4–1.7 | 30–38° | 24–30° | Very sticky/spreadable when wet |
| Copper overburden | 1.6–2.0 | 1.8–2.2 | 36–42° | 30–36° | Clay bands — temperature-sensitive |
| Mineral sand tailings | 1.35–1.55 | 1.7–1.9 | 28–35° | 20–28° | Wind-mobile at 8+ m/s |

---

# CHAPTER 2 — AHS FEASIBILITY GROUND RULES

## 2.1 AHS-Compatible Truck Fleet (Only These Trucks Are In Scope)

Verified against Cat MineStar Command for hauling documentation:

| Model | Payload (t) | Width (m) | Length (m) | Turning radius (m) | Pile footprint (m) | AHS status |
|---|---|---|---|---|---|---|
| **Cat 777G** | 100 | 7.4 | 11.7 | 12.8 | 5.5 × 4.5 | ✅ Proven — Luck Stone quarry 2024 |
| **Cat 785** | 139 | 8.2 | 12.8 | 14.2 | 7.0 × 5.5 | ✅ Being deployed (ioneer Rhyolite Ridge) |
| **Cat 789D** | 181 | 8.8 | 13.5 | 15.8 | 8.0 × 6.2 | ✅ Fully commercial |
| **Cat 793F** | 227 | 9.3 | 15.5 | 17.5 | 9.0 × 7.0 | ✅ Fully commercial — primary fleet |
| **Cat 797F** | 363 | 9.8 | 15.1 | 18.5 | 11.0 × 8.5 | ✅ Fully commercial |
| **Cat 794 AC** | 290 | 9.5 | 15.0 | 17.8 | 10.0 × 7.8 | ✅ Commercial electric drive |

**Permanently removed and why:**
- Cat 770G, Cat 772G — below minimum AHS-capable class, no Command for hauling kit
- Dragline spoil rehandling — no defined polygon, 3D terrain incompatible with AHS
- Uranium containment dump — requires separate specialist system, different safety certification
- In-pit crusher dump — fixed-point delivery, not a spatial packing problem

## 2.2 AHS Site Infrastructure Requirements

Every dump site must have ALL of the following before AHS can operate:

| Requirement | Purpose | Failure mode without it |
|---|---|---|
| RTK GPS base station within 15km | ±2cm truck positioning | Falls to S7 degraded mode |
| Wireless LAN / LTE full zone coverage | Spot assignment + state sharing | No coordination, zone stops |
| Geofenced AHS exclusion zone | Separate autonomous from manned | Regulatory non-compliance |
| A-Stop devices (every person entering zone) | Immediate all-truck halt on demand | Safety system incomplete |
| Physical zone entry barriers | Prevent unauthorized vehicle/person entry | Undetected intrusion |
| Dump polygon GeoJSON loaded into system | Boundary enforcement | No valid spot validation |
| Dual-path communications (WiFi + LTE) | Communication redundancy | Single outage halts entire zone |

---

# CHAPTER 3 — THE ARCHITECTURE DECISION

## 3.1 The Wrong Idea — ML for Strategy Selection

**What was originally proposed:** Feed scenarios into an ML model to select the
optimal truck config and packing approach.

**Why this is wrong — three reasons:**

**Reason 1 — No training data exists.**
An ML classifier needs thousands of labeled examples: (site conditions → correct
strategy). These do not exist in any mining dataset. The training set would have
to be synthetically generated from rules you define yourself — meaning the model
learns your own rules back at you with zero added intelligence, at massive added
complexity.

**Reason 2 — Black box is unacceptable in mining safety.**
Caterpillar, DGMS (India), and any mine operator will ask: "Why did the system
choose this dump spot?" An ML model cannot answer that. A decision tree can —
every branch is auditable, explainable, and challengeable by a mine engineer.
In safety-critical autonomous systems, explainability is non-negotiable.

**Reason 3 — The decision is not complex enough to warrant ML.**
The inputs are structured (slope angle, fleet type, polygon shape, rainfall).
The rules are known (regulatory slope limits, fleet homogeneity, choke geometry).
The output space is small (7 strategies). This is exactly the class of problem
where rule-based systems outperform ML — deterministic, fast, and auditable.

## 3.2 Where ML Actually Belongs

ML belongs in exactly one layer: **the perception system**. Specifically,
semantic segmentation of the LiDAR/camera sensor feed — classifying every
point in the truck's sensor field into actionable surface classes:

| Class ID | Label | Definition | Truck behavior |
|---|---|---|---|
| 0 | `EXISTING_PILE` | Previously dumped material, dry/stable | Approach to within 3.03m |
| 1 | `WET_PILE` | Previously dumped material, saturated | Increased buffer (4.5m) |
| 2 | `HARD_OBSTACLE` | Rock, berm, vehicle, structure | Full stop, do not approach |
| 3 | `SOFT_GROUND` | Unconsolidated, wet, deformed surface | No driving, no dumping |
| 4 | `DUMP_BOUNDARY` | Legal polygon edge | Stay fully inside |
| 5 | `SAFE_ZONE` | Designated waiting area | Park here if Waiter in S5 |
| 6 | `LOW_SPOT` | Topographic depression below design grade | Priority fill target |
| 7 | `HAUL_ROAD` | Active truck travel lane | Clear quickly after dump |

**The ML model lives in the perception layer.
The DSDE (decision tree) lives in the planning layer.
They are separate systems that communicate via the surface state map.**

## 3.3 The Correct Architecture — Three Layers

```
┌─────────────────────────────────────────────────────────────────┐
│  LAYER 3 — RESEARCH PAPER (Caterpillar Submission)              │
│                                                                 │
│  Argument: the 7.38m → 3.03m gap cannot be closed by any       │
│  single strategy. It requires a context-aware switching system  │
│  (DSDE) built on a two-layer communication architecture         │
│  (Server↔Client + P2P V2V). Proved by running 8 scenarios      │
│  and showing density trend charts improving in real time.       │
└──────────────────────────────┬──────────────────────────────────┘
                               │
┌──────────────────────────────▼──────────────────────────────────┐
│  LAYER 2 — COMMUNICATION SYSTEM (New Core Contribution)         │
│                                                                 │
│  Channel A: Server ↔ Client (Fleet Manager)                     │
│  FastAPI Python backend runs DSDE, assigns spots via MQTT.      │
│  Trucks subscribe to their topic, execute only when assigned.   │
│                                                                 │
│  Channel B: Truck ↔ Truck P2P (V2V)                            │
│  WebSocket direct channel between truck agents.                 │
│  Used for choke point negotiation (Scenario 3 — valley fill).  │
│  Server watches but does not intervene in P2P negotiation.      │
└──────────────────────────────┬──────────────────────────────────┘
                               │
┌──────────────────────────────▼──────────────────────────────────┐
│  LAYER 1 — SIMULATION (Existing site at optimaldumping.onrender)│
│                                                                 │
│  Enhanced: fix spacing to 3.03m, fix collision avoidance,       │
│  make every truck movement a reaction to a real MQTT message.  │
│                                                                 │
│  The simulation is the VISUALIZER — not the main topic.         │
│  It is the window into the communication system.                │
└─────────────────────────────────────────────────────────────────┘
```

---

# CHAPTER 4 — THE DUMP STRATEGY DECISION ENGINE (DSDE)

## 4.1 What the DSDE Is

The DSDE is a **real-time, rule-based decision system** — explicitly NOT an ML model.

- Monitors 30+ site condition inputs every 30 seconds
- Evaluates them in strict priority order (safety always first)
- Selects the correct packing strategy from a library of 7
- Switches strategies mid-shift with a 60-second handover protocol when conditions change
- Logs every decision with a human-readable reason string for regulatory audit

## 4.2 The 7 Strategies

| ID | Name | When Used | Core Mechanism |
|---|---|---|---|
| **S1** | Pre-Computed Grid | Homogeneous fleet, regular polygon, <80% fill, stable surface | Server pre-computes full ordered spot list; trucks follow assignments |
| **S2** | Pre-Computed Polygon-Aware | Homogeneous fleet, irregular/non-convex polygon | S1 + hexagonal staggered grid fitted to polygon shape |
| **S3** | Real-Time Adaptive | Mixed fleet, OR regular polygon ≥80% fill | Each truck scans on arrival, computes own spot, broadcasts intent |
| **S4** | Real-Time Polygon-Constrained | Mixed fleet, irregular polygon | S3 + hard polygon boundary enforcement + corner micro-spot algorithm |
| **S5** | Peer-to-Peer Sequential | Any fleet, choke point present | Trucks negotiate via V2V; Dumper/Waiter roles; safe zone protocol |
| **S6** | Safety-Priority Modifier | Added to S1–S5 when safety flags active | All spots validated against slope, bearing capacity, wet ground before assignment |
| **S7** | Degraded-Mode | Forced when GPS/LiDAR/V2V fails | Pre-loaded fallback spots, sequential only, reduced speed, radar-primary |

## 4.3 DSDE Input Variables — All 30+

**Group A — Fleet**

| Variable | Source | Type | Notes |
|---|---|---|---|
| `truck_model` | Truck onboard ID | Categorical: 777/785/789/793/797/794AC | Determines turning radius, pile footprint |
| `payload_tonnes` | Load cell | Continuous | Used for pile volume prediction |
| `fleet_homogeneity` | Fleet registry | Enum: HOMOGENEOUS / MIXED | Key branch in decision tree |
| `trucks_active_in_zone` | Fleet manager | Integer | Affects P2P trigger |
| `queue_length` | Dispatch system | Integer | Throughput planning |
| `truck_turning_radius` | Model lookup table | Continuous (m) | Used in arc sweep computation |

**Group B — Site/Polygon**

| Variable | Source | Type | Notes |
|---|---|---|---|
| `dump_type` | Mine plan | Categorical | Determines which dump-type-specific rules apply |
| `polygon_fill_pct` | Surface scan | Continuous 0–100% | Triggers S1→S3 switch at 80% |
| `polygon_shape` | GeoJSON analysis | Enum: CONVEX / NON_CONVEX / IRREGULAR | Determines S1 vs S2, S3 vs S4 |
| `choke_point_present` | Topographic model | Boolean | Triggers S5 override |
| `choke_point_width_m` | LiDAR scan | Continuous | S5 trigger threshold = truck_width × 2 + 4m |
| `edge_dump_active` | Mine plan | Boolean | Forces S3 even for homogeneous fleet |
| `available_entry_exits` | Mine plan | Integer | Single entry/exit = higher deadlock risk |

**Group C — Surface/Terrain**

| Variable | Source | Type | Notes |
|---|---|---|---|
| `terrain_slope_max_deg` | LiDAR + GPS | Continuous | >25° triggers S6 |
| `soft_ground_pct` | Thermal + LiDAR fusion | Continuous 0–100% | >30% triggers S6 |
| `pile_drift_detected` | Scan-to-model diff | Boolean | Flag: surface map needs update |
| `low_spots_count` | Surface diff model | Integer | S6 sets low_spot_priority = HIGH |
| `avg_pile_height_m` | LiDAR | Continuous | Used in slope calculation |

**Group D — Material**

| Variable | Source | Type | Notes |
|---|---|---|---|
| `material_type` | Mine plan / dispatch | Categorical | Determines bulk density and repose angle |
| `material_moisture_pct` | Sensor / weather proxy | Continuous | >15% triggers S6 |
| `material_bulk_density` | Lab / lookup table | Continuous (t/m³) | Pile mass and footprint calculation |
| `material_angle_of_repose` | Lookup table | Continuous (degrees) | Slope compliance calculation |

**Group E — Environment**

| Variable | Source | Type | Notes |
|---|---|---|---|
| `rainfall_intensity_mmhr` | Weather station | Continuous | >20mm/hr triggers S6 |
| `wind_speed_ms` | Weather station | Continuous | >8 m/s + edge dump adds wind scatter buffer |
| `wind_direction_deg` | Weather station | Continuous | Determines downwind boundary setback |
| `visibility_m` | Camera + dust sensor | Continuous | <200m + night triggers S6 night modifier |
| `temperature_celsius` | Weather station | Continuous | Affects clay-band pile spread prediction |
| `season` | Calendar | Enum: MONSOON / DRY / WINTER | Context for moisture and rain predictions |

**Group F — System Health**

| Variable | Source | Type | Notes |
|---|---|---|---|
| `v2v_link_quality` | Network monitor | Enum: GOOD / DEGRADED / LOST | LOST + trucks > 1 → force S7 |
| `gps_accuracy_cm` | GPS receiver | Continuous | >50cm → force S7 |
| `lidar_operational` | Sensor health monitor | Boolean | FALSE → force S7 |
| `fleet_mgr_online` | Network health | Boolean | FALSE → trucks operate on last assignment |
| `protocol_version` | System config | String | For backward compatibility logging |

## 4.4 The Decision Tree — Complete and Explicit

```
ROOT: Select dump strategy for the next truck assignment
│
├── ══════════════ SAFETY OVERRIDE ══════════════
│   Runs FIRST before any other check.
│   Runs every 30 seconds on a timer AND on every input variable change.
│   Any of the following immediately override all other logic:
│
│   ├── IF gps_accuracy_cm > 50
│   │   → FORCE S7. reason = "GPS_DEGRADED". EXIT TREE.
│   │
│   ├── IF lidar_operational = FALSE
│   │   → FORCE S7. reason = "LIDAR_FAULT". EXIT TREE.
│   │
│   ├── IF v2v_link_quality = LOST AND trucks_active_in_zone > 1
│   │   → FORCE S7. reason = "V2V_LOST_MULTI_TRUCK". EXIT TREE.
│   │
│   ├── IF terrain_slope_max_deg > 25°
│   │   → ADD S6 modifier. reason += "SLOPE_WARNING".
│   │
│   ├── IF soft_ground_pct > 30%
│   │   → ADD S6 modifier. reason += "SOFT_GROUND".
│   │
│   └── IF rainfall_intensity_mmhr > 20
│       → ADD S6 modifier. reason += "HEAVY_RAIN".
│
├── ══════════════ CHOKE POINT OVERRIDE ══════════════
│   If a choke point is detected, P2P is mandatory.
│   This overrides the entire fleet/geometry matrix.
│
│   ├── IF choke_point_present = TRUE
│   │   AND choke_point_width_m < (truck_width × 2 + 4.0)
│   │   → SELECT S5 (P2P Sequential).
│   │   → APPLY any S6 modifier already set above.
│   │   → reason += "CHOKE_POINT_DETECTED width={choke_width}m threshold={threshold}m"
│   │   → EXIT TREE.
│   │
│   └── ELSE → continue to fleet/geometry matrix
│
├── ══════════════ FLEET × GEOMETRY MATRIX ══════════════
│
│   ├── IF fleet_homogeneity = HOMOGENEOUS
│   │   │
│   │   ├── IF polygon_shape IN [CONVEX, RECTANGULAR]
│   │   │   AND polygon_fill_pct < 80%
│   │   │   AND terrain_slope_max_deg < 15°
│   │   │   → SELECT S1. reason = "HOMO_REGULAR_POLYGON_LOW_FILL"
│   │   │
│   │   ├── IF polygon_shape IN [NON_CONVEX, IRREGULAR]
│   │   │   → SELECT S2. reason = "HOMO_IRREGULAR_POLYGON"
│   │   │
│   │   ├── IF polygon_fill_pct >= 80%
│   │   │   → SELECT S3. reason = "HOMO_HIGH_FILL_PCT"
│   │   │   (pre-computed spots no longer valid as polygon becomes congested)
│   │   │
│   │   └── IF edge_dump_active = TRUE
│   │       → SELECT S3. reason = "HOMO_EDGE_DUMP"
│   │       (edge state changes after every dump; pre-computed spots invalid)
│   │
│   └── IF fleet_homogeneity = MIXED
│       │
│       ├── IF polygon_shape IN [CONVEX, RECTANGULAR]
│       │   AND polygon_fill_pct < 70%
│       │   → SELECT S3. reason = "MIXED_REGULAR_POLYGON"
│       │
│       ├── IF polygon_shape IN [NON_CONVEX, IRREGULAR]
│       │   → SELECT S4. reason = "MIXED_IRREGULAR_POLYGON"
│       │
│       ├── IF edge_dump_active = TRUE
│       │   → SELECT S3. reason = "MIXED_EDGE_DUMP"
│       │
│       └── IF polygon_fill_pct >= 80%
│           → SELECT S4. reason = "MIXED_HIGH_FILL_PCT"
│           (tight space + different truck sizes = hard boundary enforcement needed)
│
├── ══════════════ ENVIRONMENT MODIFIER PASS ══════════════
│   Applied AFTER strategy is selected. Modifies behavior, not strategy choice.
│
│   ├── IF material_moisture_pct > 15% OR rainfall_intensity_mmhr > 5
│   │   → ADD S6 modifier (if not already active)
│   │   → SET low_spot_priority = HIGH
│   │   → reason += "WET_MATERIAL_LOW_SPOT_PRIORITY"
│   │
│   ├── IF wind_speed_ms > 8 AND edge_dump_active = TRUE
│   │   → SET wind_scatter_buffer_m = wind_speed_ms × material_fineness_factor × 2.5
│   │   → reason += "WIND_SCATTER_BUFFER={buffer}m"
│   │
│   └── IF temperature_celsius < 8 AND material_type = "COPPER_OVERBURDEN"
│       → SET clay_freeze_modifier = TRUE
│       → Reduce expected pile footprint by 15% (clay bands more confined when cold)
│       → reason += "CLAY_FREEZE_MODIFIER"
│
└── ══════════════ OUTPUT ══════════════
    → {
        strategies: List[StrategyID],   // e.g. [S3, S6]
        s6_active: bool,
        s7_forced: bool,
        wind_scatter_buffer_m: float,   // 0.0 if not applicable
        low_spot_priority: bool,
        clay_freeze_modifier: bool,
        reason_string: str,             // human-readable, one sentence
        re_evaluate_in_seconds: 30      // always 30 unless S7 (then 10)
      }
```

## 4.5 Strategy Switching Protocol

**Trigger conditions** (immediately re-evaluate on any of these):
- Any safety override variable crosses its threshold
- `polygon_fill_pct` crosses 70% or 80%
- `rainfall_intensity_mmhr` changes by >10mm/hr
- Fleet composition changes (new truck model enters zone)
- `v2v_link_quality` degrades GOOD → DEGRADED or DEGRADED → LOST
- `gps_accuracy_cm` exceeds 50cm

**Switch procedure:**
1. DSDE issues 60-second warning to all active trucks: `STRATEGY_SWITCH_PENDING`
2. All in-progress dumps complete under the current strategy
3. No new spot assignments during the 60-second window
4. New strategy activates; all trucks receive updated configuration
5. Switch event logged: `{timestamp, old_strategy, new_strategy, reason_string}`

**Example switch (Scenario 1 — Monsoon):**
- T=0: Shift starts dry. DSDE output: S1. reason = "HOMO_REGULAR_POLYGON_LOW_FILL"
- T=3600s: Rain begins at 12mm/hr. DSDE adds S6. Reason += "WET_MATERIAL"
- T=5400s: Rain hits 25mm/hr. soft_ground_pct rises to 35%. DSDE switches S1→S3+S6.
  60-second warning issued. reason = "HEAVY_RAIN + SOFT_GROUND + HOMO_HIGH_FILL_PCT"
- T=7200s: Rain stops. soft_ground_pct drops to 18%. DSDE output: S3 (S6 removed)

---

# CHAPTER 5 — THE COMMUNICATION SYSTEM

## 5.1 Architecture Diagram

```
┌──────────────────────────────────────────────────────────────────┐
│                     FASTAPI BACKEND SERVER                        │
│                                                                  │
│  ┌──────────────┐  ┌──────────────────┐  ┌───────────────────┐  │
│  │     DSDE     │  │  Fleet Manager   │  │  Surface State    │  │
│  │  Decision    │◄►│  Spot Assigner   │◄►│  Map (NumPy 2D)  │  │
│  │  Engine      │  │                  │  │  0.25m resolution │  │
│  └──────┬───────┘  └────────┬─────────┘  └───────────────────┘  │
│         │                   │                                    │
└─────────┼───────────────────┼────────────────────────────────────┘
          │                   │
    ┌─────▼───────────────────▼────────────────────────────────┐
    │                   MQTT BROKER                             │
    │              (Mosquitto / HiveMQ Cloud)                   │
    │                                                          │
    │  Topic structure:                                        │
    │  mines/{mine_id}/trucks/{truck_id}/state                 │
    │  mines/{mine_id}/trucks/{truck_id}/assignment            │
    │  mines/{mine_id}/dump/{zone_id}/surface/update           │
    │  mines/{mine_id}/dump/{zone_id}/intent                   │
    │  mines/{mine_id}/alerts                                  │
    │  mines/{mine_id}/dsde/strategy                           │
    └───────────────────────┬──────────────────────────────────┘
                            │
              ┌─────────────┴─────────────┐
              │                           │
    ┌─────────▼──────────┐     ┌──────────▼─────────┐
    │   TRUCK-01          │     │   TRUCK-02          │
    │   (Browser Agent)   │◄───►│   (Browser Agent)   │
    │   Subscribes MQTT   │P2P  │   Subscribes MQTT   │
    │   WebSocket         │WS   │   WebSocket         │
    └─────────────────────┘     └────────────────────┘
              ↕ WebSocket /ws/p2p/{truck_id}
              (Direct truck-to-truck V2V for choke negotiation)
```

## 5.2 Channel A — Server ↔ Client (MQTT)

### Message: Truck State (truck → server, 500ms interval)
```json
{
  "msg_type": "TRUCK_STATE",
  "protocol_version": "1.0",
  "truck_id": "TRK-01",
  "model": "Cat793F",
  "position": { "x": 45.2, "y": 32.7 },
  "heading_deg": 215.3,
  "speed_ms": 2.4,
  "state": "APPROACHING",
  "assigned_spot": { "x": 52.0, "y": 28.0, "bearing_deg": 215.0 },
  "payload_tonnes": 221.4,
  "dumps_completed": 3,
  "timestamp_utc": "2025-08-14T09:32:11.421Z"
}
```

### Message: Spot Assignment (server → truck)
```json
{
  "msg_type": "SPOT_ASSIGNMENT",
  "protocol_version": "1.0",
  "truck_id": "TRK-01",
  "spot": {
    "x": 52.0,
    "y": 28.0,
    "bearing_deg": 215.0
  },
  "approach_path": [
    { "x": 38.0, "y": 40.0 },
    { "x": 45.0, "y": 35.0 },
    { "x": 52.0, "y": 28.0 }
  ],
  "strategy_id": "S3",
  "s6_active": true,
  "expected_pile_footprint": {
    "length_m": 9.1,
    "width_m": 7.0
  },
  "timestamp_utc": "2025-08-14T09:32:08.003Z"
}
```

### Message: Surface Update (truck → server, after each dump)
```json
{
  "msg_type": "SURFACE_UPDATE",
  "protocol_version": "1.0",
  "event": "DUMP_COMPLETE",
  "truck_id": "TRK-01",
  "dump_location": { "x": 52.0, "y": 28.0 },
  "pile": {
    "centroid": { "x": 52.1, "y": 28.2 },
    "height_m": 2.1,
    "footprint_length_m": 8.9,
    "footprint_width_m": 6.8,
    "surface_class": "EXISTING_PILE"
  },
  "timestamp_utc": "2025-08-14T09:34:58.003Z"
}
```

### Message: DSDE Strategy Update (server → all trucks, on strategy change)
```json
{
  "msg_type": "STRATEGY_UPDATE",
  "protocol_version": "1.0",
  "zone_id": "ZONE-A",
  "new_strategies": ["S3", "S6"],
  "s7_forced": false,
  "reason_string": "HEAVY_RAIN rainfall=25mmhr SOFT_GROUND=38%",
  "switch_in_seconds": 60,
  "timestamp_utc": "2025-08-14T10:30:00.000Z"
}
```

### Message: Alert (server → all, on safety events)
```json
{
  "msg_type": "ALERT",
  "protocol_version": "1.0",
  "alert_type": "DSDE_S7_ACTIVATED",
  "severity": "CRITICAL",
  "reason": "GPS_DEGRADED gps_accuracy=85cm LIDAR_FAULT",
  "active_trucks": 6,
  "trucks_in_zone": 2,
  "trucks_at_holding": 4,
  "throughput_loss_pct": 72,
  "recommended_action": "Check RTK base station. Verify LTE repeater north array.",
  "timestamp_utc": "2025-08-14T14:15:00.000Z"
}
```

## 5.3 Channel B — Truck ↔ Truck P2P (WebSocket V2V)

Used exclusively in Scenario 3 (valley fill) and any other choke point scenario.
The server does NOT relay these messages — they are direct truck-to-truck.

### Phase 1 — Choke Approach Notice
```json
{
  "msg_type": "CHOKE_APPROACH_NOTICE",
  "from_truck": "TRK-01",
  "choke_id": "VALLEY-A-CHOKE-EAST",
  "eta_seconds": 47,
  "intended_terrace": 3,
  "payload_tonnes": 221.4,
  "truck_width_m": 9.3,
  "timestamp_utc": "2025-08-14T09:31:00.000Z"
}
```

### Phase 2 — State Response
```json
{
  "msg_type": "CHOKE_STATE_RESPONSE",
  "from_truck": "TRK-02",
  "p2p_state": "APPROACHING",
  "eta_seconds": 65,
  "position": { "x": 120.0, "y": 88.0 },
  "safe_zone": null,
  "timestamp_utc": "2025-08-14T09:31:01.000Z"
}
```

### Phase 3 — Priority Negotiation Result
Priority order: (1) already inside choke, (2) lower ETA, (3) higher payload, (4) lower truck_id
```json
{
  "msg_type": "PRIORITY_RESULT",
  "from_truck": "TRK-01",
  "to_truck": "TRK-02",
  "dumper": "TRK-01",
  "waiter": "TRK-02",
  "priority_reason": "LOWER_ETA TRK-01=47s TRK-02=65s",
  "timestamp_utc": "2025-08-14T09:31:02.000Z"
}
```

### Phase 4 — Safe Zone Declaration (Waiter → Dumper)
```json
{
  "msg_type": "SAFE_ZONE_DECLARED",
  "from_truck": "TRK-02",
  "safe_zone": {
    "center": { "x": 135.0, "y": 95.0 },
    "width_m": 15.0,
    "length_m": 22.0,
    "bearing_capacity_kpa": 92.0,
    "slope_deg": 3.2,
    "blocks_exit_path": false
  },
  "truck_is_stationary": false,
  "eta_to_safe_zone_seconds": 18,
  "timestamp_utc": "2025-08-14T09:31:05.000Z"
}
```

### Phase 5 — Safe Zone Confirmed (Waiter → Dumper, after arriving)
```json
{
  "msg_type": "SAFE_ZONE_CONFIRMED",
  "from_truck": "TRK-02",
  "to_truck": "TRK-01",
  "truck_is_stationary": true,
  "safe_zone_position": { "x": 135.0, "y": 95.0 },
  "dumper_may_proceed": true,
  "timestamp_utc": "2025-08-14T09:31:23.000Z"
}
```

### Phase 6 — Dump Complete + Exit Intent (Dumper → Waiter)
```json
{
  "msg_type": "DUMP_COMPLETE_EXIT_INTENT",
  "from_truck": "TRK-01",
  "exit_path": [
    { "x": 52.0, "y": 28.0 },
    { "x": 42.0, "y": 35.0 },
    { "x": 30.0, "y": 50.0 }
  ],
  "timestamp_utc": "2025-08-14T09:33:45.000Z"
}
```

### Phase 7 — Exit Path Clear (Waiter → Dumper)
```json
{
  "msg_type": "EXIT_PATH_CLEAR",
  "from_truck": "TRK-02",
  "to_truck": "TRK-01",
  "dumper_may_exit": true,
  "timestamp_utc": "2025-08-14T09:33:46.000Z"
}
```

### Phase 8 — Communication Failure Handling
If no P2P message is received for >10 seconds from an expected peer:
```json
{
  "msg_type": "COMM_LOST",
  "from_truck": "TRK-01",
  "last_known_peer_state": "APPROACHING",
  "my_state": "DUMPING",
  "action_taken": "COMPLETE_DUMP_THEN_STOP",
  "timestamp_utc": "2025-08-14T09:32:00.000Z"
}
```

**Failure state machine:**
- State = DUMPING when comm lost → complete dump, then safe-stop, broadcast COMM_LOST
- State = APPROACHING → immediate safe-stop, broadcast COMM_LOST
- State = WAITING → remain stationary, broadcast COMM_LOST
- Recovery: all three peers must re-establish V2V AND share full state before resuming

---

# CHAPTER 6 — THE EXISTING PROTOTYPE — WHAT'S WRONG AND HOW TO FIX IT

## 6.1 Current State (as observed at optimaldumping.onrender.com)

The site has:
- Draw Yard tool — user draws a polygon and trucks begin filling it
- A* pathfinding for truck routing
- Unit cell matrix approach for spot selection (fills last column to front)
- Live Metrics panel (Total Dumps, Peak Dist, Density %, Active trucks)
- Fleet Configuration panel (Large trucks ×4, Small trucks ×4, total 8)
- Density Trend chart
- 2D / 3D / Heatmap view toggle
- Speed slider (1x to faster)

## 6.2 What's Broken and Why

| Issue | Root Cause | Correct Fix |
|---|---|---|
| Spacing too high (~7m+) | Unit cell size equals truck width + arbitrary buffer, not 3.03m center-to-center | Change spacing to pile-centroid-relative 3.03m |
| Spot selection not optimal | Grid walk — places spot at next available cell in row | Scan existing piles, find nearest valid gap, validate arc and footprint |
| Collision avoidance broken | Point-to-point distance check; doesn't account for reverse arc sweep | Swept-area polygon check during reverse maneuver |
| Looks like a cheap simulation | Trucks move on JS timers independently; no coordination visible | Every truck movement must be a reaction to a real MQTT message |
| No strategy switching | Single fixed algorithm regardless of conditions | Integrate DSDE; show active strategy on UI |
| No communication visible | No message log | Add live message log panel showing MQTT flows |
| No scenario loading | Manual polygon drawing only | Add scenario selector preloading all 8 scenarios |
| No P2P channel | All coordination through JS simulation | Add WebSocket P2P channel for Scenario 3 |

## 6.3 Fix 1 — Spacing Correction

**Current (wrong):**
```javascript
// Unit cell offset is truck width or some fixed arbitrary buffer
nextSpotX = prevSpotX + truckWidth + safetyBuffer; // results in 7+ meters
```

**Correct:**
```javascript
const TARGET_CENTER_SPACING_M = 3.03;

function computeNextSpot(prevPileCentroid, dumpDirection, polygon, existingPiles, truckModel) {
  // Next spot center is exactly 3.03m from previous pile centroid
  const candidateCenter = {
    x: prevPileCentroid.x + TARGET_CENTER_SPACING_M * Math.cos(dumpDirection),
    y: prevPileCentroid.y + TARGET_CENTER_SPACING_M * Math.sin(dumpDirection)
  };

  // Validate candidate — all must pass
  const pileFootprint = predictPileFootprint(truckModel);
  const reverseArc = computeReverseSweep(approachPoint, candidateCenter, truckModel);

  if (!isInsidePolygon(candidateCenter, polygon.inset)) return null; // rear axle check
  if (!footprintInsidePolygon(candidateCenter, pileFootprint, polygon)) return null;
  if (!arcInsidePolygon(reverseArc, polygon)) return null;
  if (overlapsExistingPile(candidateCenter, pileFootprint, existingPiles)) return null;
  if (causesIsolation(candidateCenter, polygon, existingPiles)) return null;

  return candidateCenter; // valid
}
```

## 6.4 Fix 2 — Swept-Area Collision Avoidance

**Current (wrong):** Circular distance check between truck centers.

**Correct:** Compute the swept polygon of the truck's full reverse arc:

```javascript
function computeReverseSweep(startPos, startHeading, targetSpot, truckModel) {
  const arcPoints = interpolateArc(
    startPos, startHeading, targetSpot, truckModel.turning_radius_m, steps=20
  );

  const sweepPolygon = [];
  const halfWidth = truckModel.width_m / 2 + 0.5; // 0.5m clearance

  for (let i = 0; i <= arcPoints.length; i++) {
    const pt = arcPoints[i];
    const heading = arcPoints[i].heading;
    // Push left and right edges of truck at this arc position
    sweepPolygon.push(offsetPoint(pt, heading + 90, halfWidth));
    sweepPolygon.unshift(offsetPoint(pt, heading - 90, halfWidth));
  }
  return sweepPolygon; // convex polygon
}

// Before assigning any truck to a spot:
function checkConflict(myTruck, mySpot, otherTrucks) {
  const mySweep = computeReverseSweep(myTruck.pos, myTruck.heading, mySpot, myTruck.model);
  for (const other of otherTrucks) {
    if (other.assignedSpot) {
      const theirSweep = computeReverseSweep(other.pos, other.heading, other.assignedSpot, other.model);
      if (polygonsIntersect(mySweep, theirSweep)) {
        return { conflict: true, with: other.id };
      }
    }
  }
  return { conflict: false };
}
```

## 6.5 Fix 3 — MQTT-Driven Truck Movement

**Current (wrong):** Trucks are JS objects that update position on `setInterval`.

**Correct:** Trucks subscribe to their MQTT assignment topic and move ONLY on receiving
an assignment message:

```javascript
// mqtt.js import: import mqtt from 'mqtt';
const client = mqtt.connect('wss://broker.hivemq.com:8884/mqtt');

// Each truck subscribes to its own assignment channel
client.subscribe(`mines/${mineId}/trucks/${truck.id}/assignment`);
client.subscribe(`mines/${mineId}/dsde/strategy`);
client.subscribe(`mines/${mineId}/alerts`);

client.on('message', (topic, payload) => {
  const msg = JSON.parse(payload.toString());

  if (topic.includes('/assignment')) {
    // Move only when server assigns
    truck.assignedSpot = msg.spot;
    truck.approachPath = msg.approach_path;
    truck.state = 'APPROACHING';
    animateTruckAlongPath(truck, msg.approach_path);
  }

  if (topic.includes('/strategy')) {
    // Update UI strategy display
    updateStrategyPanel(msg);
    addToMessageLog({ type: 'STRATEGY', ...msg });
  }

  if (topic.includes('/alerts')) {
    // Show alert banner
    showAlertBanner(msg);
    addToMessageLog({ type: 'ALERT', color: 'red', ...msg });
  }
});

// Truck publishes its own state every 500ms
const statePublishInterval = setInterval(() => {
  client.publish(
    `mines/${mineId}/trucks/${truck.id}/state`,
    JSON.stringify({
      truck_id: truck.id,
      model: truck.model,
      position: truck.position,
      heading_deg: truck.heading,
      speed_ms: truck.speed,
      state: truck.state,
      payload_tonnes: truck.payload,
      timestamp_utc: new Date().toISOString()
    })
  );
}, 500);
```

## 6.6 Fix 4 — P2P WebSocket for Choke Scenarios

```javascript
class P2PChannel {
  constructor(truckId, backendUrl) {
    this.truckId = truckId;
    this.ws = new WebSocket(`${backendUrl}/ws/p2p/${truckId}`);
    this.peers = new Map(); // truckId → last known state
    this.state = 'IDLE'; // IDLE | APPROACHING | NEGOTIATING | WAITING | DUMPING | EXITING
    this.ws.onmessage = (event) => this.handleP2PMessage(JSON.parse(event.data));
  }

  sendChokeApproachNotice(chokeId, eta, terrace, payload) {
    this.broadcast({
      msg_type: 'CHOKE_APPROACH_NOTICE',
      from_truck: this.truckId,
      choke_id: chokeId,
      eta_seconds: eta,
      intended_terrace: terrace,
      payload_tonnes: payload,
      timestamp_utc: new Date().toISOString()
    });
    this.state = 'NEGOTIATING';
  }

  handleP2PMessage(msg) {
    // Update message log UI
    addToMessageLog({ type: 'P2P', color: 'orange', ...msg });
    this.peers.set(msg.from_truck, msg);

    switch (msg.msg_type) {
      case 'CHOKE_APPROACH_NOTICE': this.onPeerApproaching(msg); break;
      case 'PRIORITY_RESULT': this.onPriorityAssigned(msg); break;
      case 'SAFE_ZONE_CONFIRMED': this.onSafeZoneConfirmed(msg); break;
      case 'DUMP_COMPLETE_EXIT_INTENT': this.onDumperExiting(msg); break;
      case 'COMM_LOST': this.onCommLost(msg); break;
    }
  }

  broadcast(msg) {
    this.ws.send(JSON.stringify(msg));
    addToMessageLog({ type: 'P2P_SENT', color: 'orange', ...msg });
  }

  onCommLost(msg) {
    // Communication failure — safe stop
    if (this.state === 'APPROACHING') {
      truck.safeStop('COMM_LOST from ' + msg.from_truck);
    }
    // If DUMPING: complete then stop (handled in dump completion callback)
  }
}
```

## 6.7 New UI Panels Required

**Panel 1 — DSDE Strategy Display** (replace or extend Live Metrics)
```
┌─────────────────────────────────────┐
│ ACTIVE STRATEGY                     │
│ S3 + S6                             │  ← gold/orange badge
│ Real-Time Adaptive + Safety-Priority│
│                                     │
│ Reason: HEAVY_RAIN=25mmhr           │
│         SOFT_GROUND=38%             │
│                                     │
│ Next re-eval: 24s ████████░░        │
│                                     │
│ ● S6 ACTIVE  ○ S7 NOT FORCED        │
└─────────────────────────────────────┘
```

**Panel 2 — Live Message Log** (new panel, scrollable)
```
┌─────────────────────────────────────────────────┐
│ LIVE MESSAGE LOG                       [Clear]   │
├─────────────────────────────────────────────────┤
│ 09:34:58 [SERVER→TRK-01] SPOT_ASSIGNMENT x=52 y=28
│ 09:34:45 [TRK-01→SERVER] DUMP_COMPLETE x=52 y=28
│ 09:33:46 [P2P TRK-02→TRK-01] EXIT_PATH_CLEAR
│ 09:33:45 [P2P TRK-01→TRK-02] DUMP_COMPLETE_EXIT_INTENT
│ 09:32:11 [SERVER→ALL] STRATEGY_UPDATE S1→S3+S6
│ 09:31:23 [P2P TRK-02→TRK-01] SAFE_ZONE_CONFIRMED
│ ...                                              │
└─────────────────────────────────────────────────┘
Color coding:
  Blue  = server → truck (MQTT)
  Green = truck → server (MQTT)
  Orange= truck → truck (P2P WebSocket)
  Red   = alert / S7 activation
```

**Panel 3 — Density Trend (enhance existing)**
- Add two horizontal reference lines:
  - **7.38m** (red dashed) — current autonomous baseline — labeled "Current AHS Baseline"
  - **3.03m** (green dashed) — human baseline / project target — labeled "Human Target"
- Current average spacing plotted in yellow
- Shade area between current line and 3.03m target line in red (represents waste)
- X-axis = time or dump count
- Y-axis = spacing in meters

**Panel 4 — Scenario Selector** (new, top of UI or sidebar)
```
┌─────────────────────────────────────────────────┐
│ SCENARIO  [Monsoon Paddock — Gevra ▼] [Load]    │
├─────────────────────────────────────────────────┤
│ Mine: Gevra Mine, Korba, Chhattisgarh           │
│ Fleet: Cat 793F (×4) + Cat 789D (×4) — Mixed   │
│ Dump: Internal Paddock Backfill                 │
│ Challenge: Monsoon rain, pile drift, slope ≤28° │
│ Expected: S1 → S3+S6 (strategy switch at rain)  │
│                                                 │
│          [ ▶ Start Simulation ]                 │
└─────────────────────────────────────────────────┘
```

---

# CHAPTER 7 — THE 8 SCENARIOS (Complete, AHS-Verified)

## Scenario 1 — Monsoon Paddock Backfill

**Mine:** Gevra Mine / Dipka Mine, Korba, Chhattisgarh (Coal India Limited)
**Coordinates:** 22.14°N, 82.56°E
**Fleet:** Cat 793F (227t) × 4 + Cat 789D (181t) × 4 — mixed, both AHS-certified
**Dump type:** Internal Paddock (backfill into mined-out void)
**Material:** Coal overburden — shale, sandstone, coal fines
**Season:** Monsoon June–September, 900–1,400mm/season
**DSDE output:** S1 (start of shift, dry) → S3 + S6 (when rain begins)

**The problem in full:**
Bulk density rises 1.4 → 1.75 t/m³ when saturated. Angle of repose drops 38° → 24°.
The 7.38m spacing creates topographic low spots that pool water, further destabilising the surface.
Piles slump 0.5–1.2m from registered centroid after 48 hours of rain (pile drift).
MoEF&CC mandates slope ≤ 28° for coal overburden.
793F pile (9m × 7m) is the designed size. When 789D (8m × 6.2m pile) uses the same spot,
it leaves ~1m × 0.8m low spot on each edge — over 50 dumps, this creates a
drainage basin that pools water and progressively softens the surrounding dump surface.

**DSDE path:**
```
Safety: rainfall=25mmhr > 20 → ADD S6
Safety: soft_ground_pct=35% > 30% → ADD S6
Choke: FALSE
Fleet: MIXED → right branch
Polygon: RECTANGULAR, fill 42% < 70% → S3
Material: moisture=28% > 15% → ADD S6 + low_spot_priority=HIGH
OUTPUT: S3 + S6. reason="MIXED_REGULAR + HEAVY_RAIN + SOFT_GROUND + WET_MATERIAL"
```

**Key constraints:**
- Slope at proposed dump location ≤ 25° after dump (5° safety margin below 28° legal limit)
- `WET_LOW_SPOT` areas: fill priority 1 (water pooling prevention)
- Approach corridor bearing capacity ≥ 75–80 kPa (793F loaded = ~80 kPa)
- Pile centroid drift > 0.4m → surface map update before adjacent spot assignment

**Regulatory:** MoEF&CC dump slope ≤28°; DGMS safety berm width ≥ half truck height;
Mines Act 1952 drainage 1–2% cross-slope requirement

---

## Scenario 2 — Edge Dump, Mixed Fleet

**Mine:** Noamundi Iron Ore Mine, West Singhbhum, Jharkhand (Tata Steel)
**Coordinates:** 22.11°N, 85.50°E
**Fleet:** Cat 777G (100t) × 4 + Cat 789D (181t) × 4 — mixed, both AHS-certified
**Dump type:** External Edge Dump (over-the-side bench extension)
**Material:** Iron ore, hematite — bulk density 2.4–2.8 t/m³
**Terrain:** Bench edge, 15–30m drop, exposed plateau, wind 6–14 m/s
**DSDE output:** S3 + wind scatter modifier

**The problem:**
Fixed spots sized for 789D (pile 8m × 6.2m) leave 1.5–2.5m edge gaps when 777G
(pile 5.5m × 4.5m) uses the same spots. Over 50 dumps per shift → 75–125m of edge
capacity wasted. Iron ore's high LiDAR reflectivity causes sensor saturation at close
range → radar required as fallback. Wind at 12 m/s scatters fine ore particles up to
30–50m downwind from dump point.

**777G slotting — quantified proof:**
- 789D pile width: 8.0m → radius 4.0m from centre
- 777G pile width: 5.5m → radius 2.75m from centre
- 777G centre placed at: 789D_centre + 3.03m along edge
- 777G pile edge extends to: 3.03 + 2.75 = 5.78m from 789D centre
- 789D pile edge: 4.0m from its own centre
- **Edge-to-edge clearance: 5.78 − 4.0 = 1.78m ✅ — valid**

A second 789D at the same 3.03m spacing would require 4.0 + 4.0 = 8.0m edge-to-edge,
meaning its centre must be ≥8.0m away to avoid overlap — 777G achieves 3.03m that
a second 789D cannot.

**Wind scatter buffer formula:**
`buffer_m = wind_speed_ms × material_fineness_factor × 2.5`
At 12 m/s for iron ore (fineness factor 1.2): `12 × 1.2 × 2.5 = 36m` setback from
the downwind boundary. Dump spots within 36m of the downwind polygon edge are suspended
when wind exceeds 8 m/s from that direction.

**DSDE path:**
```
Safety: wind=12ms > 8 + edge_dump=TRUE → ADD wind_scatter_buffer=36m
Choke: FALSE
Fleet: MIXED + edge_dump=TRUE → S3
OUTPUT: S3 + wind modifier. reason="MIXED_EDGE_DUMP + WIND_SCATTER_BUFFER=36m"
```

**Regulatory:** DGMS vehicle separation; bench load capacity (50–80 kPa rated);
simultaneous approach prohibition within 15m of active dump position

---

## Scenario 3 — Zero-Harm Concurrent Valley Fill

**Mine:** Valley fill site, Odisha/Chhattisgarh hill belt
**Reference incident:** Lalmatia Coal Mine dump failure, 29 November 2016, Godda,
Jharkhand — 23 workers killed by mass dump collapse
**Coordinates:** ~20.5°N, 83.5°E
**Fleet:** Cat 793F (227t) × 4–6 — homogeneous, AHS-certified
**Dump type:** Valley Fill / Cross-Valley Fill
**Material:** Coal overburden, mixed waste rock
**Terrain:** Valley narrowing to 18–24m at base choke point, single entry/exit road
**DSDE output:** S5 forced (choke override)

**The problem:**
Cat 793F is 9.3m wide. Two side-by-side = 18.6m + 4m manoeuvring clearance = 22.6m minimum.
At 18m choke: physically impossible for two trucks simultaneously.
Single road in = single road out. A truck dumping in the valley blocks all other trucks'
exit route. Without P2P coordination, two trucks enter simultaneously → DEADLOCK →
45–90 minute manual recovery. Terrace compliance (building in ordered horizontal lifts)
must be enforced to prevent a repeat of Lalmatia.

**DSDE path:**
```
Choke: TRUE, width=20m < 22.6m threshold → SELECT S5, EXIT TREE
OUTPUT: S5. reason="CHOKE_POINT_DETECTED width=20m threshold=22.6m"
```

**P2P Protocol — 8 phases (see Chapter 5.3 for full message schemas):**
1. Choke detection → initiate P2P
2. Peer discovery (200m V2V range) → CHOKE_APPROACH_NOTICE
3. Priority negotiation → PRIORITY_RESULT (lower ETA = Dumper)
4. Waiter finds safe zone (width ≥13.3m, length ≥20.5m, capacity ≥85 kPa, slope ≤5°, not on Dumper exit path)
5. SAFE_ZONE_DECLARED → Waiter moves to safe zone
6. SAFE_ZONE_CONFIRMED → Dumper receives clearance, begins reverse
7. DUMP_COMPLETE_EXIT_INTENT + EXIT_PATH_CLEAR → Dumper exits, Waiter proceeds
8. Communication failure handling → all trucks safe-stop

**Terrace compliance:**
`if current_height + expected_pile_height > terrace_target_elevation + 0.5m →`
dump prohibited at this point, redirect to lowest area of same terrace

**Regulatory:** DGMS Lalmatia inquiry report; MoEF&CC valley fill reclamation standards;
DGMS General Regulation 141 (vehicle separation)

---

## Scenario 4 — Irregular Polygon Heaped Fill

**Mine:** Ariyalur Limestone Quarry, Tamil Nadu / Kutch Bauxite Quarry, Gujarat
**Coordinates:** TN: 11.14°N, 79.08°E / GJ: 22.5°N, 68.8°E
**Fleet:** Cat 777G (100t) × 4 — homogeneous, AHS-proven Luck Stone 2024
**Dump type:** Heaped Fill within irregular non-convex lease polygon
**Material:** Limestone (TN) or Bauxite (Gujarat)
**Terrain:** Flat quarry floor, irregular polygon with acute corners and concave sections
**DSDE output:** S2 (+ S6 if wet bauxite detected)

**The problem:**
Lease boundary follows historical land parcel lines — non-convex polygon with acute corners
(<60°), concave sections, and narrow "ear" protrusions. Standard rectangular grid leaves
corners unfilled. Any material dumped outside boundary = MMDR Act violation.
Wet bauxite (>20% moisture): pile footprint exceeds prediction by 30–40% — risk of
unplanned boundary breach.

**Polygon-aware spot generation — 5 steps:**
1. **Ingest & inset:** GeoJSON → local Cartesian. Shrink boundary inward by 2.0m (truck overhang + pile spread margin for Cat 777)
2. **Anchor:** First spot = furthest point in inset polygon from haul road entrance (ensures exit path is always clear)
3. **Hexagonal staggered grid:** Row spacing = `3.03 × sin(60°)` = 2.62m. Row offset = 1.515m. Coverage: 90.7% vs 78.5% for square grid
4. **Validity filter per candidate spot:** rear axle inside inset polygon ✓, reverse arc (r=12.8m) inside original polygon ✓, pile footprint inside polygon ✓, reachable from haul road without crossing existing piles ✓, no-isolation (remaining polygon still connected) ✓
5. **Corner micro-spots:** corners < 60° → compute largest valid micro-spot. If none fits → flag `DOZER_FILL_REQUIRED`

**Boundary enforcement — 3 layers:**
- L1: No spot assigned unless all 5 validity checks pass (pre-assignment)
- L2: Real-time monitoring during approach — deviation >1.5m from planned path → emergency stop
- L3: Post-dump pile scan — any material outside polygon boundary → zone suspended + alert to mine manager

**DSDE path:**
```
Safety: bauxite moisture=22% > 15% → ADD S6
Choke: FALSE
Fleet: HOMOGENEOUS
Polygon: NON_CONVEX/IRREGULAR → S2
OUTPUT: S2 + S6. reason="HOMO_IRREGULAR_POLYGON + WET_MATERIAL"
```

**Regulatory:** MMDR Act (Mines and Minerals Development and Regulation Act) boundary
compliance; Forest Rights Act if adjacent to forest land (common in TN limestone areas)

---

## Scenario 5 — Sidehill Fill, Night Operations

**Mine:** Khetri Copper Complex, Jhunjhunu, Rajasthan (Hindustan Copper Ltd)
**Coordinates:** 28.01°N, 75.80°E
**Fleet:** Cat 789D (181t) × 4 + Cat 793F (227t) × 4 — mixed, both AHS-certified
**Dump type:** Sidehill Fill (slope-following, one open face downhill)
**Material:** Copper overburden — silicate rock with clay bands
**Terrain:** Rocky hillside, 15–22° natural slope, 5–12°C at night, 80–200m visibility
**DSDE output:** S3 + S6 + night modifier

**The problem:**
Night operations degrade camera-based semantic segmentation (primary visual sensor).
Clay bands in copper overburden at 5°C increase stiffness → pile spread is smaller
than daytime predictions (pile more confined, taller). 789D (8m × 6.2m pile) and 793F
(9m × 7m pile) are similar sizes but produce medium-scale low spots when a 793F spot
is used by a 789D. Sidehill dump must sequence uphill-to-downhill to prevent material
from sliding past lift boundaries.

**Night modifier rules:**
- Camera confidence threshold: 0.85 → 0.92 (higher bar in low light)
- LiDAR: primary; Radar: secondary; Camera: tertiary
- Approach speed: 3 km/h → 2 km/h
- All pile positions from previous shift: "unverified" until current-shift LiDAR scan confirms

**Clay freeze modifier:**
When `temperature_celsius < 8` AND `material_type = COPPER_OVERBURDEN`:
reduce expected pile footprint by 15% in width dimension.
This means spot spacing can be reduced slightly (piles are narrower) — an efficiency gain
in cold conditions.

**Sidehill sequence rule:** Available spots restricted to those at or below
`current_max_fill_elevation − 0.5m` only. Dumps always proceed uphill-to-downhill.

**DSDE path:**
```
Safety: slope=18° > 15° → ADD S6
Safety: visibility=120m < 200 + night_ops=TRUE → ADD S6
Choke: FALSE
Fleet: MIXED + polygon ELONGATED_RECTANGULAR + fill 35% < 70% → S3
Environment: temp=7°C + copper_overburden → clay_freeze_modifier=TRUE
OUTPUT: S3 + S6 + night_modifier + clay_freeze. reason="MIXED_REGULAR + SLOPE_WARNING + NIGHT_OPS + CLAY_FREEZE"
```

---

## Scenario 6 — ROM Stockpile with Grade Blending

**Mine:** Bailadila Iron Ore Project, Dantewada, Chhattisgarh (NMDC)
**Coordinates:** 18.73°N, 81.36°E
**Fleet:** Cat 793F (227t) × 6 — homogeneous, AHS-certified
**Dump type:** ROM (Run-of-Mine) Stockpile — active stockpile for crusher feed
**Material:** Iron ore, hematite — two grades: high-Fe (≥64%) and low-Fe (<60%)
**Terrain:** Flat processing pad, defined rectangular stockpile bays
**DSDE output:** S1 + ROM modifier

**The problem:**
ROM stockpiles must be reclaimable by dozer — every 3rd column must remain clear as
an access lane. Ore grade must be layered (high-Fe upper layers, low-Fe lower) to
deliver consistent Fe% to the crusher. Iron ore particle size segregation during
high-drop dumping reduces crusher feed consistency.

**ROM-specific spot rules:**
- Column pattern: col 1, 2 = dump; col 3 = RESERVED (dozer lane); col 4, 5 = dump; col 6 = RESERVED; repeat
- Grade assignment: truck carrying Fe ≥64% → upper-layer row; Fe <60% → lower-layer row; Fe 60–64% → intermediate
- Grade data source: shovel XRF scanner reading (15–30s latency, ±0.8% Fe accuracy)
- Segregation mitigation: truck lowers bed to ≤0.3m above current pile surface before dumping

**DSDE path:**
```
Safety: none triggered
Choke: FALSE
Fleet: HOMOGENEOUS + polygon RECTANGULAR + fill 20% < 80% → S1
ROM modifier: reclaim_access=TRUE + grade_blend=TRUE
OUTPUT: S1 + ROM_modifier. reason="HOMO_REGULAR + ROM_RECLAIM_GRADE_BLEND"
```

---

## Scenario 7 — Large Fleet Baseline (Global Reference, Australia)

**Mine:** Caval Ridge / Daunia Mine, Bowen Basin, Queensland, Australia
**Coordinates:** 22.50°S, 148.50°E
**Fleet:** Cat 793F (227t) × 10–15 — large homogeneous AHS fleet
**Dump type:** External Edge Dump (large-scale waste dump bench extension)
**Material:** Coal overburden — dry, low moisture, highly predictable pile behaviour
**Terrain:** Flat to gently sloping plateau, dry semi-arid, high truck density
**DSDE output:** S1 (early) → S3 (fill >80%); S5 applied to approach lane sequencing

**Why this scenario matters:**
Australia is where Cat's AHS was commercially proven and perfected. This establishes
the **global benchmark** — what optimal packing looks like under ideal conditions
(no monsoon, no irregular polygon, homogeneous fleet, dry material, predictable piles).
All 7 Indian scenarios can be measured against this baseline to quantify the specific
challenge introduced by each additional variable (rain, mixed fleet, irregular polygon, etc.).

In dry conditions with S1, pile footprint prediction is highly accurate
(793F pile = 9.0m × 7.0m ± 0.3m). Pre-computed spots remain valid for longer.
The S1→S3 transition happens at polygon_fill_pct = 80% rather than being forced
earlier by surface variability.

---

## Scenario 8 — Communication-Degraded Emergency Fallback

**Condition:** Multiple simultaneous system failures — applicable to any of the above scenarios
**Fleet:** Any AHS-capable fleet
**Trigger:** `gps_accuracy_cm > 50` AND `v2v_link_quality = LOST` AND `visibility_m < 80` simultaneously
**DSDE output:** S7 FORCED

**S7 — Full Specification:**
- 20 pre-loaded fallback spots per zone, computed at shift start, 5m spacing (conservative)
- One truck in zone at a time; all others hold at pre-defined holding area ≥100m from zone
- Approach speed reduced to 1.5 km/h (vs 3 km/h normal)
- Radar-primary positioning (LiDAR may be partially degraded)
- No spot optimisation — trucks take next available fallback spot in sequence
- Human notification JSON published immediately (see Chapter 5.2 alert schema)

**Recovery:** All three conditions must clear simultaneously:
`gps_accuracy_cm < 30 ✅ AND v2v_link_quality = GOOD ✅ AND lidar_operational = TRUE ✅`

---

# CHAPTER 8 — SCENARIO × STRATEGY REFERENCE TABLE

| # | Scenario | Mine / Location | Fleet | Dump Type | Strategy | S6? | Key Switch Variable |
|---|---|---|---|---|---|---|---|
| 1 | Monsoon Paddock | Gevra, CG | 793F+789D mixed | Backfill | S1→S3 | YES | Rain >20mm/hr, soft_ground >30% |
| 2 | Edge Dump | Noamundi, JH | 777G+789D mixed | Edge | S3 | Partial | Wind >8 m/s, LiDAR saturation |
| 3 | Valley Fill | Odisha hills | 793F homogeneous | Valley Fill | S5 | Conditional | Choke width <22.6m |
| 4 | Irregular Polygon | Ariyalur TN/Kutch GJ | 777G homogeneous | Heaped Fill | S2 | Conditional | Polygon non-convex, moisture >15% |
| 5 | Sidehill Night | Khetri, RJ | 789D+793F mixed | Sidehill | S3 | YES | Slope >15°, visibility <200m, temp <8°C |
| 6 | ROM Stockpile | Bailadila, CG | 793F homogeneous | ROM | S1 | NO | Grade blend, reclaim lanes |
| 7 | Large Fleet AUS | Bowen Basin, QLD | 793F homogeneous | Edge | S1→S3 | Conditional | fill >80%, night = +S6 |
| 8 | Degraded Mode | Any | Any | Any | S7 forced | N/A | GPS >50cm OR LiDAR fault OR V2V lost |

---

# CHAPTER 9 — PROJECT DELIVERABLES

## 9.1 What Gets Submitted to Caterpillar

**Type:** Both — a research paper AND a working prototype (confirmed)

**The paper's core argument:**
The 7.38m → 3.03m gap cannot be closed by any single packing strategy.
It requires a context-aware switching system (DSDE) built on a two-layer
communication architecture (Server↔Client MQTT + Truck↔Truck P2P WebSocket).
Proved by running 8 scenarios and showing density trend charts improving
from the 7.38m baseline toward the 3.03m target as the correct strategy activates.

**The prototype:** The existing site at optimaldumping.onrender.com, enhanced with
the 12 changes described in Chapter 10.

## 9.2 Recommended Paper Structure

**Section 1 — Problem Statement**
Quantify the gap (7.38m vs 3.03m). Explain the three barriers (obstacle classification,
load cell constraint, fixed spot points). State the project target (≤3.5m, ≥87% area efficiency).

**Section 2 — Why No Single Strategy Is Sufficient**
Show that S1 fails for mixed fleets, S3 fails for choke points without P2P,
S5 fails for regular polygon regular-fill scenarios (unnecessary overhead),
etc. Use the decision tree branches as structured evidence.

**Section 3 — The DSDE**
Full decision tree. All 30+ input variables categorised by group. The 7-strategy library.
The switching protocol. Argue explicitly why this is rule-based, not ML
(explainability requirement, no training data, small structured output space).

**Section 4 — The Communication Architecture**
Server↔Client (MQTT topics, message schemas). Truck↔Truck P2P (WebSocket, 8-phase protocol).
JSON message schemas for each message type. Failure handling and recovery.
Protocol versioning for backward compatibility.

**Section 5 — Scenario Analysis (8 Scenarios)**
For each: DSDE path trace → strategy selected → density achieved vs 7.38m baseline →
key safety guarantees → relevant Indian regulations enforced.

**Section 6 — Indian Regulatory Context**
MoEF&CC slope limits (28° coal overburden). DGMS General Regulations 141 (vehicle separation).
MMDR Act boundary compliance. How each regulation is enforced by the DSDE.

**Section 7 — Results and Prototype**
Density trend charts from simulation runs showing approach to 3.03m.
Strategy switch timeline showing DSDE responding to condition changes.
Communication log excerpts showing actual message flows.

**Section 8 — Conclusion and Future Work**
Current system limitations (listed in Chapter 12).
Next steps: semantic segmentation ML model for perception, real RTK GPS integration,
compaction verification sensor.

---

# CHAPTER 10 — BUILD PLAN FOR ANTIGRAVITY AGENTIC IDE

## 10.1 Critical Instruction — Read Before Any Changes

```
AGENT INSTRUCTION:
1. Do NOT rebuild from scratch.
2. First, read every existing file in the repository.
3. Identify which files contain:
   - The A* pathfinding logic
   - The unit cell / spot placement logic
   - The truck rendering / animation
   - The polygon drawing tool
   - The Live Metrics panel
   - The Density Trend chart
4. Only modify what needs to change.
5. Preserve all existing UI structure, routing, and styling.
6. Execute the 12 changes below IN ORDER.
7. After each change, verify it works before proceeding.
```

## 10.2 Do NOT Rebuild (Keep As-Is)

- Polygon drawing tool (Draw Yard)
- Basic truck rendering on canvas
- Live Metrics panel structure (extend it, don't replace it)
- Fleet Configuration panel structure
- Density Trend chart (add reference lines, don't replace)
- A* pathfinding implementation (modify the spacing input, not the algorithm)
- 2D/3D/Heatmap view toggle
- Speed slider

## 10.3 The 12 Changes (Execute In Order)

---

### CHANGE 1 — Fix Dump Spacing Algorithm
**File:** Wherever unit cell / spot selection logic lives (likely a grid/matrix module)
**What:** Replace fixed-offset placement with pile-centroid-relative 3.03m spacing

```javascript
// REMOVE whatever currently computes the next spot position
// REPLACE WITH:

const TARGET_CENTER_SPACING_M = 3.03;
const POLYGON_INSET_M = 2.0; // safety margin from boundary

function computeNextSpot(prevPileCentroid, dumpDirection, polygon, existingPiles, truckModel) {
  const pileFootprint = predictPileFootprint(truckModel);

  // Start at exactly 3.03m from previous pile centroid
  let candidateCenter = {
    x: prevPileCentroid.x + TARGET_CENTER_SPACING_M * Math.cos(dumpDirection),
    y: prevPileCentroid.y + TARGET_CENTER_SPACING_M * Math.sin(dumpDirection)
  };

  // Try up to 20 increments if initial candidate is invalid
  for (let attempt = 0; attempt < 20; attempt++) {
    const reverseArc = computeReverseSweep(
      getApproachPoint(candidateCenter, dumpDirection),
      candidateCenter,
      truckModel
    );

    const valid =
      isInsideInsetPolygon(candidateCenter, polygon, POLYGON_INSET_M) &&
      footprintInsidePolygon(candidateCenter, pileFootprint, polygon) &&
      arcInsidePolygon(reverseArc, polygon) &&
      !overlapsExistingPile(candidateCenter, pileFootprint, existingPiles) &&
      !causesIsolation(candidateCenter, polygon, existingPiles);

    if (valid) return candidateCenter;

    // Shift 0.1m further along dump direction and retry
    candidateCenter.x += 0.1 * Math.cos(dumpDirection);
    candidateCenter.y += 0.1 * Math.sin(dumpDirection);
  }

  return null; // no valid spot found in this direction
}

// Validation helpers (implement each):
function isInsideInsetPolygon(point, polygon, insetM) { /* ... */ }
function footprintInsidePolygon(center, footprint, polygon) { /* ... */ }
function arcInsidePolygon(arc, polygon) { /* use turf.js booleanContains */ }
function overlapsExistingPile(center, footprint, existingPiles) { /* ... */ }
function causesIsolation(center, polygon, existingPiles) { /* ... */ }
```

**Verify:** Average spacing shown in Density metric should be ~3.03m on clean rectangular polygon.

---

### CHANGE 2 — Add Swept-Area Collision Avoidance
**File:** New file `src/collisionAvoidance.js`

```javascript
// src/collisionAvoidance.js

export function computeReverseSweep(startPos, startHeading, targetSpot, truckModel) {
  const steps = 24;
  const halfWidth = truckModel.width_m / 2 + 0.5; // 0.5m clearance buffer
  const arcPoints = interpolateReversArc(
    startPos, startHeading, targetSpot, truckModel.turning_radius_m, steps
  );

  const leftEdge = arcPoints.map(pt => offsetPoint(pt.pos, pt.heading + 90, halfWidth));
  const rightEdge = arcPoints.map(pt => offsetPoint(pt.pos, pt.heading - 90, halfWidth))
    .reverse();

  return [...leftEdge, ...rightEdge]; // closed polygon
}

export function checkSweptAreaConflict(sweep1, sweep2) {
  // Use turf.js: booleanIntersects(polygon(sweep1), polygon(sweep2))
  return turfBooleanIntersects(toTurfPolygon(sweep1), toTurfPolygon(sweep2));
}

// Before any truck begins its approach manoeuvre:
export function resolveTruckConflicts(trucks) {
  for (let i = 0; i < trucks.length; i++) {
    if (!trucks[i].assignedSpot) continue;
    const sweepI = computeReverseSweep(
      trucks[i].position, trucks[i].heading,
      trucks[i].assignedSpot, trucks[i].model
    );
    for (let j = i + 1; j < trucks.length; j++) {
      if (!trucks[j].assignedSpot) continue;
      const sweepJ = computeReverseSweep(
        trucks[j].position, trucks[j].heading,
        trucks[j].assignedSpot, trucks[j].model
      );
      if (checkSweptAreaConflict(sweepI, sweepJ)) {
        // Lower payload truck waits
        const waiter = trucks[i].payload_tonnes < trucks[j].payload_tonnes
          ? trucks[i] : trucks[j];
        waiter.state = 'WAITING';
        waiter.waitReason = `SWEEP_CONFLICT with ${waiter === trucks[i] ? trucks[j].id : trucks[i].id}`;
        waiter.waitUntilClearMs = Date.now() + 3000; // re-check in 3 seconds
      }
    }
  }
}
```

**Verify:** Two trucks assigned to adjacent spots — one should show WAITING state, not collide.

---

### CHANGE 3 — Create Python FastAPI Backend
**New directory:** `backend/`

**`backend/requirements.txt`**
```
fastapi==0.111.0
uvicorn[standard]==0.30.0
pydantic==2.7.0
shapely==2.0.4
numpy==1.26.4
paho-mqtt==1.6.1
websockets==12.0
pytest==8.2.0
```

**`backend/main.py`**
```python
from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from contextlib import asynccontextmanager
import asyncio
import json

from dsde.decision_engine import evaluate as dsde_evaluate
from dsde.input_variables import DSDeInputState
from scenarios.scenario_loader import ScenarioLoader
from simulation.engine import SimulationEngine
from communication.p2p_manager import P2PManager

scenario_loader = ScenarioLoader()
p2p_manager = P2PManager()
simulations = {}

@asynccontextmanager
async def lifespan(app: FastAPI):
    scenario_loader.load_all()
    yield

app = FastAPI(title="ADPS Backend", lifespan=lifespan)
app.add_middleware(CORSMiddleware, allow_origins=["*"])

# ── REST Endpoints ──────────────────────────────────────────────────

@app.post("/api/dsde/evaluate")
async def evaluate_dsde(state: DSDeInputState):
    return dsde_evaluate(state)

@app.get("/api/scenarios")
async def list_scenarios():
    return scenario_loader.list_all()

@app.get("/api/scenarios/{scenario_id}")
async def get_scenario(scenario_id: str):
    return scenario_loader.get(scenario_id)

@app.post("/api/simulation/start")
async def start_simulation(body: dict):
    scenario = scenario_loader.get(body["scenario_id"])
    sim = SimulationEngine(scenario)
    sim_id = body["scenario_id"]
    simulations[sim_id] = sim
    asyncio.create_task(sim.run())
    return {"simulation_id": sim_id, "status": "started"}

@app.post("/api/simulation/{sim_id}/stop")
async def stop_simulation(sim_id: str):
    if sim_id in simulations:
        simulations[sim_id].stop()
    return {"status": "stopped"}

@app.get("/api/simulation/{sim_id}/state")
async def get_sim_state(sim_id: str):
    if sim_id not in simulations:
        return {"error": "not found"}
    return simulations[sim_id].get_state()

# ── WebSocket: Simulation state stream ─────────────────────────────

@app.websocket("/ws/simulation/{sim_id}")
async def simulation_ws(websocket: WebSocket, sim_id: str):
    await websocket.accept()
    try:
        while True:
            if sim_id in simulations:
                state = simulations[sim_id].get_state()
                await websocket.send_json(state)
            await asyncio.sleep(0.5)  # 2Hz
    except WebSocketDisconnect:
        pass

# ── WebSocket: P2P truck-to-truck relay ─────────────────────────────

@app.websocket("/ws/p2p/{truck_id}")
async def p2p_ws(websocket: WebSocket, truck_id: str):
    await p2p_manager.connect(truck_id, websocket)
    try:
        while True:
            data = await websocket.receive_text()
            msg = json.loads(data)
            # Relay to all other trucks — server watches but does not intervene
            await p2p_manager.broadcast(msg, exclude=truck_id)
    except WebSocketDisconnect:
        p2p_manager.disconnect(truck_id)
```

**`backend/dsde/input_variables.py`** — Pydantic model for all DSDE inputs
```python
from pydantic import BaseModel, Field
from enum import Enum
from typing import Optional

class FleetHomogeneity(str, Enum):
    HOMOGENEOUS = "HOMOGENEOUS"
    MIXED = "MIXED"

class PolygonShape(str, Enum):
    CONVEX = "CONVEX"
    RECTANGULAR = "RECTANGULAR"
    NON_CONVEX = "NON_CONVEX"
    IRREGULAR = "IRREGULAR"
    LINEAR_EDGE = "LINEAR_EDGE"
    ELONGATED_RECTANGULAR = "ELONGATED_RECTANGULAR"

class V2VLinkQuality(str, Enum):
    GOOD = "GOOD"
    DEGRADED = "DEGRADED"
    LOST = "LOST"

class Season(str, Enum):
    MONSOON = "MONSOON"
    DRY = "DRY"
    WINTER = "WINTER"

class MaterialType(str, Enum):
    COAL_OVERBURDEN = "COAL_OVERBURDEN"
    IRON_ORE = "IRON_ORE"
    LIMESTONE = "LIMESTONE"
    BAUXITE = "BAUXITE"
    COPPER_OVERBURDEN = "COPPER_OVERBURDEN"
    MINERAL_SAND = "MINERAL_SAND"
    GOLD_WASTE = "GOLD_WASTE"

class DumpType(str, Enum):
    INTERNAL_PADDOCK = "INTERNAL_PADDOCK"
    EDGE_DUMP = "EDGE_DUMP"
    VALLEY_FILL = "VALLEY_FILL"
    HEAPED_FILL = "HEAPED_FILL"
    SIDEHILL_FILL = "SIDEHILL_FILL"
    ROM_STOCKPILE = "ROM_STOCKPILE"

class DSDeInputState(BaseModel):
    # Group A — Fleet
    truck_model: str = Field(..., description="e.g. Cat793F")
    payload_tonnes: float = Field(..., ge=0)
    fleet_homogeneity: FleetHomogeneity
    trucks_active_in_zone: int = Field(..., ge=0)
    queue_length: int = Field(..., ge=0)
    truck_turning_radius_m: float = Field(..., gt=0)
    truck_width_m: float = Field(..., gt=0)

    # Group B — Site/Polygon
    dump_type: DumpType
    polygon_fill_pct: float = Field(..., ge=0, le=100)
    polygon_shape: PolygonShape
    choke_point_present: bool = False
    choke_point_width_m: Optional[float] = None
    edge_dump_active: bool = False
    available_entry_exits: int = Field(default=2, ge=1)

    # Group C — Surface/Terrain
    terrain_slope_max_deg: float = Field(..., ge=0)
    soft_ground_pct: float = Field(..., ge=0, le=100)
    pile_drift_detected: bool = False
    low_spots_count: int = Field(default=0, ge=0)
    avg_pile_height_m: float = Field(default=0.0, ge=0)

    # Group D — Material
    material_type: MaterialType
    material_moisture_pct: float = Field(..., ge=0)
    material_bulk_density: float = Field(..., gt=0)
    material_angle_of_repose: float = Field(..., gt=0)

    # Group E — Environment
    rainfall_intensity_mmhr: float = Field(default=0.0, ge=0)
    wind_speed_ms: float = Field(default=0.0, ge=0)
    wind_direction_deg: float = Field(default=0.0, ge=0, le=360)
    visibility_m: float = Field(default=1000.0, ge=0)
    temperature_celsius: float = Field(default=25.0)
    season: Season = Season.DRY

    # Group F — System Health
    v2v_link_quality: V2VLinkQuality = V2VLinkQuality.GOOD
    gps_accuracy_cm: float = Field(default=2.0, ge=0)
    lidar_operational: bool = True
    fleet_mgr_online: bool = True
    protocol_version: str = "1.0"
```

**`backend/dsde/decision_engine.py`** — The full decision tree
```python
from .input_variables import (
    DSDeInputState, FleetHomogeneity, PolygonShape, V2VLinkQuality
)
from dataclasses import dataclass, field
from typing import List
from enum import Enum

class StrategyID(str, Enum):
    S1 = "S1"
    S2 = "S2"
    S3 = "S3"
    S4 = "S4"
    S5 = "S5"
    S6 = "S6"
    S7 = "S7"

@dataclass
class DSDeOutput:
    strategies: List[StrategyID]
    s6_active: bool = False
    s7_forced: bool = False
    wind_scatter_buffer_m: float = 0.0
    low_spot_priority: bool = False
    clay_freeze_modifier: bool = False
    reason_string: str = ""
    re_evaluate_in_seconds: int = 30

def evaluate(state: DSDeInputState) -> DSDeOutput:
    strategies: List[StrategyID] = []
    s6_active = False
    s7_forced = False
    wind_scatter_buffer_m = 0.0
    low_spot_priority = False
    clay_freeze_modifier = False
    reason_parts: List[str] = []

    # ── SAFETY OVERRIDE ───────────────────────────────────────────────
    if state.gps_accuracy_cm > 50:
        return DSDeOutput(
            strategies=[StrategyID.S7], s7_forced=True,
            reason_string="S7_FORCED: GPS_DEGRADED gps_accuracy={}cm".format(state.gps_accuracy_cm),
            re_evaluate_in_seconds=10
        )
    if not state.lidar_operational:
        return DSDeOutput(
            strategies=[StrategyID.S7], s7_forced=True,
            reason_string="S7_FORCED: LIDAR_FAULT",
            re_evaluate_in_seconds=10
        )
    if state.v2v_link_quality == V2VLinkQuality.LOST and state.trucks_active_in_zone > 1:
        return DSDeOutput(
            strategies=[StrategyID.S7], s7_forced=True,
            reason_string="S7_FORCED: V2V_LOST trucks_active={}".format(state.trucks_active_in_zone),
            re_evaluate_in_seconds=10
        )
    if state.terrain_slope_max_deg > 25:
        s6_active = True
        reason_parts.append("SLOPE_WARNING={}deg".format(round(state.terrain_slope_max_deg, 1)))
    if state.soft_ground_pct > 30:
        s6_active = True
        reason_parts.append("SOFT_GROUND={}pct".format(round(state.soft_ground_pct, 1)))
    if state.rainfall_intensity_mmhr > 20:
        s6_active = True
        reason_parts.append("HEAVY_RAIN={}mmhr".format(round(state.rainfall_intensity_mmhr, 1)))

    # ── CHOKE POINT OVERRIDE ──────────────────────────────────────────
    if state.choke_point_present and state.choke_point_width_m is not None:
        threshold = state.truck_width_m * 2 + 4.0
        if state.choke_point_width_m < threshold:
            strategies = [StrategyID.S5]
            if s6_active:
                strategies.append(StrategyID.S6)
            reason_parts.insert(0, "CHOKE_POINT_DETECTED width={}m threshold={}m".format(
                round(state.choke_point_width_m, 1), round(threshold, 1)))
            return DSDeOutput(
                strategies=strategies, s6_active=s6_active,
                reason_string=" | ".join(reason_parts),
                re_evaluate_in_seconds=30
            )

    # ── FLEET × GEOMETRY MATRIX ───────────────────────────────────────
    selected = None
    if state.fleet_homogeneity == FleetHomogeneity.HOMOGENEOUS:
        if (state.polygon_shape in [PolygonShape.CONVEX, PolygonShape.RECTANGULAR]
                and state.polygon_fill_pct < 80
                and state.terrain_slope_max_deg < 15):
            selected = StrategyID.S1
            reason_parts.insert(0, "HOMO_REGULAR_LOW_FILL")
        elif state.polygon_shape in [PolygonShape.NON_CONVEX, PolygonShape.IRREGULAR]:
            selected = StrategyID.S2
            reason_parts.insert(0, "HOMO_IRREGULAR_POLYGON")
        elif state.polygon_fill_pct >= 80:
            selected = StrategyID.S3
            reason_parts.insert(0, "HOMO_HIGH_FILL_PCT")
        elif state.edge_dump_active:
            selected = StrategyID.S3
            reason_parts.insert(0, "HOMO_EDGE_DUMP")
        else:
            selected = StrategyID.S1
            reason_parts.insert(0, "HOMO_DEFAULT")
    else:  # MIXED
        if (state.polygon_shape in [PolygonShape.CONVEX, PolygonShape.RECTANGULAR]
                and state.polygon_fill_pct < 70):
            selected = StrategyID.S3
            reason_parts.insert(0, "MIXED_REGULAR_POLYGON")
        elif state.polygon_shape in [PolygonShape.NON_CONVEX, PolygonShape.IRREGULAR]:
            selected = StrategyID.S4
            reason_parts.insert(0, "MIXED_IRREGULAR_POLYGON")
        elif state.edge_dump_active:
            selected = StrategyID.S3
            reason_parts.insert(0, "MIXED_EDGE_DUMP")
        elif state.polygon_fill_pct >= 80:
            selected = StrategyID.S4
            reason_parts.insert(0, "MIXED_HIGH_FILL_PCT")
        else:
            selected = StrategyID.S3
            reason_parts.insert(0, "MIXED_DEFAULT")

    strategies = [selected]

    # ── ENVIRONMENT MODIFIER PASS ─────────────────────────────────────
    if state.material_moisture_pct > 15 or state.rainfall_intensity_mmhr > 5:
        if not s6_active:
            s6_active = True
            reason_parts.append("WET_MATERIAL moisture={}pct".format(
                round(state.material_moisture_pct, 1)))
        low_spot_priority = True
        reason_parts.append("LOW_SPOT_PRIORITY=HIGH")

    if state.wind_speed_ms > 8 and state.edge_dump_active:
        material_fineness = _material_fineness_factor(state.material_type)
        wind_scatter_buffer_m = state.wind_speed_ms * material_fineness * 2.5
        reason_parts.append("WIND_SCATTER_BUFFER={}m".format(round(wind_scatter_buffer_m, 1)))

    if state.temperature_celsius < 8 and state.material_type.value == "COPPER_OVERBURDEN":
        clay_freeze_modifier = True
        reason_parts.append("CLAY_FREEZE_MODIFIER temp={}C".format(state.temperature_celsius))

    if s6_active:
        strategies.append(StrategyID.S6)

    return DSDeOutput(
        strategies=strategies,
        s6_active=s6_active,
        s7_forced=False,
        wind_scatter_buffer_m=wind_scatter_buffer_m,
        low_spot_priority=low_spot_priority,
        clay_freeze_modifier=clay_freeze_modifier,
        reason_string=" | ".join(reason_parts),
        re_evaluate_in_seconds=30
    )

def _material_fineness_factor(material_type) -> float:
    factors = {
        "COAL_OVERBURDEN": 1.0,
        "IRON_ORE": 1.2,
        "LIMESTONE": 0.9,
        "BAUXITE": 1.1,
        "COPPER_OVERBURDEN": 1.0,
        "MINERAL_SAND": 1.8,
        "GOLD_WASTE": 0.95,
    }
    return factors.get(material_type.value, 1.0)
```

**Verify:** `POST /api/dsde/evaluate` with Scenario 1 monsoon inputs returns `{strategies: ["S3","S6"]}`.

---

### CHANGE 4 — Write All Tests for Decision Engine
**New file:** `backend/tests/test_decision_engine.py`

```python
import pytest
from dsde.decision_engine import evaluate, StrategyID
from dsde.input_variables import DSDeInputState, FleetHomogeneity, PolygonShape, V2VLinkQuality

BASE_STATE = {
    "truck_model": "Cat793F", "payload_tonnes": 220.0,
    "fleet_homogeneity": "HOMOGENEOUS", "trucks_active_in_zone": 2,
    "queue_length": 4, "truck_turning_radius_m": 17.5, "truck_width_m": 9.3,
    "dump_type": "INTERNAL_PADDOCK", "polygon_fill_pct": 30.0,
    "polygon_shape": "RECTANGULAR", "choke_point_present": False,
    "edge_dump_active": False, "terrain_slope_max_deg": 5.0,
    "soft_ground_pct": 5.0, "pile_drift_detected": False, "low_spots_count": 0,
    "avg_pile_height_m": 1.5, "material_type": "COAL_OVERBURDEN",
    "material_moisture_pct": 5.0, "material_bulk_density": 1.4,
    "material_angle_of_repose": 38.0, "rainfall_intensity_mmhr": 0.0,
    "wind_speed_ms": 0.0, "wind_direction_deg": 0.0, "visibility_m": 1000.0,
    "temperature_celsius": 25.0, "season": "DRY",
    "v2v_link_quality": "GOOD", "gps_accuracy_cm": 2.0,
    "lidar_operational": True, "fleet_mgr_online": True,
}

def make_state(**overrides):
    return DSDeInputState(**{**BASE_STATE, **overrides})

# Safety overrides
def test_s7_forced_on_gps_degraded():
    out = evaluate(make_state(gps_accuracy_cm=85.0))
    assert out.s7_forced is True
    assert StrategyID.S7 in out.strategies

def test_s7_forced_on_lidar_fault():
    out = evaluate(make_state(lidar_operational=False))
    assert out.s7_forced is True

def test_s7_forced_on_v2v_lost_multi_truck():
    out = evaluate(make_state(v2v_link_quality="LOST", trucks_active_in_zone=3))
    assert out.s7_forced is True

def test_s6_added_on_slope():
    out = evaluate(make_state(terrain_slope_max_deg=27.0))
    assert out.s6_active is True
    assert StrategyID.S6 in out.strategies

def test_s6_added_on_heavy_rain():
    out = evaluate(make_state(rainfall_intensity_mmhr=25.0))
    assert out.s6_active is True

def test_s6_added_on_soft_ground():
    out = evaluate(make_state(soft_ground_pct=45.0))
    assert out.s6_active is True

# Choke point override
def test_s5_on_narrow_choke():
    out = evaluate(make_state(choke_point_present=True, choke_point_width_m=18.0))
    assert StrategyID.S5 in out.strategies
    assert StrategyID.S3 not in out.strategies  # S5 overrides

def test_no_s5_on_wide_enough_choke():
    out = evaluate(make_state(choke_point_present=True, choke_point_width_m=30.0))
    assert StrategyID.S5 not in out.strategies

# Fleet × geometry matrix
def test_s1_homogeneous_regular_low_fill():
    out = evaluate(make_state(fleet_homogeneity="HOMOGENEOUS", polygon_shape="RECTANGULAR",
                               polygon_fill_pct=30.0, terrain_slope_max_deg=5.0))
    assert StrategyID.S1 in out.strategies

def test_s2_homogeneous_irregular():
    out = evaluate(make_state(fleet_homogeneity="HOMOGENEOUS", polygon_shape="IRREGULAR"))
    assert StrategyID.S2 in out.strategies

def test_s3_homogeneous_high_fill():
    out = evaluate(make_state(fleet_homogeneity="HOMOGENEOUS", polygon_fill_pct=85.0))
    assert StrategyID.S3 in out.strategies

def test_s3_homogeneous_edge_dump():
    out = evaluate(make_state(fleet_homogeneity="HOMOGENEOUS", edge_dump_active=True))
    assert StrategyID.S3 in out.strategies

def test_s3_mixed_regular_polygon():
    out = evaluate(make_state(fleet_homogeneity="MIXED", polygon_shape="RECTANGULAR",
                               polygon_fill_pct=40.0))
    assert StrategyID.S3 in out.strategies

def test_s4_mixed_irregular_polygon():
    out = evaluate(make_state(fleet_homogeneity="MIXED", polygon_shape="NON_CONVEX"))
    assert StrategyID.S4 in out.strategies

def test_s4_mixed_high_fill():
    out = evaluate(make_state(fleet_homogeneity="MIXED", polygon_fill_pct=85.0))
    assert StrategyID.S4 in out.strategies

# Environment modifiers
def test_low_spot_priority_on_wet_material():
    out = evaluate(make_state(material_moisture_pct=20.0))
    assert out.low_spot_priority is True

def test_wind_scatter_buffer_on_edge_dump():
    out = evaluate(make_state(wind_speed_ms=12.0, edge_dump_active=True,
                               fleet_homogeneity="MIXED", material_type="IRON_ORE"))
    assert out.wind_scatter_buffer_m > 0

def test_clay_freeze_modifier_on_cold_copper():
    out = evaluate(make_state(temperature_celsius=6.0, material_type="COPPER_OVERBURDEN"))
    assert out.clay_freeze_modifier is True

# Combined scenario tests
def test_scenario_1_monsoon_output():
    out = evaluate(make_state(
        fleet_homogeneity="MIXED", polygon_shape="RECTANGULAR",
        rainfall_intensity_mmhr=25.0, soft_ground_pct=35.0,
        material_moisture_pct=28.0
    ))
    assert StrategyID.S3 in out.strategies
    assert StrategyID.S6 in out.strategies
    assert out.low_spot_priority is True

def test_scenario_3_valley_fill_output():
    out = evaluate(make_state(
        fleet_homogeneity="HOMOGENEOUS", choke_point_present=True,
        choke_point_width_m=20.0
    ))
    assert StrategyID.S5 in out.strategies
```

**Verify:** All 20 tests pass with `pytest backend/tests/test_decision_engine.py -v`.

---

### CHANGE 5 — Create All 8 Scenario JSON Configs
**New directory:** `backend/scenarios/configs/`

**`scenario_01_monsoon.json`**
```json
{
  "scenario_id": "S01",
  "name": "Monsoon Paddock Backfill",
  "mine": "Gevra Mine, Korba, Chhattisgarh",
  "coordinates": { "lat": 22.14, "lon": 82.56 },
  "fleet": [
    { "model": "Cat793F", "count": 4, "payload_t": 227, "width_m": 9.3, "turning_radius_m": 17.5, "pile_l": 9.0, "pile_w": 7.0 },
    { "model": "Cat789D", "count": 4, "payload_t": 181, "width_m": 8.8, "turning_radius_m": 15.8, "pile_l": 8.0, "pile_w": 6.2 }
  ],
  "dump_type": "INTERNAL_PADDOCK",
  "material": "COAL_OVERBURDEN",
  "polygon": {
    "shape": "RECTANGULAR",
    "coordinates": [[0,0],[120,0],[120,80],[0,80],[0,0]]
  },
  "initial_conditions": {
    "fleet_homogeneity": "MIXED",
    "polygon_fill_pct": 0,
    "terrain_slope_max_deg": 5,
    "rainfall_intensity_mmhr": 0,
    "material_moisture_pct": 8,
    "soft_ground_pct": 5,
    "v2v_link_quality": "GOOD",
    "gps_accuracy_cm": 2,
    "season": "MONSOON"
  },
  "event_sequence": [
    { "time_s": 0, "event": "SHIFT_START" },
    { "time_s": 3600, "event": "WEATHER_CHANGE", "rainfall_intensity_mmhr": 12, "material_moisture_pct": 18 },
    { "time_s": 5400, "event": "WEATHER_CHANGE", "rainfall_intensity_mmhr": 28, "soft_ground_pct": 38 },
    { "time_s": 7200, "event": "WEATHER_CHANGE", "rainfall_intensity_mmhr": 0, "soft_ground_pct": 15 }
  ],
  "expected_strategy_path": ["S1", "S3+S6", "S3+S6", "S3"],
  "expected_density_target_m": 3.03,
  "regulatory_constraints": {
    "max_slope_deg": 28,
    "regulation": "MoEF&CC dump slope guidelines (India)",
    "enforced_by": "S6 slope validation"
  },
  "fallback_spots_s7": [
    {"x": 5, "y": 5, "bearing_deg": 180}, {"x": 10, "y": 5, "bearing_deg": 180},
    {"x": 15, "y": 5, "bearing_deg": 180}, {"x": 20, "y": 5, "bearing_deg": 180},
    {"x": 25, "y": 5, "bearing_deg": 180}, {"x": 30, "y": 5, "bearing_deg": 180},
    {"x": 35, "y": 5, "bearing_deg": 180}, {"x": 40, "y": 5, "bearing_deg": 180},
    {"x": 45, "y": 5, "bearing_deg": 180}, {"x": 50, "y": 5, "bearing_deg": 180},
    {"x": 5, "y": 12, "bearing_deg": 180}, {"x": 10, "y": 12, "bearing_deg": 180},
    {"x": 15, "y": 12, "bearing_deg": 180}, {"x": 20, "y": 12, "bearing_deg": 180},
    {"x": 25, "y": 12, "bearing_deg": 180}, {"x": 30, "y": 12, "bearing_deg": 180},
    {"x": 35, "y": 12, "bearing_deg": 180}, {"x": 40, "y": 12, "bearing_deg": 180},
    {"x": 45, "y": 12, "bearing_deg": 180}, {"x": 50, "y": 12, "bearing_deg": 180}
  ]
}
```

*(Create scenarios S02 through S08 following the same structure using the data from Chapter 7)*

---

### CHANGE 6 — Add MQTT Integration to Frontend
**Files to modify:** Main simulation file, truck agent files

See the full MQTT integration code in Chapter 6.3 (Fix 3). Add to package.json:
```json
"dependencies": {
  "mqtt": "^5.5.0"
}
```

**Verify:** Open browser network tab — truck agents should show WebSocket connection to
MQTT broker. Disconnecting the backend should freeze all truck movement (they no longer
move on JS timers).

---

### CHANGE 7 — Add P2P WebSocket Channel
**New file:** `src/p2p/P2PChannel.js`

See the full P2PChannel implementation in Chapter 6.4. The backend `/ws/p2p/{truck_id}`
endpoint is already created in Change 3.

**Activate for Scenario 3 only:** P2PChannel is instantiated only when
`scenario.dump_type === "VALLEY_FILL"` and `state.choke_point_present === true`.

**Verify:** Load Scenario 3. Two trucks approaching the choke point. Orange P2P messages
should appear in the message log. One truck should show WAITING state with a safe zone
indicator on the canvas.

---

### CHANGE 8 — Add DSDE Strategy Panel to UI
**File:** Main UI component or sidebar component

Add the Strategy Panel described in Chapter 6.7, Panel 1.
Connect to the `mines/${mineId}/dsde/strategy` MQTT topic.
Update the display on every received `STRATEGY_UPDATE` message.

---

### CHANGE 9 — Add Live Message Log Panel
**New component:** `src/components/MessageLog.jsx` (or equivalent)

Add the scrollable message log described in Chapter 6.7, Panel 2.
All MQTT messages received and sent by the frontend should be appended to this log.
All P2P WebSocket messages should also appear (in orange).
Cap at last 50 messages. Add Clear button.

---

### CHANGE 10 — Enhance Density Trend Chart
**File:** Density Trend chart component

Add three horizontal reference lines:
- `y = 7.38` — red dashed — label "AHS Baseline (7.38m)"
- `y = 3.5` — yellow dashed — label "Project Target (3.5m)"
- `y = 3.03` — green dashed — label "Human Target (3.03m)"

Shade the area between the current average spacing line and the 3.03m line in light red
(represents wasted spacing vs. human baseline).

---

### CHANGE 11 — Add Scenario Selector
**New component:** `src/components/ScenarioSelector.jsx`

- Dropdown listing all 8 scenarios by name
- On selection: fetch `GET /api/scenarios/{id}`, display summary card
- "Load Scenario" button: load the polygon from scenario config, pre-populate DSDE state,
  configure truck fleet to match scenario
- "Start Simulation" button: POST to `/api/simulation/start`

---

### CHANGE 12 — End-to-End Test All 8 Scenarios
Run each scenario from selection through completion. Verify:
- Strategy switches occur at the event sequence timestamps
- No crashes, no infinite loops
- No boundary violations (no pile outside polygon)
- No deadlocks (no truck stuck WAITING indefinitely)
- Density metric trends from ~7.38m toward ≤3.5m
- Message log shows actual message flows for each scenario

---

## 10.4 Implementation Order (Strict)

```
STEP 01  CHANGE 1 — Fix spacing algorithm
         → Verify: avg spacing ≈ 3.03m on clean rectangular polygon

STEP 02  CHANGE 2 — Add swept-area collision avoidance
         → Verify: two trucks with overlapping sweep paths — one waits

STEP 03  CHANGE 3 — Create Python FastAPI backend (directory + main.py)
         → Verify: uvicorn starts, /api/dsde/evaluate returns 200

STEP 04  CHANGE 4 (same as step 3) — Write decision_engine.py
         → Verify: ALL 20 pytest tests pass before proceeding

STEP 05  CHANGE 5 — Create all 8 scenario JSON configs
         → Verify: /api/scenarios returns 8 entries

STEP 06  CHANGE 6 — MQTT integration in frontend
         → Verify: trucks freeze when backend is stopped

STEP 07  CHANGE 7 — P2P WebSocket channel
         → Verify: Scenario 3 shows orange P2P messages in log

STEP 08  CHANGE 8 — DSDE Strategy Panel
         → Verify: panel shows S1 at start, switches to S3+S6 when rain event fires

STEP 09  CHANGE 9 — Live Message Log panel
         → Verify: all 3 message types (blue/green/orange) appear

STEP 10  CHANGE 10 — Density Trend reference lines
         → Verify: 7.38m and 3.03m lines visible on chart

STEP 11  CHANGE 11 — Scenario Selector
         → Verify: all 8 scenarios load polygon and fleet correctly

STEP 12  CHANGE 12 — End-to-end test all 8 scenarios
         → Verify: no crashes, all density trends improve from baseline
```

## 10.5 Tech Stack

**Existing frontend (keep):**
- JavaScript (whatever framework is in use — React / vanilla / Vue)
- Canvas / SVG for truck and polygon rendering
- A* pathfinding library

**New frontend packages:**
```json
"mqtt": "^5.5.0",
"@turf/turf": "^6.5.0"
```

**New backend:**
- Python 3.11+
- FastAPI 0.111+ (REST + WebSocket)
- Pydantic v2 (all data models and validation)
- Shapely 2.0+ (polygon geometry — inset, validity checks)
- NumPy 1.26+ (surface map as 2D array, 0.25m cells)
- Mosquitto or HiveMQ Cloud (MQTT broker)
- uvicorn (ASGI server)
- pytest (testing — all tests in `backend/tests/`)

## 10.6 Coding Standards for the Agent

1. Every strategy must implement the same interface:
   - `isApplicable(state) → bool`
   - `computeSpot(truck, surfaceMap, polygon) → SpotPoint | null`
   - `getStrategyId() → StrategyID`

2. The DSDE decision tree must be explicit if/elif chains. Never a trained model. Never a neural network.

3. All geometry uses Shapely (Python) or turf.js (JavaScript). No custom polygon algorithms.

4. All MQTT messages validated against Pydantic schemas before publish.

5. Surface map: 2D NumPy array, cell size = 0.25m × 0.25m.
   Each cell: `{height_m: float, surface_class: int, pile_id: int}`.

6. All distances in meters. All angles in degrees. No implicit unit conversions.

7. Every function has a docstring: purpose, inputs, outputs, relevant scenario(s).

8. **Every truck movement in the browser must originate from a received MQTT message.
   No JS-timer-driven truck movement.**

---

# CHAPTER 11 — OPEN PROBLEMS (Future Work for Paper Section 8)

These are intentionally unsolved — they represent honest limitations suitable for the
paper's future work section:

1. **Semantic segmentation model not implemented.** The perception layer requires a
   trained ML model (PointNet++ or VoxelNet on LiDAR point clouds) to classify surface
   zones. The simulation uses synthetic surface state data as a proxy.

2. **Pile footprint prediction is approximate.** The model assumes a fixed ellipse
   per truck model. Real footprints vary with material compaction, dump speed, bed angle,
   and moisture content. A physical pile dynamics model would improve accuracy.

3. **Compaction verification is not automated.** Valley fill (Scenario 3) requires each
   terrace lift to be compacted before the next begins. The autonomous system cannot
   currently verify compaction — this requires a manual checkpoint or an integrated
   compaction sensor (nuclear density gauge or GPS-based compaction monitoring).

4. **RTK GPS simulation is idealised.** The simulation assumes ±2cm accuracy throughout.
   Real mines experience multipath errors near pit walls, tree canopy, and atmospheric delay.

5. **Regulatory compliance log is not cryptographically signed.** Logs are not
   tamper-evident. Production deployment would require HSM-backed timestamps for
   DGMS/MoEF&CC regulatory admissibility.

6. **P2P safe zone re-validation is not implemented.** In the valley fill scenario,
   the fill surface rises with each dump. A safe zone stable at shift start may become
   over-height by midday. Dynamic re-validation is not yet built.

7. **Weather forecasting integration is not implemented.** The DSDE reacts to current
   conditions, not predicted conditions. Integrating a local weather forecast API would
   allow the system to pre-switch strategies before rain begins, not after.

---

# CHAPTER 12 — RESEARCH VERIFICATION CHECKLIST

Before finalising any scenario's design:

- [ ] Truck specs confirmed at **cat.com** for the exact model used in the scenario
- [ ] Mine confirmed on **Google Earth** — dump area visible in satellite imagery
- [ ] Cat MineStar Command for hauling confirmed compatible at **cat.com/mining**
- [ ] Indian regulations confirmed at **dgms.gov.in** and **moef.gov.in**

| Scenario | Mine | Coordinates | Primary regulation |
|---|---|---|---|
| 1 | Gevra Mine, Korba | 22.14°N, 82.56°E | MoEF&CC slope ≤28°, DGMS drainage |
| 2 | Noamundi, Jharkhand | 22.11°N, 85.50°E | DGMS vehicle separation |
| 3 | Odisha valley | ~20.5°N, 83.5°E | DGMS Lalmatia inquiry; GR141 |
| 4 | Ariyalur, Tamil Nadu | 11.14°N, 79.08°E | MMDR Act boundary compliance |
| 5 | Khetri Copper, Rajasthan | 28.01°N, 75.80°E | DGMS slope; night ops rules |
| 6 | Bailadila, Chhattisgarh | 18.73°N, 81.36°E | ROM pad access, NMDC operational |
| 7 | Bowen Basin, Queensland | 22.50°S, 148.50°E | WA Mines Safety Inspection Act |
| 8 | System-level scenario | N/A | N/A |

---

*Document: ADPS Complete Context Transfer — Final Master Version*
*Covers: Every conversation, correction, design decision, and build instruction*
*Prototype: https://optimaldumping.onrender.com*
*Agentic IDE: Antigravity (Google) — share GitHub repo before executing build plan*
*Status: Prototype live. All 12 changes await implementation.*
