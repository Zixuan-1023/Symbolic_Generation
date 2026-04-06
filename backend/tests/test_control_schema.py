"""Tests for utils/control_schema.py (Phase-1 canonical control mapping)."""
from __future__ import annotations

import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[1]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from schemas import (
    ArvaeControls,
    GenerationContext,
    GenerationControls,
    GenerationRequest,
)
from utils.control_schema import (
    CONTROL_SCHEMA,
    map_arvae_to_canonical,
    map_generation_controls_to_canonical,
    map_pitch_slider_to_midi_range,
    map_request_to_canonical_control,
    map_rhythm_to_duration_range_ql,
)


def test_control_schema_has_core_keys():
    for k in ("key", "instrument", "density", "rhythm_complexity", "pitch_range", "duration_range"):
        assert k in CONTROL_SCHEMA


def test_map_pitch_slider_deterministic():
    lo, hi = map_pitch_slider_to_midi_range(0.5)
    lo2, hi2 = map_pitch_slider_to_midi_range(0.5)
    assert (lo, hi) == (lo2, hi2)
    assert lo < hi


def test_map_rhythm_duration_monotonic():
    a0 = map_rhythm_to_duration_range_ql(0.0)
    a1 = map_rhythm_to_duration_range_ql(1.0)
    assert a0[0] <= a1[1]


def test_map_generation_new_ui_fields():
    gen = GenerationControls(
        instrument="piano",
        key="C major",
        tempo=0.5,
        time_signature="4/4",
        bars=8,
        danceability=0.7,
        rhythm_intensity=0.4,
    )
    ctx = GenerationContext(
        bpm=120, time_signature="4/4", start_bar=0, length_bars=8
    )
    d = map_generation_controls_to_canonical(
        gen, prompt="test prompt", context=ctx
    )
    assert d["instrument"] == "piano"
    assert d["key"] == "C major"
    assert d["density"] == 0.7
    assert d["rhythm_complexity"] == 0.4
    assert d["context_bpm"] == 120
    assert d["prompt"] == "test prompt"


def test_map_transformation_overrides_density():
    req = GenerationRequest(
        mode="transformation",
        generation=GenerationControls(danceability=0.1),
        arvae=ArvaeControls(
            note_density=0.9,
            rhy_complexity=0.3,
            pitch_range=0.5,
            contour=0.5,
        ),
    )
    m = map_request_to_canonical_control(req)
    assert m["density"] == 0.9
    assert m["rhythm_complexity"] == 0.3
    assert "min" in m["pitch_range_midi"]


if __name__ == "__main__":
    test_control_schema_has_core_keys()
    test_map_pitch_slider_deterministic()
    test_map_rhythm_duration_monotonic()
    test_map_generation_new_ui_fields()
    test_map_transformation_overrides_density()
    print("ok")
