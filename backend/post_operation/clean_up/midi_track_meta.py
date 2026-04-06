from __future__ import annotations

"""
Restore per-track display metadata and **GM program numbers** from a reference MIDI.

Hosts usually label tracks from ``program_change``, not only ``instrument_name`` text;
music21 cleanup often rewrites programs to 0 (Acoustic Grand). We strip bad
``program_change`` events on the target and re-apply the reference track's first
program on the target's actual note channels.
"""

from pathlib import Path
from typing import List, Optional, Tuple


def _first_program_from_ref(source_track) -> Tuple[Optional[int], Optional[int]]:
    """First program number and channel from reference (Type 1 track)."""
    for msg in source_track:
        if msg.type == "program_change":
            return msg.program, msg.channel
    return None, None


def _note_channels_for_program(target_track) -> List[int]:
    """Channels that carry note traffic; prefer note_on (vel>0), else note_off."""
    ch_on = set()
    ch_off = set()
    for msg in target_track:
        if msg.type == "note_on" and getattr(msg, "velocity", 0) > 0:
            ch_on.add(msg.channel)
        elif msg.type == "note_off":
            ch_off.add(msg.channel)
    return sorted(ch_on) if ch_on else sorted(ch_off)


def _merge_one_track(source_track, target_track):
    from mido import Message, MetaMessage, MidiTrack

    stn: Optional[str] = None
    sin: Optional[str] = None
    for msg in source_track:
        if msg.type == "track_name" and stn is None:
            stn = msg.name
        if msg.type == "instrument_name" and sin is None:
            sin = msg.name

    ref_prog, ref_ch = _first_program_from_ref(source_track)
    note_chans = _note_channels_for_program(target_track)

    body = [
        m
        for m in target_track
        if m.type not in ("track_name", "instrument_name", "program_change")
    ]
    out = MidiTrack()
    if stn is not None:
        out.append(MetaMessage("track_name", name=stn, time=0))
    if sin is not None:
        out.append(MetaMessage("instrument_name", name=sin, time=0))

    if ref_prog is not None:
        if note_chans:
            for ch in note_chans:
                out.append(
                    Message("program_change", channel=ch, program=ref_prog, time=0)
                )
        elif ref_ch is not None:
            out.append(
                Message("program_change", channel=ref_ch, program=ref_prog, time=0)
            )

    for m in body:
        out.append(m.copy())
    return out


def restore_track_metadata(
    reference_midi_path: str,
    target_midi_path: str,
) -> dict:
    """
    Copy per-track ``track_name``, ``instrument_name``, and the reference track's
    first **program number** onto ``target_midi_path`` (same track index). Target
    ``program_change`` events are replaced so hosts no longer show everything as
    Acoustic Grand when only text meta was restored. Overwrites in-place.

    If track counts differ, applies to the first ``min(n_ref, n_tgt)`` tracks only.

    Returns a small stats dict (or raises if ``mido`` is unavailable).
    """
    try:
        from mido import MidiFile
    except ImportError as e:
        raise ImportError(
            "restore_track_metadata requires the 'mido' package: pip install mido"
        ) from e

    reference_midi_path = str(Path(reference_midi_path).resolve())
    target_midi_path = str(Path(target_midi_path).resolve())

    ref = MidiFile(reference_midi_path)
    tgt = MidiFile(target_midi_path)

    n_tgt_before = len(tgt.tracks)
    n = min(len(ref.tracks), len(tgt.tracks))
    new_tracks = []
    for i in range(n):
        new_tracks.append(_merge_one_track(ref.tracks[i], tgt.tracks[i]))
    for i in range(n, len(tgt.tracks)):
        new_tracks.append(tgt.tracks[i])

    tgt.tracks = new_tracks
    tgt.save(target_midi_path)

    return {
        "reference_midi_path": reference_midi_path,
        "target_midi_path": target_midi_path,
        "tracks_merged": n,
        "reference_tracks": len(ref.tracks),
        "target_tracks_before": n_tgt_before,
    }
