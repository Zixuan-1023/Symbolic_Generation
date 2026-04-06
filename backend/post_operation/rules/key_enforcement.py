"""
Rule 1 — Key enforcement: snap out-of-scale pitches to nearest scale tone (non-drum parts only).
Bar-aware: each ``Measure`` is processed independently (Phase 3).
"""
from __future__ import annotations

import sys
from pathlib import Path
from typing import Any, Dict, Set

_PO_ROOT = Path(__file__).resolve().parents[1]
if str(_PO_ROOT) not in sys.path:
    sys.path.insert(0, str(_PO_ROOT))

import music21
from music21 import chord as m21chord
from music21 import note as m21note
from music21 import stream

from clean_up.tonal_correction import (
    build_scale_pitch_classes,
    nearest_legal_pitch,
)
from clean_up.track_alignment import _is_drum_part

from post_operation.rules.bar_structure import build_piece_bar_grid, iter_bars


def enforce_key_on_bar(
    measure: stream.Measure,
    scale_pcs: Set[int],
    *,
    tie_break: str = "down",
) -> Dict[str, Any]:
    """Snap every Note / Chord in this bar to the nearest diatonic pitch."""
    pitched_events = 0
    out_before = 0
    snapped = 0

    for el in measure.recurse():
        if isinstance(el, m21note.Note):
            pitched_events += 1
            p = int(el.pitch.midi)
            if (p % 12) in scale_pcs:
                continue
            out_before += 1
            new_p = nearest_legal_pitch(p, scale_pcs, tie_break=tie_break)
            if new_p != p:
                el.pitch.midi = new_p
                snapped += 1
        elif isinstance(el, m21chord.Chord):
            pitched_events += 1
            changed = False
            for p in el.pitches:
                midi = int(p.midi)
                if (midi % 12) in scale_pcs:
                    continue
                out_before += 1
                new_m = nearest_legal_pitch(midi, scale_pcs, tie_break=tie_break)
                if new_m != midi:
                    p.midi = new_m
                    changed = True
            if changed:
                snapped += 1

    return {
        "pitched_events": pitched_events,
        "out_of_key_before": out_before,
        "snapped_events": snapped,
    }


def _count_still_out_in_bar(measure: stream.Measure, scale_pcs: Set[int]) -> int:
    still = 0
    for el in measure.recurse():
        if isinstance(el, m21note.Note):
            if (int(el.pitch.midi) % 12) not in scale_pcs:
                still += 1
        elif isinstance(el, m21chord.Chord):
            for p in el.pitches:
                if (int(p.midi) % 12) not in scale_pcs:
                    still += 1
    return still


def enforce_key_on_score(
    score: music21.stream.Score,
    *,
    tonic_pc: int,
    mode: str,
    tie_break: str = "down",
) -> Dict[str, Any]:
    """
    Apply :func:`enforce_key_on_bar` to every bar of every non-drum track, then verify.
    """
    scale_pcs = build_scale_pitch_classes(int(tonic_pc), mode)
    piece = build_piece_bar_grid(score)

    pitched_events = 0
    out_before = 0
    snapped = 0
    bars_touched = 0

    for _ti, _bi, bar in iter_bars(piece):
        bars_touched += 1
        st = enforce_key_on_bar(bar, scale_pcs, tie_break=tie_break)
        pitched_events += int(st["pitched_events"])
        out_before += int(st["out_of_key_before"])
        snapped += int(st["snapped_events"])

    still_out = 0
    for _ti, _bi, bar in iter_bars(piece):
        still_out += _count_still_out_in_bar(bar, scale_pcs)

    return {
        "rule": "key_enforcement",
        "tonic_pc": int(tonic_pc),
        "mode": mode,
        "bars_touched": bars_touched,
        "pitched_events": pitched_events,
        "out_of_key_before": out_before,
        "snapped_events": snapped,
        "still_out_of_key": still_out,
    }


def key_stats_for_score(score: music21.stream.Score, scale_pcs: Set[int]) -> Dict[str, Any]:
    """Compute out-of-key rate for evaluation (before/after)."""
    piece = build_piece_bar_grid(score)
    total = 0
    bad = 0
    for _ti, _bi, bar in iter_bars(piece):
        for el in bar.recurse():
            if isinstance(el, m21note.Note):
                total += 1
                if (int(el.pitch.midi) % 12) not in scale_pcs:
                    bad += 1
            elif isinstance(el, m21chord.Chord):
                for p in el.pitches:
                    total += 1
                    if (int(p.midi) % 12) not in scale_pcs:
                        bad += 1
    rate = float(bad) / float(total) if total else 0.0
    return {"pitch_events": total, "out_of_key": bad, "out_of_key_rate": rate}
