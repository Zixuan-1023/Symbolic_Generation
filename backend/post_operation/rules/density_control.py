"""
Rule 2 — Density control (MVP): per measure, per non-drum track, cap note/chord count.

Bar-aware: :func:`enforce_density_on_bar` is the unit of adjustment (Phase 3).

If count > target_onsets_per_bar: remove shortest-duration events first (then weakest beat if tie).
Does not insert notes when below target (safe default for thesis).
"""
from __future__ import annotations

import sys
from pathlib import Path
from typing import Any, Dict, List, Tuple

_PO_ROOT = Path(__file__).resolve().parents[1]
if str(_PO_ROOT) not in sys.path:
    sys.path.insert(0, str(_PO_ROOT))

import music21
from music21 import chord as m21chord
from music21 import note as m21note
from music21 import stream

from post_operation.rules.bar_structure import build_piece_bar_grid, iter_bars


def _beat_strength_simple(offset_in_bar: float, bar_ql: float) -> float:
    """Match refine-style 16-step strength (0.4–1.0)."""
    if bar_ql <= 1e-6:
        return 0.4
    pos = (offset_in_bar % bar_ql) / bar_ql
    step = int(min(15, pos * 16.0))
    if step == 0:
        return 1.0
    if step == 8:
        return 0.8
    if step in (4, 12):
        return 0.6
    return 0.4


def density_target_onsets_per_bar(density_01: float) -> int:
    """Map [0,1] to low/mid/high onset budget per bar."""
    d = max(0.0, min(1.0, float(density_01)))
    if d < 1.0 / 3.0:
        return 4
    if d < 2.0 / 3.0:
        return 8
    return 16


def enforce_density_on_bar(
    measure: stream.Measure,
    *,
    target_onsets_per_bar: int,
) -> Dict[str, Any]:
    """
    If this bar has more Note/Chord onsets than ``target``, drop excess (shortest / weakest first).
    """
    target = int(target_onsets_per_bar)
    bar_ql = float(measure.barDuration.quarterLength) if measure.barDuration else 4.0
    candidates: List[Tuple[Any, float, float]] = []
    for el in measure.recurse():
        if not isinstance(el, (m21note.Note, m21chord.Chord)):
            continue
        try:
            off = float(el.offset)
        except Exception:
            off = 0.0
        dur = float(el.duration.quarterLength)
        bs = _beat_strength_simple(off, bar_ql)
        candidates.append((el, dur, bs))

    if len(candidates) <= target:
        return {"removed_note_events": 0, "reduced": False}

    candidates.sort(key=lambda t: (t[1], t[2]))
    n_remove = len(candidates) - target
    removed = 0
    for i in range(n_remove):
        el = candidates[i][0]
        site = el.activeSite
        if site is not None:
            try:
                site.remove(el)
                removed += 1
            except Exception:
                pass

    return {"removed_note_events": removed, "reduced": removed > 0}


def enforce_density_on_score(
    score: music21.stream.Score,
    *,
    density_01: float,
) -> Dict[str, Any]:
    """Apply :func:`enforce_density_on_bar` to every bar of every non-drum track."""
    target = density_target_onsets_per_bar(density_01)
    piece = build_piece_bar_grid(score)
    removed = 0
    measures_touched = 0
    bars_touched = 0

    for _ti, _bi, bar in iter_bars(piece):
        bars_touched += 1
        st = enforce_density_on_bar(bar, target_onsets_per_bar=target)
        r = int(st["removed_note_events"])
        removed += r
        if st.get("reduced"):
            measures_touched += 1

    return {
        "rule": "density_control",
        "target_onsets_per_bar": target,
        "density_01": float(density_01),
        "bars_touched": bars_touched,
        "removed_note_events": removed,
        "measures_reduced": measures_touched,
    }
