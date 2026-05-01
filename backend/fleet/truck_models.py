from __future__ import annotations

from typing import Dict, Mapping, Union

from pydantic import BaseModel


class TruckModel(BaseModel):
    model_name: str
    payload_tonnes: float
    width_m: float
    length_m: float
    turning_radius_m: float
    pile_length_m: float
    pile_width_m: float


TRUCK_MODEL_REGISTRY: Dict[str, TruckModel] = {
    "Cat 777G": TruckModel(
        model_name="Cat 777G",
        payload_tonnes=100,
        width_m=7.4,
        length_m=11.7,
        turning_radius_m=12.8,
        pile_length_m=5.5,
        pile_width_m=4.5,
    ),
    "Cat 785": TruckModel(
        model_name="Cat 785",
        payload_tonnes=139,
        width_m=8.2,
        length_m=12.8,
        turning_radius_m=14.2,
        pile_length_m=7.0,
        pile_width_m=5.5,
    ),
    "Cat 789D": TruckModel(
        model_name="Cat 789D",
        payload_tonnes=181,
        width_m=8.8,
        length_m=13.5,
        turning_radius_m=15.8,
        pile_length_m=8.0,
        pile_width_m=6.2,
    ),
    "Cat 793F": TruckModel(
        model_name="Cat 793F",
        payload_tonnes=227,
        width_m=9.3,
        length_m=15.5,
        turning_radius_m=17.5,
        pile_length_m=9.0,
        pile_width_m=7.0,
    ),
    "Cat 797F": TruckModel(
        model_name="Cat 797F",
        payload_tonnes=363,
        width_m=9.8,
        length_m=15.1,
        turning_radius_m=18.5,
        pile_length_m=11.0,
        pile_width_m=8.5,
    ),
    "Cat 794 AC": TruckModel(
        model_name="Cat 794 AC",
        payload_tonnes=290,
        width_m=9.5,
        length_m=15.0,
        turning_radius_m=17.8,
        pile_length_m=10.0,
        pile_width_m=7.8,
    ),
}


def get_truck_model(model_name: str) -> TruckModel:
    model = TRUCK_MODEL_REGISTRY.get(model_name)
    if not model:
        allowed = ", ".join(sorted(TRUCK_MODEL_REGISTRY.keys()))
        raise ValueError(f"Unsupported truck model '{model_name}'. Allowed AHS models: {allowed}")
    # Return a detached copy so callers cannot mutate the shared registry object.
    return TruckModel.parse_obj(model.dict())


def resolve_truck_model(value: Union[str, TruckModel, Mapping[str, object]]) -> TruckModel:
    """
    Resolve incoming API payload to a canonical AHS-compatible TruckModel.
    Only models from TRUCK_MODEL_REGISTRY are accepted.
    """
    if isinstance(value, str):
        return get_truck_model(value)

    if isinstance(value, TruckModel):
        canonical = get_truck_model(value.model_name)
        if value.dict() != canonical.dict():
            raise ValueError("Custom truck dimensions are not allowed. Use a registered AHS model.")
        return canonical

    if isinstance(value, Mapping):
        model_name = value.get("model_name")
        if not isinstance(model_name, str):
            raise ValueError("Truck model payload must include model_name")
        canonical = get_truck_model(model_name)
        incoming = TruckModel.parse_obj(value)
        if incoming.dict() != canonical.dict():
            raise ValueError("Custom truck dimensions are not allowed. Use a registered AHS model.")
        return canonical

    raise ValueError("Invalid truck model payload")
