"""
post_operation: generation_cleanup (new/continue) and transformation (AR-VAE + cleanup).

Resolution order:
  1. POST_OPERATION_ROOT if set and is a directory
  2. Else <Backend repo>/post_operation if that directory exists (symlink or copy your project here)
"""
from __future__ import annotations

import os
import shutil
import subprocess
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple


def _backend_root() -> Path:
    return Path(__file__).resolve().parents[1]


def _default_post_operation_dir() -> Path:
    return _backend_root() / "post_operation"


def resolve_arvae_morph_script() -> Path:
    """``ar-vae/scripts/arvae_morph_midi.py`` under the Backend repo."""
    p = _backend_root() / "ar-vae" / "scripts" / "arvae_morph_midi.py"
    return p


def is_arvae_morph_configured() -> bool:
    return resolve_arvae_morph_script().is_file()


def resolve_post_operation_root() -> Path:
    """
    Directory used as cwd for `python -m generation_cleanup` (and AR-VAE uses the repo layout separately).
    """
    raw = os.environ.get("POST_OPERATION_ROOT", "").strip()
    if raw:
        p = Path(raw).expanduser().resolve()
        if not p.is_dir():
            raise RuntimeError(f"POST_OPERATION_ROOT is not a directory: {p}")
        return p
    fallback = _default_post_operation_dir()
    if fallback.is_dir():
        return fallback
    raise RuntimeError(
        "post_operation not found. Do one of: "
        "(1) export POST_OPERATION_ROOT=/path/to/the/folder where `python -m generation_cleanup` works, "
        f"or (2) symlink/copy that folder to: {fallback}"
    )


def _python_bin() -> str:
    py = os.environ.get("POST_OPERATION_PYTHON") or os.environ.get("MUSECOCO_PYTHON", "")
    if not py:
        raise RuntimeError(
            "Set MUSECOCO_PYTHON or POST_OPERATION_PYTHON for post_operation subprocesses"
        )
    return py


def is_post_operation_root_configured() -> bool:
    """True if we can resolve a post_operation cwd (env or Backend/post_operation)."""
    raw = os.environ.get("POST_OPERATION_ROOT", "").strip()
    if raw:
        return Path(raw).expanduser().resolve().is_dir()
    return _default_post_operation_dir().is_dir()


def require_post_operation_root() -> Path:
    return resolve_post_operation_root()


def _append_cleanup_pipeline_flags(
    cmd: List[str],
    *,
    track_alignment: Optional[bool] = None,
    timing_cleanup: Optional[bool] = None,
    timing_strength: Optional[float] = None,
    timing_grid_quarter_length: Optional[float] = None,
    onset_align_threshold: Optional[float] = None,
    duration_cleanup: Optional[bool] = None,
    overlap_cleanup: Optional[bool] = None,
    tonal_correction: Optional[bool] = None,
    preserve_track_metadata: Optional[bool] = None,
) -> None:
    """Append ``generation_cleanup`` CLI flags; env kill-switches apply when kw is None."""
    ta = track_alignment
    if ta is None and os.environ.get("POST_OP_CLEANUP_DISABLE_TRACK_ALIGNMENT") == "1":
        ta = False
    if ta is True:
        cmd.extend(["--track-alignment", "on"])
    elif ta is False:
        cmd.extend(["--track-alignment", "off"])

    tc = timing_cleanup
    if tc is None and os.environ.get("POST_OP_CLEANUP_DISABLE_TIMING_CLEANUP") == "1":
        tc = False
    if tc is False:
        cmd.append("--disable-timing-cleanup")

    dc = duration_cleanup
    if dc is None and os.environ.get("POST_OP_CLEANUP_DISABLE_DURATION_CLEANUP") == "1":
        dc = False
    if dc is False:
        cmd.append("--disable-duration-cleanup")

    oc = overlap_cleanup
    if oc is None and os.environ.get("POST_OP_CLEANUP_DISABLE_OVERLAP_CLEANUP") == "1":
        oc = False
    if oc is False:
        cmd.append("--disable-overlap-cleanup")

    pm = preserve_track_metadata
    if pm is None and os.environ.get("POST_OP_CLEANUP_NO_PRESERVE_TRACK_METADATA") == "1":
        pm = False
    if pm is False:
        cmd.append("--no-preserve-track-metadata")

    ts = timing_strength
    if ts is None:
        raw = os.environ.get("POST_OP_CLEANUP_TIMING_STRENGTH", "").strip()
        if raw:
            try:
                ts = float(raw)
            except ValueError:
                ts = None
    if ts is not None:
        cmd.extend(["--timing-strength", str(ts)])

    gq = timing_grid_quarter_length
    if gq is None:
        raw = os.environ.get("POST_OP_CLEANUP_GRID", "").strip()
        if raw:
            try:
                gq = float(raw)
            except ValueError:
                gq = None
    if gq is not None:
        cmd.extend(["--grid", str(gq)])

    ot = onset_align_threshold
    if ot is None:
        raw = os.environ.get("POST_OP_CLEANUP_ONSET_THRESHOLD", "").strip()
        if raw:
            try:
                ot = float(raw)
            except ValueError:
                ot = None
    if ot is not None:
        cmd.extend(["--onset-threshold", str(ot)])

    if tonal_correction is True:
        cmd.append("--enable-tonal-correction")


def run_generation_cleanup(
    input_midi: Path,
    output_midi: Path,
    *,
    target_bars: Optional[int] = None,
    target_bpm: Optional[float] = None,
    target_key: Optional[str] = None,
    time_signature: str = "4/4",
    tonal_snap: str = "gentle",
    track_alignment: Optional[bool] = None,
    timing_cleanup: Optional[bool] = None,
    timing_strength: Optional[float] = None,
    timing_grid_quarter_length: Optional[float] = None,
    onset_align_threshold: Optional[float] = None,
    duration_cleanup: Optional[bool] = None,
    overlap_cleanup: Optional[bool] = None,
    tonal_correction: Optional[bool] = None,
    preserve_track_metadata: Optional[bool] = None,
) -> None:
    """
    MuseCoco output → cleaned MIDI (new / continue only).

    Hard targets (bars, BPM, key) map to ``generation_cleanup`` CLI. Pipeline tuning
    (``track_alignment``, ``timing_strength``, …) controls alignment / quantization;
    ``track_alignment=None`` (default) lets the subprocess use **auto** (skip cross-track
    alignment when only one pitched track).

    Env (when a kw is not passed): ``POST_OP_CLEANUP_DISABLE_*``, ``POST_OP_CLEANUP_TIMING_STRENGTH``,
    ``POST_OP_CLEANUP_GRID``, ``POST_OP_CLEANUP_ONSET_THRESHOLD``.
    """
    root = resolve_post_operation_root()
    py = _python_bin()
    cmd: List[str] = [
        py,
        "-m",
        "generation_cleanup",
        str(input_midi.resolve()),
        str(output_midi.resolve()),
    ]
    _append_cleanup_pipeline_flags(
        cmd,
        track_alignment=track_alignment,
        timing_cleanup=timing_cleanup,
        timing_strength=timing_strength,
        timing_grid_quarter_length=timing_grid_quarter_length,
        onset_align_threshold=onset_align_threshold,
        duration_cleanup=duration_cleanup,
        overlap_cleanup=overlap_cleanup,
        tonal_correction=tonal_correction,
        preserve_track_metadata=preserve_track_metadata,
    )
    if target_bars is not None:
        cmd.extend(["--target-bars", str(int(target_bars))])
        cmd.extend(["--time-signature", time_signature])
    if target_bpm is not None:
        cmd.extend(["--target-bpm", str(float(target_bpm))])
    if target_key:
        cmd.extend(["--target-key", target_key])
        cmd.extend(["--tonal-snap", tonal_snap])
    env = os.environ.copy()
    subprocess.run(cmd, cwd=str(root), env=env, check=True)


def _python_for_arvae() -> str:
    py = os.environ.get("ARVAE_PYTHON", "").strip()
    if py:
        return py
    return _python_bin()


def _clamp01(x: float) -> float:
    """AR-VAE morph sliders are defined on [0, 1] (see ``arvae_morph_midi.py``)."""
    return max(0.0, min(1.0, float(x)))


def run_transformation_pipeline(
    input_midi: Path,
    output_midi: Path,
    sliders: Tuple[float, float, float, float],
    *,
    cleanup_kwargs: Optional[Dict[str, Any]] = None,
    disable_cleanup: bool = False,
) -> Dict[str, Any]:
    """
    Transformation: AR-VAE latent morph (four sliders) → optional ``generation_cleanup``.

    ``sliders``: ``(rhy_complexity, pitch_range, note_density, contour)`` in ``[0, 1]``.
    ``cleanup_kwargs``: forwarded to :func:`run_generation_cleanup` (merged request cleanup).
    """
    script = resolve_arvae_morph_script()
    if not script.is_file():
        raise RuntimeError(
            f"AR-VAE morph script missing: {script}. "
            "Ensure the ar-vae tree is present or set paths via deployment docs."
        )
    py = _python_for_arvae()
    arvae_root = script.resolve().parents[2]
    rhy, pitch, dens, cont = sliders
    applied = (
        _clamp01(rhy),
        _clamp01(pitch),
        _clamp01(dens),
        _clamp01(cont),
    )
    z_scale = float((os.environ.get("ARVAE_Z_SCALE", "0.8").strip() or "0.8"))
    z_deltas = [(s - 0.5) * 2.0 * z_scale for s in applied]

    tmp_arvae = output_midi.parent / f"{output_midi.stem}_arvae_raw.mid"
    tmp_arvae.parent.mkdir(parents=True, exist_ok=True)

    cmd: List[str] = [
        py,
        str(script),
        "--input",
        str(Path(input_midi).resolve()),
        "--output",
        str(tmp_arvae.resolve()),
        "--rhy_complexity",
        str(applied[0]),
        "--pitch_range",
        str(applied[1]),
        "--note_density",
        str(applied[2]),
        "--contour",
        str(applied[3]),
    ]
    env = os.environ.copy()
    subprocess.run(cmd, cwd=str(arvae_root), env=env, check=True)

    out: Dict[str, Any] = {
        "arvae_python": py,
        "arvae_script": str(script),
        "arvae_intermediate": str(tmp_arvae.resolve()),
        "sliders_raw": {
            "rhy_complexity": float(rhy),
            "pitch_range": float(pitch),
            "note_density": float(dens),
            "contour": float(cont),
        },
        "sliders_applied": {
            "rhy_complexity": applied[0],
            "pitch_range": applied[1],
            "note_density": applied[2],
            "contour": applied[3],
        },
        "arvae_latent_shift": {
            "z_scale": z_scale,
            "delta_z_dims_0_to_3": z_deltas,
            "order": ["rhy_complexity", "pitch_range", "note_density", "contour"],
            "formula": "z[0:4] += (s - 0.5) * 2 * ARVAE_Z_SCALE; s=0.5 => no delta",
        },
    }

    cleanup_kwargs = cleanup_kwargs or {}
    if disable_cleanup:
        shutil.copyfile(tmp_arvae, output_midi)
        out["cleanup"] = {"skipped": True, "reason": "POST_TRANSFORMATION_DISABLE_CLEANUP or POST_REFINE_DISABLE_CLEANUP"}
        return out

    if not is_post_operation_root_configured():
        shutil.copyfile(tmp_arvae, output_midi)
        out["cleanup"] = {
            "skipped": True,
            "reason": "POST_OPERATION_ROOT not configured — returning raw AR-VAE MIDI only",
        }
        return out

    try:
        run_generation_cleanup(tmp_arvae, output_midi, **cleanup_kwargs)
        out["cleanup"] = {"applied": True, "kwargs_keys": list(cleanup_kwargs.keys())}
    except Exception as exc:
        shutil.copyfile(tmp_arvae, output_midi)
        out["cleanup"] = {"error": str(exc), "fallback": "copied AR-VAE output without cleanup"}
    return out


def run_refine_pipeline(
    input_midi: Path,
    output_midi: Path,
    sliders: Tuple[float, float, float, float],
    *,
    use_controls: bool = True,
    disable_cleanup: bool = False,
    seed: Optional[int] = None,
    humanize: Optional[float] = None,
    melody_part_index: int = 0,
    tonal_triad_snap: bool = False,
) -> Dict[str, Any]:
    """
    Deprecated name: same as :func:`run_transformation_pipeline` without request-merged cleanup kwargs.

    Extra arguments (``seed``, ``humanize``, …) are ignored; use ``transformation`` mode + ``cleanup`` on the API.
    """
    _ = (use_controls, seed, humanize, melody_part_index, tonal_triad_snap)
    return run_transformation_pipeline(
        input_midi,
        output_midi,
        sliders,
        cleanup_kwargs={},
        disable_cleanup=disable_cleanup,
    )


def skip_cleanup_after_musecoco() -> bool:
    """If 1, new/continue skip generation_cleanup (debug only)."""
    return os.environ.get("POST_OP_SKIP_CLEANUP_AFTER_MUSECOCO", "0") == "1"


def refine_use_controls() -> bool:
    """If 0, refine runs without --controls (manual pipeline only)."""
    return os.environ.get("POST_REFINE_USE_CONTROLS", "1") != "0"


def refine_disable_cleanup_flag() -> bool:
    """Deprecated: use :func:`transformation_disable_cleanup_flag`."""
    return transformation_disable_cleanup_flag()


def transformation_disable_cleanup_flag() -> bool:
    """Skip ``generation_cleanup`` after AR-VAE (raw morph only)."""
    if os.environ.get("POST_TRANSFORMATION_DISABLE_CLEANUP", "").strip() == "1":
        return True
    return os.environ.get("POST_REFINE_DISABLE_CLEANUP", "0") == "1"
