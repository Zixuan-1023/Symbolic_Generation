from __future__ import annotations

import argparse
import shutil
import tempfile
from pathlib import Path
from typing import Any, Dict, Optional

from analysis.key_detection import detect_key_music21
from clean_up.hard_constraints import (
    enforce_num_bars,
    parse_target_key,
    parse_time_signature,
    set_tempo_bpm,
)
from clean_up.duration_cleanup import cleanup_duration
from clean_up.midi_track_meta import restore_track_metadata
from clean_up.overlap_cleanup import cleanup_overlaps
from clean_up.timing_cleanup import cleanup_timing
from clean_up.tonal_correction import apply_tonal_correction
from clean_up.track_alignment import align_track_onsets, count_non_drum_tracks_with_pitched_notes


def run_generation_cleanup(
    input_midi_path: str,
    output_midi_path: str,
    *,
    enable_track_alignment: Optional[bool] = None,
    enable_timing_cleanup: Optional[bool] = None,
    enable_duration_cleanup: Optional[bool] = None,
    enable_overlap_cleanup: Optional[bool] = None,
    enable_tonal_correction: Optional[bool] = None,
    onset_threshold_quarter_length: float = 0.03,
    grid_quarter_length: float = 0.25,
    timing_strength: float = 0.82,
    min_duration_quarter_length: float = 0.25,
    duration_mode: str = "extend",
    overlap_min_duration_quarter_length: float = 0.01,
    tonal_correction_mode: str = "gentle",
    delete_short_out_of_key: bool = False,
    short_note_threshold_quarter_length: float = 0.25,
    tonal_tie_break: str = "down",
    preserve_track_metadata: Optional[bool] = None,
    preserve_track_metadata_from: Optional[str] = None,
    target_bars: Optional[int] = None,
    target_bpm: Optional[float] = None,
    target_key: Optional[str] = None,
    time_signature: str = "4/4",
    tonal_snap: str = "gentle",
) -> Dict[str, Any]:
    """
    Cleanup-only pipeline for generated MIDI: fix symbolic defects without
    style/register/density control (those live under ``control/`` later).

    Order when enabled:
    1. Key detection (always, for metadata and optional tonal step)
    2. Track alignment — small cross-part onset deviations; ``enable_track_alignment=None``
       (default) skips this step when only one non-drum pitched track (typical MuseCoco solo).
    3. Timing cleanup — soft grid quantization (default strength 0.82 toward grid)
    4. Duration cleanup — mostly extend short/fragmentary notes
    5. Overlap cleanup — same-pitch overlaps
    6. Tonal correction — optional; default pipeline leaves this off;
       when on, ``gentle`` only adjusts short out-of-key events (unless ``target_key``
       is set, which enables tonal snap to that key).
    7. Hard constraints (optional): exact bar count, global BPM, target key for tonal.

    Run from the ``post_operation`` directory so ``analysis`` and ``clean_up`` import.

    When ``preserve_track_metadata`` is True, per-track ``track_name`` / ``instrument_name``
    meta events are copied from ``preserve_track_metadata_from`` (default: input file) onto
    the final output so DAWs still show original instrument names (requires ``mido``).
    """
    input_midi_path = str(Path(input_midi_path).resolve())
    output_midi_path = str(Path(output_midi_path).resolve())

    key_info = detect_key_music21(input_midi_path)
    step_results: Dict[str, Any] = {"key_detection": key_info}

    _use_timing = True if enable_timing_cleanup is None else bool(enable_timing_cleanup)
    _use_duration = True if enable_duration_cleanup is None else bool(enable_duration_cleanup)
    _use_overlap = True if enable_overlap_cleanup is None else bool(enable_overlap_cleanup)
    _use_tonal = False if enable_tonal_correction is None else bool(enable_tonal_correction)
    _preserve_meta = True if preserve_track_metadata is None else bool(preserve_track_metadata)

    _align = enable_track_alignment
    if _align is None:
        _align = count_non_drum_tracks_with_pitched_notes(input_midi_path) > 1

    current = input_midi_path
    step_idx = 0

    with tempfile.TemporaryDirectory() as tmp:
        tmp_path = Path(tmp)

        def _next_mid() -> str:
            nonlocal step_idx
            step_idx += 1
            return str(tmp_path / f"cleanup_{step_idx}.mid")

        if _align:
            out = _next_mid()
            step_results["track_alignment"] = align_track_onsets(
                current,
                out,
                onset_threshold_quarter_length=onset_threshold_quarter_length,
            )
            current = out
        else:
            reason = (
                "auto_single_track"
                if enable_track_alignment is None
                else "disabled"
            )
            step_results["track_alignment"] = {"enabled": False, "reason": reason}

        if _use_timing:
            out = _next_mid()
            step_results["timing_cleanup"] = cleanup_timing(
                current,
                out,
                grid_quarter_length=grid_quarter_length,
                strength=timing_strength,
            )
            current = out
        else:
            step_results["timing_cleanup"] = {"enabled": False}

        if _use_duration:
            out = _next_mid()
            step_results["duration_cleanup"] = cleanup_duration(
                current,
                out,
                min_duration_quarter_length=min_duration_quarter_length,
                mode=duration_mode,
            )
            current = out
        else:
            step_results["duration_cleanup"] = {"enabled": False}

        if _use_overlap:
            out = _next_mid()
            step_results["overlap_cleanup"] = cleanup_overlaps(
                current,
                out,
                min_duration_quarter_length=overlap_min_duration_quarter_length,
            )
            current = out
        else:
            step_results["overlap_cleanup"] = {"enabled": False}

        use_tonal = _use_tonal or (target_key is not None)
        if use_tonal:
            if target_key:
                t_pc, t_mode = parse_target_key(target_key)
                corr_mode = tonal_snap.lower().strip()
                if corr_mode not in {"gentle", "strict"}:
                    corr_mode = "gentle"
            else:
                t_pc = int(key_info["tonic_pc"])
                t_mode = str(key_info["mode"])
                corr_mode = tonal_correction_mode
            out = _next_mid()
            step_results["tonal_correction"] = apply_tonal_correction(
                current,
                out,
                tonic_pc=t_pc,
                mode=t_mode,
                correction_mode=corr_mode,
                delete_short_out_of_key=delete_short_out_of_key,
                short_note_threshold_quarter_length=short_note_threshold_quarter_length,
                tie_break=tonal_tie_break,
            )
            current = out
        else:
            step_results["tonal_correction"] = {"enabled": False}

        if target_bars is not None:
            ts_n, ts_d = parse_time_signature(time_signature)
            out = _next_mid()
            step_results["bar_enforce"] = enforce_num_bars(
                current,
                out,
                int(target_bars),
                ts_n,
                ts_d,
            )
            current = out

        if target_bpm is not None:
            out = _next_mid()
            step_results["tempo_hard"] = set_tempo_bpm(
                current, out, float(target_bpm)
            )
            current = out

        shutil.copy2(current, output_midi_path)

    if _preserve_meta:
        meta_ref = preserve_track_metadata_from or input_midi_path
        try:
            step_results["track_metadata_restore"] = restore_track_metadata(
                meta_ref, output_midi_path
            )
        except Exception as exc:
            step_results["track_metadata_restore"] = {
                "enabled": True,
                "error": str(exc),
            }
    else:
        step_results["track_metadata_restore"] = {"enabled": False}

    return step_results


def _build_arg_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        description="Cleanup pipeline: repair timing, duration, overlap, optional tonal noise."
    )
    p.add_argument("input_midi", help="Input MIDI path")
    p.add_argument("output_midi", help="Output MIDI path")
    p.add_argument(
        "--track-alignment",
        dest="track_alignment",
        choices=("auto", "on", "off"),
        default="auto",
        help="auto: skip alignment when only one non-drum pitched track; on/off: force",
    )
    p.add_argument(
        "--disable-track-alignment",
        action="store_true",
        help="Deprecated: same as --track-alignment off",
    )
    p.add_argument(
        "--disable-timing-cleanup",
        action="store_true",
        help="Skip timing / grid quantization",
    )
    p.add_argument(
        "--disable-duration-cleanup",
        action="store_true",
        help="Skip duration cleanup",
    )
    p.add_argument(
        "--disable-overlap-cleanup",
        action="store_true",
        help="Skip overlap trimming",
    )
    p.add_argument(
        "--enable-tonal-correction",
        action="store_true",
        help="Run tonal correction (default: off for conservative cleanup)",
    )
    p.add_argument(
        "--tonal-mode",
        choices=("gentle", "strict"),
        default="gentle",
        help="Tonal step: gentle = short notes only; strict = all out-of-key",
    )
    p.add_argument(
        "--onset-threshold",
        type=float,
        default=0.03,
        help="Track alignment threshold (quarter lengths; keep small)",
    )
    p.add_argument(
        "--grid",
        type=float,
        default=0.25,
        help="Timing cleanup grid step (quarter lengths)",
    )
    p.add_argument(
        "--timing-strength",
        type=float,
        default=0.82,
        help="Timing cleanup blend toward grid [0, 1]",
    )
    p.add_argument(
        "--min-duration",
        type=float,
        default=0.25,
        help="Duration cleanup minimum length (quarter lengths)",
    )
    p.add_argument(
        "--duration-mode",
        choices=("extend", "delete"),
        default="extend",
        help="Duration cleanup mode",
    )
    p.add_argument(
        "--overlap-min-duration",
        type=float,
        default=0.01,
        help="Overlap cleanup: minimum length after trim",
    )
    p.add_argument(
        "--no-preserve-track-metadata",
        action="store_true",
        help="Do not copy track/instrument names from the input onto the output (mido).",
    )
    p.add_argument(
        "--target-bars",
        type=int,
        default=None,
        help="Hard length: truncate or pad with rests to exactly this many measures.",
    )
    p.add_argument(
        "--target-bpm",
        type=float,
        default=None,
        help="Hard tempo: set a single global BPM (replaces MetronomeMarks).",
    )
    p.add_argument(
        "--target-key",
        type=str,
        default=None,
        help='Hard key: e.g. "C major", "A minor" — enables tonal snap to this key.',
    )
    p.add_argument(
        "--time-signature",
        type=str,
        default="4/4",
        help="Meter for --target-bars bar length (e.g. 4/4, 3/4).",
    )
    p.add_argument(
        "--tonal-snap",
        choices=("gentle", "strict"),
        default="gentle",
        help="With --target-key: gentle = short passing tones; strict = all pitches in scale.",
    )
    return p


def main() -> None:
    args = _build_arg_parser().parse_args()
    if args.disable_track_alignment:
        track_align: Optional[bool] = False
    else:
        track_align = {"auto": None, "on": True, "off": False}[args.track_alignment]
    summary = run_generation_cleanup(
        args.input_midi,
        args.output_midi,
        enable_track_alignment=track_align,
        enable_timing_cleanup=not args.disable_timing_cleanup,
        enable_duration_cleanup=not args.disable_duration_cleanup,
        enable_overlap_cleanup=not args.disable_overlap_cleanup,
        enable_tonal_correction=args.enable_tonal_correction,
        tonal_correction_mode=args.tonal_mode,
        onset_threshold_quarter_length=args.onset_threshold,
        grid_quarter_length=args.grid,
        timing_strength=args.timing_strength,
        min_duration_quarter_length=args.min_duration,
        duration_mode=args.duration_mode,
        overlap_min_duration_quarter_length=args.overlap_min_duration,
        preserve_track_metadata=not args.no_preserve_track_metadata,
        target_bars=args.target_bars,
        target_bpm=args.target_bpm,
        target_key=args.target_key,
        time_signature=args.time_signature,
        tonal_snap=args.tonal_snap,
    )
    print("Key:", summary["key_detection"].get("key_name"))
    print("Output:", args.output_midi)
    for name in (
        "track_alignment",
        "timing_cleanup",
        "duration_cleanup",
        "overlap_cleanup",
        "tonal_correction",
        "bar_enforce",
        "tempo_hard",
    ):
        r = summary.get(name)
        if isinstance(r, dict) and r.get("enabled") is False:
            print(f"  {name}: skipped")
        else:
            print(f"  {name}: ok")
    tr = summary.get("track_metadata_restore")
    if isinstance(tr, dict) and tr.get("error"):
        print("  track_metadata_restore: failed:", tr["error"])
    elif isinstance(tr, dict) and tr.get("enabled") is False:
        print("  track_metadata_restore: skipped")
    else:
        print("  track_metadata_restore: ok")


if __name__ == "__main__":
    main()
