"""
Map **phrase length** (and optional explicit token bounds) to MuseCoco Stage2 fairseq:

``--min-len`` / ``--max-len-b`` constrain the **target REMI token sequence** length, not bar count.

Precedence (highest first):

1. ``render.min_len`` + ``render.max_len_b`` (explicit snapshot from PluginEditor).
2. ``render.phrase_length`` → tier table (when lengths omitted).
3. ``generation.phrase_length`` → tier table.
4. ``generation.bars`` → heuristic tier.
5. Legacy defaults (512 / 2560).

Env overrides per tier (integers):

- ``MUSECOCO_PHRASE_SHORT_MIN``, ``MUSECOCO_PHRASE_SHORT_MAX``
- ``MUSECOCO_PHRASE_MEDIUM_MIN``, ``MUSECOCO_PHRASE_MEDIUM_MAX``
- ``MUSECOCO_PHRASE_LONG_MIN``, ``MUSECOCO_PHRASE_LONG_MAX``
"""
from __future__ import annotations

import os
from typing import Dict, Literal, Tuple

from schemas import GenerationRequest

PhraseLength = Literal["short", "medium", "long"]

# (min_len, max_len_b) — aligned with PluginEditor phrase-length mapping (~0.8× max for min)
_DEFAULTS: Dict[PhraseLength, Tuple[int, int]] = {
    "short": (410, 512),
    "medium": (819, 1024),
    "long": (1638, 2048),
}


def _tier_from_env(tier: PhraseLength) -> Tuple[int, int]:
    base_min, base_max = _DEFAULTS[tier]
    prefix = f"MUSECOCO_PHRASE_{tier.upper()}"
    mn = os.environ.get(f"{prefix}_MIN", "").strip()
    mx = os.environ.get(f"{prefix}_MAX", "").strip()
    lo = int(mn) if mn else base_min
    hi = int(mx) if mx else base_max
    if lo > hi:
        lo, hi = hi, lo
    return lo, hi


def _bars_to_tier(bars: int) -> PhraseLength:
    """Heuristic when only ``generation.bars`` is set (legacy)."""
    b = max(1, min(512, int(bars)))
    if b <= 4:
        return "short"
    if b <= 12:
        return "medium"
    return "long"


def resolve_stage2_length_constraints(
    request: GenerationRequest,
) -> Tuple[float, int, str]:
    """
    Returns ``(min_len, max_len_b, source_tag)`` for ``run_stage2_generate``.
    """
    r = request.render
    if r is not None:
        if r.min_len is not None and r.max_len_b is not None:
            lo = float(r.min_len)
            hi = int(r.max_len_b)
            if lo > hi:
                lo, hi = float(hi), int(lo)
            return lo, hi, "render:explicit"
        if r.phrase_length is not None:
            tier = r.phrase_length
            if tier not in ("short", "medium", "long"):
                tier = "medium"
            lo, hi = _tier_from_env(tier)
            return float(lo), int(hi), f"render:phrase_length:{tier}"

    g = request.generation
    if g is None:
        return 512.0, 2560, "default"

    if g.phrase_length is not None:
        tier = g.phrase_length
        if tier not in ("short", "medium", "long"):
            tier = "medium"
        lo, hi = _tier_from_env(tier)
        return float(lo), int(hi), f"generation:phrase_length:{tier}"

    if g.bars is not None:
        tier = _bars_to_tier(int(g.bars))
        lo, hi = _tier_from_env(tier)
        return float(lo), int(hi), f"bars_heuristic:{tier}"

    return 512.0, 2560, "default"
