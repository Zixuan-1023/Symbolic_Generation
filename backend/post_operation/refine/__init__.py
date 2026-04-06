"""Refine mode: local melody transform, tonal constraints, pipeline."""

from refine.control_mapping import (
    DEFAULT_CONTOUR,
    DEFAULT_HUMANIZE,
    DEFAULT_NOTE_DENSITY,
    DEFAULT_PITCH_RANGE,
    DEFAULT_RHYTHM_COMPLEXITY,
    DEFAULT_TONAL_MODE,
    map_controls_to_refine_params,
)
from refine.pipeline import run_refine_pipeline, run_refine_with_controls
from refine.structure_extract import (
    extract_structure,
    extract_structure_from_score,
    get_melody_part,
)
from refine.tonal_postprocess import apply_tonal_constraints
from refine.transform_engine import (
    MelodyTransformEvent,
    extract_melody_events_from_part,
    summarize_melody_extraction,
    transform_melody_events,
)
from refine.types import ExtractedStructure, GeneratorConfig

__all__ = [
    "ExtractedStructure",
    "GeneratorConfig",
    "MelodyTransformEvent",
    "apply_tonal_constraints",
    "extract_melody_events_from_part",
    "summarize_melody_extraction",
    "extract_structure",
    "extract_structure_from_score",
    "get_melody_part",
    "DEFAULT_CONTOUR",
    "DEFAULT_HUMANIZE",
    "DEFAULT_NOTE_DENSITY",
    "DEFAULT_PITCH_RANGE",
    "DEFAULT_RHYTHM_COMPLEXITY",
    "DEFAULT_TONAL_MODE",
    "map_controls_to_refine_params",
    "run_refine_pipeline",
    "run_refine_with_controls",
    "transform_melody_events",
]
