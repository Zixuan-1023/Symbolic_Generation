#!/usr/bin/env python3
"""
Convert REMI token .txt files (from generation) to MIDI and optionally play.
Usage:
  # Convert one file (content is "attr ... <sep> remi tokens" or just "remi tokens")
  python remi_to_midi.py path/to/remi/0.txt -o path/to/out.mid

  # Convert all remi/*.txt in a generation folder and save to midi/
  python remi_to_midi.py path/to/generation/0/remi --batch -o path/to/generation/0/midi

  # Convert and open with default app (Linux: xdg-open)
  python remi_to_midi.py path/to/remi/0.txt -o out.mid --play
"""

import argparse
import os
import sys

# Run from linear_mask so midiprocessor is importable
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from midiprocessor import MidiDecoder


def extract_remi_tokens(line: str):
    """From full sequence 'attr ... <sep> remi ...' return list of remi token strings."""
    tokens = line.strip().split()
    if "<sep>" in tokens:
        idx = tokens.index("<sep>")
        return tokens[idx + 1:]
    return tokens


def convert_file(remi_path: str, midi_path: str, encoding: str = "REMIGEN2") -> bool:
    with open(remi_path, "r") as f:
        line = f.read()
    token_list = extract_remi_tokens(line)
    if not token_list:
        print(f"Empty tokens in {remi_path}", file=sys.stderr)
        return False
    try:
        decoder = MidiDecoder(encoding)
        midi_obj = decoder.decode_from_token_str_list(token_list)
        os.makedirs(os.path.dirname(midi_path) or ".", exist_ok=True)
        midi_obj.dump(midi_path)
        print(f"Saved: {midi_path}")
        return True
    except Exception as e:
        print(f"Decode failed for {remi_path}: {e}", file=sys.stderr)
        return False


def main():
    p = argparse.ArgumentParser(description="REMI .txt -> MIDI .mid")
    p.add_argument("input", help="Path to .txt file or directory (with --batch)")
    p.add_argument("-o", "--output", default=None, help="Output .mid file or directory (with --batch)")
    p.add_argument("--batch", action="store_true", help="Input is a dir of remi/*.txt; -o is output dir (e.g. midi/)")
    p.add_argument("--play", action="store_true", help="Open output MIDI with default app (Linux)")
    p.add_argument("--encoding", default="REMIGEN2", choices=("REMIGEN", "REMIGEN2"))
    args = p.parse_args()

    if args.batch:
        if not args.output:
            args.output = os.path.join(os.path.dirname(args.input.rstrip("/")), "midi")
        os.makedirs(args.output, exist_ok=True)
        for name in sorted(os.listdir(args.input)):
            if not name.endswith(".txt"):
                continue
            remi_path = os.path.join(args.input, name)
            base = os.path.splitext(name)[0]
            midi_path = os.path.join(args.output, base + ".mid")
            convert_file(remi_path, midi_path, args.encoding)
        if args.play:
            mids = [f for f in os.listdir(args.output) if f.endswith(".mid")]
            if mids:
                first_mid = os.path.join(args.output, sorted(mids)[0])
                os.system(f'xdg-open "{first_mid}" 2>/dev/null || open "{first_mid}" 2>/dev/null')
        return

    # Single file
    if not args.output:
        args.output = os.path.splitext(args.input)[0] + ".mid"
    ok = convert_file(args.input, args.output, args.encoding)
    if ok and args.play:
        os.system(f'xdg-open "{args.output}" 2>/dev/null || open "{args.output}" 2>/dev/null')


if __name__ == "__main__":
    main()
