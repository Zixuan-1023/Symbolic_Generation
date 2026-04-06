"""
Map exceptions to stable ``error_code`` + short user-facing copy for polling clients.
Technical detail stays in ``message`` (original exception string).
"""
from __future__ import annotations

import subprocess
from typing import Any, Dict, Optional, Tuple


def describe_job_failure(exc: BaseException) -> Tuple[str, str, Optional[str]]:
    """
    Returns (error_code, user_message, hint_or_none).
    """
    msg = str(exc).strip()
    low = msg.lower()

    if isinstance(exc, subprocess.CalledProcessError):
        return (
            "subprocess_failed",
            "Generation stopped because an external step failed.",
            "Check server logs for this job id. If it persists, verify MUSECOCO_PYTHON and model paths.",
        )

    if "midi is required" in low or "requires midi" in low:
        return (
            "midi_required",
            "This mode needs a MIDI file.",
            "Send midi as base64 (recommended) or bytes; path only works on trusted servers.",
        )

    if "continue mode requires" in low and "controls" in low:
        return (
            "continue_needs_controls",
            "Continue mode needs text controls or style settings in addition to MIDI.",
            "Add a prompt, generation, attributes, or controls alongside the MIDI.",
        )

    if "monophonic" in low or "single-voice" in low or "at most one" in low:
        return (
            "refine_polyphony",
            "Refine works on a single melody line on the target track.",
            "Export one melodic track, or merge to monophonic, then try again.",
        )

    if "no non-drum parts" in low:
        return (
            "midi_no_melody_track",
            "No playable (non-drum) track was found in this MIDI.",
            "Use a file with at least one melodic instrument track.",
        )

    if "melody_part_index" in low and "out of range" in low:
        return (
            "melody_part_invalid",
            "The melody track index does not exist in this file.",
            "Try track index 0, or fewer parts in the MIDI.",
        )

    if "musecoco python" in low or "musecoco_python" in low:
        return (
            "config_python",
            "The server is not configured to run MuseCoco.",
            "Set environment variable MUSECOCO_PYTHON to your MuseCoco conda Python.",
        )

    if "post_operation not found" in low or "post_operation" in low and "not found" in low:
        return (
            "config_post_operation",
            "Post-processing is not available on this server.",
            "Set POST_OPERATION_ROOT or install Backend/post_operation; generation may still return raw MIDI.",
        )

    if "prompt" in low and "too long" in low:
        return ("prompt_too_long", msg, "Shorten the text prompt.")

    if "no midi files generated" in low or "no midi" in low and "generated" in low:
        return (
            "generation_empty",
            "The music model did not produce a MIDI file.",
            "Try again with a different seed, or check Stage 2 logs (GPU memory, checkpoint path).",
        )

    if "invalid or missing api key" in low:
        return ("auth", "API key missing or wrong.", "Send header X-MuseCoco-Key or Authorization: Bearer …")

    return ("internal_error", "Something went wrong while processing your request.", None)


def job_failure_dict(job_id: str, exc: BaseException) -> Dict[str, Any]:
    code, user_msg, hint = describe_job_failure(exc)
    return {
        "status": "error",
        "job_id": job_id,
        "error_code": code,
        "message": str(exc),
        "user_message": user_msg,
        "hint": hint,
    }
