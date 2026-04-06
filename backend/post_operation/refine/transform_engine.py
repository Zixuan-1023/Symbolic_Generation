from __future__ import annotations

"""
Local, structure-preserving melody transforms (pitch / split / merge / motif / humanize).

Polyphonic parts are reduced to one line via **onset-group scoring** (v2: highest
pitch for the first onset; later groups balance **top-voice bias** vs **melodic
continuity** instead of always taking the chord top).

This is **not** a generator: it edits extracted monophonic events while keeping
order, bar alignment, and phrase contour broadly intact.
"""

import random
from collections import defaultdict
from dataclasses import dataclass, replace
from typing import Dict, List, Optional, Sequence, Tuple, Union, cast

import music21
from music21 import note


@dataclass
class MelodyTransformEvent:
    onset_quarter: float
    duration_quarter: float
    pitch: int
    velocity: int
    bar_index: int
    beat_strength: float


def _measure_bar_duration_ql(measure: music21.stream.Measure) -> float:
    if hasattr(measure, "barDuration") and measure.barDuration is not None:
        return float(measure.barDuration.quarterLength)
    ts = measure.timeSignature
    if ts is not None:
        return float(ts.barDuration.quarterLength)
    return 4.0


def _beat_strength_at_offset_in_bar(offset_in_bar_ql: float, bar_ql: float) -> float:
    """4/4-style 16-step grid mapped to arbitrary bar length."""
    if bar_ql <= 1e-6:
        return 0.4
    pos = (offset_in_bar_ql % bar_ql) / bar_ql
    step = int(min(15, pos * 16.0))
    if step == 0:
        return 1.0
    if step == 8:
        return 0.8
    if step in (4, 12):
        return 0.6
    return 0.4


def _update_event_position_meta(ev: MelodyTransformEvent) -> MelodyTransformEvent:
    """
    Recompute ``bar_index`` / ``beat_strength`` from ``onset_quarter`` (v1: 4 quarters / bar).
    """
    bar_index = max(0, int(ev.onset_quarter // 4.0))
    offset_in_bar = ev.onset_quarter - 4.0 * float(bar_index)
    beat_strength = _beat_strength_at_offset_in_bar(offset_in_bar, 4.0)
    return replace(ev, bar_index=bar_index, beat_strength=beat_strength)


def _tonic_triad_pcs(tonic_pc: int, mode: str) -> set[int]:
    r = tonic_pc % 12
    if mode.lower().strip() == "minor":
        return {r, (r + 3) % 12, (r + 7) % 12}
    return {r, (r + 4) % 12, (r + 7) % 12}


def _snap_pc_to_scale(pitch: int, scale_pitch_classes: set[int]) -> int:
    if (pitch % 12) in scale_pitch_classes:
        return pitch
    best = pitch
    best_d = 12
    for d in range(1, 12):
        for sign in (-1, 1):
            p = pitch + sign * d
            if (p % 12) in scale_pitch_classes:
                if d < best_d or (d == best_d and p < best):
                    best_d = d
                    best = p
    return best


def summarize_melody_extraction(
    raw_note_count: int,
    grouped_onset_count: int,
    extracted_event_count: int,
) -> Dict[str, int]:
    """Debug counts (subset; v2 extraction adds more keys in ``extract_melody_events_from_part``)."""
    return {
        "raw_note_count": int(raw_note_count),
        "grouped_onset_count": int(grouped_onset_count),
        "extracted_event_count": int(extracted_event_count),
    }


# SNR-style gates (low risk; keep melody simple when stats say so)
SNR_LOW_AVG_LEAP = 2.0
SNR_PITCH_VARIATION_ATTENUATION = 0.5
MIN_BARS_MOTIF_GATE = 4
MIN_NOTES_MOTIF_GATE = 16
MERGE_INTERVAL_VARIANCE_FLOOR = 0.5
MIN_NOTES_FOR_MERGE_VARIANCE_GATE = 3


def _group_highest_midi(group: List[note.Note]) -> int:
    return max(int(n.pitch.midi) for n in group)


def _interval_variance(leaps: List[int]) -> float:
    if len(leaps) < 2:
        return 0.0
    mean = sum(leaps) / float(len(leaps))
    return sum((x - mean) ** 2 for x in leaps) / float(len(leaps))


def melody_line_metrics(events: Sequence[MelodyTransformEvent]) -> Dict[str, float]:
    """
    SNR-style stats on an ordered monophonic line (by onset).

    - ``avg_melodic_leap``: mean |Δpitch| between consecutive notes.
    - ``note_interval_variance``: variance of those |Δpitch| values (low = very regular).
    """
    ordered = sorted(events, key=lambda e: (e.onset_quarter, e.bar_index))
    if len(ordered) < 2:
        return {
            "avg_melodic_leap": 0.0,
            "note_interval_variance": 0.0,
            "num_bars_spanned": float(max((e.bar_index for e in ordered), default=0) + 1),
            "num_notes": float(len(ordered)),
        }
    leaps = [
        abs(ordered[i].pitch - ordered[i - 1].pitch) for i in range(1, len(ordered))
    ]
    avg = sum(leaps) / float(len(leaps))
    var = _interval_variance(leaps)
    nb = max(e.bar_index for e in ordered) + 1
    return {
        "avg_melodic_leap": avg,
        "note_interval_variance": var,
        "num_bars_spanned": float(nb),
        "num_notes": float(len(ordered)),
    }


# Extraction scoring: higher melody_follow → penalize leaps more, less top-voice bias.
def _select_melody_note_from_group(
    group: List[note.Note],
    prev_pitch: int,
    *,
    melody_follow: float = 0.5,
    beat_strength: float = 0.5,
) -> note.Note:
    """
    Pick one note from a same-onset chord: continuity cost + top-voice bonus + leap
    penalties + slight preference for longer duration (lower total score wins).

    ``melody_follow`` in [0, 1] couples to UI ``contour``: higher → stronger leap
    penalty and weaker chord-top preference (smoother line).
    """
    mf = max(0.0, min(1.0, float(melody_follow)))
    bs = max(0.0, min(1.0, float(beat_strength)))

    # Beat-aware scoring:
    # - strong beats: prefer chord-top / harmonic stability, allow less "continuity panic"
    # - weak beats: prefer smooth continuity, penalize large leaps more
    top_voice_bonus = (3.0 - 2.0 * mf) * (0.8 + 0.4 * bs)
    leap_penalty = (2.0 + 4.0 * mf) * (0.8 + 0.6 * (1.0 - bs))

    top_m = _group_highest_midi(group)
    best: Optional[note.Note] = None
    best_score = float("inf")

    for n in group:
        candidate_pitch = int(n.pitch.midi)
        dur = float(n.duration.quarterLength)
        leap = abs(candidate_pitch - prev_pitch)
        is_top_voice = candidate_pitch == top_m

        score = float(leap)
        if is_top_voice:
            score -= top_voice_bonus
        if leap > 7:
            score += 2.0 * leap_penalty
        if leap > 12:
            score += 4.0 * leap_penalty
        score -= 0.1 * dur

        if best is None:
            best = n
            best_score = score
            continue

        if score < best_score - 1e-9:
            best_score = score
            best = n
        elif abs(score - best_score) < 1e-9:
            # Tie-break: slightly prefer higher pitch, then longer note
            if candidate_pitch > int(best.pitch.midi):
                best = n
            elif candidate_pitch == int(best.pitch.midi) and dur > float(best.duration.quarterLength):
                best = n

    assert best is not None
    return best


def _note_onset_in_part(n: music21.note.Note, part: music21.stream.Part) -> float:
    """Quarter offset from the start of ``part`` (global timeline)."""
    try:
        return float(n.getOffsetInHierarchy(part))
    except (AttributeError, TypeError, Exception):
        pass
    try:
        return float(n.offset)
    except (AttributeError, TypeError, Exception):
        return 0.0


def _bar_index_and_beat_strength_from_note(
    part: music21.stream.Part,
    onset_global: float,
    n: note.Note,
) -> Tuple[int, float]:
    measure_number = n.measureNumber
    if measure_number is not None:
        m = part.measure(measure_number)
        if m is not None:
            off_bar = onset_global - float(m.offset)
            bar_ql = _measure_bar_duration_ql(m)
            bar_idx = max(0, int(measure_number) - 1)
            return bar_idx, _beat_strength_at_offset_in_bar(off_bar, bar_ql)
    bar_idx = max(0, int(onset_global // 4.0)) if onset_global >= 0 else 0
    off_bar = onset_global - bar_idx * 4.0
    return bar_idx, _beat_strength_at_offset_in_bar(off_bar, 4.0)


def extract_melody_events_from_part(
    part: music21.stream.Part,
    score: music21.stream.Score,
    *,
    return_stats: bool = False,
    melody_follow: float = 0.5,
) -> Union[
    List[MelodyTransformEvent],
    Tuple[List[MelodyTransformEvent], Dict[str, Union[int, float]]],
]:
    """
    Extract a **monophonic melody line** from a part (e.g. polyphonic piano).

    Notes are grouped by onset (quarters, rounded to 6 decimals). The **first**
    group uses the **highest pitch** (longer duration tie-break). **Later** groups
    use a small scoring heuristic: continuity vs previous pitch, a bonus if the
    candidate is the chord top, penalties for large leaps, and a mild preference
    for longer durations — v2 refine extraction, not full polyphonic reduction.
    ``melody_follow`` ∈ [0, 1] (often tied to UI ``contour``) increases leap
    penalties and reduces top-voice bias for a smoother extracted line.

    ``onset_quarter`` is global offset from the start of the part.
    """
    _ = score  # reserved for future score-level context

    def _element_onset_in_part(el: Any) -> float:
        """Quarter offset from the start of ``part`` for both Note and Chord."""
        try:
            return float(el.getOffsetInHierarchy(part))
        except Exception:
            pass
        try:
            return float(el.offset)
        except Exception:
            return 0.0

    def _chord_to_synth_note(ch: music21.chord.Chord) -> note.Note:
        """Represent a chord as its top pitch for monophonic melody extraction."""
        top_p = max(ch.pitches, key=lambda p: int(p.midi))
        n = note.Note(int(top_p.midi))
        try:
            n.quarterLength = float(ch.duration.quarterLength)
        except Exception:
            n.quarterLength = 1.0
        vel = 80
        try:
            if ch.volume and ch.volume.velocity is not None:
                vel = int(ch.volume.velocity)
        except Exception:
            pass
        vol = music21.volume.Volume()
        vol.velocity = vel
        n.volume = vol
        return n

    by_onset: Dict[float, List[note.Note]] = defaultdict(list)
    raw_note_count = 0
    for el in part.flatten().notes:
        if isinstance(el, note.Note):
            candidate = el
        elif isinstance(el, music21.chord.Chord):
            candidate = _chord_to_synth_note(el)
        else:
            continue
        o = _element_onset_in_part(el)
        key = round(float(o), 6)
        by_onset[key].append(candidate)
        raw_note_count += 1

    grouped_onset_count = len(by_onset)

    events: List[MelodyTransformEvent] = []
    num_top_voice_selected = 0
    num_non_top_voice_selected = 0
    melodic_leaps: List[int] = []
    prev_extracted_pitch: Optional[int] = None

    sorted_onsets = sorted(by_onset.keys())
    for i, onset_key in enumerate(sorted_onsets):
        group = by_onset[onset_key]
        if i == 0:
            winner = max(
                group,
                key=lambda x: (
                    int(x.pitch.midi),
                    float(x.duration.quarterLength),
                ),
            )
        else:
            assert prev_extracted_pitch is not None
            # Beat-aware selection for smoother melody extraction.
            # Compute beat strength at this onset using a representative candidate.
            _, bs = _bar_index_and_beat_strength_from_note(
                part, onset_key, group[0]
            )
            winner = _select_melody_note_from_group(
                group,
                prev_extracted_pitch,
                melody_follow=melody_follow,
                beat_strength=bs,
            )

        top_m = _group_highest_midi(group)
        if int(winner.pitch.midi) == top_m:
            num_top_voice_selected += 1
        else:
            num_non_top_voice_selected += 1

        p = int(winner.pitch.midi)
        if prev_extracted_pitch is not None:
            melodic_leaps.append(abs(p - prev_extracted_pitch))
        prev_extracted_pitch = p

        onset_global = onset_key
        dur = float(winner.duration.quarterLength)
        bar_idx, bs = _bar_index_and_beat_strength_from_note(part, onset_global, winner)
        vel = 80
        if winner.volume and winner.volume.velocity is not None:
            vel = int(winner.volume.velocity)
        events.append(
            MelodyTransformEvent(
                onset_quarter=onset_global,
                duration_quarter=dur,
                pitch=p,
                velocity=max(1, min(127, vel)),
                bar_index=bar_idx,
                beat_strength=bs,
            )
        )

    n_ev = len(events)
    max_leap = max(melodic_leaps) if melodic_leaps else 0
    avg_leap = sum(melodic_leaps) / float(len(melodic_leaps)) if melodic_leaps else 0.0
    niv = _interval_variance(melodic_leaps) if len(melodic_leaps) >= 2 else 0.0

    extraction_stats: Dict[str, Union[int, float]] = {
        **summarize_melody_extraction(raw_note_count, grouped_onset_count, n_ev),
        "num_top_voice_selected": num_top_voice_selected,
        "num_non_top_voice_selected": num_non_top_voice_selected,
        "avg_melodic_leap": avg_leap,
        "max_melodic_leap": max_leap,
        "note_interval_variance": niv,
        "melody_follow": float(max(0.0, min(1.0, melody_follow))),
    }

    if return_stats:
        return events, extraction_stats
    return cast(List[MelodyTransformEvent], events)


def apply_pitch_variation(
    events: Sequence[MelodyTransformEvent],
    *,
    variation_strength: float,
    scale_pitch_classes: set[int],
    tonic_pc: int,
    mode: str,
    seed: int = 42,
    max_pitch_changes: Optional[int] = None,
    weak_beat_max_semitones_from_prev: int = 5,
) -> Tuple[List[MelodyTransformEvent], int]:
    """
    Conservative local pitch edits (``variation_strength`` ∈ [0, 1]).

    If ``max_pitch_changes`` is set, at most that many notes may end with a different pitch
    than the input (remaining candidates are reverted).

    Strong beats: no triad *blend*; ``vs < 0.5`` leaves them unchanged; higher ``vs`` may
    lightly snap toward a nearby triad pitch only when the pitch class is not already triadic.
    Weak beats: only ±2 / ±1 / 0 (no ±3). Final scale snap; tonal_postprocess does global tidy.
    """
    rng = random.Random(seed)
    triad = _tonic_triad_pcs(tonic_pc, mode)
    out: List[MelodyTransformEvent] = []
    changed = 0
    vs = max(0.0, min(1.0, float(variation_strength)))
    pitch_changes_used = 0
    wmax = int(weak_beat_max_semitones_from_prev)
    ordered_in = sorted(events, key=lambda e: (e.onset_quarter, e.bar_index))
    prev_out: Optional[int] = None

    for ev in ordered_in:
        if vs <= 1e-9:
            out.append(replace(ev))
            continue

        strong = ev.beat_strength >= 0.85
        weak = ev.beat_strength <= 0.45

        new_pitch = ev.pitch

        if strong:
            if vs < 0.5:
                new_pitch = ev.pitch
            else:
                p_touch = vs * 0.12
                if rng.random() > p_touch:
                    new_pitch = ev.pitch
                else:
                    new_pitch = ev.pitch
                    if (ev.pitch % 12) not in triad:
                        candidates: List[int] = []
                        for base in range(0, 128, 12):
                            for t in triad:
                                p = base + int(t)
                                if 0 <= p <= 127:
                                    candidates.append(p)
                        if candidates:
                            new_pitch = min(candidates, key=lambda p: (abs(p - ev.pitch), p))
                    new_pitch = _snap_pc_to_scale(new_pitch, scale_pitch_classes)

        elif weak:
            p_edit = vs * (0.10 + 0.45 * vs)
            if rng.random() > p_edit:
                new_pitch = ev.pitch
            else:
                step = rng.choice([-2, -1, 0, 1, 2])
                new_pitch = _snap_pc_to_scale(ev.pitch + step, scale_pitch_classes)
        else:
            p_edit = vs * (0.10 + 0.42 * vs)
            if rng.random() > p_edit:
                new_pitch = ev.pitch
            else:
                pool = [-1, 0, 1] if vs < 0.55 else [-2, -1, 0, 1, 2]
                step = rng.choice(pool)
                new_pitch = _snap_pc_to_scale(ev.pitch + step, scale_pitch_classes)

        new_pitch = _snap_pc_to_scale(new_pitch, scale_pitch_classes)

        # Weak-beat guard: avoid sudden large leaps from previous output (anti-"AI spike").
        if (
            wmax > 0
            and prev_out is not None
            and float(ev.beat_strength) < 0.85
            and abs(new_pitch - prev_out) > wmax
        ):
            new_pitch = ev.pitch

        if new_pitch != ev.pitch:
            if max_pitch_changes is not None:
                if pitch_changes_used >= max_pitch_changes:
                    new_pitch = ev.pitch
                else:
                    pitch_changes_used += 1
        if new_pitch != ev.pitch:
            changed += 1
        out.append(replace(ev, pitch=new_pitch))
        prev_out = new_pitch

    return out, changed


def apply_note_split(
    events: Sequence[MelodyTransformEvent],
    *,
    split_strength: float,
    min_duration_quarter: float = 1.0,
    seed: int = 42,
) -> Tuple[List[MelodyTransformEvent], int]:
    """
    Split long notes into two equal halves; prefer weak-beat / non-downbeat anchors.

    Returns ``(new_events, num_splits)``.
    """
    rng = random.Random(seed + 1)
    ss = max(0.0, min(1.0, float(split_strength)))
    out: List[MelodyTransformEvent] = []
    splits = 0
    min_d = float(min_duration_quarter)
    splits_per_bar: Dict[int, int] = defaultdict(int)

    for ev in sorted(events, key=lambda e: (e.onset_quarter, e.bar_index)):
        dur = ev.duration_quarter
        if float(ev.beat_strength) >= 0.85:
            out.append(replace(ev))
            continue
        if splits_per_bar.get(ev.bar_index, 0) >= 1:
            out.append(replace(ev))
            continue
        if dur < 2.0 * min_d - 1e-6:
            out.append(replace(ev))
            continue
        if ss <= 1e-9:
            out.append(replace(ev))
            continue
        prefer = ev.beat_strength < 0.85
        eff = ss * (0.15 + 0.85 * ss)
        prob = eff * (0.38 + 0.48 * prefer)
        if rng.random() > prob:
            out.append(replace(ev))
            continue

        half = dur / 2.0
        if half < min_d - 1e-6:
            out.append(replace(ev))
            continue

        splits += 1
        splits_per_bar[ev.bar_index] += 1
        a = _update_event_position_meta(replace(ev, duration_quarter=half))
        b = _update_event_position_meta(
            replace(
                ev,
                onset_quarter=ev.onset_quarter + half,
                duration_quarter=half,
            )
        )
        out.extend([a, b])

    out.sort(key=lambda e: (e.onset_quarter, e.bar_index))
    return out, splits


def _merge_pair(a: MelodyTransformEvent, b: MelodyTransformEvent) -> MelodyTransformEvent:
    total_d = a.duration_quarter + b.duration_quarter
    vel = (a.velocity + b.velocity) // 2
    return replace(
        a,
        duration_quarter=total_d,
        velocity=max(1, min(127, vel)),
        pitch=a.pitch,
        beat_strength=a.beat_strength,
    )


def apply_note_merge(
    events: Sequence[MelodyTransformEvent],
    *,
    merge_strength: float,
    seed: int = 42,
    max_merged_duration_quarter: float = 1.5,
    max_merges: Optional[int] = None,
) -> Tuple[List[MelodyTransformEvent], int]:
    """
    Merge adjacent, near-touching notes **only when same pitch** (repeated notes).

    Returns ``(new_events, num_merges)``.
    """
    rng = random.Random(seed + 2)
    ms = max(0.0, min(1.0, float(merge_strength)))
    max_dur = float(max_merged_duration_quarter)
    merge_cap = max_merges
    ordered = sorted(events, key=lambda e: (e.onset_quarter, e.bar_index))
    if not ordered:
        return [], 0

    out: List[MelodyTransformEvent] = []
    merges = 0
    i = 0

    while i < len(ordered):
        cur = ordered[i]
        if i + 1 >= len(ordered) or ms <= 1e-9:
            out.append(replace(cur))
            i += 1
            continue
        if merge_cap is not None and merges >= merge_cap:
            out.append(replace(cur))
            i += 1
            continue
        nxt = ordered[i + 1]
        gap = nxt.onset_quarter - (cur.onset_quarter + cur.duration_quarter)
        same_pitch = cur.pitch == nxt.pitch
        contiguous = gap <= 0.05
        merged_dur = cur.duration_quarter + nxt.duration_quarter

        eff_m = ms * (0.12 + 0.88 * ms)
        if (
            contiguous
            and same_pitch
            and merged_dur <= max_dur + 1e-6
            and rng.random() < eff_m * 0.58
        ):
            merged = _merge_pair(cur, nxt)
            out.append(merged)
            merges += 1
            i += 2
        else:
            out.append(replace(cur))
            i += 1

    return out, merges


def apply_motif_local_variation(
    events: Sequence[MelodyTransformEvent],
    *,
    motif_strength: float,
    bars_per_motif: int = 2,
    scale_pitch_classes: set[int],
    seed: int = 42,
    force_run: bool = False,
    max_edits_cap: Optional[int] = None,
) -> Tuple[List[MelodyTransformEvent], int]:
    """
    Nudge a single later window toward the interval contour of the first ``bars_per_motif`` bars.

    Returns ``(new_events, num_edits)``.
    """
    rng = random.Random(seed + 3)
    ms = max(0.0, min(1.0, float(motif_strength)))
    if max_edits_cap is not None and int(max_edits_cap) <= 0:
        return [replace(e) for e in events], 0
    if ms <= 1e-9 or not events:
        return [replace(e) for e in events], 0

    span = max(1, int(bars_per_motif))
    sorted_e = sorted(events, key=lambda x: (x.onset_quarter, x.bar_index))
    ref_notes = [e for e in sorted_e if e.bar_index < span]
    if len(ref_notes) < 2:
        return [replace(e) for e in events], 0

    ref_intervals = [ref_notes[i + 1].pitch - ref_notes[i].pitch for i in range(len(ref_notes) - 1)]
    max_bar = max(e.bar_index for e in events)
    tgt_lo = 2 * span
    tgt_hi = tgt_lo + span - 1
    if max_bar < tgt_hi:
        return [replace(e) for e in events], 0

    run_motif = min(1.0, ms * (0.35 + 0.9 * ms))
    if not force_run and rng.random() > run_motif:
        return [replace(e) for e in events], 0

    out_list = [replace(e) for e in sorted_e]
    tgt_idx = [i for i, e in enumerate(out_list) if tgt_lo <= e.bar_index <= tgt_hi]
    if len(tgt_idx) < 2:
        return out_list, 0

    ref_count = len(ref_notes)
    tgt_count = len(tgt_idx)
    if abs(tgt_count - ref_count) > 2:
        return out_list, 0

    cap = 2 if ms >= 0.6 else 1
    if max_edits_cap is not None:
        cap = min(cap, max(0, int(max_edits_cap)))
    max_edits = cap
    if max_edits <= 0:
        return out_list, 0
    candidate_positions = list(tgt_idx[1:])
    rng.shuffle(candidate_positions)
    selected = sorted(candidate_positions[:max_edits])

    edits = 0
    transpose_pool = [0] if ms < 0.5 else [-1, 0, 1]

    for ii in selected:
        local_idx = tgt_idx.index(ii)
        prev_i = tgt_idx[local_idx - 1]
        ri = (local_idx - 1) % max(1, len(ref_intervals))
        delta = ref_intervals[ri]
        transpose = rng.choice(transpose_pool)
        jitter = rng.choice([-1, 0, 1]) if rng.random() < 0.25 * ms else 0
        new_p = _snap_pc_to_scale(
            out_list[prev_i].pitch + delta + jitter + transpose,
            scale_pitch_classes,
        )
        if new_p != out_list[ii].pitch:
            edits += 1
        out_list[ii] = replace(out_list[ii], pitch=new_p)

    return out_list, edits


def apply_humanization(
    events: Sequence[MelodyTransformEvent],
    *,
    timing_amount: float = 0.0,
    velocity_amount: float = 0.0,
    seed: int = 42,
) -> Tuple[List[MelodyTransformEvent], Dict[str, object]]:
    """Tiny onset / velocity jitter; ordering preserved.

    Debuggable: also returns a small stats dict so we can confirm `humanize`
    actually modified onsets/velocities (and quantify the magnitude).
    """
    rng = random.Random(seed + 7)
    ta = max(0.0, min(1.0, float(timing_amount)))
    va = max(0.0, min(1.0, float(velocity_amount)))
    out: List[MelodyTransformEvent] = []

    num_humanized_notes = 0
    num_onset_shifted = 0
    num_velocity_shifted = 0
    onset_shift_total = 0.0
    onset_shift_total_abs = 0.0
    velocity_shift_total = 0
    velocity_shift_total_abs = 0
    max_abs_onset_shift = 0.0
    max_abs_velocity_shift = 0

    events_sorted = sorted(events, key=lambda e: (e.onset_quarter, e.bar_index))
    for ev in events_sorted:
        dt = 0.0
        dv = 0
        # Beat-aware humanization:
        # - strong beats (beat_strength close to 1): smaller jitter (more stable)
        # - weak beats: larger jitter (more expressive / less "grid-locked")
        bs = max(0.0, min(1.0, float(getattr(ev, "beat_strength", 0.5))))
        beat_weight = 0.6 + 0.8 * (1.0 - bs)  # range ~[0.6, 1.4]
        if ta > 1e-9:
            dt = rng.uniform(-0.04, 0.04) * ta * beat_weight
        if va > 1e-9:
            # Velocity jitter: use a larger scale so `dv` is frequently non-zero.
            dv = int(round(rng.uniform(-12.0, 12.0) * va * beat_weight))

        did = abs(dt) > 1e-12 or dv != 0
        if did:
            num_humanized_notes += 1

        if abs(dt) > 1e-12:
            num_onset_shifted += 1
            onset_shift_total += dt
            onset_shift_total_abs += abs(dt)
            max_abs_onset_shift = max(max_abs_onset_shift, abs(dt))
        if dv != 0:
            num_velocity_shifted += 1
            velocity_shift_total += dv
            velocity_shift_total_abs += abs(dv)
            max_abs_velocity_shift = max(max_abs_velocity_shift, abs(dv))

        out.append(
            replace(
                ev,
                onset_quarter=max(0.0, ev.onset_quarter + dt),
                velocity=max(1, min(127, ev.velocity + dv)),
            )
        )

    stats: Dict[str, object] = {
        "humanize_timing_amount": ta,
        "humanize_velocity_amount": va,
        "num_input_events_humanize": int(len(events_sorted)),
        "num_humanized_notes": int(num_humanized_notes),
        "num_onset_shifted": int(num_onset_shifted),
        "num_velocity_shifted": int(num_velocity_shifted),
        "avg_onset_shift_quarter_abs": onset_shift_total_abs / max(1, num_onset_shifted),
        "avg_onset_shift_quarter_signed": onset_shift_total / max(1, num_onset_shifted),
        "avg_velocity_shift_abs": velocity_shift_total_abs / max(1, num_velocity_shifted),
        "avg_velocity_shift_signed": velocity_shift_total / max(1, num_velocity_shifted),
        "max_abs_onset_shift_quarter": max_abs_onset_shift,
        "max_abs_velocity_shift": max_abs_velocity_shift,
    }

    return out, stats


def transform_melody_events(
    events: Sequence[MelodyTransformEvent],
    *,
    pitch_variation: float,
    rhythm_variation: float,
    motif_variation: float,
    humanize: float,
    scale_pitch_classes: set[int],
    tonic_pc: int,
    mode: str,
    seed: int = 42,
    enable_note_merge: bool = True,
    enable_motif_variation: bool = True,
    force_motif_variation: bool = False,
    merge_strength: Optional[float] = None,
) -> Tuple[List[MelodyTransformEvent], Dict[str, object]]:
    """
    Apply transforms in order: pitch → merge → motif → humanize.

    Uses a **unified edit budget** (~20% of notes, split 50% / 30% / 20% for pitch /
    motif / merge caps) and **SNR gates**: low average melodic leap scales pitch
    strength; short / low-variance lines disable motif / merge when appropriate.

    Note-split is currently disabled (merge-only rhythm shaping) to avoid
    over-aggressive local density changes.

    ``rhythm_variation`` scales merge strength (0–1) when ``merge_strength`` is None.
    If ``merge_strength`` is set, it overrides the merge step only (still clipped to [0, 1]).
    Split is skipped.
    ``humanize`` scales timing/velocity jitter.
    """
    base = [replace(e) for e in events]
    n_in = len(base)
    pv = max(0.0, min(1.0, float(pitch_variation)))
    rv = max(0.0, min(1.0, float(rhythm_variation)))
    mv = max(0.0, min(1.0, float(motif_variation)))
    hz = max(0.0, min(1.0, float(humanize)))
    merge_ms = rv if merge_strength is None else max(0.0, min(1.0, float(merge_strength)))

    if n_in == 0:
        return [], {
            "num_input_events": 0,
            "num_output_events": 0,
            "num_pitch_changed": 0,
            "num_split": 0,
            "num_merge": 0,
            "num_motif_variations": 0,
            "avg_pitch_before": 0.0,
            "avg_pitch_after": 0.0,
            "max_pitch_change_budget": 0,
            "total_edit_budget": 0,
            "pitch_budget": 0,
            "motif_budget": 0,
            "merge_budget": 0,
            "pitch_variation": pv,
            "pitch_variation_effective": pv,
            "snr_avg_melodic_leap": 0.0,
            "note_interval_variance": 0.0,
            "gate_motif_passed": False,
            "gate_merge_passed": False,
            "rhythm_variation": rv,
            "motif_variation": mv,
            "humanize": hz,
            "enable_note_merge": enable_note_merge,
            "enable_motif_variation": enable_motif_variation,
            "force_motif_variation": force_motif_variation,
            "merge_strength_applied": 0.0,
        }

    avg_before = sum(e.pitch for e in base) / float(n_in)
    line = melody_line_metrics(base)
    avg_leap = float(line["avg_melodic_leap"])
    niv = float(line["note_interval_variance"])
    num_bars_spanned = int(line["num_bars_spanned"])
    n_notes_line = int(line["num_notes"])

    pv_use = (
        pv * SNR_PITCH_VARIATION_ATTENUATION
        if avg_leap < SNR_LOW_AVG_LEAP
        else pv
    )

    total_edit_budget = max(1, int(0.2 * n_in))
    pitch_budget = max(1, int(total_edit_budget * 0.5))
    motif_budget = max(0, int(total_edit_budget * 0.3))
    merge_budget = max(0, int(total_edit_budget * 0.2))

    gate_motif = (
        enable_motif_variation
        and num_bars_spanned >= MIN_BARS_MOTIF_GATE
        and n_notes_line >= MIN_NOTES_MOTIF_GATE
    )
    gate_merge = enable_note_merge and (
        n_notes_line < MIN_NOTES_FOR_MERGE_VARIANCE_GATE
        or niv >= MERGE_INTERVAL_VARIANCE_FLOOR
    )

    cur, n_pc = apply_pitch_variation(
        base,
        variation_strength=pv_use,
        scale_pitch_classes=scale_pitch_classes,
        tonic_pc=tonic_pc,
        mode=mode,
        seed=seed,
        max_pitch_changes=pitch_budget,
    )

    # Note-split disabled for conservative melody refine (pseudo-polyphony / density).
    n_sp = 0

    if gate_merge:
        cur, n_mg = apply_note_merge(
            cur,
            merge_strength=merge_ms,
            seed=seed,
            max_merges=merge_budget,
        )
    else:
        n_mg = 0

    if gate_motif:
        cur, n_mv = apply_motif_local_variation(
            cur,
            motif_strength=mv,
            bars_per_motif=2,
            scale_pitch_classes=scale_pitch_classes,
            seed=seed,
            force_run=force_motif_variation,
            max_edits_cap=motif_budget,
        )
    else:
        n_mv = 0

    humanize_stats: Dict[str, object] = {
        "humanize_timing_amount": 0.0,
        "humanize_velocity_amount": 0.0,
        "num_input_events_humanize": 0,
        "num_humanized_notes": 0,
        "num_onset_shifted": 0,
        "num_velocity_shifted": 0,
        "avg_onset_shift_quarter_abs": 0.0,
        "avg_onset_shift_quarter_signed": 0.0,
        "avg_velocity_shift_abs": 0.0,
        "avg_velocity_shift_signed": 0.0,
        "max_abs_onset_shift_quarter": 0.0,
        "max_abs_velocity_shift": 0,
    }

    if hz > 1e-9:
        cur, humanize_stats = apply_humanization(
            cur,
            timing_amount=hz * 0.38,
            velocity_amount=hz * 0.42,
            seed=seed,
        )

    n_out = len(cur)
    avg_after = sum(e.pitch for e in cur) / float(n_out) if n_out else 0.0

    stats: Dict[str, object] = {
        "num_input_events": n_in,
        "num_output_events": n_out,
        "num_pitch_changed": n_pc,
        "num_split": n_sp,
        "num_merge": n_mg,
        "num_motif_variations": n_mv,
        "avg_pitch_before": avg_before,
        "avg_pitch_after": avg_after,
        "max_pitch_change_budget": pitch_budget,
        "total_edit_budget": total_edit_budget,
        "pitch_budget": pitch_budget,
        "motif_budget": motif_budget,
        "merge_budget": merge_budget,
        "pitch_variation": pv,
        "pitch_variation_effective": pv_use,
        "snr_avg_melodic_leap": avg_leap,
        "note_interval_variance": niv,
        "gate_motif_passed": gate_motif,
        "gate_merge_passed": gate_merge,
        "rhythm_variation": rv,
        "motif_variation": mv,
        "humanize": hz,
        **humanize_stats,
        "enable_note_merge": enable_note_merge,
        "enable_motif_variation": enable_motif_variation,
        "force_motif_variation": force_motif_variation,
        "merge_strength_applied": merge_ms,
    }
    return cur, stats
