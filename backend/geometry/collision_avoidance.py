import math
from typing import Tuple, List, Sequence
from shapely.geometry import Polygon, Point
from shapely.ops import unary_union

def normalize_angle(theta: float) -> float:
    return math.atan2(math.sin(theta), math.cos(theta))

def truck_footprint(x: float, y: float, heading: float, length_m: float, width_m: float) -> Polygon:
    half_width = width_m / 2.0
    half_length = length_m / 2.0
    
    local_corners = (
        (half_length, half_width),
        (half_length, -half_width),
        (-half_length, -half_width),
        (-half_length, half_width),
    )
    
    cos_h = math.cos(heading)
    sin_h = math.sin(heading)
    world_corners = []
    for lx, ly in local_corners:
        wx = x + (lx * cos_h - ly * sin_h)
        wy = y + (lx * sin_h + ly * cos_h)
        world_corners.append((wx, wy))
        
    return Polygon(world_corners)

def computeReverseSweep(
    startPos: Tuple[float, float],
    startHeading: float,
    targetSpot: Tuple[float, float],
    truckModel: object
) -> Polygon:
    """
    Computes a 2D swept-area polygon for a reverse maneuver from startPos to targetSpot.
    Assumes the truck drives backwards along a circular arc.
    """
    length_m = float(getattr(truckModel, "length_m", getattr(truckModel, "pile_length_m", 12.0)))
    width_m = float(getattr(truckModel, "width_m", getattr(truckModel, "pile_width_m", 8.0)))
    
    x1, y1 = startPos
    x2, y2 = targetSpot
    dx = x2 - x1
    dy = y2 - y1
    d = math.hypot(dx, dy)
    
    if d < 0.1:
        # Basically at the target
        return truck_footprint(x2, y2, startHeading, length_m, width_m).buffer(0.5)

    reverse_heading = startHeading + math.pi
    nx = -math.sin(reverse_heading)
    ny = math.cos(reverse_heading)
    
    denominator = 2.0 * (dx * nx + dy * ny)
    
    path_points: List[Tuple[float, float, float]] = [] # (x, y, heading)
    
    # If denominator is tiny, it's a straight line
    if abs(denominator) < 1e-6:
        steps = max(2, int(d / 1.0))
        steps = min(steps, 200)  # Bound maximum steps
        for i in range(steps + 1):
            t = i / steps
            px = x1 + t * dx
            py = y1 + t * dy
            path_points.append((px, py, startHeading))
    else:
        Rc = (d * d) / denominator
        cx = x1 + Rc * nx
        cy = y1 + Rc * ny
        
        gamma1 = math.atan2(y1 - cy, x1 - cx)
        gamma2 = math.atan2(y2 - cy, x2 - cx)
        
        d_gamma = normalize_angle(gamma2 - gamma1)
        
        # Arc length
        arc_length = abs(Rc * d_gamma)
        steps = max(2, int(arc_length / 1.0))
        steps = min(steps, 200)  # Bound the maximum number of steps to avoid infinite loops
        
        for i in range(steps + 1):
            t = i / steps
            gamma_t = gamma1 + t * d_gamma
            px = cx + abs(Rc) * math.cos(gamma_t)
            py = cy + abs(Rc) * math.sin(gamma_t)
            
            # The tangent angle is gamma_t + pi/2 if Rc > 0 else gamma_t - pi/2
            if Rc > 0:
                tangent = gamma_t + math.pi / 2.0
            else:
                tangent = gamma_t - math.pi / 2.0
                
            # truck heading is tangent - pi (since tangent is reverse direction)
            truck_heading = normalize_angle(tangent - math.pi)
            path_points.append((px, py, truck_heading))
            
    footprints = [truck_footprint(px, py, h, length_m, width_m) for px, py, h in path_points]
    
    sweep_parts = []
    for i in range(1, len(footprints)):
        sweep_parts.append(footprints[i-1].union(footprints[i]).convex_hull)
        
    if not sweep_parts:
        sweep_parts = footprints
        
    final_sweep = unary_union(sweep_parts)
    # Apply the required 0.5m clearance buffer
    return final_sweep.buffer(0.5)


def check_swept_area_conflict(
    my_sweep: Polygon,
    other_footprints: List[Polygon],
) -> bool:
    """
    Check if my swept area intersects with any existing pile footprints.
    Returns True if conflict detected.
    """
    for footprint in other_footprints:
        if my_sweep.intersects(footprint):
            return True
    return False


def resolve_truck_conflicts(
    my_position: Tuple[float, float],
    my_heading: float,
    my_target: Tuple[float, float],
    my_truck_model: object,
    other_trucks: List[dict],
) -> List[dict]:
    """
    Check for conflicts between my truck and other trucks' swept areas.
    Returns list of trucks that should wait (has conflict).
    """
    if not other_trucks:
        return []
    
    my_sweep = computeReverseSweep(my_position, my_heading, my_target, my_truck_model)
    
    # Build other trucks' potential footprints
    other_footprints = []
    pending = []
    
    for truck in other_trucks:
        if not truck.get("assigned_spot"):
            continue
            
        tx = truck["assigned_spot"].get("x", 0)
        ty = truck["assigned_spot"].get("y", 0)
        theading = truck.get("heading", 0.0)
        tmodel = truck.get("model")
        
        if tx and ty and tmodel:
            other_footprints.append(
                truck_footprint(tx, ty, theading,
                getattr(tmodel, "length_m", 12.0),
                getattr(tmodel, "width_m", 8.0)
            )
        else:
            pending.append(truck)
    
    # Check for conflict with my sweep
    conflicts = []
    for i, footprint in enumerate(other_footprints):
        if my_sweep.intersects(footprint):
            if i < len([t for t in other_trucks if t.get("assigned_spot")]):
                conflicts.append(other_trucks[i])
    
    return conflicts
