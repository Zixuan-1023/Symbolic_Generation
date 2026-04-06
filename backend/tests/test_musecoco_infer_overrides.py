"""Tests for MuseCoco infer_test.bin generation overrides (I1s2 family layout)."""
from __future__ import annotations

import sys
from pathlib import Path

# Repo root: Backend/
_ROOT = Path(__file__).resolve().parents[1]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from schemas import GenerationControls
from utils.musecoco_infer_overrides import (
    NUM_I1S2_FAMILIES,
    _apply_i1s2_instrument_override,
    _guess_i1s2_family_index,
)


def _na():
    return [0, 0, 1]


def _yes():
    return [1, 0, 0]


def _no():
    return [0, 1, 0]


def test_guess_family_acoustic_guitar():
    assert _guess_i1s2_family_index("acoustic guitar") == 4  # guitar


def test_guess_family_bassoon_not_bass():
    assert _guess_i1s2_family_index("bassoon solo") == 19


def test_guess_canonical_token_drums():
    assert _guess_i1s2_family_index("drums") == 27
    assert _guess_i1s2_family_index("drum") == 27


def test_guess_canonical_token_piano_exact():
    assert _guess_i1s2_family_index("piano") == 0


def test_guess_canonical_token_strings():
    assert _guess_i1s2_family_index("strings") == 10


def test_i1s2_flat_28_families_sets_one_yes():
    pl = {"I1s2": [_na() for _ in range(NUM_I1S2_FAMILIES)]}
    pp = {"I1s2": [[0.01, 0.01, 0.98] for _ in range(NUM_I1S2_FAMILIES)]}
    _apply_i1s2_instrument_override(pl, pp, 4)  # guitar
    for j in range(NUM_I1S2_FAMILIES):
        if j == 4:
            expected = _yes()
        elif j in (2, 27):
            expected = _no()  # explicit deny percussion + drum for non-kit instruments
        else:
            expected = _na()
        assert pl["I1s2"][j] == expected, f"slot {j}"
        assert len(pp["I1s2"][j]) == 3
        if j == 4:
            assert pp["I1s2"][j][0] > 0.9
        elif j in (2, 27):
            assert pp["I1s2"][j][1] > 0.9
        else:
            assert pp["I1s2"][j][2] > 0.9


def test_i1s2_per_bar_nested_lists():
    bars = 3
    pl = {
        "I1s2": [
            [_na() for _ in range(bars)] for _ in range(NUM_I1S2_FAMILIES)
        ]
    }
    pp = {
        "I1s2": [
            [[0.01, 0.01, 0.98] for _ in range(bars)]
            for _ in range(NUM_I1S2_FAMILIES)
        ]
    }
    _apply_i1s2_instrument_override(pl, pp, 0)
    for j in range(NUM_I1S2_FAMILIES):
        for b in range(bars):
            if j == 0:
                exp = _yes()
            elif j in (2, 27):
                exp = _no()
            else:
                exp = _na()
            assert pl["I1s2"][j][b] == exp


def test_apply_generation_does_not_assign_matrix_to_slot():
    from utils import musecoco_infer_overrides as m

    pl = {"I1s2": [_na() for _ in range(28)], "T1s1": [1, 0, 0, 0]}
    pp = {"I1s2": [[0.01, 0.01, 0.98] for _ in range(28)]}
    m._apply_i1s2_instrument_override(pl, pp, 5)
    assert isinstance(pl["I1s2"][0], list) and len(pl["I1s2"][0]) == 3
    assert not isinstance(pl["I1s2"][0][0], list)


if __name__ == "__main__":
    test_guess_family_acoustic_guitar()
    test_guess_family_bassoon_not_bass()
    test_i1s2_flat_28_families_sets_one_yes()
    test_i1s2_per_bar_nested_lists()
    test_apply_generation_does_not_assign_matrix_to_slot()
    print("ok")
