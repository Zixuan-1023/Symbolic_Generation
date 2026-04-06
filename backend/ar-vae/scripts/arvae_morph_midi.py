#!/usr/bin/env python3
"""
Encode MIDI -> adjust first 4 latent dims (MUSIC_REG_TYPE) -> decode, bar by bar.
Sliders in [0,1]; 0.5 means no delta on that dimension.
"""
import argparse
import os
import sys

import music21
import numpy as np
import torch

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from data.dataloaders.bar_dataset import FolkNBarDataset
from data.dataloaders.bar_dataset_helpers import fix_and_expand_score, is_score_on_ticks, TICK_VALUES
from measurevae.measure_vae import MeasureVAE


def _first_part(stream_obj):
    """First Part from a Score; if already a Part (or other Stream), return as-is."""
    if isinstance(stream_obj, music21.stream.Score):
        return stream_obj.parts[0] if stream_obj.parts else stream_obj.flatten()
    return stream_obj


def quantize_score_to_ticks(score, num_bars=4):
    tick_positions = []
    for bar in range(num_bars):
        for beat in range(4):
            for t in TICK_VALUES:
                tick_positions.append(bar * 4 + beat + float(t))
    tick_positions = np.array(tick_positions)
    part = _first_part(score)
    for n in part.recurse().getElementsByClass(music21.note.Note):
        off = n.offset
        nearest = tick_positions[np.argmin(np.abs(tick_positions - off))]
        n.offset = float(nearest)
    for n in part.recurse().getElementsByClass(music21.note.Rest):
        off = n.offset
        nearest = tick_positions[np.argmin(np.abs(tick_positions - off))]
        n.offset = float(nearest)
    return score


def estimate_bars_from_score(score) -> int:
    max_off = 0.0
    part = _first_part(score)
    for el in part.recurse().notesAndRests:
        max_off = max(max_off, float(el.offset) + float(el.duration.quarterLength))
    return max(1, int(np.ceil(max_off / 4.0)) + 1)


def main():
    p = argparse.ArgumentParser(description="AR-VAE morph: MIDI -> z -> adjust z[0:4] -> MIDI")
    p.add_argument("--input", required=True, help="Input .mid")
    p.add_argument("--output", required=True, help="Output .mid")
    p.add_argument(
        "--ckpt",
        default=os.environ.get(
            "ARVAE_CKPT",
            os.path.join(
                os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                "models",
                "folk_MeasureVAE_r_0_b_0.001_g_1.0_d_10.0_all_",
                "folk_MeasureVAE_r_0_b_0.001_g_1.0_d_10.0_all_.pt",
            ),
        ),
        help="Path to MeasureVAE .pt (override with ARVAE_CKPT)",
    )
    p.add_argument("--rhy_complexity", type=float, default=0.5)
    p.add_argument("--pitch_range", type=float, default=0.5)
    p.add_argument("--note_density", type=float, default=0.5)
    p.add_argument("--contour", type=float, default=0.5)
    p.add_argument(
        "--z-scale",
        type=float,
        default=float(os.environ.get("ARVAE_Z_SCALE", "0.8")),
        help="Max z delta magnitude per dim (at slider 0 or 1)",
    )
    p.add_argument("--max-bars", type=int, default=512, help="Safety cap on number of bars")
    args = p.parse_args()

    if not os.path.isfile(args.input):
        print("Input not found:", args.input, file=sys.stderr)
        return 1
    if not os.path.isfile(args.ckpt):
        print("Checkpoint not found:", args.ckpt, file=sys.stderr)
        return 1

    device = torch.device("cuda" if torch.cuda.is_available() else "cpu")

    # Re-parse MIDI with enough quantize grid for long pieces
    score = music21.converter.parse(args.input)
    if score.parts:
        score = score.parts[0]
    score = fix_and_expand_score(score)
    if score is None:
        print("fix_and_expand_score failed", file=sys.stderr)
        return 1
    nb = min(args.max_bars, estimate_bars_from_score(score))
    quantize_score_to_ticks(score, num_bars=nb)
    if not is_score_on_ticks(score, TICK_VALUES):
        print("Notes not on tick grid after quantize", file=sys.stderr)
        return 1

    dataset = FolkNBarDataset(dataset_type="train", is_short=False, num_bars=1)
    score_tensor = dataset.get_tensor(score, freeze_vocab=True)
    if score_tensor is None:
        print("get_tensor failed (encoding / vocabulary)", file=sys.stderr)
        return 1
    bars = dataset.split_tensor_to_bars(score_tensor)
    bar_list = [bars[i : i + 1] for i in range(bars.size(0))]
    if not bar_list:
        print("No bars in MIDI", file=sys.stderr)
        return 1

    model = MeasureVAE(
        dataset=dataset,
        note_embedding_dim=10,
        metadata_embedding_dim=2,
        num_encoder_layers=2,
        encoder_hidden_size=128,
        encoder_dropout_prob=0.5,
        latent_space_dim=32,
        num_decoder_layers=2,
        decoder_hidden_size=128,
        decoder_dropout_prob=0.5,
        has_metadata=False,
        dataset_type="folk",
    ).to(device)
    state = torch.load(args.ckpt, map_location=device)
    model.load_state_dict(state)
    model.eval()

    bar_seq_len = dataset.beat_subdivisions * 4
    dummy_score = torch.zeros(1, bar_seq_len, device=device, dtype=torch.long)

    sliders = [
        args.rhy_complexity,
        args.pitch_range,
        args.note_density,
        args.contour,
    ]
    z_deltas = [(s - 0.5) * 2.0 * args.z_scale for s in sliders]

    out_scores = []
    with torch.no_grad():
        for bar_tensor in bar_list:
            bt = bar_tensor.to(device)
            z_dist = model.encoder(bt)
            z = z_dist.mean.clone()
            for dim in range(4):
                z[0, dim] = z[0, dim] + z_deltas[dim]
            _, tensor_out = model.decoder(z, dummy_score, train=False)
            s_one = dataset.tensor_to_m21score(tensor_out.cpu())
            out_scores.append(s_one)

    if len(out_scores) == 1:
        final = out_scores[0]
    else:
        final = dataset.concatenate_scores(out_scores)

    os.makedirs(os.path.dirname(os.path.abspath(args.output)) or ".", exist_ok=True)
    final.write("midi", fp=args.output)
    print("Wrote", args.output)
    return 0


if __name__ == "__main__":
    sys.exit(main())
