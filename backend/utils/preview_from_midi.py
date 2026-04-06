"""
Build plugin-friendly preview JSON from a MIDI file (notes for piano-roll style UIs).

If music21 is unavailable or parsing fails, returns empty notes + optional error string.
"""
from __future__ import annotations

import os
from pathlib import Path
from typing import Any, Dict, List

# Avoid huge JSON in browser / DAW plugins
_MAX_NOTES = int(os.environ.get("BACKEND_PREVIEW_MAX_NOTES", "8000"))


def build_preview_payload(midi_path: Path, default_bpm: int = 120) -> Dict[str, Any]:
    if not midi_path.is_file():
        return {
            "notes": [],
            "bpm": default_bpm,
            "preview_error": "midi_file_missing",
        }

    try:
        import music21
        from music21 import tempo as m21tempo

        score = music21.converter.parse(str(midi_path))
        bpm = int(default_bpm)
        mms = score.flatten().getElementsByClass(m21tempo.MetronomeMark)
        if mms:
            n = mms[0].number
            if n is not None:
                bpm = int(n)

        part = score.parts[0] if score.parts else score
        notes_out: List[Dict[str, Any]] = []
        truncated = False

        for el in part.flatten().notesAndRests:
            if len(notes_out) >= _MAX_NOTES:
                truncated = True
                break
            if el.isNote:
                notes_out.append(
                    {
                        "midi": int(el.pitch.midi),
                        "start": float(el.offset),
                        "duration": float(el.duration.quarterLength),
                    }
                )
            elif getattr(el, "isChord", False) and el.isChord:
                o = float(el.offset)
                d = float(el.duration.quarterLength)
                for p in el.pitches:
                    if len(notes_out) >= _MAX_NOTES:
                        truncated = True
                        break
                    notes_out.append(
                        {"midi": int(p.midi), "start": o, "duration": d}
                    )

        out: Dict[str, Any] = {
            "notes": notes_out,
            "bpm": bpm,
            "note_count": len(notes_out),
        }
        if truncated:
            out["truncated"] = True
        return out
    except Exception as e:
        return {
            "notes": [],
            "bpm": int(default_bpm),
            "preview_error": "parse_failed",
            "preview_error_detail": str(e)[:500],
        }
