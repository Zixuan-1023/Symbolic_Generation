"""
Apply MuseCoco `generation` controls onto infer_test.bin (pred_labels).

**Priority (``mode=new``):** Stage1 BERT still reads the **prompt** to fill all attributes,
then this module **overwrites** ``pred_labels`` for each field present in ``generation``
(key, instrument, tempo, bars, …). Those knobs are therefore **harder than the prompt**
for the covered keys. Remaining attributes (e.g. genre ``S4``) still follow Stage1 unless
you extend overrides.

AR-VAE controls are never passed here — transformation mode does not use this module.

I1s2 layout (from ``stage2_pre`` + ``interactive_dict`` ``convert_vector_to_token``):
``pred_labels["I1s2"]`` is a length-28 list (one slot per instrument family, order in
``_I1S2_FAMILIES`` / ``att_key``). Each slot is either a flat length-3 one-hot
``[是, 否, NA]``, or a list of such one-hots (one per predicted bar). The downstream
``get_id(attri_vector[i])`` requires each *slot* to be a one-hot vector, not a nested
matrix — overrides must set **per-family** yes/NA, not a full 28×3 row per index.
"""
from __future__ import annotations

import os
import pickle
from pathlib import Path
from typing import Any, Dict, List, Optional

from schemas import GenerationControls


def _one_hot(n: int, idx: int) -> List[int]:
    idx = max(0, min(n - 1, int(idx)))
    return [1 if i == idx else 0 for i in range(n)]


def _uniform_probs(n: int, idx: int) -> List[float]:
    """Softmax-ish placeholder: peak at idx."""
    idx = max(0, min(n - 1, int(idx)))
    out = [0.01 / (n - 1)] * n
    out[idx] = 0.99
    return out


# I1s2 family order matches musecoco att_key / num_labels keys prefix I1s2_
_I1S2_FAMILIES = [
    "piano",
    "keyboard",
    "percussion",
    "organ",
    "guitar",
    "bass",
    "violin",
    "viola",
    "cello",
    "harp",
    "strings",
    "voice",
    "trumpet",
    "trombone",
    "tuba",
    "horn",
    "brass",
    "sax",
    "oboe",
    "bassoon",
    "clarinet",
    "piccolo",
    "flute",
    "pipe",
    "synthesizer",
    "ethnic_instruments",
    "sound_effects",
    "drum",
]

NUM_I1S2_FAMILIES = len(_I1S2_FAMILIES)

# Frontend / API may send stable lowercase tokens (exact match wins before substring heuristics).
# Keys must stay in sync with ``_I1S2_FAMILIES`` indices.
_INSTRUMENT_CANONICAL_TOKENS: Dict[str, int] = {
    "piano": 0,
    "keyboard": 1,
    "percussion": 2,
    "organ": 3,
    "guitar": 4,
    "bass": 5,
    "violin": 6,
    "viola": 7,
    "cello": 8,
    "harp": 9,
    "strings": 10,
    "voice": 11,
    "trumpet": 12,
    "trombone": 13,
    "tuba": 14,
    "horn": 15,
    "brass": 16,
    "sax": 17,
    "oboe": 18,
    "bassoon": 19,
    "clarinet": 20,
    "piccolo": 21,
    "flute": 22,
    "pipe": 23,
    "synthesizer": 24,
    "ethnic_instruments": 25,
    "sound_effects": 26,
    "drum": 27,
    "drums": 27,
}


def _is_len3_scalar_vector(v: Any) -> bool:
    return (
        isinstance(v, list)
        and len(v) == 3
        and all(isinstance(x, (int, float)) and not isinstance(x, bool) for x in v)
    )


def _guess_i1s2_family_index(inst: str) -> int:
    """
    Map a free-text instrument hint to an I1s2 family index in ``0 .. NUM_I1S2_FAMILIES-1``.

    1) Exact lowercase tokens (e.g. ``piano``, ``drums``) from clients take precedence.
    2) Otherwise substring match with longer family names first so e.g. ``bassoon``
       does not match ``bass``.

    Returns ``-1`` if nothing matches (caller should not overwrite I1s2).
    """
    raw = (inst or "").strip()
    if not raw:
        return -1
    token = raw.lower()
    if token in _INSTRUMENT_CANONICAL_TOKENS:
        return int(_INSTRUMENT_CANONICAL_TOKENS[token])

    s = token
    for i, fam in sorted(enumerate(_I1S2_FAMILIES), key=lambda t: -len(t[1])):
        if fam in s:
            return int(i)
    return -1


def _apply_i1s2_instrument_override(
    pl: Dict[str, Any], pp: Dict[str, Any], fam_idx: int
) -> None:
    """
    Set one I1s2 family to *yes* and all others to *NA*, matching each slot's shape:
    flat ``[3]`` or per-bar ``[[3], ...]``.

    For non-percussion / non-drum selections, **explicitly set** the ``percussion`` (index 2)
    and ``drum`` (index 27) slots to *no* (否) — not only NA. Stage1 often predicts drums;
    leaving those slots as NA lets the AR model still attend strongly to drum-like tokens.
    """
    if "I1s2" not in pl or not isinstance(pl["I1s2"], list) or not pl["I1s2"]:
        return
    i1 = pl["I1s2"]
    n = len(i1)
    if n == 0:
        return
    fam_idx = max(0, min(fam_idx, n - 1))

    na_l = _one_hot(3, 2)
    yes_l = _one_hot(3, 0)
    no_l = _one_hot(3, 1)
    na_p = _uniform_probs(3, 2)
    yes_p = _uniform_probs(3, 0)
    no_p = _uniform_probs(3, 1)

    for j in range(n):
        is_yes = j == fam_idx
        lab = yes_l if is_yes else na_l
        prb = yes_p if is_yes else na_p
        cur = i1[j]
        if _is_len3_scalar_vector(cur):
            i1[j] = list(lab)
        elif isinstance(cur, list) and cur and _is_len3_scalar_vector(cur[0]):
            i1[j] = [list(lab) for _ in range(len(cur))]
        # else: unknown layout; leave unchanged to avoid corrupting bins

    # Explicit "no" on percussion + drum kits when user asked for a melodic / non-kit family.
    if fam_idx not in (2, 27):
        for deny_j in (2, 27):
            if deny_j >= n:
                continue
            cur = i1[deny_j]
            if _is_len3_scalar_vector(cur):
                i1[deny_j] = list(no_l)
            elif isinstance(cur, list) and cur and _is_len3_scalar_vector(cur[0]):
                i1[deny_j] = [list(no_l) for _ in range(len(cur))]

    if "I1s2" not in pp or not isinstance(pp["I1s2"], list):
        return
    p1 = pp["I1s2"]
    if len(p1) != n:
        return
    for j in range(n):
        is_yes = j == fam_idx
        prb = yes_p if is_yes else na_p
        cur = p1[j]
        if _is_len3_scalar_vector(cur):
            p1[j] = list(prb)
        elif isinstance(cur, list) and cur and _is_len3_scalar_vector(cur[0]):
            p1[j] = [list(prb) for _ in range(len(cur))]

    if fam_idx not in (2, 27):
        for deny_j in (2, 27):
            if deny_j >= n:
                continue
            cur = p1[deny_j]
            if _is_len3_scalar_vector(cur):
                p1[deny_j] = list(no_p)
            elif isinstance(cur, list) and cur and _is_len3_scalar_vector(cur[0]):
                p1[deny_j] = [list(no_p) for _ in range(len(cur))]


def apply_generation_overrides_infer_bin(
    infer_bin_path: Path, gen: Optional[GenerationControls]
) -> None:
    if gen is None:
        return
    path = Path(infer_bin_path)
    if not path.is_file():
        return

    with open(path, "rb") as f:
        data = pickle.load(f)

    if not isinstance(data, list) or len(data) == 0:
        return

    for sample in data:
        if not isinstance(sample, dict) or "pred_labels" not in sample:
            continue
        pl: Dict[str, Any] = sample["pred_labels"]
        pp: Dict[str, Any] = sample.setdefault("pred_probs", {})

        # --- tempo (0–1) -> T1s1 (4 classes) ---
        if gen.tempo is not None:
            t = float(gen.tempo)
            ti = min(3, int(t * 4))
            pl["T1s1"] = _one_hot(4, ti)
            pp["T1s1"] = _uniform_probs(4, ti)

        # --- danceability -> EM1 (5) ---
        if gen.danceability is not None:
            d = float(gen.danceability)
            ei = min(4, int(d * 5))
            pl["EM1"] = _one_hot(5, ei)
            pp["EM1"] = _uniform_probs(5, ei)

        # --- rhythm_intensity -> R1 (3) ---
        if gen.rhythm_intensity is not None:
            r = float(gen.rhythm_intensity)
            ri = min(2, int(r * 3))
            pl["R1"] = _one_hot(3, ri)
            pp["R1"] = _uniform_probs(3, ri)

        # --- key string -> K1 (3) major / minor / other ---
        if gen.key:
            kl = gen.key.lower()
            if "minor" in kl or "min" in kl:
                ki = 1
            elif "major" in kl or "maj" in kl:
                ki = 0
            else:
                ki = 2
            pl["K1"] = _one_hot(3, ki)
            pp["K1"] = _uniform_probs(3, ki)

        # --- time_signature -> TS1s1 (8) only common meters ---
        if gen.time_signature:
            ts = gen.time_signature.strip()
            ts_map = {
                "4/4": 0,
                "3/4": 1,
                "6/8": 2,
                "2/4": 3,
                "12/8": 4,
            }
            tsi = ts_map.get(ts, 0)
            pl["TS1s1"] = _one_hot(8, tsi)
            pp["TS1s1"] = _uniform_probs(8, tsi)

        # --- instrument -> I1s2: 28 families × (是/否/NA); index = family, not bar ---
        if gen.instrument:
            fam_idx = _guess_i1s2_family_index(gen.instrument)
            if fam_idx >= 0:
                _apply_i1s2_instrument_override(pl, pp, fam_idx)
                if os.environ.get("BACKEND_LOG_INFER_OVERRIDES", "0").strip() == "1":
                    print(
                        f"[infer_overrides] instrument={gen.instrument!r} -> I1s2 family_index={fam_idx} "
                        f"({ _I1S2_FAMILIES[fam_idx]}); percussion+drum explicitly set to NO when not selected."
                    )
            elif os.environ.get("BACKEND_LOG_INFER_OVERRIDES", "0").strip() == "1":
                print(
                    f"[infer_overrides] instrument={gen.instrument!r} did not map to an I1s2 family; "
                    "Stage1 I1s2 left unchanged."
                )

        # --- bars: stored for clients; generation length uses env / interactive defaults ---
        # Optional: nudge B1s1 (5) from bars bucket
        if gen.bars is not None and "B1s1" in pl:
            b = max(1, min(512, int(gen.bars)))
            bi = min(4, max(0, int((b - 4) / 32)))  # coarse bins
            pl["B1s1"] = _one_hot(5, bi)
            pp["B1s1"] = _uniform_probs(5, bi)

    with open(path, "wb") as f:
        pickle.dump(data, f)
