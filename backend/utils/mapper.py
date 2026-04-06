"""Mapper utilities for translating UI controls to model attributes."""

from typing import Any, Dict

from schemas import GenerationRequest


def clamp01(x: float) -> float:
    return max(0.0, min(1.0, float(x)))


def map_float_to_bin(value: float, num_bins: int) -> int:
    value = clamp01(value)
    return min(int(value * num_bins), num_bins - 1)


# TODO: align with MuseCoco's canonical attribute definitions
BIN_CONFIG: Dict[str, Dict[str, Any]] = {
    "density": {"bins": 10, "key": "density_bin"},
    "tempo": {"bins": 8, "key": "tempo_bin"},
    "bass_energy": {"bins": 5, "key": "bass_energy_bin"},
}


def merge_user_controls(
    request: GenerationRequest, inferred_attributes: Dict[str, Any]
) -> Dict[str, Any]:
    final_attrs = inferred_attributes.copy()

    # New API (`generation`): echoed here for job JSON / logs. MuseCoco Stage2 controls are
    # applied separately in ``apply_generation_overrides_infer_bin`` (infer_test.bin), not
    # via this legacy merge — an empty merge used to mean "no legacy sliders", not "no gen".
    if request.generation is not None:
        ga = (
            request.generation.model_dump(exclude_none=True)
            if hasattr(request.generation, "model_dump")
            else request.generation.dict(exclude_none=True)  # type: ignore[call-arg]
        )
        final_attrs["generation"] = ga

    # ---------- Hard Controls ----------
    hard = None
    if request.controls is not None:
        hard = request.controls.hard
    elif getattr(request, "attributes", None) is not None:
        hard = request.attributes

    if hard is None:
        return final_attrs

    # Density
    cfg = BIN_CONFIG["density"]
    final_attrs[cfg["key"]] = map_float_to_bin(hard.density, cfg["bins"])

    # Tempo
    cfg = BIN_CONFIG["tempo"]
    final_attrs[cfg["key"]] = map_float_to_bin(hard.tempo, cfg["bins"])

    # Bass Energy
    cfg = BIN_CONFIG["bass_energy"]
    final_attrs[cfg["key"]] = map_float_to_bin(hard.bass_energy, cfg["bins"])

    # ---------- Constraints ----------
    constraints = request.controls.constraints if request.controls is not None else None
    if constraints:
        if constraints.key:
            final_attrs["key"] = constraints.key

        if constraints.instrument_id is not None:
            final_attrs["instrument_id"] = int(constraints.instrument_id)

    return final_attrs