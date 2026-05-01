"""Strategy modules for dump assignment v2."""

from .s1_grid_strategy import get_assignment as get_s1_assignment
from .s2_polygon_aware_grid import get_assignment as get_s2_assignment
from .s3_adaptive_strategy import get_assignment as get_s3_assignment
from .s4_polygon_constrained_adaptive import get_assignment as get_s4_assignment
from .s5_p2p_coordination_strategy import get_assignment as get_s5_assignment
from .s6_safety_modifier import get_assignment as get_s6_assignment
from .s7_fallback_strategy import get_assignment as get_s7_assignment

__all__ = [
    "get_s1_assignment",
    "get_s2_assignment",
    "get_s3_assignment",
    "get_s4_assignment",
    "get_s5_assignment",
    "get_s6_assignment",
    "get_s7_assignment",
]