from __future__ import annotations

import math
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


def _nearest_grid_onset(onset: float, grid_quarter_length: float) -> float:
    if grid_quarter_length <= 0:
        raise ValueError("grid_quarter_length must be > 0.")
    scaled = onset / grid_quarter_length
    nearest_idx = math.floor(scaled + 0.5)
    return nearest_idx * grid_quarter_length


def cleanup_timing(
    input_midi_path: str,
    output_midi_path: str,
    grid_quarter_length: float = 0.25,
    strength: float = 1.0,
) -> Dict[str, object]:
    """
    Quantize non-drum note/chord onsets to a fixed global grid
    without changing durations.

    t' = t + strength * (t_hat - t), where t_hat is nearest grid onset.
    """
    if not (0.0 <= strength <= 1.0):
        raise ValueError("strength must be within [0, 1].")

    score = music21.converter.parse(input_midi_path)

    total_non_drum_events = 0
    moved_events = 0

    for part in score.parts:
        if _is_drum_part(part):
            continue

        for element in part.recurse():
            if not isinstance(element, (music21.note.Note, music21.chord.Chord)):
                continue

            total_non_drum_events += 1
            absolute_onset = float(element.getOffsetInHierarchy(score))
            nearest_grid = _nearest_grid_onset(absolute_onset, grid_quarter_length)
            new_absolute_onset = absolute_onset + strength * (nearest_grid - absolute_onset)
            delta = new_absolute_onset - absolute_onset

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
        "grid_quarter_length": grid_quarter_length,
        "strength": strength,
        "total_non_drum_events": total_non_drum_events,
        "moved_events": moved_events,
    }

