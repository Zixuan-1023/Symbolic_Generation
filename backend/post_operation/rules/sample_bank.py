"""
Generate ~20 fixed MIDI samples for ``eval_ab`` (normal / abnormal mix).

Writes ``*.mid`` into ``post_operation/rules/eval_samples/`` (next to this file).

Run::

    cd /path/to/Backend
    python -m post_operation.rules.sample_bank
    python -m post_operation.rules.eval_ab --midi-dir post_operation/rules/eval_samples
"""
from __future__ import annotations

import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[2]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

import music21
from music21 import chord, meter, note, stream

DEST = Path(__file__).resolve().parent / "eval_samples"


def _score_one_part(measures: list[stream.Measure]) -> music21.stream.Score:
    s = stream.Score()
    p = stream.Part()
    for m in measures:
        p.append(m)
    s.insert(0, p)
    return s


def _m(ts: str = "4/4") -> stream.Measure:
    m = stream.Measure()
    m.timeSignature = meter.TimeSignature(ts)
    return m


def write_01_c_major_scale() -> None:
    """Normal: C major scale segment, MIDI 60–67, in eval range when shifted… keep 60–67."""
    m = _m()
    for i, p in enumerate([60, 62, 64, 65, 67, 65, 64, 62]):
        m.insert(float(i) * 0.5, note.Note(p, quarterLength=0.45))
    _score_one_part([m]).write("midi", fp=str(DEST / "01_c_major_scale.mid"))


def write_02_arpeggio_triads() -> None:
    """Normal: C–E–G arpeggios."""
    m = _m()
    for i, p in enumerate([60, 64, 67, 72, 67, 64, 60]):
        m.insert(float(i) * 0.5, note.Note(min(72, p), quarterLength=0.45))
    _score_one_part([m]).write("midi", fp=str(DEST / "02_arpeggio_triads.mid"))


def write_03_two_bars_sparse() -> None:
    """Normal: two bars, few notes, all diatonic."""
    m1 = _m()
    m1.insert(0, note.Note(60, quarterLength=1))
    m1.insert(1, note.Note(64, quarterLength=1))
    m1.insert(2, note.Note(67, quarterLength=1))
    m2 = _m()
    m2.insert(0, note.Note(65, quarterLength=2))
    m2.insert(2, note.Note(69, quarterLength=2))
    _score_one_part([m1, m2]).write("midi", fp=str(DEST / "03_two_bars_sparse.mid"))


def write_04_quarter_melody() -> None:
    """Normal: quarter notes, C major."""
    m = _m()
    pcs = [60, 62, 64, 65, 67, 65, 64, 62, 60, 64, 67, 72]
    for i, p in enumerate(pcs):
        m.insert(float(i), note.Note(p, quarterLength=0.95))
    _score_one_part([m]).write("midi", fp=str(DEST / "04_quarter_melody.mid"))


def write_05_chord_sustain() -> None:
    """Normal: triads in root position, C major."""
    m = _m()
    m.insert(0, chord.Chord([60, 64, 67], quarterLength=2))
    m.insert(2, chord.Chord([65, 69, 72], quarterLength=2))
    _score_one_part([m]).write("midi", fp=str(DEST / "05_chord_sustain.mid"))


def write_06_passing_diatonic() -> None:
    """Normal: stepwise, in range."""
    m = _m()
    for i in range(16):
        p = 60 + [0, 2, 2, 4, 4, 5, 5, 7, 7, 5, 5, 4, 4, 2, 2, 0][i]
        m.insert(i * 0.25, note.Note(p, quarterLength=0.2))
    _score_one_part([m]).write("midi", fp=str(DEST / "06_passing_diatonic.mid"))


def write_07_very_sparse() -> None:
    """Normal: single bar, three notes."""
    m = _m()
    m.insert(0, note.Note(60, quarterLength=1.5))
    m.insert(2, note.Note(64, quarterLength=1.5))
    _score_one_part([m]).write("midi", fp=str(DEST / "07_very_sparse.mid"))


def write_08_bass_line() -> None:
    """Normal: low but still in 48–72 if we use 48–60 range — use 48–60."""
    m = _m()
    for i, p in enumerate([48, 50, 52, 53, 55, 53, 52, 50]):
        m.insert(float(i) * 0.5, note.Note(p, quarterLength=0.45))
    _score_one_part([m]).write("midi", fp=str(DEST / "08_bass_line_48_60.mid"))


def write_09_chromatic_run() -> None:
    """Abnormal: chromatic (many out of C major)."""
    m = _m()
    for i in range(12):
        m.insert(i * 0.25, note.Note(60 + i, quarterLength=0.2))
    _score_one_part([m]).write("midi", fp=str(DEST / "09_chromatic_run.mid"))


def write_10_out_of_range_low() -> None:
    """Abnormal: very low MIDI."""
    m = _m()
    for i in range(8):
        m.insert(i * 0.5, note.Note(20 + i, quarterLength=0.45))
    _score_one_part([m]).write("midi", fp=str(DEST / "10_out_of_range_low.mid"))


def write_11_out_of_range_high() -> None:
    """Abnormal: very high MIDI."""
    m = _m()
    for i in range(8):
        m.insert(i * 0.5, note.Note(100 + i, quarterLength=0.45))
    _score_one_part([m]).write("midi", fp=str(DEST / "11_out_of_range_high.mid"))


def write_12_dense_16ths() -> None:
    """Abnormal: >8 onsets per bar, mostly diatonic."""
    m = _m()
    pat = [60, 62, 64, 65, 67, 65, 64, 62, 60, 62, 64, 65, 67, 69, 67, 65]
    for i, p in enumerate(pat * 2):
        m.insert(i * 0.25, note.Note(p, quarterLength=0.2))
    _score_one_part([m]).write("midi", fp=str(DEST / "12_dense_16ths.mid"))


def write_13_chromatic_dense_combo() -> None:
    """Abnormal: dense + chromatic + two out-of-range."""
    m = _m()
    pcs = [60, 61, 62, 63, 24, 96, 64, 65, 66, 67, 68, 69]
    for i, p in enumerate(pcs):
        m.insert(float(i) * 0.25, note.Note(p, quarterLength=0.2))
    _score_one_part([m]).write("midi", fp=str(DEST / "13_chromatic_dense_combo.mid"))


def write_14_f_sharp_minor_ish() -> None:
    """Abnormal vs fixed C major: F# minor-ish pitches."""
    m = _m()
    # F# minor scale fragment: many C# F# etc.
    pcs = [66, 68, 69, 71, 73, 71, 69, 68, 66, 64, 66]
    for i, p in enumerate(pcs):
        m.insert(float(i) * 0.4, note.Note(p, quarterLength=0.35))
    _score_one_part([m]).write("midi", fp=str(DEST / "14_f_sharp_minor_ish.mid"))


def write_15_whole_tone() -> None:
    """Abnormal: whole-tone pattern (all out of diatonic C major)."""
    m = _m()
    for i in range(10):
        m.insert(i * 0.4, note.Note(60 + 2 * i, quarterLength=0.35))
    _score_one_part([m]).write("midi", fp=str(DEST / "15_whole_tone.mid"))


def write_16_randomish() -> None:
    """Abnormal: pseudo-random accidentals."""
    m = _m()
    pcs = [60, 61, 63, 64, 66, 67, 70, 72, 73, 74, 76, 77]
    for i, p in enumerate(pcs):
        m.insert(float(i) * 0.33, note.Note(p, quarterLength=0.3))
    _score_one_part([m]).write("midi", fp=str(DEST / "16_accidental_cluster.mid"))


def write_17_mixed_good_bad() -> None:
    """Mixed: bar with both diatonic and chromatic + one low outlier."""
    m = _m()
    seq = [60, 64, 67, 61, 64, 67, 22, 65, 69, 72]
    for i, p in enumerate(seq):
        m.insert(float(i) * 0.4, note.Note(p, quarterLength=0.35))
    _score_one_part([m]).write("midi", fp=str(DEST / "17_mixed_good_bad.mid"))


def write_18_octave_leaps_or() -> None:
    """Abnormal: wide jumps including out of range."""
    m = _m()
    seq = [48, 72, 36, 96, 60, 60, 24, 108]
    for i, p in enumerate(seq):
        m.insert(float(i) * 0.5, note.Note(p, quarterLength=0.45))
    _score_one_part([m]).write("midi", fp=str(DEST / "18_octave_leaps_wide.mid"))


def write_19_polyphony_dense() -> None:
    """Abnormal: chord + many melody notes (high onset count)."""
    m = _m()
    m.insert(0, chord.Chord([60, 64, 67], quarterLength=3.5))
    for i in range(14):
        m.insert(0.25 * i, note.Note(72 + (i % 5), quarterLength=0.2))
    _score_one_part([m]).write("midi", fp=str(DEST / "19_polyphony_dense.mid"))


def write_20_two_voices_simple() -> None:
    """Borderline normal: two measures, melody + lower harmony (diatonic)."""
    m1 = _m()
    m1.insert(0, note.Note(60, quarterLength=1))
    m1.insert(0, note.Note(48, quarterLength=1))
    m1.insert(1, note.Note(64, quarterLength=1))
    m1.insert(1, note.Note(52, quarterLength=1))
    m2 = _m()
    m2.insert(0, note.Note(67, quarterLength=2))
    m2.insert(0, note.Note(55, quarterLength=2))
    _score_one_part([m1, m2]).write("midi", fp=str(DEST / "20_two_voice_diatonic.mid"))


def generate_all() -> int:
    DEST.mkdir(parents=True, exist_ok=True)
    writers = [
        write_01_c_major_scale,
        write_02_arpeggio_triads,
        write_03_two_bars_sparse,
        write_04_quarter_melody,
        write_05_chord_sustain,
        write_06_passing_diatonic,
        write_07_very_sparse,
        write_08_bass_line,
        write_09_chromatic_run,
        write_10_out_of_range_low,
        write_11_out_of_range_high,
        write_12_dense_16ths,
        write_13_chromatic_dense_combo,
        write_14_f_sharp_minor_ish,
        write_15_whole_tone,
        write_16_randomish,
        write_17_mixed_good_bad,
        write_18_octave_leaps_or,
        write_19_polyphony_dense,
        write_20_two_voices_simple,
    ]
    for fn in writers:
        fn()
    return len(writers)


def main() -> None:
    n = generate_all()
    print(f"Wrote {n} MIDI files to {DEST}")
    print("Run eval:")
    print(f"  python -m post_operation.rules.eval_ab --midi-dir {DEST}")


if __name__ == "__main__":
    main()
