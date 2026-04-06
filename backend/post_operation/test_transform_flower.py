#!/usr/bin/env python3
"""Smoke test: transform_engine on Flower Dance.mid → Flower Dance_transformed.mid"""

from __future__ import annotations

from pathlib import Path

import music21
from music21 import instrument, note, volume

from analysis.key_detection import detect_key_music21
from refine.transform_engine import (
    extract_melody_events_from_part,
    transform_melody_events,
)


def _is_drum_part(part: music21.stream.Part) -> bool:
    for inst in part.recurse().getElementsByClass(instrument.Instrument):
        if isinstance(inst, instrument.UnpitchedPercussion):
            return True
        if getattr(inst, "midiChannel", None) == 9:
            return True
    return False


def _non_drum_parts(score: music21.stream.Score) -> list[music21.stream.Part]:
    return [p for p in score.parts if not _is_drum_part(p)]


def _scale_pitch_classes(tonic_pc: int, mode: str) -> set[int]:
    r = tonic_pc % 12
    m = mode.lower().strip()
    if m == "minor":
        intervals = (0, 2, 3, 5, 7, 8, 10)
    else:
        intervals = (0, 2, 4, 5, 7, 9, 11)
    return {(r + i) % 12 for i in intervals}


def _strip_part_notes(part: music21.stream.Part) -> None:
    for el in list(part.recurse()):
        if isinstance(el, note.Note):
            site = el.activeSite
            if site is not None:
                site.remove(el)


def _apply_events_to_part(part: music21.stream.Part, events) -> None:
    for ev in sorted(events, key=lambda e: (e.onset_quarter, e.bar_index)):
        n = note.Note(int(ev.pitch))
        n.quarterLength = float(ev.duration_quarter)
        vol = volume.Volume()
        vol.velocity = int(ev.velocity)
        n.volume = vol
        part.insert(float(ev.onset_quarter), n)


def main() -> None:
    root = Path(__file__).resolve().parent
    inp = root / "Flower Dance.mid"
    out = root / "Flower Dance_transformed.mid"

    path_str = str(inp)
    score = music21.converter.parse(path_str)
    parts_nd = _non_drum_parts(score)
    if not parts_nd:
        raise SystemExit("No non-drum parts found.")
    part = parts_nd[0]

    key_info = detect_key_music21(path_str)
    tonic_pc = int(key_info["tonic_pc"])
    mode = str(key_info["mode"])
    scale_pcs = _scale_pitch_classes(tonic_pc, mode)

    raw = extract_melody_events_from_part(part, score)
    print(f"Extracted {len(raw)} melody notes.")

    transformed, stats = transform_melody_events(
        raw,
        pitch_variation=0.35,
        rhythm_variation=0.25,
        motif_variation=0.3,
        humanize=0.15,
        scale_pitch_classes=scale_pcs,
        tonic_pc=tonic_pc,
        mode=mode,
        seed=2026,
    )

    print("Key:", key_info.get("key_name"), "scale pcs:", sorted(scale_pcs))
    print("Stats:", stats)

    _strip_part_notes(part)
    _apply_events_to_part(part, transformed)

    score.write("midi", fp=str(out))
    print(f"Wrote: {out}")


if __name__ == "__main__":
    main()
