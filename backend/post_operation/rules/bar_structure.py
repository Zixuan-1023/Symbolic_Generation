"""
Phase-3 bar-aware layout: ``piece = [ track_0, track_1, ... ]`` where each track is
``[ Measure, Measure, ... ]`` (each ``Measure`` is a music21 bar container with notes inside).

Non-drum parts only; drum tracks are omitted from the grid (rules do not apply there).
"""
from __future__ import annotations

import sys
from pathlib import Path
from typing import List

_PO_ROOT = Path(__file__).resolve().parents[1]
if str(_PO_ROOT) not in sys.path:
    sys.path.insert(0, str(_PO_ROOT))

import music21
from music21 import stream

from clean_up.track_alignment import _is_drum_part

# Type aliases for thesis / API clarity
Bar = stream.Measure
Track = List[Bar]
Piece = List[Track]


def ensure_non_drum_parts_measured(score: music21.stream.Score) -> None:
    """
    Ensure each non-drum ``Part`` is split into ``Measure`` objects.
    Flat streams get ``makeMeasures(inPlace=True)`` so rules see a stable bar grid.
    """
    for part in score.parts:
        if _is_drum_part(part):
            continue
        if part.getElementsByClass(stream.Measure):
            continue
        try:
            part.makeMeasures(inPlace=True)
        except Exception:
            # Rare malformed imports: leave as-is; grid may be empty for this track.
            pass


def build_piece_bar_grid(score: music21.stream.Score) -> Piece:
    """
    Return ``piece[i][j]`` = j-th bar of i-th **non-drum** track (same objects as in the score).
    Call :func:`ensure_non_drum_parts_measured` first if parts may be flat.
    """
    ensure_non_drum_parts_measured(score)
    piece: Piece = []
    for part in score.parts:
        if _is_drum_part(part):
            continue
        measures = list(part.getElementsByClass(stream.Measure))
        piece.append(measures)
    return piece


def iter_bars(piece: Piece):
    """Yield ``(track_index, bar_index, measure)`` for nested-loop rule application."""
    for ti, track in enumerate(piece):
        for bi, bar in enumerate(track):
            yield ti, bi, bar
