from __future__ import annotations

from dataclasses import replace
from typing import Dict, List, Optional, Tuple

from refine.transform_engine import MelodyTransformEvent


def snap_pitch_to_scale_nearest(pitch: int, scale_pitch_classes: set[int]) -> int:
    """If already in scale, return ``pitch``; else nearest by semitone distance (tie → lower)."""
    pc = pitch % 12
    if pc in scale_pitch_classes:
        return pitch
    best_p = pitch
    best_d = 12
    for d in range(1, 12):
        for sign in (-1, 1):
            p = pitch + sign * d
            if (p % 12) in scale_pitch_classes:
                if d < best_d or (d == best_d and p < best_p):
                    best_d = d
                    best_p = p
    return best_p


def snap_pitch_to_stable_tone_nearest(
    pitch: int,
    tonic_pc: int,
    mode: str,
) -> int:
    """
    Snap to nearest MIDI pitch in 0..127 whose class is I‑chord tone.

    Major: tonic, mediant, dominant (0, 4, 7). Minor: (0, 3, 7). Tie → lower pitch.
    """
    r = tonic_pc % 12
    m = mode.lower().strip()
    if m == "minor":
        stable_pcs = {r, (r + 3) % 12, (r + 7) % 12}
    else:
        stable_pcs = {r, (r + 4) % 12, (r + 7) % 12}

    if (pitch % 12) in stable_pcs:
        return max(0, min(127, pitch))

    best_p = pitch
    best_d = 200
    for p in range(0, 128):
        if (p % 12) not in stable_pcs:
            continue
        d = abs(p - pitch)
        if d < best_d or (d == best_d and p < best_p):
            best_d = d
            best_p = p
    return best_p


def apply_tonal_constraints(
    events: List[MelodyTransformEvent],
    *,
    scale_pitch_classes: set[int],
    tonic_pc: int,
    mode: str,
    strong_beat_tonic_triad_snap: bool = True,
    nudge_weak_repeated_pitch: bool = False,
) -> Tuple[List[MelodyTransformEvent], Dict[str, object]]:
    """
    Post-transform tonal tidy: **always** diatonic first, optionally strong beats lean to I‑chord.

    Order per note:

    1. ``snap_pitch_to_scale_nearest`` — guarantees pitch class is in ``scale_pitch_classes``.
    2. If strong beat (``>= 0.85``) and ``strong_beat_tonic_triad_snap``: I‑chord snap
       plus final scale safety net.
    3. Without triad snap, strong beats keep step 1 only (still diatonic).

    Does not change onset, duration, velocity, or beat_strength.

    When ``nudge_weak_repeated_pitch`` is True, weak-beat notes that would repeat the
    previous output pitch are nudged to a nearby scale tone (reduces static reiterations).
    """
    n = len(events)
    time_order = sorted(
        range(n),
        key=lambda i: (events[i].onset_quarter, events[i].bar_index),
    )
    new_by_index: Dict[int, int] = {}
    corrected = 0
    strong_c = 0
    weak_c = 0
    nudge_count = 0
    prev_out: Optional[int] = None

    for ii in time_order:
        ev = events[ii]
        old = ev.pitch
        new_p = snap_pitch_to_scale_nearest(old, scale_pitch_classes)

        if float(ev.beat_strength) >= 0.85:
            if strong_beat_tonic_triad_snap:
                new_p = snap_pitch_to_stable_tone_nearest(new_p, tonic_pc, mode)
                new_p = snap_pitch_to_scale_nearest(new_p, scale_pitch_classes)
            if new_p != old:
                strong_c += 1
        else:
            if new_p != old:
                weak_c += 1

        if (
            nudge_weak_repeated_pitch
            and prev_out is not None
            and float(ev.beat_strength) < 0.85
            and new_p == prev_out
        ):
            for delta in (-2, -1, 1, 2):
                cand = snap_pitch_to_scale_nearest(new_p + delta, scale_pitch_classes)
                if cand != new_p:
                    new_p = cand
                    nudge_count += 1
                    break

        final_p = int(new_p)
        if final_p != old:
            corrected += 1
        new_by_index[ii] = final_p
        prev_out = final_p

    out = [replace(events[i], pitch=new_by_index[i]) for i in range(n)]

    stats: Dict[str, object] = {
        "enabled": True,
        "num_events": len(events),
        "num_pitch_corrected": corrected,
        "num_strong_beat_corrections": strong_c,
        "num_weak_beat_corrections": weak_c,
        "strong_beat_tonic_triad_snap": strong_beat_tonic_triad_snap,
        "nudge_weak_repeated_pitch": nudge_weak_repeated_pitch,
        "num_weak_repeat_nudges": nudge_count,
    }
    return out, stats
