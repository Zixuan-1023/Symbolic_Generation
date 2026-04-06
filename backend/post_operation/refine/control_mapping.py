from __future__ import annotations

import os
import math
from typing import Any, Dict

# ---------------------------------------------------------------------------
# Recommended defaults (demo, thesis, UI initial state)
#
#   rhythm_complexity = 0.5
#   pitch_range       = 0.5
#   note_density      = 0.5
#   contour           = 0.5
#   tonal_mode        = scale_only  (always from map_controls_to_refine_params)
#   humanize          = derived from the four sliders (no extra UI field)
#
# Use the DEFAULT_* constants below so CLI / API / docs stay aligned.
# ---------------------------------------------------------------------------
DEFAULT_RHYTHM_COMPLEXITY = 0.5
DEFAULT_PITCH_RANGE = 0.5
DEFAULT_NOTE_DENSITY = 0.5
DEFAULT_CONTOUR = 0.5
DEFAULT_TONAL_MODE = "scale_only"
DEFAULT_HUMANIZE = 0.0


def _clamp01(x: float) -> float:
    return max(0.0, min(1.0, float(x)))

def _nonlinear_unit_interval(
    x: float,
    *,
    mode: str = "gamma",
    gamma: float = 0.85,
    log_k: float = 8.0,
) -> float:
    """
    Non-linear curve in [0, 1] with invariant endpoints:
    - x=0 -> 0
    - x=1 -> 1
    Used for "product feel" so middle sliders are more audible.
    """
    u = _clamp01(x)
    m = (mode or "gamma").strip().lower()
    if m == "log":
        k = max(1e-6, float(log_k))
        return float(math.log1p(k * u) / math.log1p(k))
    # Default: gamma with gamma<1 boosts middle values; gamma>=1 becomes gentler.
    g = float(gamma)
    if g <= 0:
        return u
    return float(u ** g)


def map_controls_to_refine_params(
    rhythm_complexity: float,
    pitch_range: float,
    note_density: float,
    contour: float,
    *,
    center_pitch: float,
) -> Dict[str, Any]:
    """
    Map four UI-style controls in [0, 1] to backend refine parameters.

    Deterministic, no randomness. Intended for single-voice melody input.
    """
    rc = _clamp01(rhythm_complexity)
    pr = _clamp01(pitch_range)
    nd = _clamp01(note_density)
    co = _clamp01(contour)

    motif_variation = 0.02 + 0.28 * rc
    rhythm_variation = 0.00 + 0.12 * rc

    enable_note_merge = nd < 0.60
    merge_strength = (
        (max(0.0, 0.6 - nd) / 0.6) * rhythm_variation if enable_note_merge else 0.0
    )

    range_semitones = 5 + int(round(7 * pr))
    cp = int(round(float(center_pitch)))
    min_pitch = cp - range_semitones
    max_pitch = cp + range_semitones
    min_pitch = max(0, min(127, min_pitch))
    max_pitch = max(0, min(127, max_pitch))
    if min_pitch > max_pitch:
        min_pitch, max_pitch = max_pitch, min_pitch

    tonal_mode = "scale_only"
    enable_motif_variation = motif_variation > 0.05

    # Backend-only expressiveness: same four sliders also drive micro-timing/velocity jitter
    # so a frozen UI still gets audible "humanize" when contour/rhythm/density change.
    try:
        # Default gain is tuned to make humanize visible after MIDI quantization
        # for typical mid-slider UI defaults.
        hz_gain = float(os.environ.get("POST_REFINE_HUMANIZE_GAIN", "1.5").strip())
    except ValueError:
        hz_gain = 1.0
    hz_gain = max(0.0, min(2.0, hz_gain))
    def _env_float(name: str, default: float) -> float:
        try:
            return float(os.environ.get(name, str(default)).strip())
        except ValueError:
            return float(default)

    # "Frozen slider" product feel: non-linear mapping so middle values are
    # more likely to be audible after MIDI quantization, while preserving
    # endpoints (0=off, 1=max).
    nonlin_mode = os.environ.get(
        "POST_REFINE_SLIDER_NONLIN_MODE", "gamma"
    ).strip().lower()
    nonlin_humanize_gamma = _env_float("POST_REFINE_HUMANIZE_SLIDER_GAMMA", 0.85)
    nonlin_pitch_gamma = _env_float("POST_REFINE_PITCH_SLIDER_GAMMA", 0.85)

    # Apply non-linearity to pitch "contour" before converting to pitch_variation.
    co_n = _nonlinear_unit_interval(co, mode=nonlin_mode, gamma=nonlin_pitch_gamma)
    pitch_variation = 0.05 + 0.35 * co_n

    humanize_linear = (0.02 + 0.20 * co + 0.07 * rc + 0.05 * (1.0 - nd)) * hz_gain
    humanize_linear = _clamp01(humanize_linear)
    humanize = _nonlinear_unit_interval(
        humanize_linear,
        mode=nonlin_mode,
        gamma=nonlin_humanize_gamma,
        log_k=8.0,
    )

    def _r(x: float) -> float:
        return round(float(x), 6)

    return {
        "pitch_variation": _r(pitch_variation),
        "rhythm_variation": _r(rhythm_variation),
        "motif_variation": _r(motif_variation),
        "humanize": _r(humanize),
        "enable_note_merge": enable_note_merge,
        "merge_strength": _r(merge_strength),
        "min_pitch": min_pitch,
        "max_pitch": max_pitch,
        "tonal_mode": tonal_mode,
        "enable_motif_variation": enable_motif_variation,
        "force_motif_variation": False,
    }
