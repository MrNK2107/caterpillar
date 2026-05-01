from __future__ import annotations

from typing import Callable, Dict

from .s1_grid_strategy import get_assignment as get_s1_assignment
from .s2_polygon_aware_grid import get_assignment as get_s2_assignment
from .s3_adaptive_strategy import get_assignment as get_s3_assignment
from .s4_polygon_constrained_adaptive import get_assignment as get_s4_assignment
from .s5_p2p_coordination_strategy import get_assignment as get_s5_assignment
from .s6_safety_modifier import get_assignment as get_s6_assignment
from .s7_fallback_strategy import get_assignment as get_s7_assignment


StrategyGetter = Callable[[object, object], object]

STRATEGY_GETTERS: Dict[str, StrategyGetter] = {
    "S1": get_s1_assignment,
    "S2": get_s2_assignment,
    "S3": get_s3_assignment,
    "S4": get_s4_assignment,
    "S5": get_s5_assignment,
    "S6": get_s6_assignment,
    "S7": get_s7_assignment,
}


def get_strategy_getter(strategy_name: str) -> StrategyGetter:
    try:
        return STRATEGY_GETTERS[strategy_name]
    except KeyError as error:
        allowed = ", ".join(sorted(STRATEGY_GETTERS))
        raise ValueError(f"Unknown DSDE strategy '{strategy_name}'. Allowed strategies: {allowed}") from error