#!/usr/bin/env python3
"""
Extract last N measures from a MIDI file and encode to REMIGEN2 token string (space-separated).
Used for continue mode: [attributes] <sep> [these tokens] -> model continues.
"""
import argparse
import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from music21 import converter, stream
from midiprocessor import MidiEncoder


def extract_last_measures_to_score(midi_path: str, num_bars: int):
    s = converter.parse(midi_path)
    part = s.parts[0] if s.parts else s
    measures = list(part.getElementsByClass("Measure"))
    if len(measures) == 0:
        # no explicit measures — use whole part as one chunk
        np = stream.Part()
        for e in part.recurse().notesAndRests:
            np.insert(e.offset, e)
        ns = stream.Score()
        ns.append(np)
        return ns
    take = measures[-num_bars:] if len(measures) >= num_bars else measures
    np = stream.Part()
    for m in take:
        np.append(m)
    ns = stream.Score()
    ns.append(np)
    return ns


def midi_to_remi_line(midi_path: Path) -> str:
    enc = MidiEncoder("REMIGEN2")
    token_lists = enc.encode_file(str(midi_path))
    str_lists = enc.convert_token_lists_to_token_str_lists(token_lists)
    flat = []
    for sl in str_lists:
        flat.extend(sl)
    return " ".join(flat)


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--input", required=True, help="Input MIDI path")
    p.add_argument("--out", required=True, help="Output .txt (space-separated REMI tokens)")
    p.add_argument("--bars", type=int, default=4, help="Number of last measures to take")
    p.add_argument("--tmp-midi", default=None, help="Optional temp MIDI path for debug")
    args = p.parse_args()

    ns = extract_last_measures_to_score(args.input, args.bars)
    tmp = Path(args.tmp_midi) if args.tmp_midi else Path(args.out).with_suffix(".tmp.mid")
    tmp.parent.mkdir(parents=True, exist_ok=True)
    ns.write("midi", fp=str(tmp))

    line = midi_to_remi_line(tmp)
    Path(args.out).write_text(line, encoding="utf-8")
    print(f"Wrote {len(line.split())} tokens to {args.out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
