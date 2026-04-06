from __future__ import annotations

from typing import Set

import music21

from analysis.key_detection import detect_key_music21
from refine.types import ExtractedStructure

MAJOR_SCALE_INTERVALS = (0, 2, 4, 5, 7, 9, 11)
MINOR_SCALE_INTERVALS = (0, 2, 3, 5, 7, 8, 10)


def _build_scale_pitch_classes(tonic_pc: int, mode: str) -> Set[int]:
    tonic_pc = tonic_pc % 12
    mode_norm = mode.lower().strip()
    if mode_norm == "major":
        intervals = MAJOR_SCALE_INTERVALS
    elif mode_norm == "minor":
        intervals = MINOR_SCALE_INTERVALS
    else:
        raise ValueError(f"Unsupported mode: {mode}")
    return {(tonic_pc + interval) % 12 for interval in intervals}


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


def _get_non_drum_parts(score: music21.stream.Score) -> list[music21.stream.Part]:
    return [part for part in score.parts if not _is_drum_part(part)]


def _compute_center_pitch(part: music21.stream.Part) -> float:
    pitches: list[int] = []
    for element in part.recurse():
        if isinstance(element, music21.note.Note):
            pitches.append(int(element.pitch.midi))
        elif isinstance(element, music21.chord.Chord):
            pitches.extend(int(p.midi) for p in element.pitches)
    if not pitches:
        return 60.0
    return float(sum(pitches) / len(pitches))


def _extract_tempo_bpm(score: music21.stream.Score) -> float:
    mm = score.recurse().getElementsByClass(music21.tempo.MetronomeMark)
    if mm:
        value = mm[0].number
        if value is not None:
            return float(value)
    return 120.0


def _extract_time_signature(score: music21.stream.Score) -> str:
    ts = score.recurse().getElementsByClass(music21.meter.TimeSignature)
    if ts:
        return ts[0].ratioString
    return "4/4"


def _estimate_num_bars(score: music21.stream.Score) -> int:
    parts_nd = _get_non_drum_parts(score)
    ref_part = parts_nd[0] if parts_nd else (score.parts[0] if score.parts else None)
    if ref_part is None:
        return 1
    measures = list(ref_part.getElementsByClass(music21.stream.Measure))
    if measures:
        return len(measures)
    highest_time = float(score.highestTime)
    return max(1, round(highest_time / 4.0))


def _note_chord_count(part: music21.stream.Part) -> int:
    return sum(
        1
        for el in part.recurse()
        if isinstance(el, (music21.note.Note, music21.chord.Chord))
    )


def resolve_melody_part_index(score: music21.stream.Score, requested: int) -> int:
    """
    Pick a non-drum part index for refine. If the requested part has no notes (common when
    track 0 is empty or only meta), fall back to the **busiest** non-drum part so a UI
    that always sends ``0`` still processes the intended melodic material when possible.

    Set env ``POST_REFINE_DISABLE_MELODY_FALLBACK=1`` to require strict ``requested`` only.
    """
    import os

    non_drum_parts = _get_non_drum_parts(score)
    if not non_drum_parts:
        raise ValueError("No non-drum parts found in the MIDI file.")
    if os.environ.get("POST_REFINE_DISABLE_MELODY_FALLBACK", "0").strip() == "1":
        if requested < 0 or requested >= len(non_drum_parts):
            raise ValueError(
                f"melody_part_index={requested} out of range for {len(non_drum_parts)} non-drum parts."
            )
        return requested
    req = max(0, min(int(requested), len(non_drum_parts) - 1))
    if _note_chord_count(non_drum_parts[req]) > 0:
        return req
    counts = [_note_chord_count(p) for p in non_drum_parts]
    best = int(max(range(len(counts)), key=lambda i: counts[i]))
    return best


def get_melody_part(
    score: music21.stream.Score,
    melody_part_index: int,
) -> music21.stream.Part:
    non_drum_parts = _get_non_drum_parts(score)
    if not non_drum_parts:
        raise ValueError("No non-drum parts found in the MIDI file.")
    if melody_part_index < 0 or melody_part_index >= len(non_drum_parts):
        raise ValueError(
            f"melody_part_index={melody_part_index} out of range for {len(non_drum_parts)} non-drum parts."
        )
    return non_drum_parts[melody_part_index]


def extract_structure_from_score(
    score: music21.stream.Score,
    melody_part_index: int,
    *,
    input_midi_path: str,
) -> ExtractedStructure:
    resolved = resolve_melody_part_index(score, melody_part_index)
    melody_part = get_melody_part(score, resolved)
    key_info = detect_key_music21(input_midi_path)
    tonic_pc = int(key_info["tonic_pc"])
    mode = str(key_info["mode"])
    scale_pitch_classes = _build_scale_pitch_classes(tonic_pc, mode)
    center_pitch = _compute_center_pitch(melody_part)
    return ExtractedStructure(
        tempo_bpm=_extract_tempo_bpm(score),
        time_signature=_extract_time_signature(score),
        num_bars=_estimate_num_bars(score),
        tonic_pc=tonic_pc,
        mode=mode,
        scale_pitch_classes=scale_pitch_classes,
        center_pitch=center_pitch,
        melody_part_index=resolved,
    )


def extract_structure(input_midi_path: str, melody_part_index: int = 0) -> ExtractedStructure:
    score = music21.converter.parse(input_midi_path)
    return extract_structure_from_score(
        score, melody_part_index, input_midi_path=input_midi_path
    )
