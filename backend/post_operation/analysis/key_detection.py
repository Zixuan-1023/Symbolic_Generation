import music21
from music21 import note as m21note
from music21 import percussion as m21perc
from music21 import stream as m21stream


def _stream_pitched_notes_only(score: music21.stream.Stream) -> m21stream.Stream:
    """
    Key analysis assumes pitched notes; drum tracks break music21's pitch-class
    step (Unpitched, PercussionChord — no usable ``.pitch`` on every element).
    """
    out = m21stream.Stream()
    for el in score.flatten().notes:
        if isinstance(el, m21note.Unpitched):
            continue
        if isinstance(el, m21perc.PercussionChord):
            continue
        out.insert(el.offset, el)
    return out


def detect_key_music21(midi_path: str) -> dict:
    """
    Detect key from MIDI with music21 and return a lightweight dict.
    """
    score = music21.converter.parse(midi_path)
    if len(list(score.recurse().notes)) == 0:
        raise ValueError(f"No notes found in MIDI: {midi_path}")

    pitched = _stream_pitched_notes_only(score)
    if len(list(pitched.notes)) == 0:
        raise ValueError(f"No pitched notes found in MIDI (only unpitched/percussion?): {midi_path}")

    key = pitched.analyze('key')
    mode = key.mode.lower().strip() if getattr(key, "mode", None) else "major"
    if mode not in {"major", "minor"}:
        # Keep downstream behavior stable by defaulting uncommon modes to major.
        mode = "major"

    result = {
        "tonic_name": key.tonic.name,
        "tonic_pc": key.tonic.pitchClass,
        "mode": mode,
        "key_name": str(key),
        "confidence": getattr(key, 'correlationCoefficient', None)
    }

    return result


if __name__ == "__main__":
    midi_path = "test.mid"
    res = detect_key_music21(midi_path)

    print("Detected:", res["key_name"])
    print("Tonic PC:", res["tonic_pc"])
    print("Confidence:", res["confidence"])