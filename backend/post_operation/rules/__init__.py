"""Phase-2/3 deterministic rules (key, density, pitch range).

Phase 3 uses a **bar grid** — see :mod:`post_operation.rules.bar_structure`.
"""

from __future__ import annotations

import warnings

# ``requests`` (pulled in by analysis / deps) often warns about urllib3/chardet pins
# in conda envs; match from message start (stdlib ``warnings`` semantics).
warnings.filterwarnings("ignore", message=r"urllib3 .*")

from post_operation.rules.bar_structure import Bar, Piece, Track, build_piece_bar_grid

__all__ = [
    "Bar",
    "Piece",
    "Track",
    "build_piece_bar_grid",
]
