# Graph Report - caterpillar  (2026-05-05)

## Corpus Check
- 133 files · ~92,718 words
- Verdict: corpus is large enough that graph structure adds value.

## Summary
- 820 nodes · 1522 edges · 29 communities detected
- Extraction: 75% EXTRACTED · 25% INFERRED · 0% AMBIGUOUS · INFERRED: 378 edges (avg confidence: 0.68)
- Token cost: 0 input · 0 output

## Graph Freshness
- Built from commit: `ad06bcd8`
- Run `git rev-parse HEAD` and compare to check if the graph is stale.
- Run `graphify update .` after code changes (no API cost).

## Community Hubs (Navigation)
- [[_COMMUNITY_Community 0|Community 0]]
- [[_COMMUNITY_Community 1|Community 1]]
- [[_COMMUNITY_Community 2|Community 2]]
- [[_COMMUNITY_Community 3|Community 3]]
- [[_COMMUNITY_Community 4|Community 4]]
- [[_COMMUNITY_Community 5|Community 5]]
- [[_COMMUNITY_Community 6|Community 6]]
- [[_COMMUNITY_Community 7|Community 7]]
- [[_COMMUNITY_Community 8|Community 8]]
- [[_COMMUNITY_Community 9|Community 9]]
- [[_COMMUNITY_Community 10|Community 10]]
- [[_COMMUNITY_Community 11|Community 11]]
- [[_COMMUNITY_Community 12|Community 12]]
- [[_COMMUNITY_Community 13|Community 13]]
- [[_COMMUNITY_Community 14|Community 14]]
- [[_COMMUNITY_Community 15|Community 15]]
- [[_COMMUNITY_Community 16|Community 16]]
- [[_COMMUNITY_Community 17|Community 17]]
- [[_COMMUNITY_Community 18|Community 18]]
- [[_COMMUNITY_Community 20|Community 20]]
- [[_COMMUNITY_Community 21|Community 21]]
- [[_COMMUNITY_Community 23|Community 23]]
- [[_COMMUNITY_Community 25|Community 25]]
- [[_COMMUNITY_Community 32|Community 32]]
- [[_COMMUNITY_Community 33|Community 33]]
- [[_COMMUNITY_Community 34|Community 34]]
- [[_COMMUNITY_Community 35|Community 35]]
- [[_COMMUNITY_Community 37|Community 37]]
- [[_COMMUNITY_Community 38|Community 38]]

## God Nodes (most connected - your core abstractions)
1. `DumpManager` - 72 edges
2. `TruckAgent` - 54 edges
3. `DSDEDecisionEngine` - 44 edges
4. `cn()` - 44 edges
5. `Point` - 32 edges
6. `SurfaceMap` - 32 edges
7. `HybridAStarPlanner` - 29 edges
8. `ReservationSystem` - 29 edges
9. `TruckModel` - 24 edges
10. `BaseModel` - 22 edges

## Surprising Connections (you probably didn't know these)
- `get_dump_assignment()` --calls--> `get_strategy_getter()`  [INFERRED]
  backend/app/assignment_service.py → backend/strategies_v2/registry.py
- `get_return_route_api()` --calls--> `Point`  [INFERRED]
  backend/app/main.py → backend/app/models.py
- `LocalTruckView` --uses--> `HybridAStarPlanner`  [INFERRED]
  backend/agents/truck_agent.py → backend/geometry/path_planner.py
- `LocalTruckView` --uses--> `SurfaceMap`  [INFERRED]
  backend/agents/truck_agent.py → backend/perception/surface_map.py
- `LocalTruckView` --uses--> `ReservationSystem`  [INFERRED]
  backend/agents/truck_agent.py → backend/simulation/reservation_system.py

## Communities (66 total, 11 thin omitted)

### Community 0 - "Community 0"
Cohesion: 0.06
Nodes (36): assigned_spot(), AssignmentOutcome, get_dump_assignment(), SystemAssignmentState, TruckAssignmentState, _candidate_metadata(), DumpManager, DumpZone (+28 more)

### Community 1 - "Community 1"
Cohesion: 0.05
Nodes (70): _cell_center(), generate_candidate_spots(), _in_polygon(), _local_slope(), _neighbor_heights(), _score_candidate(), inverse_score(), score_candidate() (+62 more)

### Community 2 - "Community 2"
Cohesion: 0.06
Nodes (27): _append_modifier(), _build_modifier_list(), _build_reason(), decide_dump_strategy(), DecisionResult, DSDEState, _fleet_signature(), from_any() (+19 more)

### Community 3 - "Community 3"
Cohesion: 0.08
Nodes (7): LocalTruckView, RuleContext, _to_truck_runtime_state(), TruckAgent, InMemoryV2VProtocol, V2VMessage, ScoreWeights

### Community 4 - "Community 4"
Cohesion: 0.07
Nodes (42): _ensure_registry_built(), get_centralized_assignment(), _path_length_threshold_m(), _polygon_edge_clearance_m(), Centralized Row Planner — S3A and S3B strategies.  S3A (Static Choke / Mixed-Fle, Build the slot registry if not already built.     Returns True if registry is us, S3A/S3B assignment via slot registry.          1. Ensure registry is built (idem, S3A/S3B assignment via slot registry.          1. Ensure registry is built (idem (+34 more)

### Community 5 - "Community 5"
Cohesion: 0.11
Nodes (33): ConnectionManager, p2p_websocket_endpoint(), ActivationBands, ActivationPreconditions, AssignDumpRequest, DegreeSafetyLimits, DSDEThresholds, DumpZoneCreate (+25 more)

### Community 6 - "Community 6"
Cohesion: 0.08
Nodes (40): DSDEDecisionEngine, According to SPEC: Mixed fleet + regular polygon = S3 (not S2), Edge dump requires real-time adaptive strategy., Irregular polygon with homogeneous fleet uses S2., Irregular polygon with mixed fleet uses S4., Mixed fleet with regular polygon uses S3., Wind scatter buffer applied on edge dump with high wind., Low spot priority on wet material. (+32 more)

### Community 7 - "Community 7"
Cohesion: 0.07
Nodes (16): Enum, _avg_payload_t(), _avg_turning_radius_m(), _fleet_pressure_band_from_counts(), _norm(), _queue_pressure_band_from_p95(), Persistent row/slot registry for S3A and S3B.  Implements: - Geometry-correct ro, Emergency pool recovery: move RELEASED state slots back to FREE while         pr (+8 more)

### Community 8 - "Community 8"
Cohesion: 0.06
Nodes (25): assign_dump_spot(), complete_dump(), create_dump_zone(), get_return_route_api(), get_state_v1(), get_system_status(), init_yard(), list_scenarios() (+17 more)

### Community 10 - "Community 10"
Cohesion: 0.07
Nodes (16): getCtx(), playCollisionWarning(), playDumpSound(), applyDumpToGrid(), createTrucks(), executeBackendStep(), getDemoDumpRadius(), getDemoDumpTarget() (+8 more)

### Community 11 - "Community 11"
Cohesion: 0.12
Nodes (8): _extract_dump_polygon_from_metadata(), _extract_path_points_from_metadata(), _normalize_heading(), Reservation, ReservationSystem, _truck_footprint_polygon(), test_cleanup_stale_by_ttl(), test_intent_commit_abort_flow()

### Community 12 - "Community 12"
Cohesion: 0.14
Nodes (22): applyDump(), buildColumnSlots(), chooseColumnSlot(), clamp(), computeFrontier(), computeStats(), createState(), decideDump() (+14 more)

### Community 13 - "Community 13"
Cohesion: 0.13
Nodes (8): AStarPathfinder, BFS outward from node to find nearest walkable, non-obstacle cell., Remove collinear intermediate waypoints to reduce jitter., Bresenham-style line of sight check on the grid., Pre-compute all grid cells that are inside the polygon OR near the entry point., Adds a single dumped pile as an obstacle. Uses tight 1-cell buffer., SensorSnapshot, SurfaceSensorModel

### Community 14 - "Community 14"
Cohesion: 0.17
Nodes (6): ConflictArbiter, DeadlockEvent, ResolutionPolicy, test_blocked_path_holds_or_yields(), test_clear_path_proceeds(), test_pair_cycle_emits_deadlock_after_window()

### Community 16 - "Community 16"
Cohesion: 0.33
Nodes (8): check_swept_area_conflict(), computeReverseSweep(), normalize_angle(), Check if my swept area intersects with any existing pile footprints.     Return, Check for conflicts between my truck and other trucks' swept areas.     Returns, Computes a 2D swept-area polygon for a reverse maneuver from startPos to targetS, resolve_truck_conflicts(), truck_footprint()

### Community 20 - "Community 20"
Cohesion: 0.43
Nodes (4): getInitialSpacing(), getMaterialProfile(), predictNextSpotSpacing(), updateDynamicSpacingState()

### Community 21 - "Community 21"
Cohesion: 0.6
Nodes (5): _coerce_point(), _entry_to_cell(), is_reachable(), _neighbors(), _traversable()

### Community 25 - "Community 25"
Cohesion: 0.83
Nodes (3): _init_simple_yard(), test_status_exposes_decision_state_and_rejection_summary(), test_truck_assignment_diagnostics_include_assignment_trace()

## Knowledge Gaps
- **71 isolated node(s):** `Truck agent implementations.`, `Invariant recovery:         if anchor candidates are zero while many slots are m`, `Find the best dump spot using DSDE-selected strategy execution.`, `Fire any timeline events that have passed the current simulation time.`, `Initializes the whole yard with a dynamic polygon and entry point.` (+66 more)
  These have ≤1 connection - possible missing edges or undocumented components.
- **11 thin communities (<3 nodes) omitted from report** — run `graphify query` to explore isolated nodes.

## Suggested Questions
_Questions this graph is uniquely positioned to answer:_

- **Why does `DumpManager` connect `Community 0` to `Community 2`, `Community 3`, `Community 5`, `Community 6`, `Community 13`, `Community 14`?**
  _High betweenness centrality (0.147) - this node is a cross-community bridge._
- **Why does `Point` connect `Community 0` to `Community 1`, `Community 2`, `Community 4`, `Community 5`, `Community 7`, `Community 8`, `Community 13`?**
  _High betweenness centrality (0.094) - this node is a cross-community bridge._
- **Why does `TruckAgent` connect `Community 3` to `Community 0`, `Community 2`, `Community 4`, `Community 6`, `Community 11`?**
  _High betweenness centrality (0.087) - this node is a cross-community bridge._
- **Are the 23 inferred relationships involving `DumpManager` (e.g. with `Point` and `Truck`) actually correct?**
  _`DumpManager` has 23 INFERRED edges - model-reasoned connections that need verification._
- **Are the 18 inferred relationships involving `TruckAgent` (e.g. with `V2VMessage` and `HybridAStarPlanner`) actually correct?**
  _`TruckAgent` has 18 INFERRED edges - model-reasoned connections that need verification._
- **Are the 40 inferred relationships involving `DSDEDecisionEngine` (e.g. with `DumpZone` and `DumpManager`) actually correct?**
  _`DSDEDecisionEngine` has 40 INFERRED edges - model-reasoned connections that need verification._
- **Are the 32 inferred relationships involving `str` (e.g. with `.__init__()` and `get_dump_assignment()`) actually correct?**
  _`str` has 32 INFERRED edges - model-reasoned connections that need verification._