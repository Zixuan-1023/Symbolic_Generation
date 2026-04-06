from __future__ import annotations

from typing import Dict, List, Tuple

import music21


def _is_drum_part(part: music21.stream.Part) -> bool:
    # Heuristic: MIDI channel 10 (index 9), percussion instruments, or name hints.
    part_name = f"{part.partName or ''} {part.id or ''}".lower()
    if "drum" in part_name or "perc" in part_name:
        return True

    for inst in part.recurse().getElementsByClass(music21.instrument.Instrument):
        if isinstance(inst, music21.instrument.UnpitchedPercussion):
            return True
        if getattr(inst, "midiChannel", None) == 9:
            return True

    return False


def _collect_non_drum_events(
    score: music21.stream.Score,
) -> List[Tuple[music21.base.Music21Object, float, int]]:
    events: List[Tuple[music21.base.Music21Object, float, int]] = []
    for part_idx, part in enumerate(score.parts):
        if _is_drum_part(part):
            continue
        for element in part.recurse():
            if isinstance(element, (music21.note.Note, music21.chord.Chord)):
                onset = float(element.getOffsetInHierarchy(score))
                events.append((element, onset, part_idx))
    return events


def _cluster_onsets(onsets: List[float], threshold: float) -> Dict[float, float]:
    if not onsets:
        return {}

    unique_onsets = sorted(set(onsets))
    clusters: List[List[float]] = [[unique_onsets[0]]]

    for onset in unique_onsets[1:]:
        current_cluster = clusters[-1]
        center = sum(current_cluster) / len(current_cluster)
        if abs(onset - center) <= threshold:
            current_cluster.append(onset)
        else:
            clusters.append([onset])

    onset_to_representative: Dict[float, float] = {}
    for cluster in clusters:
        # Use an existing onset nearest to the cluster center instead of
        # arithmetic mean to avoid creating new "off-grid" fractional positions.
        center = sum(cluster) / len(cluster)
        representative = min(cluster, key=lambda x: abs(x - center))
        for onset in cluster:
            onset_to_representative[onset] = representative

    return onset_to_representative


def count_non_drum_tracks_with_pitched_notes(input_midi_path: str) -> int:
    """
    Number of non-drum parts that contain at least one Note or Chord.
    Used to skip global onset alignment for typical single-track MuseCoco output.
    """
    score = music21.converter.parse(input_midi_path)
    n = 0
    for part in score.parts:
        if _is_drum_part(part):
            continue
        for element in part.recurse():
            if isinstance(element, (music21.note.Note, music21.chord.Chord)):
                n += 1
                break
    return n


def align_track_onsets(
    input_midi_path: str,
    output_midi_path: str,
    onset_threshold_quarter_length: float = 0.05,
) -> Dict[str, object]:
    """
    Align non-drum note/chord onsets across tracks.

    Core idea:
    - collect all non-drum note/chord onsets
    - if onsets are close enough (within threshold), cluster them
    - snap each onset to a cluster representative onset
    Note:
    - this is currently global onset clustering (not strictly cross-track-only)
    """
    score = music21.converter.parse(input_midi_path)
    events = _collect_non_drum_events(score)
    onset_to_rep = _cluster_onsets(
        [onset for _, onset, _ in events], onset_threshold_quarter_length
    )

    moved_events = 0
    total_events = 0

    for element, absolute_onset, _part_idx in events:
        total_events += 1
        representative = onset_to_rep.get(absolute_onset, absolute_onset)
        delta = representative - absolute_onset

        if abs(delta) <= 1e-12:
            continue

        if element.activeSite is not None:
            new_local_offset = max(0.0, float(element.offset) + delta)
            element.activeSite.setElementOffset(element, new_local_offset)
            moved_events += 1

    score.write("midi", fp=output_midi_path)

    return {
        "input_midi_path": input_midi_path,
        "output_midi_path": output_midi_path,
        "onset_threshold_quarter_length": onset_threshold_quarter_length,
        "total_non_drum_events": total_events,
        "moved_events": moved_events,
        "clusters": len(set(onset_to_rep.values())) if onset_to_rep else 0,
    }

