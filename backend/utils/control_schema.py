"""
Phase-1 canonical control schema + deterministic UI/API → control mapping.

This module is **standalone**: safe to delete or stop importing if the approach changes.
It does not alter MuseCoco inference by itself — use outputs for logging, evaluation,
or future rule layers.

Frontend (New generation) typically sends:
  prompt, instrument, key, tempo, time_signature, bars, danceability, rhythm_intensity
→ :class:`schemas.GenerationControls` + optional :class:`schemas.GenerationContext`.

Refine mode uses :class:`schemas.ArvaeControls` for note_density / rhy_complexity / pitch_range / contour.
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional, Tuple, Union

from schemas import ArvaeControls, GenerationContext, GenerationControls, GenerationRequest

# ---------------------------------------------------------------------------
# Step 1 — structured schema (documentation + optional runtime validation)
# ---------------------------------------------------------------------------
# Keys are *canonical* names used in thesis/evaluation. ``range`` uses MIDI for pitch,
# quarterLength for duration (music21 convention: 1.0 = quarter note).

CONTROL_SCHEMA: Dict[str, Dict[str, Any]] = {
    "key": {"type": "categorical", "description": "tonality / mode string"},
    "instrument": {"type": "categorical", "description": "I1s2 family token or substring"},
    "tempo": {"type": "value", "range": [0.0, 1.0], "description": "MuseCoco T1s1 bucket input"},
    "time_signature": {"type": "categorical", "description": 'e.g. "4/4", "3/4"'},
    "bars": {"type": "value", "range": [1, 512], "description": "target length (bars)"},
    "density": {
        "type": "value",
        "range": [0.0, 1.0],
        "description": "Refine: note_density; New: proxied by danceability (see mapper note)",
    },
    "rhythm_complexity": {
        "type": "value",
        "range": [0.0, 1.0],
        "description": "Refine: rhy_complexity; New: rhythm_intensity",
    },
    "pitch_range": {
        "type": "range",
        "min": 0,
        "max": 127,
        "description": "MIDI note bounds (deterministic mapping from refine pitch_range slider)",
    },
    "duration_range": {
        "type": "range",
        "bins_quarter_length": [0.25, 0.5, 1.0, 2.0],
        "description": "min/max note length in quarter lengths; mapped from rhythm slider",
    },
    "prompt": {"type": "categorical", "description": "free text → Stage1 (not a hard constraint)"},
}


def _clamp01(x: float) -> float:
    return max(0.0, min(1.0, float(x)))


def map_pitch_slider_to_midi_range(
    pitch_range_slider: float,
    *,
    center_midi: int = 60,
) -> Tuple[int, int]:
    """
    Deterministic mapping aligned with ``post_operation/refine/control_mapping.py`` spirit:
    ``range_semitones = 5 + round(7 * pitch_range)`` → [center±range].
    """
    pr = _clamp01(pitch_range_slider)
    range_semitones = 5 + int(round(7 * pr))
    lo = max(0, min(127, center_midi - range_semitones))
    hi = max(0, min(127, center_midi + range_semitones))
    if lo > hi:
        lo, hi = hi, lo
    return lo, hi


def map_rhythm_to_duration_range_ql(rhythm_01: float) -> Tuple[float, float]:
    """
    Map a single [0,1] rhythm control to (min_ql, max_ql) allowed duration span.
    Uses fixed bins in quarter lengths: 16th, 8th, quarter, half.
    """
    bins: Tuple[float, ...] = (0.25, 0.5, 1.0, 2.0)
    r = _clamp01(rhythm_01)
    # Spread increases with r: low r → narrow window; high r → full span
    idx = int(round(r * float(len(bins) - 1)))
    idx = max(0, min(len(bins) - 1, idx))
    lo_i = max(0, idx - 1)
    return (bins[lo_i], bins[idx])


def map_generation_controls_to_canonical(
    gen: Optional[GenerationControls],
    *,
    prompt: Optional[str] = None,
    context: Optional[GenerationContext] = None,
) -> Dict[str, Any]:
    """
    Map API ``GenerationControls`` (+ optional context) to a flat canonical dict.

    For New/Continue, ``density`` is **proxied** by ``danceability`` (same [0,1] scale)
    until a dedicated density field exists on ``GenerationControls``.
    """
    out: Dict[str, Any] = {
        "schema_version": "1.0",
        "prompt": (prompt or "").strip() or None,
    }
    if gen is not None:
        g = gen.model_dump(exclude_none=False)
        out["key"] = g.get("key")
        out["instrument"] = g.get("instrument")
        out["tempo"] = g.get("tempo")
        out["time_signature"] = g.get("time_signature")
        out["bars"] = g.get("bars")
        out["danceability"] = g.get("danceability")
        out["rhythm_intensity"] = g.get("rhythm_intensity")
        # Canonical aliases (deterministic)
        d = g.get("danceability")
        out["density"] = float(d) if d is not None else None  # MVP proxy for "density"
        ri = g.get("rhythm_intensity")
        out["rhythm_complexity"] = float(ri) if ri is not None else None
        # No pitch/duration sliders on GenerationControls — leave explicit None
        out["pitch_range_midi"] = None
        out["duration_range_quarter_length"] = None

    if context is not None:
        out["context_bpm"] = int(context.bpm)
        out["context_time_signature"] = context.time_signature
        out["context_length_bars"] = int(context.length_bars)
        out["context_start_bar"] = int(context.start_bar)

    return out


def map_arvae_to_canonical(arvae: Optional[ArvaeControls]) -> Dict[str, Any]:
    """Refine sliders → canonical density / rhythm / pitch / duration fields."""
    out: Dict[str, Any] = {}
    if arvae is None:
        return out
    a = arvae
    out["note_density"] = float(a.note_density)
    out["rhy_complexity"] = float(a.rhy_complexity)
    out["pitch_range_slider"] = float(a.pitch_range)
    out["contour"] = float(a.contour)
    out["density"] = float(a.note_density)
    out["rhythm_complexity"] = float(a.rhy_complexity)
    lo, hi = map_pitch_slider_to_midi_range(a.pitch_range)
    out["pitch_range_midi"] = {"min": lo, "max": hi}
    d0, d1 = map_rhythm_to_duration_range_ql(a.rhy_complexity)
    out["duration_range_quarter_length"] = {"min": d0, "max": d1}
    return out


def map_request_to_canonical_control(request: GenerationRequest) -> Dict[str, Any]:
    """
    Single entry point: combine generation (+context) and refine (arvae) into one dict.

    Refine mode: ``arvae`` overrides ``density`` / ``rhythm_complexity`` and fills pitch/duration.
    """
    base = map_generation_controls_to_canonical(
        request.generation,
        prompt=request.prompt,
        context=request.context,
    )
    arv = map_arvae_to_canonical(request.arvae)
    merged = {**base, **arv}
    merged["mode"] = request.mode
    # Transformation (or legacy ``refine``): prefer arvae-derived density/rhythm/pitch/duration
    _m = request.mode or "new"
    if _m == "refine":
        _m = "transformation"
    if _m == "transformation" and request.arvae is not None:
        merged["density"] = float(request.arvae.note_density)
        merged["rhythm_complexity"] = float(request.arvae.rhy_complexity)
    return merged


def control_schema_summary() -> Dict[str, Any]:
    """Return schema + version for /health or debug."""
    return {
        "control_schema_version": "1.0",
        "control_schema": CONTROL_SCHEMA,
    }
