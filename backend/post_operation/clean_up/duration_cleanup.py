from __future__ import annotations

from typing import Dict

import music21


def _is_drum_part(part: music21.stream.Part) -> bool:
    part_name = f"{part.partName or ''} {part.id or ''}".lower()
    if "drum" in part_name or "perc" in part_name:
        return True

    for inst in part.recurse().getElementsByClass(music21.instrument.Instrument):
        if isinstance(inst, music21.instrument.UnpitchedPercussion):
            return True
        if getattr(inst, "midiChannel", None) == 9:
            return True

    return False


def cleanup_duration(
    input_midi_path: str,
    output_midi_path: str,
    min_duration_quarter_length: float = 0.25,
    mode: str = "extend",
) -> Dict[str, object]:
    """
    Clean up non-drum note/chord durations shorter than a minimum threshold.

    - mode="extend": set short durations to min_duration_quarter_length
    - mode="delete": remove short note/chord objects
    """
    if min_duration_quarter_length <= 0:
        raise ValueError("min_duration_quarter_length must be > 0.")
    if mode not in {"extend", "delete"}:
        raise ValueError("mode must be 'extend' or 'delete'.")

    score = music21.converter.parse(input_midi_path)

    total_non_drum_events = 0
    short_events = 0
    extended_events = 0
    deleted_events = 0

    for part in score.parts:
        if _is_drum_part(part):
            continue

        for element in list(part.recurse()):
            if not isinstance(element, (music21.note.Note, music21.chord.Chord)):
                continue

            total_non_drum_events += 1
            ql = float(element.quarterLength)
            if ql >= min_duration_quarter_length:
                continue

            short_events += 1
            if mode == "extend":
                element.quarterLength = min_duration_quarter_length
                extended_events += 1
            else:  # mode == "delete"
                if element.activeSite is not None:
                    element.activeSite.remove(element)
                    deleted_events += 1

    score.write("midi", fp=output_midi_path)

    return {
        "input_midi_path": input_midi_path,
        "output_midi_path": output_midi_path,
        "min_duration_quarter_length": min_duration_quarter_length,
        "mode": mode,
        "total_non_drum_events": total_non_drum_events,
        "short_events": short_events,
        "extended_events": extended_events,
        "deleted_events": deleted_events,
    }

