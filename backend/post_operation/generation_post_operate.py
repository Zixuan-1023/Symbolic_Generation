"""
Backward-compatible name for the cleanup-only pipeline.

Prefer: ``from generation_cleanup import run_generation_cleanup``.
"""

from generation_cleanup import main
from generation_cleanup import run_generation_cleanup
from generation_cleanup import run_generation_cleanup as run_generation_post_operate

__all__ = [
    "main",
    "run_generation_cleanup",
    "run_generation_post_operate",
]

if __name__ == "__main__":
    main()
