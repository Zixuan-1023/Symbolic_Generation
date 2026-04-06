from __future__ import annotations

import argparse
import os
import shutil
import tempfile
from collections import defaultdict
from dataclasses import replace
from pathlib import Path
from typing import Any, Dict, List, Optional

import music21
from music21 import chord, converter, note, volume

from generation_cleanup import run_generation_cleanup
from refine.control_mapping import (
    DEFAULT_CONTOUR,
    DEFAULT_NOTE_DENSITY,
    DEFAULT_PITCH_RANGE,
    DEFAULT_RHYTHM_COMPLEXITY,
    map_controls_to_refine_params,
)
from refine.structure_extract import extract_structure_from_score, get_melody_part
from refine.tonal_postprocess import apply_tonal_constraints, snap_pitch_to_scale_nearest
from refine.transform_engine import (
    MelodyTransformEvent,
    _note_onset_in_part,
    extract_melody_events_from_part,
    transform_melody_events,
)
from refine.types import GeneratorConfig


def _count_notes_in_part(part: music21.stream.Part) -> int:
    """Count note.Note objects under a part recursively."""
    count = 0
    for el in part.recurse():
        if isinstance(el, note.Note):
            count += 1
    return count


def _strip_melody_notes_and_chords(part: music21.stream.Part) -> int:
    """
    Remove all Note/Chord from target part while preserving tempo/meter/instrument/meta.

    We clear both measure-level containers and part-top-level residues to avoid leftovers.
    Returns number of removed elements.
    """
    removed = 0
    for measure in part.getElementsByClass(music21.stream.Measure):
        # Important: recurse to catch notes nested inside Voice containers.
        for el in list(measure.recurse()):
            if isinstance(el, (note.Note, chord.Chord)):
                site = el.activeSite
                if site is not None:
                    site.remove(el)
                    removed += 1
    for el in list(part):
        if isinstance(el, (note.Note, chord.Chord)):
            part.remove(el)
            removed += 1
    return removed


def _clamp_event_pitch(ev: MelodyTransformEvent, lo: int, hi: int) -> MelodyTransformEvent:
    p = max(lo, min(hi, ev.pitch))
    return replace(ev, pitch=p)


def _validate_monophonic_melody_part(part: music21.stream.Part) -> Dict[str, int]:
    """
    Check polyphony on the target part.

    Historically we hard-failed when multiple ``Note`` objects share the same onset.
    In product terms this makes refine brittle for real-world MIDI exports.

    Now default behavior is:
    - If polyphony detected: do not raise; let `extract_melody_events_from_part` pick
      a single melody line.
    - If env `POST_REFINE_STRICT_MONOPHONIC=1`: keep the old hard failure.
    """
    by_onset: Dict[float, List[note.Note]] = defaultdict(list)
    for el in part.flatten().notes:
        if isinstance(el, note.Note):
            o = _note_onset_in_part(el, part)
            by_onset[round(float(o), 6)].append(el)
    strict = os.environ.get("POST_REFINE_STRICT_MONOPHONIC", "0").strip() == "1"
    num_conflicting_onsets = 0
    num_conflicting_notes_total = 0
    for onset_key, group in by_onset.items():
        if len(group) <= 1:
            continue
        num_conflicting_onsets += 1
        num_conflicting_notes_total += len(group)
        if strict:
            raise ValueError(
                "Expected single-voice melody on the target part: "
                f"{len(group)} notes at onset {onset_key} (quarter offset). "
                "Reduce polyphony or use a single-track export."
            )

    return {
        "num_conflicting_onsets": int(num_conflicting_onsets),
        "num_conflicting_notes_total": int(num_conflicting_notes_total),
    }


def _write_melody_events_to_part(part: music21.stream.Part, events: List[MelodyTransformEvent]) -> None:
    for ev in sorted(events, key=lambda e: (e.onset_quarter, e.bar_index)):
        n = note.Note(int(ev.pitch))
        n.quarterLength = float(ev.duration_quarter)
        vol = volume.Volume()
        vol.velocity = int(ev.velocity)
        n.volume = vol
        part.insert(float(ev.onset_quarter), n)


def run_refine_pipeline(
    input_midi_path: str,
    output_midi_path: str,
    *,
    melody_part_index: int = 0,
    pitch_variation: float = 0.20,
    rhythm_variation: float = 0.05,
    motif_variation: float = 0.10,
    humanize: float = 0.0,
    min_pitch: int = 48,
    max_pitch: int = 84,
    steps_per_bar: int = 16,
    seed: int = 42,
    enable_cleanup: bool = True,
    preserve_track_metadata_on_cleanup: bool = True,
    debug_writeback: bool = False,
    enable_tonal_postprocess: bool = True,
    tonal_strong_beat_triad_snap: bool = True,
    enable_note_merge: bool = True,
    enable_motif_variation: bool = True,
    force_motif_variation: bool = False,
    merge_strength: Optional[float] = None,
    melody_follow: float = 0.5,
    nudge_weak_repeated_pitch: Optional[bool] = None,
) -> Dict[str, Any]:
    """
    Refine mode: extract melody → local transform → tonal constraints → write part → cleanup.

    Does not alter tempo, time signature, instrument, or program/control changes globally;
    only the target non-drum part's ``Note`` / ``Chord`` content is replaced by monophonic notes.
    """
    input_midi_path = str(Path(input_midi_path).resolve())
    output_midi_path = str(Path(output_midi_path).resolve())
    Path(output_midi_path).parent.mkdir(parents=True, exist_ok=True)

    _ = GeneratorConfig(
        steps_per_bar=steps_per_bar,
        min_pitch=min_pitch,
        max_pitch=max_pitch,
        seed=seed,
    )

    score = converter.parse(input_midi_path)
    structure = extract_structure_from_score(
        score,
        melody_part_index,
        input_midi_path=input_midi_path,
    )
    melody_part = get_melody_part(score, structure.melody_part_index)

    mf = max(0.0, min(1.0, float(melody_follow)))
    raw_events, extraction_stats = extract_melody_events_from_part(
        melody_part, score, return_stats=True, melody_follow=mf
    )
    transformed, transform_stats = transform_melody_events(
        raw_events,
        pitch_variation=pitch_variation,
        rhythm_variation=rhythm_variation,
        motif_variation=motif_variation,
        humanize=humanize,
        scale_pitch_classes=set(structure.scale_pitch_classes),
        tonic_pc=structure.tonic_pc,
        mode=structure.mode,
        seed=seed,
        enable_note_merge=enable_note_merge,
        enable_motif_variation=enable_motif_variation,
        force_motif_variation=force_motif_variation,
        merge_strength=merge_strength,
    )

    # --- Humanize debug (before tonal/clamp and before cleanup) ---
    # This is intentionally lightweight and opt-in: it helps confirm whether
    # UI sliders -> mapped params -> humanize edits -> cleanup does/doesn't erase them.
    humanize_debug = os.environ.get("POST_REFINE_HUMANIZE_DEBUG", "0").strip() == "1"
    if humanize_debug:
        print("[refine] derived_humanize:", float(transform_stats.get("humanize", 0.0)))
        print(
            "[refine] humanize stats:",
            {
                "num_humanized_notes": transform_stats.get("num_humanized_notes", 0),
                "num_onset_shifted": transform_stats.get("num_onset_shifted", 0),
                "num_velocity_shifted": transform_stats.get("num_velocity_shifted", 0),
                "avg_onset_shift_quarter_abs": transform_stats.get(
                    "avg_onset_shift_quarter_abs", 0.0
                ),
                "avg_velocity_shift_abs": transform_stats.get("avg_velocity_shift_abs", 0.0),
                "max_abs_onset_shift_quarter": transform_stats.get(
                    "max_abs_onset_shift_quarter", 0.0
                ),
                "max_abs_velocity_shift": transform_stats.get(
                    "max_abs_velocity_shift", 0
                ),
            },
        )

    nudge_repeats = nudge_weak_repeated_pitch
    if nudge_repeats is None:
        nudge_repeats = (not tonal_strong_beat_triad_snap) and enable_tonal_postprocess

    if enable_tonal_postprocess:
        constrained, tonal_stats = apply_tonal_constraints(
            transformed,
            scale_pitch_classes=set(structure.scale_pitch_classes),
            tonic_pc=structure.tonic_pc,
            mode=structure.mode,
            strong_beat_tonic_triad_snap=tonal_strong_beat_triad_snap,
            nudge_weak_repeated_pitch=nudge_repeats,
        )
    else:
        constrained = [replace(e) for e in transformed]
        tonal_stats = {
            "enabled": False,
            "num_events": len(transformed),
            "num_pitch_corrected": 0,
            "num_strong_beat_corrections": 0,
            "num_weak_beat_corrections": 0,
            "strong_beat_tonic_triad_snap": False,
            "nudge_weak_repeated_pitch": False,
            "num_weak_repeat_nudges": 0,
        }

    scale_set = set(structure.scale_pitch_classes)
    clamped = [_clamp_event_pitch(e, min_pitch, max_pitch) for e in constrained]
    # Clamp can push pitch class off-scale; force back onto detected scale.
    final_events = [
        replace(e, pitch=snap_pitch_to_scale_nearest(e.pitch, scale_set)) for e in clamped
    ]

    before_strip = _count_notes_in_part(melody_part)
    removed = _strip_melody_notes_and_chords(melody_part)
    after_strip = _count_notes_in_part(melody_part)
    _write_melody_events_to_part(melody_part, final_events)
    after_insert = _count_notes_in_part(melody_part)
    writeback_debug = {
        "before_strip": before_strip,
        "removed": removed,
        "after_strip": after_strip,
        "after_insert": after_insert,
        "events_to_insert": len(final_events),
    }
    if debug_writeback:
        print("writeback_debug:", writeback_debug)

    structure_summary: Dict[str, Any] = {
        "tempo_bpm": structure.tempo_bpm,
        "time_signature": structure.time_signature,
        "num_bars": structure.num_bars,
        "tonic_pc": structure.tonic_pc,
        "mode": structure.mode,
        "scale_pitch_classes": sorted(structure.scale_pitch_classes),
        "center_pitch": structure.center_pitch,
        "melody_part_index": structure.melody_part_index,
    }

    cleanup_result: Dict[str, Any] = {}

    # Humanize protection: generation_cleanup timing quantization can "wash out"
    # micro-jitter. When derived_humanize is high we reduce or disable timing cleanup.
    derived_humanize_now = float(transform_stats.get("humanize", 0.0))
    cleanup_humanize_protection = False
    cleanup_effective_timing_cleanup_enabled: Optional[bool] = None
    cleanup_effective_timing_strength: Optional[float] = None
    if derived_humanize_now >= 0.65:
        cleanup_humanize_protection = True
        cleanup_effective_timing_cleanup_enabled = False
        cleanup_effective_timing_strength = None
    elif derived_humanize_now >= 0.35:
        cleanup_humanize_protection = True
        cleanup_effective_timing_cleanup_enabled = True
        cleanup_effective_timing_strength = 0.35

    with tempfile.TemporaryDirectory() as tmpd:
        raw_path = str(Path(tmpd) / "refine_raw.mid")
        score.write("midi", fp=raw_path)
        if enable_cleanup:
            try:
                cleanup_result = run_generation_cleanup(
                    raw_path,
                    output_midi_path,
                    enable_track_alignment=None,
                    enable_timing_cleanup=cleanup_effective_timing_cleanup_enabled,
                    enable_duration_cleanup=None,
                    enable_overlap_cleanup=None,
                    enable_tonal_correction=False,
                    preserve_track_metadata=preserve_track_metadata_on_cleanup,
                    preserve_track_metadata_from=input_midi_path,
                    timing_strength=(
                        cleanup_effective_timing_strength
                        if cleanup_effective_timing_strength is not None
                        else 0.82
                    ),
                )
            except ValueError as e:
                # If the refined writeback produced an empty MIDI (no notes at all),
                # key detection in generation_cleanup will crash. In product terms,
                # better to return the transform-only MIDI than fail the whole job.
                shutil.copyfile(raw_path, output_midi_path)
                cleanup_result = {
                    "enabled": False,
                    "error": str(e),
                    "note_detection_skipped": True,
                }
        else:
            shutil.copyfile(raw_path, output_midi_path)

    # If cleanup does timing grid quantization, it can effectively remove tiny
    # onset jitter introduced by humanize. We expose a debug estimate.
    derived_humanize = derived_humanize_now
    timing_moved = 0
    if isinstance(cleanup_result, dict):
        tc = cleanup_result.get("timing_cleanup") or {}
        if isinstance(tc, dict):
            timing_moved = int(tc.get("moved_events", 0) or 0)
    cleanup_suppressed_humanize = bool(derived_humanize > 1e-9 and timing_moved > 0)

    return {
        "input_midi_path": input_midi_path,
        "output_midi_path": output_midi_path,
        "structure": structure_summary,
        "transform_stats": transform_stats,
        "extraction_stats": extraction_stats,
        "tonal_stats": tonal_stats,
        "writeback_debug": writeback_debug,
        "cleanup_enabled": enable_cleanup,
        "cleanup_result": cleanup_result,
        # --- Humanize observability (product/debug) ---
        "derived_humanize": derived_humanize,
        "cleanup_humanize_protection": cleanup_humanize_protection,
        "cleanup_effective_timing_cleanup_enabled": cleanup_effective_timing_cleanup_enabled,
        "cleanup_effective_timing_strength": cleanup_effective_timing_strength,
        "num_humanized_notes": transform_stats.get("num_humanized_notes", 0),
        "avg_onset_shift": transform_stats.get("avg_onset_shift_quarter_signed", 0.0),
        "avg_velocity_shift": transform_stats.get("avg_velocity_shift_signed", 0.0),
        "cleanup_suppressed_humanize": cleanup_suppressed_humanize,
        "cleanup_timing_moved_events": timing_moved,
        "refine_controls": {
            "enable_tonal_postprocess": enable_tonal_postprocess,
            "tonal_strong_beat_triad_snap": tonal_strong_beat_triad_snap
            if enable_tonal_postprocess
            else False,
            "enable_note_merge": enable_note_merge,
            "enable_motif_variation": enable_motif_variation,
            "force_motif_variation": force_motif_variation,
            "melody_follow": mf,
            "nudge_weak_repeated_pitch": nudge_repeats
            if enable_tonal_postprocess
            else False,
        },
        "config": {
            "steps_per_bar": steps_per_bar,
            "min_pitch": min_pitch,
            "max_pitch": max_pitch,
            "seed": seed,
            "melody_follow": mf,
        },
    }


def run_refine_with_controls(
    input_midi_path: str,
    output_midi_path: str,
    *,
    rhythm_complexity: float = DEFAULT_RHYTHM_COMPLEXITY,
    pitch_range: float = DEFAULT_PITCH_RANGE,
    note_density: float = DEFAULT_NOTE_DENSITY,
    contour: float = DEFAULT_CONTOUR,
    melody_part_index: int = 0,
    seed: int = 42,
    enable_cleanup: bool = True,
    steps_per_bar: int = 16,
    debug_writeback: bool = False,
    humanize: Optional[float] = None,
    tonal_triad_snap: bool = False,
) -> Dict[str, Any]:
    """
    Control-sliders → ``map_controls_to_refine_params`` → :func:`run_refine_pipeline`.

    Input: single-part monophonic melody MIDI. Validates one note per onset on the
    target part before processing.
    """
    input_midi_path = str(Path(input_midi_path).resolve())
    output_midi_path = str(Path(output_midi_path).resolve())

    score = converter.parse(input_midi_path)
    structure = extract_structure_from_score(
        score,
        melody_part_index,
        input_midi_path=input_midi_path,
    )
    melody_part = get_melody_part(score, structure.melody_part_index)
    mono_stats = _validate_monophonic_melody_part(melody_part)

    mapped = map_controls_to_refine_params(
        rhythm_complexity,
        pitch_range,
        note_density,
        contour,
        center_pitch=float(structure.center_pitch),
    )

    triad_snap = tonal_triad_snap or (mapped["tonal_mode"] != "scale_only")

    hz = float(mapped["humanize"])
    if humanize is not None:
        hz = max(0.0, min(1.0, float(humanize)))

    co_clamped = max(0.0, min(1.0, float(contour)))
    summary = run_refine_pipeline(
        input_midi_path,
        output_midi_path,
        melody_part_index=melody_part_index,
        pitch_variation=mapped["pitch_variation"],
        rhythm_variation=mapped["rhythm_variation"],
        motif_variation=mapped["motif_variation"],
        humanize=hz,
        min_pitch=int(mapped["min_pitch"]),
        max_pitch=int(mapped["max_pitch"]),
        steps_per_bar=steps_per_bar,
        seed=seed,
        enable_cleanup=enable_cleanup,
        debug_writeback=debug_writeback,
        enable_tonal_postprocess=True,
        tonal_strong_beat_triad_snap=triad_snap,
        enable_note_merge=bool(mapped["enable_note_merge"]),
        enable_motif_variation=bool(mapped["enable_motif_variation"]),
        force_motif_variation=bool(mapped["force_motif_variation"]),
        merge_strength=float(mapped["merge_strength"]),
        melody_follow=co_clamped,
    )

    controls_in = {
        "rhythm_complexity": max(0.0, min(1.0, float(rhythm_complexity))),
        "pitch_range": max(0.0, min(1.0, float(pitch_range))),
        "note_density": max(0.0, min(1.0, float(note_density))),
        "contour": max(0.0, min(1.0, float(contour))),
    }

    return {
        "input_midi_path": summary["input_midi_path"],
        "output_midi_path": summary["output_midi_path"],
        "controls": controls_in,
        "mapped_params": mapped,
        "transform_stats": summary["transform_stats"],
        "tonal_stats": summary["tonal_stats"],
        "cleanup_enabled": summary["cleanup_enabled"],
        "cleanup_result": summary.get("cleanup_result", {}),
        "extraction_stats": summary["extraction_stats"],
        "structure": summary["structure"],
        "writeback_debug": summary["writeback_debug"],
        "refine_controls": summary["refine_controls"],
        "config": summary["config"],
        "polyphony_check": mono_stats,
    }


def _build_arg_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        description="Refine: structure-preserving melody transform + tonal pass + optional cleanup."
    )
    p.add_argument("input_midi", help="Input MIDI path")
    p.add_argument("output_midi", help="Output MIDI path")
    p.add_argument("--melody-part-index", type=int, default=0)
    p.add_argument("--pitch-variation", type=float, default=0.20)
    p.add_argument("--rhythm-variation", type=float, default=0.05)
    p.add_argument("--motif-variation", type=float, default=0.10)
    p.add_argument("--humanize", type=float, default=0.0)
    p.add_argument("--min-pitch", type=int, default=48)
    p.add_argument("--max-pitch", type=int, default=84)
    p.add_argument("--steps-per-bar", type=int, default=16)
    p.add_argument("--seed", type=int, default=42)
    p.add_argument(
        "--debug-writeback",
        action="store_true",
        help="Print before/after strip+insert note counts for melody part.",
    )
    p.add_argument(
        "--disable-cleanup",
        action="store_true",
        help="Skip generation_cleanup; write transform-only MIDI.",
    )
    p.add_argument(
        "--skip-tonal",
        action="store_true",
        help="Skip refine tonal post-process (scale/triad snap); only clamp + final scale snap.",
    )
    p.add_argument(
        "--tonal-scale-only",
        action="store_true",
        help="Keep tonal pass but disable strong-beat I-chord snap (reduces 'B4 wall' pulls).",
    )
    p.add_argument(
        "--no-merge",
        action="store_true",
        help="Disable same-pitch note merge (rhythm_variation merge step skipped).",
    )
    p.add_argument(
        "--no-motif",
        action="store_true",
        help="Disable motif local variation (deterministic vs random 'no run').",
    )
    p.add_argument(
        "--force-motif",
        action="store_true",
        help="Always attempt motif window (when enabled), skipping the random 'skip' draw.",
    )
    p.add_argument(
        "--controls",
        action="store_true",
        help="Use four sliders (rhythm / pitch range / density / contour) → mapped params; implies scale-only tonal.",
    )
    p.add_argument(
        "--rhythm-complexity",
        type=float,
        default=DEFAULT_RHYTHM_COMPLEXITY,
        help="[With --controls] rhythm / motif strength driver in [0, 1].",
    )
    p.add_argument(
        "--pitch-range",
        type=float,
        default=DEFAULT_PITCH_RANGE,
        help="[With --controls] pitch clamp window driver in [0, 1].",
    )
    p.add_argument(
        "--note-density",
        type=float,
        default=DEFAULT_NOTE_DENSITY,
        help="[With --controls] merge / density driver in [0, 1].",
    )
    p.add_argument(
        "--contour",
        type=float,
        default=DEFAULT_CONTOUR,
        help="[With --controls] pitch variation (contour) driver in [0, 1].",
    )
    p.add_argument(
        "--melody-follow",
        type=float,
        default=0.5,
        help="Extraction line choice (0–1): higher = smoother contour / less top-voice bias. "
        "Default 0.5; --controls uses --contour for this.",
    )
    p.add_argument(
        "--refine-humanize",
        type=float,
        default=None,
        help="[With --controls] Override mapped humanize [0,1] (mapper default is usually 0).",
    )
    p.add_argument(
        "--tonal-triad-snap",
        action="store_true",
        help="[With --controls] Strong-beat tonic triad snap (more tonal pull than scale-only).",
    )
    return p


def main() -> None:
    args = _build_arg_parser().parse_args()
    if args.controls:
        summary = run_refine_with_controls(
            args.input_midi,
            args.output_midi,
            rhythm_complexity=args.rhythm_complexity,
            pitch_range=args.pitch_range,
            note_density=args.note_density,
            contour=args.contour,
            melody_part_index=args.melody_part_index,
            seed=args.seed,
            enable_cleanup=not args.disable_cleanup,
            steps_per_bar=args.steps_per_bar,
            debug_writeback=args.debug_writeback,
            humanize=args.refine_humanize,
            tonal_triad_snap=args.tonal_triad_snap,
        )
        print("Refine pipeline complete (control mapping).")
        print("Wrote:", summary["output_midi_path"])
        print("Sliders:", summary["controls"])
        print("Mapped:", summary["mapped_params"])
        print("Cleanup:", summary["cleanup_enabled"])
        print("Refine flags:", summary["refine_controls"])
        print("Transform:", summary["transform_stats"])
        print("Tonal:", summary["tonal_stats"])
        return

    if args.skip_tonal and args.tonal_scale_only:
        raise SystemExit("Choose at most one of --skip-tonal and --tonal-scale-only.")
    if args.no_motif and args.force_motif:
        raise SystemExit("Do not combine --no-motif with --force-motif.")

    enable_tonal = not args.skip_tonal
    triad_snap = not args.tonal_scale_only

    summary = run_refine_pipeline(
        input_midi_path=args.input_midi,
        output_midi_path=args.output_midi,
        melody_part_index=args.melody_part_index,
        pitch_variation=args.pitch_variation,
        rhythm_variation=args.rhythm_variation,
        motif_variation=args.motif_variation,
        humanize=args.humanize,
        min_pitch=args.min_pitch,
        max_pitch=args.max_pitch,
        steps_per_bar=args.steps_per_bar,
        seed=args.seed,
        enable_cleanup=not args.disable_cleanup,
        debug_writeback=args.debug_writeback,
        enable_tonal_postprocess=enable_tonal,
        tonal_strong_beat_triad_snap=triad_snap if enable_tonal else False,
        enable_note_merge=not args.no_merge,
        enable_motif_variation=not args.no_motif,
        force_motif_variation=args.force_motif,
        melody_follow=args.melody_follow,
    )
    print("Refine pipeline complete.")
    print("Wrote:", summary["output_midi_path"])
    print("Cleanup:", summary["cleanup_enabled"])
    print("Controls:", summary["refine_controls"])
    print("Transform:", summary["transform_stats"])
    print("Tonal:", summary["tonal_stats"])


if __name__ == "__main__":
    main()
