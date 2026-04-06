"""
Hard symbolic constraints applied after soft model output: exact length in bars,
global tempo, and target key (for tonal snap).

These are deterministic algorithmic steps, not neural controls.
"""
from __future__ import annotations

import re
from typing import Any, Dict, Tuple, Union

import music21
from music21 import key as m21key
from music21 import stream as m21stream
from music21 import tempo as m21tempo


def _bar_quarter_length(ts_num: int, ts_den: int) -> float:
    return 4.0 * float(ts_num) / float(ts_den)


def parse_time_signature(s: str) -> Tuple[int, int]:
    s = s.strip()
    m = re.match(r"^(\d+)\s*/\s*(\d+)$", s)
    if not m:
        raise ValueError(f"Invalid time signature: {s!r} (expected e.g. 4/4)")
    num, den = int(m.group(1)), int(m.group(2))
    if num < 1 or den < 1:
        raise ValueError(f"Invalid time signature: {s!r}")
    return num, den


def _normalize_key_string(raw: str) -> str:
    """
    Accept common DAW / plugin spellings before music21 parsing:
    ``C:maj``, ``D:min``, ``Cmaj``, ``Am``, ``Bbm``, ``f#`` (minor).
    Output space-separated tonic + ``major`` or ``minor`` when possible.
    """
    s = raw.strip().replace("♯", "#").replace("♭", "b")
    if not s:
        return s

    # --- C:maj / F#:min / Bb:major ---
    if ":" in s:
        left, right = s.split(":", 1)
        lt, rt = left.strip(), right.strip().lower()
        if rt in ("maj", "major"):
            return f"{lt} major"
        if rt in ("min", "minor"):
            return f"{lt} minor"
        s = f"{lt} {right.strip()}"

    # --- Cmaj, Amin, F#maj (no space) ---
    m_glued = re.match(
        r"^([A-G][#b]?)(maj|min|major|minor)$",
        s,
        re.IGNORECASE,
    )
    if m_glued:
        tonic = m_glued.group(1)
        suf = m_glued.group(2).lower()
        mode = "minor" if suf in ("min", "minor") else "major"
        return f"{tonic} {mode}"

    # --- Am, Bbm, C#m (jazz-style minor) ---
    m_m = re.match(r"^([A-G][#b]?)\s*m\s*$", s, re.IGNORECASE)
    if m_m:
        return f"{m_m.group(1)} minor"

    return s


def parse_target_key(key_str: str) -> Tuple[int, str]:
    """
    Map user-facing strings like "C major", "C:maj", "Am", "Bb" to (tonic_pc, mode).
    music21 ``Key("C major")`` as one string is invalid; we split tonic vs mode ourselves.
    """
    s = _normalize_key_string(key_str)
    if not s:
        raise ValueError("empty target key")

    parts = s.split()
    mode = "major"
    name_part = s
    if len(parts) >= 2 and parts[-1].lower() in ("major", "minor", "maj", "min"):
        mode = "minor" if parts[-1].lower() in ("minor", "min") else "major"
        name_part = " ".join(parts[:-1]).strip()
    elif len(parts) == 1 and parts[0] and parts[0][0].islower():
        # music21-style: leading lowercase tonic → minor (e.g. "a" = A minor)
        mode = "minor"
        name_part = parts[0]

    try:
        k = m21key.Key(name_part)
    except Exception as e:
        raise ValueError(
            f"Unrecognized key tonic {name_part!r} (from {key_str!r}). "
            'Try e.g. "C major", "C:maj", "Am", "Bb minor".'
        ) from e
    out_mode = mode if mode in ("major", "minor") else "major"
    return int(k.tonic.pitchClass), out_mode


def _parse_midi_to_score(path: str) -> m21stream.Score:
    """Normalize converter.parse() result to a Score (handles Part / Opus)."""
    obj = music21.converter.parse(path)
    if isinstance(obj, m21stream.Score):
        return obj
    if isinstance(obj, m21stream.Opus):
        return obj.mergeScores()
    s = m21stream.Score()
    s.insert(0, obj)
    return s


def _set_tempo_bpm_music21(
    input_midi_path: str, output_midi_path: str, bpm: float
) -> Dict[str, Any]:
    """Fallback: music21 round-trip (can change MIDI layout); prefer mido path."""
    score = music21.converter.parse(input_midi_path)
    for mm in list(score.recurse().getElementsByClass(m21tempo.MetronomeMark)):
        parent = mm.activeSite
        if parent is not None:
            parent.remove(mm)

    score.insert(0, m21tempo.MetronomeMark(number=bpm))
    score.write("midi", fp=output_midi_path)
    return {"bpm": bpm, "output_midi_path": output_midi_path, "backend": "music21"}


def set_tempo_bpm(input_midi_path: str, output_midi_path: str, bpm: float) -> Dict[str, Any]:
    """
    Overwrite tempo with a single global BPM.

    Uses **mido** so track count / MIDI format are preserved. (music21 parse→write
    was collapsing multi-track files for some users after cleanup hard constraints.)
    """
    bpm = float(bpm)
    if bpm <= 0:
        raise ValueError("bpm must be positive")

    try:
        from mido import MetaMessage, MidiFile
    except ImportError:
        return _set_tempo_bpm_music21(input_midi_path, output_midi_path, bpm)

    usec = int(round(60000000.0 / bpm))
    mf = MidiFile(input_midi_path)
    for tr in mf.tracks:
        kept = [m for m in tr if m.type != "set_tempo"]
        tr.clear()
        tr.extend(kept)
    if mf.tracks:
        t0 = mf.tracks[0]
        old = list(t0)
        t0.clear()
        t0.append(MetaMessage("set_tempo", tempo=usec, time=0))
        t0.extend(old)
    mf.save(output_midi_path)
    return {"bpm": bpm, "output_midi_path": output_midi_path, "backend": "mido"}


def _truncate_or_pad_ql(score: Union[music21.stream.Score, music21.stream.Stream], target_ql: float) -> None:
    """In-place: clip notes/rests to [0, target_ql); pad each part with rests if shorter."""
    for el in list(score.recurse().notesAndRests):
        o = float(el.offset)
        dur = float(el.duration.quarterLength)
        if o >= target_ql - 1e-9:
            site = el.activeSite
            if site is not None:
                site.remove(el)
        elif o + dur > target_ql + 1e-9:
            el.quarterLength = max(0.0, target_ql - o)

    streams: Tuple[music21.stream.Stream, ...] = (
        tuple(score.parts) if score.parts else (score,)
    )
    for p in streams:
        ht = float(p.highestTime)
        if ht < target_ql - 1e-6:
            p.insert(ht, music21.note.Rest(quarterLength=target_ql - ht))


def enforce_num_bars(
    input_midi_path: str,
    output_midi_path: str,
    num_bars: int,
    time_signature_num: int = 4,
    time_signature_den: int = 4,
) -> Dict[str, Any]:
    """
    Force the score to cover exactly ``num_bars`` measures at the given meter.
    Longer material is truncated; shorter scores are padded with rests.
    """
    if num_bars < 1:
        raise ValueError("num_bars must be >= 1")

    bar_ql = _bar_quarter_length(time_signature_num, time_signature_den)
    target_ql = num_bars * bar_ql

    score = _parse_midi_to_score(input_midi_path)
    # Ensure meter is visible for DAWs (does not rewrite note offsets)
    ts = music21.meter.TimeSignature(f"{time_signature_num}/{time_signature_den}")
    if score.timeSignature is None:
        score.insert(0, ts)

    _truncate_or_pad_ql(score, target_ql)
    score.write("midi", fp=output_midi_path)
    return {
        "num_bars": num_bars,
        "time_signature": f"{time_signature_num}/{time_signature_den}",
        "target_quarter_length": target_ql,
        "output_midi_path": output_midi_path,
    }
