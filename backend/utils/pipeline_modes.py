"""
Mode routing helpers (MuseCoco vs transformation / AR-VAE).

- New: Stage1 text-to-attribute → Stage2 → generation_cleanup.
- Continue: REMI prefix from input MIDI; Stage1 skipped by default (stub attrs + Stage2)
  unless ``MUSECOCO_CONTINUE_RUN_STAGE1=1``; ``generation`` overrides stay ignored.
- Transformation (alias ``refine``): AR-VAE latent morph + generation_cleanup; ``generation`` ignored for MuseCoco.
"""
from __future__ import annotations

import os
from typing import Any, Dict, Optional, Tuple

from schemas import (
    ArvaeControls,
    CleanupHardControls,
    GenerationControls,
    GenerationRequest,
)


def effective_cleanup_hard(request: GenerationRequest) -> Optional[CleanupHardControls]:
    """
    Symbolic hard constraints for ``generation_cleanup``.

    Merge order (later wins): ``context`` (bpm, length_bars, time_signature) → if there is no
    ``context``, ``generation`` may supply ``bars`` / ``time_signature`` → ``generation.key``
    (if no key yet) → ``cleanup`` (explicit overrides). If nothing applies, returns None.
    """
    merged: Dict[str, Any] = {}

    if request.context is not None:
        ctx = request.context
        merged.update(
            {
                "bpm": float(ctx.bpm),
                "bars": int(ctx.length_bars),
                "time_signature": ctx.time_signature,
            }
        )
    elif request.generation is not None:
        g = request.generation
        if g.bars is not None:
            merged["bars"] = int(g.bars)
        if g.time_signature:
            merged["time_signature"] = g.time_signature

    if request.generation is not None and request.generation.key:
        merged.setdefault("key", request.generation.key)

    if request.cleanup is not None:
        merged.update(request.cleanup.model_dump(exclude_none=True))

    # Frozen UI often always sends ``context.length_bars`` → hard truncate in cleanup.
    # Deploy with BACKEND_CLEANUP_DROP_CONTEXT_BARS=1 to keep BPM/meter but drop bar enforcement.
    if os.environ.get("BACKEND_CLEANUP_DROP_CONTEXT_BARS", "0").strip() == "1":
        merged.pop("bars", None)

    if not merged:
        return None

    return CleanupHardControls(**merged)


def effective_musecoco_generation(request: GenerationRequest) -> Optional[GenerationControls]:
    """
    Controls applied to infer_test.bin via apply_generation_overrides_infer_bin.
    Uses `generation` when set; legacy mapping is optional/thin.
    """
    m = request.mode or "new"
    if m == "refine":
        m = "transformation"
    # Continue: REMI prefix continuity; transformation: not MuseCoco.
    if m == "continue":
        return None
    if m == "transformation":
        return None

    if request.generation is not None:
        return request.generation
    # Legacy: no GenerationControls — overrides skipped (same as prior behavior).
    return None


def effective_arvae_sliders_transformation(request: GenerationRequest) -> Tuple[float, float, float, float]:
    """
    Four AR-VAE sliders ``[0,1]``. Prefers ``arvae``; falls back to legacy
    ``controls`` / ``attributes`` hard sliders when present.
    """
    if request.arvae is not None:
        a = request.arvae
        return (a.rhy_complexity, a.pitch_range, a.note_density, a.contour)

    h = None
    if request.controls is not None:
        h = request.controls.hard
    elif request.attributes is not None:
        h = request.attributes
    if h is None:
        return (0.5, 0.5, 0.5, 0.5)

    def _g(name: str) -> float:
        v = getattr(h, name, None)
        return 0.5 if v is None else float(v)

    return (
        _g("rhy_complexity"),
        _g("pitch_range"),
        _g("note_density"),
        _g("contour"),
    )


def effective_arvae_controls_transformation(request: GenerationRequest) -> Optional[ArvaeControls]:
    """Concrete ``ArvaeControls`` echoed in API response for transformation mode."""
    if request.arvae is not None:
        return request.arvae
    rhy, pitch, dens, cont = effective_arvae_sliders_transformation(request)
    return ArvaeControls(
        rhy_complexity=rhy,
        pitch_range=pitch,
        note_density=dens,
        contour=cont,
    )


# Backwards-compatible names (deprecated)
effective_arvae_sliders_refine = effective_arvae_sliders_transformation
effective_arvae_controls_refine = effective_arvae_controls_transformation


def legacy_merge_final_attrs(request: GenerationRequest, inferred: Dict[str, Any]) -> Dict[str, Any]:
    """Preserve existing density/tempo/bass_energy bin mapping for API visibility."""
    from utils.mapper import merge_user_controls

    return merge_user_controls(request, inferred)
