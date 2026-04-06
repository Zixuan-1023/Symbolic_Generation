"""
Phase-2/3 rule layer: key enforcement, density cap, pitch-range octave wrap.

Phase 4: fixed ``rule_layer`` JSON fields for thesis / debugging (see :func:`apply_rule_layer`).

**Phase 3:** rules run on a **bar grid** — ``piece[track][bar]`` is a music21
:class:`~music21.stream.Measure`; each bar is processed in order (pitch range → key → density).

Enable from server with env ``BACKEND_RULE_LAYER=1``.
"""
from __future__ import annotations

import os
import sys
from pathlib import Path
from typing import Any, Dict, Optional, Set, Tuple

import music21

# ``clean_up`` / ``analysis`` live under ``post_operation/`` (same parent as ``rules/``).
_PO_ROOT = Path(__file__).resolve().parents[1]
if str(_PO_ROOT) not in sys.path:
    sys.path.insert(0, str(_PO_ROOT))

from analysis.key_detection import detect_key_music21
from clean_up.hard_constraints import parse_target_key
from clean_up.tonal_correction import build_scale_pitch_classes

from post_operation.rules.density_control import enforce_density_on_score
from post_operation.rules.key_enforcement import enforce_key_on_score
from post_operation.rules.metrics import (
    bars_touched_count,
    count_in_key_pitch_events,
    count_out_of_range_pitch_events,
    mean_onsets_per_bar,
)
from post_operation.rules.pitch_range import enforce_pitch_range_on_score


def _load_score(path: str) -> music21.stream.Score:
    obj = music21.converter.parse(path)
    if isinstance(obj, music21.stream.Score):
        return obj
    if isinstance(obj, music21.stream.Opus):
        return obj.mergeScores()
    s = music21.stream.Score()
    s.insert(0, obj)
    return s


def resolve_key_tonic_mode(key_str: Optional[str]) -> Tuple[int, str]:
    if key_str and str(key_str).strip():
        return parse_target_key(str(key_str).strip())
    raise ValueError("empty key")


def _rule_layer_error(message: str) -> Dict[str, Any]:
    """Fixed schema when the rule layer does not complete successfully."""
    return {
        "enabled": False,
        "error": message,
        "key_notes_before": None,
        "key_notes_after": None,
        "density_before": None,
        "density_after": None,
        "pitch_out_of_range_before": None,
        "pitch_out_of_range_after": None,
        "bars_touched": None,
        "input": None,
        "output": None,
        "steps": [],
        "key_source": None,
        "key_enforcement_error": None,
    }


def _try_resolve_scale_pcs(
    inp: str, key_str: Optional[str]
) -> Tuple[Optional[Set[int]], Optional[str]]:
    """
    Same tonic/mode as enforcement: request key else detect from MIDI path.
    Returns ``(scale_pcs, key_source)`` or ``(None, None)`` if resolution fails.
    """
    try:
        if key_str and str(key_str).strip():
            tonic_pc, mode = resolve_key_tonic_mode(key_str)
            pcs = build_scale_pitch_classes(int(tonic_pc), mode)
            return pcs, "request"
        det = detect_key_music21(inp)
        tonic_pc = int(det["tonic_pc"])
        mode = str(det["mode"])
        pcs = build_scale_pitch_classes(tonic_pc, mode)
        return pcs, "detected"
    except Exception:
        return None, None


def apply_rule_layer(
    input_midi_path: str,
    output_midi_path: str,
    *,
    key_str: Optional[str] = None,
    density_01: Optional[float] = None,
    pitch_low_midi: Optional[int] = None,
    pitch_high_midi: Optional[int] = None,
    enable_key: bool = True,
    enable_density: bool = True,
    enable_pitch_range: bool = True,
) -> Dict[str, Any]:
    """
    For each non-drum track and each bar, apply **pitch range → key → density**
    (density last so it operates on final pitches).

    Returns a **fixed-schema** dict (Phase 4): ``enabled``, ``error``,
    ``key_notes_before`` / ``key_notes_after`` — counts of **in-key** pitch events
    (each ``Note`` and each ``Chord`` tone); ``density_*`` — mean Note+Chord onsets
    per bar cell; ``pitch_out_of_range_*`` — counts of pitches outside
    ``[pitch_low, pitch_high]``; ``bars_touched``; optional ``steps`` (per-rule debug).
    """
    inp = str(Path(input_midi_path).resolve())
    out = str(Path(output_midi_path).resolve())

    pl = pitch_low_midi
    ph = pitch_high_midi
    if pl is None:
        pl = int(os.environ.get("BACKEND_RULE_PITCH_LOW", "36").strip())
    if ph is None:
        ph = int(os.environ.get("BACKEND_RULE_PITCH_HIGH", "84").strip())

    d = density_01
    if d is None:
        d = float(os.environ.get("BACKEND_RULE_DEFAULT_DENSITY", "0.5").strip())

    try:
        score = _load_score(inp)
        scale_pcs, key_src = _try_resolve_scale_pcs(inp, key_str)

        bars = bars_touched_count(score)
        pitch_b = count_out_of_range_pitch_events(score, pl, ph)
        dens_b = round(mean_onsets_per_bar(score), 4)
        if scale_pcs is not None:
            key_b = count_in_key_pitch_events(score, scale_pcs)
        else:
            key_b = None

        stats: Dict[str, Any] = {"input": inp, "steps": []}

        if enable_pitch_range:
            st = enforce_pitch_range_on_score(score, low_midi=pl, high_midi=ph)
            stats["steps"].append(st)

        if enable_key:
            try:
                if key_str and str(key_str).strip():
                    tonic_pc, mode = resolve_key_tonic_mode(key_str)
                else:
                    det = detect_key_music21(inp)
                    tonic_pc = int(det["tonic_pc"])
                    mode = str(det["mode"])
                st = enforce_key_on_score(score, tonic_pc=tonic_pc, mode=mode)
                stats["steps"].append(st)
                stats["key_source"] = "request" if key_str else "detected"
            except Exception as e:
                stats["key_enforcement_error"] = str(e)

        if enable_density:
            st = enforce_density_on_score(score, density_01=float(d))
            stats["steps"].append(st)

        pitch_a = count_out_of_range_pitch_events(score, pl, ph)
        dens_a = round(mean_onsets_per_bar(score), 4)
        if scale_pcs is not None:
            key_a = count_in_key_pitch_events(score, scale_pcs)
        else:
            key_a = None

        score.write("midi", fp=out)

        return {
            "enabled": True,
            "error": None,
            "key_notes_before": key_b,
            "key_notes_after": key_a,
            "density_before": dens_b,
            "density_after": dens_a,
            "pitch_out_of_range_before": pitch_b,
            "pitch_out_of_range_after": pitch_a,
            "bars_touched": bars,
            "input": inp,
            "output": out,
            "steps": stats["steps"],
            "key_source": stats.get("key_source") or key_src,
            "key_enforcement_error": stats.get("key_enforcement_error"),
        }
    except Exception as e:
        err = _rule_layer_error(str(e))
        err["input"] = inp
        return err


def rule_layer_failure(message: str, input_path: Optional[str] = None) -> Dict[str, Any]:
    """Same fixed schema as a failed :func:`apply_rule_layer` (for server fallback)."""
    err = _rule_layer_error(message)
    if input_path is not None:
        err["input"] = input_path
    return err
