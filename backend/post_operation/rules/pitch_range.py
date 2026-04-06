"""
Rule 3 — Pitch range: shift by octaves (±12) until MIDI pitch lies in [low, high].
Bar-aware: each rule applies to one ``Measure`` at a time (Phase 3).
"""
from __future__ import annotations

import sys
from pathlib import Path
from typing import Any, Dict

_PO_ROOT = Path(__file__).resolve().parents[1]
if str(_PO_ROOT) not in sys.path:
    sys.path.insert(0, str(_PO_ROOT))

import music21
from music21 import chord as m21chord
from music21 import note as m21note
from music21 import stream

from clean_up.track_alignment import _is_drum_part

from post_operation.rules.bar_structure import build_piece_bar_grid, iter_bars


def enforce_pitch_range_on_bar(
    measure: stream.Measure,
    *,
    low_midi: int,
    high_midi: int,
) -> Dict[str, Any]:
    """Octave-wrap every Note/Chord inside this bar."""
    lo = max(0, min(127, int(low_midi)))
    hi = max(0, min(127, int(high_midi)))
    if lo > hi:
        lo, hi = hi, lo

    shifted = 0
    events = 0

    for el in measure.recurse():
        if isinstance(el, m21note.Note):
            events += 1
            m = int(el.pitch.midi)
            new_m = _wrap_octave(m, lo, hi)
            if new_m != m:
                el.pitch.midi = new_m
                shifted += 1
        elif isinstance(el, m21chord.Chord):
            events += 1
            chg = False
            for p in el.pitches:
                m = int(p.midi)
                new_m = _wrap_octave(m, lo, hi)
                if new_m != m:
                    p.midi = new_m
                    chg = True
            if chg:
                shifted += 1

    return {
        "pitched_events": events,
        "events_with_octave_shift": shifted,
    }


def enforce_pitch_range_on_score(
    score: music21.stream.Score,
    *,
    low_midi: int = 36,
    high_midi: int = 84,
) -> Dict[str, Any]:
    """Apply :func:`enforce_pitch_range_on_bar` to every bar of every non-drum track."""
    lo = max(0, min(127, int(low_midi)))
    hi = max(0, min(127, int(high_midi)))
    if lo > hi:
        lo, hi = hi, lo

    piece = build_piece_bar_grid(score)
    tot_events = 0
    tot_shifted = 0
    bars_touched = 0

    for _ti, _bi, bar in iter_bars(piece):
        bars_touched += 1
        st = enforce_pitch_range_on_bar(bar, low_midi=lo, high_midi=hi)
        tot_events += int(st["pitched_events"])
        tot_shifted += int(st["events_with_octave_shift"])

    return {
        "rule": "pitch_range",
        "low_midi": lo,
        "high_midi": hi,
        "bars_touched": bars_touched,
        "pitched_events": tot_events,
        "events_with_octave_shift": tot_shifted,
    }


def _wrap_octave(midi: int, lo: int, hi: int) -> int:
    m = midi
    for _ in range(12):
        if lo <= m <= hi:
            return m
        if m < lo:
            m += 12
        elif m > hi:
            m -= 12
    return max(lo, min(hi, m))
