from __future__ import annotations

from typing import Dict, Iterable, Set

import music21
from music21 import note as m21note
from music21 import percussion as m21perc

from analysis.key_detection import detect_key_music21
from clean_up.track_alignment import _is_drum_part


MAJOR_SCALE_INTERVALS = (0, 2, 4, 5, 7, 9, 11)
MINOR_SCALE_INTERVALS = (0, 2, 3, 5, 7, 8, 10)  # natural minor


def build_scale_pitch_classes(tonic_pc: int, mode: str) -> Set[int]:
    """
    Build pitch classes (0-11) for a major/minor scale.
    Note: minor is approximated as natural minor only.
    """
    tonic_pc = tonic_pc % 12
    mode_norm = mode.lower().strip()

    if mode_norm == "major":
        intervals = MAJOR_SCALE_INTERVALS
    elif mode_norm == "minor":
        intervals = MINOR_SCALE_INTERVALS
    else:
        raise ValueError(f"Unsupported mode: {mode}. Use 'major' or 'minor'.")

    return {(tonic_pc + interval) % 12 for interval in intervals}


def is_note_in_key(midi_pitch: int, scale_pitch_classes: Set[int]) -> bool:
    """
    Return True if the MIDI pitch belongs to the scale.
    """
    return (midi_pitch % 12) in scale_pitch_classes


def nearest_legal_pitch(
    midi_pitch: int,
    scale_pitch_classes: Set[int],
    tie_break: str = "down",
) -> int:
    """
    Map an out-of-key MIDI pitch to the nearest in-key pitch (greedy search).
    tie_break: "down" or "up" for equal-distance cases.
    """
    if is_note_in_key(midi_pitch, scale_pitch_classes):
        return midi_pitch

    if tie_break not in {"down", "up"}:
        raise ValueError("tie_break must be 'down' or 'up'.")

    # Searching within one octave is sufficient because pitch classes repeat
    # every 12 semitones.
    for distance in range(1, 12):
        down_candidate = midi_pitch - distance
        up_candidate = midi_pitch + distance
        down_ok = is_note_in_key(down_candidate, scale_pitch_classes)
        up_ok = is_note_in_key(up_candidate, scale_pitch_classes)

        if down_ok and up_ok:
            chosen = down_candidate if tie_break == "down" else up_candidate
            return max(0, min(127, chosen))
        if down_ok:
            return max(0, min(127, down_candidate))
        if up_ok:
            return max(0, min(127, up_candidate))

    return max(0, min(127, midi_pitch))


def _iter_notes_and_chords_non_drum(
    score: music21.stream.Stream,
) -> Iterable[music21.base.Music21Object]:
    """
    Pitched notes/chords only, excluding drum/percussion parts.

    Skipping drum parts is required: GM drums use ``Note`` with MIDI pitches;
    tonal snap would remap kicks/snares into scale tones and ruin the kit.
    """
    for part in score.parts:
        if _is_drum_part(part):
            continue
        for element in part.recurse():
            if isinstance(element, m21note.Unpitched):
                continue
            if isinstance(element, m21perc.PercussionChord):
                continue
            if isinstance(element, (music21.note.Note, music21.chord.Chord)):
                yield element


def apply_tonal_correction(
    input_midi_path: str,
    output_midi_path: str,
    tonic_pc: int | None = None,
    mode: str | None = None,
    correction_mode: str = "gentle",
    delete_short_out_of_key: bool = False,
    short_note_threshold_quarter_length: float = 0.25,
    tie_break: str = "down",
) -> Dict[str, object]:
    """
    Tonal correction for a MIDI file.

    correction_mode:
    - "gentle": only snap/delete out-of-key notes shorter than
      short_note_threshold_quarter_length; longer notes are left unchanged
      (passing tones, borrowings, etc.).
    - "strict": map every out-of-key pitch to the nearest scale tone.

    Features:
    - major/minor scale building
    - in-key judgement
    - nearest legal note mapping
    - optional deletion for short out-of-key notes
    """
    correction_profile = correction_mode.lower().strip()
    if correction_profile not in {"gentle", "strict"}:
        raise ValueError("correction_mode must be 'gentle' or 'strict'.")
    score = music21.converter.parse(input_midi_path)

    detected_key = None
    if tonic_pc is None or mode is None:
        detected_key = detect_key_music21(input_midi_path)
        tonic_pc = detected_key["tonic_pc"]
        mode = detected_key["mode"]

    scale_pitch_classes = build_scale_pitch_classes(int(tonic_pc), str(mode))

    corrected_notes = 0
    deleted_notes = 0
    unchanged_notes = 0
    gentle_skipped_long = 0

    for element in list(_iter_notes_and_chords_non_drum(score)):
        if isinstance(element, music21.note.Note):
            old_pitch = element.pitch.midi
            in_key = is_note_in_key(old_pitch, scale_pitch_classes)

            if in_key:
                unchanged_notes += 1
                continue

            if (
                correction_profile == "gentle"
                and element.quarterLength > short_note_threshold_quarter_length
            ):
                gentle_skipped_long += 1
                unchanged_notes += 1
                continue

            if delete_short_out_of_key and element.quarterLength <= short_note_threshold_quarter_length:
                if element.activeSite is not None:
                    element.activeSite.remove(element)
                    deleted_notes += 1
                continue

            new_pitch = nearest_legal_pitch(old_pitch, scale_pitch_classes, tie_break=tie_break)
            if new_pitch != old_pitch:
                element.pitch.midi = new_pitch
                corrected_notes += 1
            else:
                unchanged_notes += 1

        elif isinstance(element, music21.chord.Chord):
            if (
                correction_profile == "gentle"
                and element.quarterLength > short_note_threshold_quarter_length
            ):
                gentle_skipped_long += len(element.pitches)
                unchanged_notes += len(element.pitches)
                continue

            if (
                delete_short_out_of_key
                and all(not is_note_in_key(p.midi, scale_pitch_classes) for p in element.pitches)
                and element.quarterLength <= short_note_threshold_quarter_length
            ):
                if element.activeSite is not None:
                    element.activeSite.remove(element)
                    deleted_notes += len(element.pitches)
                continue

            new_pitches = []
            for p in element.pitches:
                old_pitch = p.midi
                if is_note_in_key(old_pitch, scale_pitch_classes):
                    new_pitches.append(old_pitch)
                    unchanged_notes += 1
                    continue

                new_pitch = nearest_legal_pitch(old_pitch, scale_pitch_classes, tie_break=tie_break)
                new_pitches.append(new_pitch)
                if new_pitch != old_pitch:
                    corrected_notes += 1
                else:
                    unchanged_notes += 1

            if any(new != old.midi for old, new in zip(element.pitches, new_pitches)):
                element.pitches = [music21.pitch.Pitch(midi=m) for m in new_pitches]

    score.write("midi", fp=output_midi_path)

    return {
        "input_midi_path": input_midi_path,
        "output_midi_path": output_midi_path,
        "tonic_pc": tonic_pc,
        "mode": mode,
        "correction_mode": correction_profile,
        "scale_pitch_classes": sorted(scale_pitch_classes),
        "corrected_notes": corrected_notes,
        "deleted_notes": deleted_notes,
        "unchanged_notes": unchanged_notes,
        "gentle_skipped_long_note_events": gentle_skipped_long,
        "detected_key": detected_key,
    }

