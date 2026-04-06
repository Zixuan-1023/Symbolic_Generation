"""
Best-effort GPU memory cleanup after each generation job.

Heavy inference runs in subprocesses; this still helps the API process reclaim
cached allocator blocks and reduces fragmentation when anything touched CUDA in-process.
Disable with BACKEND_SKIP_CUDA_RELEASE=1.
"""
from __future__ import annotations

import gc
import os


def release_gpu_memory_best_effort() -> None:
    if os.environ.get("BACKEND_SKIP_CUDA_RELEASE", "0") == "1":
        return
    gc.collect()
    try:
        import torch

        if torch.cuda.is_available():
            torch.cuda.synchronize()
            torch.cuda.empty_cache()
    except Exception:
        pass
