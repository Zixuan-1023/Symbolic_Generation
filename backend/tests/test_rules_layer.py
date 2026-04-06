"""Smoke tests for post_operation/rules (Phase-2)."""
from __future__ import annotations

import os
import sys
import tempfile
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[1]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

import post_operation.rules  # noqa: F401 — installs warning filter before music21/requests

from music21 import meter, note, stream

from post_operation.rules.bar_structure import build_piece_bar_grid
from post_operation.rules.run import apply_rule_layer


def _tiny_score_path() -> str:
    s = stream.Score()
    p = stream.Part()
    m = stream.Measure()
    m.timeSignature = meter.TimeSignature("4/4")
    m.insert(0, note.Note(60, quarterLength=1.0))
    m.insert(1, note.Note(61, quarterLength=0.25))  # C# — out of C major
    p.append(m)
    s.insert(0, p)
    fd, path = tempfile.mkstemp(suffix=".mid")
    os.close(fd)
    s.write("midi", fp=path)
    return path


def test_flat_part_becomes_bar_grid():
    """Phase 3: flat non-drum parts are split into Measures before rules run."""
    s = stream.Score()
    p = stream.Part()
    p.insert(0, note.Note(60, quarterLength=4.0))
    s.insert(0, p)
    piece = build_piece_bar_grid(s)
    assert len(piece) == 1
    assert len(piece[0]) >= 1


def test_apply_rule_layer_runs():
    inp = _tiny_score_path()
    outp: str | None = None
    try:
        fd2, outp = tempfile.mkstemp(suffix=".mid")
        os.close(fd2)
        st = apply_rule_layer(
            inp,
            outp,
            key_str="C major",
            density_01=0.9,
            pitch_low_midi=48,
            pitch_high_midi=72,
        )
        assert Path(outp).is_file()
        assert st.get("enabled") is True
        assert st.get("error") is None
        assert "steps" in st
        assert st["output"] == outp
        assert isinstance(st.get("bars_touched"), int)
        assert "key_notes_before" in st and "key_notes_after" in st
        assert "density_before" in st and "density_after" in st
        assert "pitch_out_of_range_before" in st
        for step in st["steps"]:
            assert "bars_touched" in step
    finally:
        try:
            os.unlink(inp)
        except OSError:
            pass
        if outp:
            try:
                os.unlink(outp)
            except OSError:
                pass


if __name__ == "__main__":
    test_flat_part_becomes_bar_grid()
    test_apply_rule_layer_runs()
    print("ok")
