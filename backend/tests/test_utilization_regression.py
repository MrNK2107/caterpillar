from __future__ import annotations

import math

from shapely.geometry import Point, Polygon

from fleet.truck_models import get_truck_model
from perception.surface_map import SurfaceMap
from strategies.candidate_generation import generate_candidate_spots
from strategies_v2.common import directional_centroid_candidates, normalize_system_state, rank_candidates_for_utilization


def test_early_fill_does_not_collapse_into_narrow_ridge() -> None:
    polygon = Polygon([(10.0, 10.0), (110.0, 10.0), (110.0, 110.0), (10.0, 110.0)])
    entry = Point(0.0, 60.0)
    model = get_truck_model("Cat 793F")

    surface_map = SurfaceMap(resolution=1.0)
    surface_map.initialize_grid(polygon.bounds)

    dump_records: list[tuple[float, float, float]] = []
    placements: list[tuple[float, float]] = []

    for step in range(12):
        truck_id = f"T{(step % 3) + 1}"
        system_state = normalize_system_state(
            {
                "surface_map": surface_map,
                "dump_polygon": polygon,
                "entry_point": entry,
                "dump_records": tuple(dump_records),
                "material_type": "ore",
                "material_moisture_pct": 10.0,
                "objective_weights": {
                    "coverage": 1.7,
                    "slope_safety": 1.0,
                    "spacing": 1.3,
                    "lane_spread": 1.1,
                },
            }
        )

        candidates = directional_centroid_candidates(
            system_state=system_state,
            truck_position=(entry.x, entry.y),
            truck_model=model,
            truck_id=truck_id,
            strict_boundary=False,
        )
        if not candidates:
            candidates = generate_candidate_spots(
                surface_map=surface_map,
                dump_polygon=polygon,
                truck_position=(entry.x, entry.y),
                truck_model=model,
                entry_point=entry,
            )
            candidates = rank_candidates_for_utilization(candidates, system_state, truck_id)
        assert candidates, f"no candidate generated at step {step}"
        c = candidates[0]

        placements.append((c.x, c.y))
        radius = math.hypot(model.pile_length_m / 2.0, model.pile_width_m / 2.0)
        dump_records.append((c.x, c.y, radius))
        surface_map.update_after_dump(
            center={"x": c.x, "y": c.y},
            truck_model=model,
            spread_factor=1.0,
            rain_intensity=0.0,
            wind_speed=0.0,
            wind_direction_deg=0.0,
        )

    xs = [p[0] for p in placements]
    ys = [p[1] for p in placements]
    span_x = max(xs) - min(xs)
    span_y = max(ys) - min(ys)
    major = max(span_x, span_y)
    minor = min(span_x, span_y)
    anisotropy_ratio = minor / max(major, 1e-6)

    # Regression gate:
    # Prevent early-fill collapse into a single, thin ridge.
    assert anisotropy_ratio > 0.22, (
        f"early fill too narrow: span_x={span_x:.2f}, span_y={span_y:.2f}, "
        f"anisotropy_ratio={anisotropy_ratio:.3f}"
    )
