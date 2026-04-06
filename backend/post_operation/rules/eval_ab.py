"""
Small before/after evaluation (Phase 4): same fixed controls, baseline MIDI vs rule-layer output.

Metrics (three thesis-facing numbers):
  - **key consistency** — fraction of pitch events in the resolved diatonic scale
  - **density deviation** — ``|mean_onsets_per_bar − target|`` with
    ``target = density_target_onsets_per_bar(density_01)``
  - **pitch range violation rate** — share of pitch events outside ``[low, high]``

Run from repository root::

    # Built-in synthetic fixtures (default)
    python -m post_operation.rules.eval_ab

    # Batch of fixed MIDI files (one evaluation per file; same KEY_STR / density / pitch range)
    python -m post_operation.rules.eval_ab --midi-dir path/to/sample_midis

``--midi-dir`` loads every ``*.mid`` in that directory (non-recursive), sorted by name.

To (re)generate ~20 mixed normal/abnormal MIDIs into ``eval_samples/``::

    python -m post_operation.rules.sample_bank

Uses only local MIDI (no MuseCoco); evidence for write-ups / tables.
"""
from __future__ import annotations

import argparse
import os
import sys
import tempfile
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[2]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

import music21
from music21 import meter, note, stream

from post_operation.rules.density_control import density_target_onsets_per_bar
from post_operation.rules.metrics import (
    density_deviation,
    key_consistency_rate,
    pitch_range_violation_rate,
)
from post_operation.rules.run import apply_rule_layer, resolve_key_tonic_mode
from clean_up.tonal_correction import build_scale_pitch_classes

# Fixed “experiment” controls (thesis: one row per sample)
DENSITY_01 = 0.5
KEY_STR = "C major"
PITCH_LO = 48
PITCH_HI = 72


def _write_score(s: music21.stream.Score) -> str:
    fd, path = tempfile.mkstemp(suffix=".mid")
    os.close(fd)
    s.write("midi", fp=path)
    return path


def fixture_chromatic_and_dense() -> music21.stream.Score:
    """Some out-of-key pitches, out-of-range notes, and >8 onsets in one bar."""
    s = stream.Score()
    p = stream.Part()
    m = stream.Measure()
    m.timeSignature = meter.TimeSignature("4/4")
    pcs = [60, 61, 62, 63, 64, 65, 66, 67, 68, 24, 96]
    for i, pc in enumerate(pcs):
        m.insert(float(i) * 0.25, note.Note(pc, quarterLength=0.2))
    p.append(m)
    s.insert(0, p)
    return s


def fixture_clean_c() -> music21.stream.Score:
    """Mostly diatonic, in range, sparse."""
    s = stream.Score()
    p = stream.Part()
    m = stream.Measure()
    m.timeSignature = meter.TimeSignature("4/4")
    m.insert(0, note.Note(60, quarterLength=1.0))
    m.insert(1, note.Note(64, quarterLength=1.0))
    m.insert(2, note.Note(67, quarterLength=1.0))
    p.append(m)
    s.insert(0, p)
    return s


def _metrics_row(
    label: str,
    path: str,
    scale_pcs: set[int],
    target_onsets: float,
) -> dict[str, float | str]:
    sc = music21.converter.parse(path)
    if isinstance(sc, music21.stream.Opus):
        sc = sc.mergeScores()
    assert isinstance(sc, music21.stream.Score)
    kc = key_consistency_rate(sc, scale_pcs)
    dd = density_deviation(sc, target_onsets)
    pv = pitch_range_violation_rate(sc, PITCH_LO, PITCH_HI)
    return {
        "sample": label,
        "key_consistency": float(kc) if kc is not None else -1.0,
        "density_deviation": float(dd),
        "pitch_range_violation_rate": float(pv),
    }


def _run_one_sample(
    label: str,
    inp: str,
    rows: list[dict[str, float | str]],
    scale_pcs: set[int],
    target: float,
    *,
    cleanup_inp: bool,
) -> None:
    fd_o, out = tempfile.mkstemp(suffix=".mid")
    os.close(fd_o)
    try:
        off = _metrics_row(f"{label}_rule_off", inp, scale_pcs, target)
        rows.append(off)

        st = apply_rule_layer(
            inp,
            out,
            key_str=KEY_STR,
            density_01=DENSITY_01,
            pitch_low_midi=PITCH_LO,
            pitch_high_midi=PITCH_HI,
        )
        if not st.get("enabled"):
            print(f"[{label}] apply_rule_layer failed:", st.get("error"))
            return
        on = _metrics_row(f"{label}_rule_on", out, scale_pcs, target)
        rows.append(on)
        print(
            f"[{label}] rule_layer JSON: "
            f"key_notes {st.get('key_notes_before')}->{st.get('key_notes_after')}, "
            f"density {st.get('density_before')}->{st.get('density_after')}, "
            f"range_viol {st.get('pitch_out_of_range_before')}->"
            f"{st.get('pitch_out_of_range_after')}, "
            f"bars_touched={st.get('bars_touched')}"
        )
    finally:
        try:
            if os.path.isfile(out):
                os.unlink(out)
        except OSError:
            pass
        if cleanup_inp:
            try:
                os.unlink(inp)
            except OSError:
                pass


def main() -> None:
    ap = argparse.ArgumentParser(description="Rule layer off vs on — small eval batch.")
    ap.add_argument(
        "--midi-dir",
        type=Path,
        default=None,
        help="Directory of fixed *.mid samples (non-recursive). If omitted, use built-in fixtures.",
    )
    args = ap.parse_args()

    tonic_pc, mode = resolve_key_tonic_mode(KEY_STR)
    scale_pcs = build_scale_pitch_classes(int(tonic_pc), mode)
    target = float(density_target_onsets_per_bar(DENSITY_01))

    rows: list[dict[str, float | str]] = []

    if args.midi_dir is not None:
        d = args.midi_dir.resolve()
        if not d.is_dir():
            raise SystemExit(f"not a directory: {d}")
        midis = sorted(d.glob("*.mid"))
        if not midis:
            raise SystemExit(f"no *.mid under {d}")
        print(
            f"Using KEY_STR={KEY_STR!r} DENSITY_01={DENSITY_01} "
            f"PITCH=[{PITCH_LO},{PITCH_HI}] — {len(midis)} file(s)\n"
        )
        for path in midis:
            label = path.stem
            _run_one_sample(
                label,
                str(path),
                rows,
                scale_pcs,
                target,
                cleanup_inp=False,
            )
    else:
        fixtures = [
            ("chromatic_dense", fixture_chromatic_and_dense),
            ("clean_c_major", fixture_clean_c),
        ]
        for label, mk in fixtures:
            score = mk()
            inp = _write_score(score)
            _run_one_sample(
                label,
                inp,
                rows,
                scale_pcs,
                target,
                cleanup_inp=True,
            )

    print()
    print("metric,sample,value")
    for r in rows:
        for k in ("key_consistency", "density_deviation", "pitch_range_violation_rate"):
            print(f"{k},{r['sample']},{r[k]:.6f}")


if __name__ == "__main__":
    main()
