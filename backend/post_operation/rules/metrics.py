"""
Phase-4: stable before/after counters on the non-drum bar grid (thesis + debug).

Pitch event = one MIDI pitch (``Note`` counts 1; each ``Chord`` tone counts 1).
"""
from __future__ import annotations

import sys
from pathlib import Path
from typing import Optional, Set

_PO_ROOT = Path(__file__).resolve().parents[1]
if str(_PO_ROOT) not in sys.path:
    sys.path.insert(0, str(_PO_ROOT))

import music21
from music21 import chord as m21chord
from music21 import note as m21note

from post_operation.rules.bar_structure import build_piece_bar_grid, iter_bars


def iter_pitched_elements(score: music21.stream.Score):
    """Yield (midi_int,) for each pitch event in the bar grid (non-drum only)."""
    piece = build_piece_bar_grid(score)
    for _ti, _bi, bar in iter_bars(piece):
        for el in bar.recurse():
            if isinstance(el, m21note.Note):
                yield int(el.pitch.midi)
            elif isinstance(el, m21chord.Chord):
                for p in el.pitches:
                    yield int(p.midi)


def count_pitch_events(score: music21.stream.Score) -> int:
    return sum(1 for _ in iter_pitched_elements(score))


def count_in_key_pitch_events(
    score: music21.stream.Score, scale_pcs: Set[int]
) -> int:
    n = 0
    for m in iter_pitched_elements(score):
        if (m % 12) in scale_pcs:
            n += 1
    return n


def count_out_of_range_pitch_events(
    score: music21.stream.Score, low_midi: int, high_midi: int
) -> int:
    lo = max(0, min(127, int(low_midi)))
    hi = max(0, min(127, int(high_midi)))
    if lo > hi:
        lo, hi = hi, lo
    n = 0
    for m in iter_pitched_elements(score):
        if m < lo or m > hi:
            n += 1
    return n


def mean_onsets_per_bar(score: music21.stream.Score) -> float:
    """Mean count of Note+Chord *elements* per bar cell (matches density rule onset budget)."""
    piece = build_piece_bar_grid(score)
    counts: list[int] = []
    for _ti, _bi, bar in iter_bars(piece):
        c = sum(
            1
            for el in bar.recurse()
            if isinstance(el, (m21note.Note, m21chord.Chord))
        )
        counts.append(c)
    if not counts:
        return 0.0
    return float(sum(counts)) / float(len(counts))


def bars_touched_count(score: music21.stream.Score) -> int:
    piece = build_piece_bar_grid(score)
    return sum(len(t) for t in piece)


def key_consistency_rate(score: music21.stream.Score, scale_pcs: Optional[Set[int]]) -> Optional[float]:
    """Fraction of pitch events whose pitch class is diatonic; ``None`` if ``scale_pcs`` is None."""
    if scale_pcs is None:
        return None
    total = count_pitch_events(score)
    if total == 0:
        return 1.0
    return float(count_in_key_pitch_events(score, scale_pcs)) / float(total)


def density_deviation(
    score: music21.stream.Score, target_onsets_per_bar: float
) -> float:
    """Absolute deviation of mean onsets/bar from a fixed target (evaluation)."""
    return abs(mean_onsets_per_bar(score) - float(target_onsets_per_bar))


def pitch_range_violation_rate(
    score: music21.stream.Score, low_midi: int, high_midi: int
) -> float:
    total = count_pitch_events(score)
    if total == 0:
        return 0.0
    return float(count_out_of_range_pitch_events(score, low_midi, high_midi)) / float(
        total
    )
