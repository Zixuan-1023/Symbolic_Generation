"""
Extra fields on completed job payloads so web / Electron / Cursor plugins that expect
camelCase or `success` / `completed` strings still work without guessing server conventions.
"""
from __future__ import annotations

from typing import Any, Dict, Optional


def enrich_completed_job(result: Dict[str, Any]) -> Dict[str, Any]:
    """Mutates and returns `result` (completed job only)."""
    job_id = result.get("job_id")
    midi_url = result.get("midi_url")
    preview_url = result.get("preview_url")
    md = result.get("midi_download_url")
    pd = result.get("preview_download_url")

    result["success"] = True
    result["ready"] = True
    result["finished"] = True

    # Some clients treat only "completed" / "success" as done
    result["completion"] = "completed"
    result["job_status"] = "completed"

    if job_id is not None:
        result["jobId"] = job_id

    if midi_url:
        result["midiUrl"] = midi_url
    if preview_url:
        result["previewUrl"] = preview_url
    if md is not None:
        result["midiDownloadUrl"] = md
    if pd is not None:
        result["previewDownloadUrl"] = pd

    # Flat output object for minimal clients
    result["output"] = {
        "midiUrl": midi_url,
        "previewUrl": preview_url,
        "midiDownloadUrl": md,
        "previewDownloadUrl": pd,
    }

    # Nested `result` for clients that resolve MIDI as: result.midi_path → result.midi_url → …
    # (same strings as top-level midi_path / midi_url)
    midi_path = result.get("midi_path")
    result["result"] = {
        "midi_path": midi_path,
        "midi_url": midi_url,
        "preview_url": preview_url,
        "midi_download_url": md,
        "preview_download_url": pd,
        "job_id": job_id,
    }

    vars_ = result.get("variations") or []
    if vars_ and isinstance(vars_[0], dict):
        v0 = vars_[0]
        v0.setdefault("midiUrl", v0.get("midi_url"))
        v0.setdefault("previewUrl", v0.get("preview_url"))
        v0.setdefault("midiDownloadUrl", v0.get("midi_download_url"))
        v0.setdefault("previewDownloadUrl", v0.get("preview_download_url"))
        result["primaryVariation"] = v0

    return result


def enrich_failed_job(result: Dict[str, Any]) -> Dict[str, Any]:
    """Align failed jobs with clients that look for ``success`` / ``job_status`` / ``completed``."""
    result["success"] = False
    result["completed"] = False
    result["ready"] = False
    result["finished"] = True
    result["job_status"] = "failed"
    result["completion"] = "failed"
    if result.get("job_id") is not None:
        result["jobId"] = result["job_id"]
    return result
