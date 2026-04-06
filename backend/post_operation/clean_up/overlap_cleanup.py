from __future__ import annotations

from collections import defaultdict
from typing import DefaultDict, Dict, List, Tuple

import music21


def _is_drum_part(part: music21.stream.Part) -> bool:
    """
    Heuristically detect whether a part is a drum/percussion part.
    """
    part_name = f"{part.partName or ''} {part.id or ''}".lower()
    if "drum" in part_name or "perc" in part_name:
        return True

    for inst in part.recurse().getElementsByClass(music21.instrument.Instrument):
        if isinstance(inst, music21.instrument.UnpitchedPercussion):
            return True
        if getattr(inst, "midiChannel", None) == 9:
            return True

    return False


def _collect_note_events_by_pitch(
    part: music21.stream.Part,
    score: music21.stream.Score,
) -> DefaultDict[int, List[Tuple[music21.note.Note, float, float]]]:
    """
    Collect note events (excluding chords) from a part and group them by MIDI pitch.

    Each grouped item is stored as:
        (note_object, absolute_start, absolute_end)
    """
    grouped: DefaultDict[int, List[Tuple[music21.note.Note, float, float]]] = defaultdict(list)

    for element in part.recurse():
        if not isinstance(element, music21.note.Note):
            continue

        start = float(element.getOffsetInHierarchy(score))
        end = start + float(element.quarterLength)
        grouped[int(element.pitch.midi)].append((element, start, end))

    return grouped


def cleanup_overlaps(
    input_midi_path: str,
    output_midi_path: str,
    min_duration_quarter_length: float = 0.01,
) -> Dict[str, object]:
    """
    Trim same-pitch note overlaps within each non-drum part.

    v1 rule:
    - For two consecutive notes with the same pitch in the same part,
      if the next note starts before the previous note ends,
      shorten the previous note so that it ends exactly at the next note onset.

    Notes:
    - This v1 implementation handles only Note objects, not Chord objects.
    - If trimming would make the previous note shorter than
      `min_duration_quarter_length`, the overlap is left unchanged.
    """
    if min_duration_quarter_length <= 0:
        raise ValueError("min_duration_quarter_length must be > 0.")

    score = music21.converter.parse(input_midi_path)

    total_notes_checked = 0
    overlap_pairs_found = 0
    trimmed_notes = 0
    skipped_too_short = 0

    for part in score.parts:
        if _is_drum_part(part):
            continue

        grouped = _collect_note_events_by_pitch(part, score)

        for _pitch, events in grouped.items():
            events.sort(key=lambda x: x[1])  # sort by absolute onset

            total_notes_checked += len(events)
            if len(events) < 2:
                continue

            for i in range(len(events) - 1):
                prev_note, prev_start, prev_end = events[i]
                _next_note, next_start, _next_end = events[i + 1]

                if next_start >= prev_end:
                    continue

                overlap_pairs_found += 1
                new_duration = next_start - prev_start

                if new_duration < min_duration_quarter_length:
                    skipped_too_short += 1
                    continue

                prev_note.quarterLength = new_duration
                trimmed_notes += 1

                # Keep the cached end time in sync for subsequent checks.
                events[i] = (prev_note, prev_start, next_start)

    score.write("midi", fp=output_midi_path)

    return {
        "input_midi_path": input_midi_path,
        "output_midi_path": output_midi_path,
        "min_duration_quarter_length": min_duration_quarter_length,
        "total_notes_checked": total_notes_checked,
        "overlap_pairs_found": overlap_pairs_found,
        "trimmed_notes": trimmed_notes,
        "skipped_too_short": skipped_too_short,
    }