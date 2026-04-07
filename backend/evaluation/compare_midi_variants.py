#!/usr/bin/env python3
"""
Compare symbolic MIDI variants with basic structural metrics.

Requires: miditoolkit (already listed in backend requirements).
"""

from __future__ import annotations

import argparse
import csv
import math
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, Iterable, List, Optional, Tuple

import miditoolkit


@dataclass
class MidiMetrics:
    name: str
    total_notes: int
    duration_sec: float
    notes_per_sec: float
    min_pitch: Optional[int]
    max_pitch: Optional[int]
    pitch_range: Optional[int]
    unique_pitches: int
    mean_note_dur: Optional[float]
    min_note_dur: Optional[float]
    overlap_count: int
    overlap_rate: float
    mean_onset_dev_16th: Optional[float]
    max_polyphony: int
    mean_polyphony: Optional[float]


def _tempo_segments(
    tempo_changes: Iterable,
    ticks_per_beat: int,
    max_tick: int,
) -> List[Tuple[int, int, float, float]]:
    # Support both (tick, bpm) tuples and miditoolkit.TempoChange objects.
    parsed: List[Tuple[int, float]] = []
    for item in tempo_changes or []:
        if hasattr(item, "time") and hasattr(item, "tempo"):
            parsed.append((int(item.time), float(item.tempo)))
        else:
            parsed.append((int(item[0]), float(item[1])))

    if not parsed:
        parsed = [(0, 120.0)]

    parsed.sort(key=lambda x: x[0])
    if parsed[0][0] > 0:
        parsed.insert(0, (0, parsed[0][1]))

    segments: List[Tuple[int, int, float, float]] = []
    cur_sec = 0.0
    for i, (tick, bpm) in enumerate(parsed):
        next_tick = parsed[i + 1][0] if i + 1 < len(parsed) else max_tick
        sec_per_tick = 60.0 / (bpm * ticks_per_beat)
        segments.append((tick, next_tick, sec_per_tick, cur_sec))
        cur_sec += (next_tick - tick) * sec_per_tick
    return segments


def _tick_to_sec(segments: List[Tuple[int, int, float, float]], tick: int) -> float:
    for start_tick, end_tick, sec_per_tick, start_sec in segments:
        if tick < end_tick:
            return start_sec + (tick - start_tick) * sec_per_tick
    # fallback to last segment
    start_tick, end_tick, sec_per_tick, start_sec = segments[-1]
    return start_sec + (tick - start_tick) * sec_per_tick


def _collect_notes(midi: miditoolkit.MidiFile) -> List[miditoolkit.Note]:
    notes: List[miditoolkit.Note] = []
    for inst in midi.instruments:
        notes.extend(inst.notes)
    return notes


def _overlap_count(notes: List[miditoolkit.Note]) -> int:
    # count overlaps of same pitch
    overlaps = 0
    by_pitch: Dict[int, List[miditoolkit.Note]] = {}
    for n in notes:
        by_pitch.setdefault(n.pitch, []).append(n)
    for pitch, plist in by_pitch.items():
        plist.sort(key=lambda n: (n.start, n.end))
        last_end = -1
        for n in plist:
            if n.start < last_end:
                overlaps += 1
            last_end = max(last_end, n.end)
    return overlaps


def _polyphony_stats(
    notes: List[miditoolkit.Note],
    tick_to_sec,
) -> Tuple[int, Optional[float]]:
    if not notes:
        return 0, None
    events: List[Tuple[int, int]] = []
    for n in notes:
        events.append((n.start, 1))
        events.append((n.end, -1))
    events.sort(key=lambda x: (x[0], -x[1]))

    max_poly = 0
    cur_poly = 0
    total_time = 0.0
    weighted_poly = 0.0

    for i in range(len(events) - 1):
        tick, delta = events[i]
        cur_poly += delta
        max_poly = max(max_poly, cur_poly)
        next_tick = events[i + 1][0]
        if next_tick > tick:
            dt = tick_to_sec(next_tick) - tick_to_sec(tick)
            total_time += dt
            weighted_poly += cur_poly * dt
    mean_poly = (weighted_poly / total_time) if total_time > 0 else None
    return max_poly, mean_poly


def compute_metrics(path: Path, label: Optional[str] = None) -> MidiMetrics:
    midi = miditoolkit.MidiFile(str(path))
    notes = _collect_notes(midi)
    max_tick = max((n.end for n in notes), default=0)
    segments = _tempo_segments(midi.tempo_changes, midi.ticks_per_beat, max_tick)
    tick_to_sec = lambda t: _tick_to_sec(segments, t)

    duration_sec = tick_to_sec(max_tick) if max_tick > 0 else 0.0

    if notes:
        pitches = [n.pitch for n in notes]
        min_pitch = min(pitches)
        max_pitch = max(pitches)
        pitch_range = max_pitch - min_pitch
        unique_pitches = len(set(pitches))
        durations = [tick_to_sec(n.end) - tick_to_sec(n.start) for n in notes]
        mean_note_dur = sum(durations) / len(durations)
        min_note_dur = min(durations)
    else:
        min_pitch = max_pitch = pitch_range = None
        unique_pitches = 0
        mean_note_dur = min_note_dur = None

    total_notes = len(notes)
    notes_per_sec = (total_notes / duration_sec) if duration_sec > 0 else 0.0

    overlaps = _overlap_count(notes)
    overlap_rate = (overlaps / total_notes) if total_notes > 0 else 0.0

    # Onset deviation to 16th grid (use first tempo)
    if midi.tempo_changes:
        first = midi.tempo_changes[0]
        base_bpm = float(first.tempo) if hasattr(first, "tempo") else float(first[1])
    else:
        base_bpm = 120.0
    sec_per_beat = 60.0 / base_bpm
    grid = sec_per_beat / 4.0
    if notes and grid > 0:
        deviations = []
        for n in notes:
            onset = tick_to_sec(n.start)
            mod = onset % grid
            dev = min(mod, grid - mod)
            deviations.append(dev)
        mean_onset_dev = sum(deviations) / len(deviations)
    else:
        mean_onset_dev = None

    max_poly, mean_poly = _polyphony_stats(notes, tick_to_sec)

    return MidiMetrics(
        name=label or path.stem,
        total_notes=total_notes,
        duration_sec=duration_sec,
        notes_per_sec=notes_per_sec,
        min_pitch=min_pitch,
        max_pitch=max_pitch,
        pitch_range=pitch_range,
        unique_pitches=unique_pitches,
        mean_note_dur=mean_note_dur,
        min_note_dur=min_note_dur,
        overlap_count=overlaps,
        overlap_rate=overlap_rate,
        mean_onset_dev_16th=mean_onset_dev,
        max_polyphony=max_poly,
        mean_polyphony=mean_poly,
    )


def _format_float(x: Optional[float], digits: int = 4) -> str:
    if x is None:
        return "NA"
    return f"{x:.{digits}f}"


def print_markdown(metrics: List[MidiMetrics]) -> None:
    headers = [
        "name", "notes", "duration_s", "notes/s",
        "min_pitch", "max_pitch", "range", "unique",
        "mean_dur", "min_dur",
        "overlaps", "overlap_rate",
        "onset_dev_16th", "max_poly", "mean_poly",
    ]
    print("| " + " | ".join(headers) + " |")
    print("|" + "|".join(["---"] * len(headers)) + "|")
    for m in metrics:
        row = [
            m.name,
            str(m.total_notes),
            _format_float(m.duration_sec, 2),
            _format_float(m.notes_per_sec, 3),
            str(m.min_pitch) if m.min_pitch is not None else "NA",
            str(m.max_pitch) if m.max_pitch is not None else "NA",
            str(m.pitch_range) if m.pitch_range is not None else "NA",
            str(m.unique_pitches),
            _format_float(m.mean_note_dur),
            _format_float(m.min_note_dur),
            str(m.overlap_count),
            _format_float(m.overlap_rate),
            _format_float(m.mean_onset_dev_16th),
            str(m.max_polyphony),
            _format_float(m.mean_polyphony),
        ]
        print("| " + " | ".join(row) + " |")


def write_csv(metrics: List[MidiMetrics], path: Path) -> None:
    fieldnames = list(MidiMetrics.__annotations__.keys())
    with path.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        for m in metrics:
            writer.writerow(m.__dict__)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--inputs",
        nargs="+",
        required=True,
        help="List of MIDI files (e.g., S1.mid S2.mid S3.mid S4.mid)",
    )
    parser.add_argument(
        "--labels",
        nargs="*",
        default=None,
        help="Optional labels aligned with inputs",
    )
    parser.add_argument(
        "--csv",
        default="",
        help="Optional path to save CSV output",
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    paths = [Path(p) for p in args.inputs]
    labels = args.labels or []
    metrics: List[MidiMetrics] = []
    for i, p in enumerate(paths):
        label = labels[i] if i < len(labels) else None
        metrics.append(compute_metrics(p, label=label))

    print_markdown(metrics)
    if args.csv:
        write_csv(metrics, Path(args.csv))


if __name__ == "__main__":
    main()
