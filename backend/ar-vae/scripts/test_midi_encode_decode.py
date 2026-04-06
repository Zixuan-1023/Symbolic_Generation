#!/usr/bin/env python3
"""
Test whether the trained MeasureVAE can encode existing MIDI and decode (morphing).
Usage:
  # Test 1: use a bar from the dataset (proves roundtrip)
  python scripts/test_midi_encode_decode.py

  # Test 2: use your own MIDI file (must be 4/4, single melody; will try to quantize)
  python scripts/test_midi_encode_decode.py path/to/your.mid
"""
import os
import sys
import argparse
import torch
import numpy as np
import music21

# project root
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from data.dataloaders.bar_dataset import FolkNBarDataset
from data.dataloaders.bar_dataset_helpers import (
    get_notes,
    fix_and_expand_score,
    is_score_on_ticks,
    TICK_VALUES,
)
from measurevae.measure_vae import MeasureVAE


def quantize_score_to_ticks(score, num_bars=4):
    """Snap each note's offset to the model's tick grid so get_tensor() can be used."""
    ticks_per_beat = len(TICK_VALUES)
    tick_positions = []
    for bar in range(num_bars):
        for beat in range(4):
            for t in TICK_VALUES:
                tick_positions.append(bar * 4 + beat + float(t))
    tick_positions = np.array(tick_positions)

    part = score.parts[0] if score.parts else score.flatten()
    for n in part.recurse().getElementsByClass(music21.note.Note):
        off = n.offset
        nearest = tick_positions[np.argmin(np.abs(tick_positions - off))]
        n.offset = float(nearest)
    for n in part.recurse().getElementsByClass(music21.note.Rest):
        off = n.offset
        nearest = tick_positions[np.argmin(np.abs(tick_positions - off))]
        n.offset = float(nearest)
    return score


def midi_to_bar_tensors(midi_path, dataset):
    """Load MIDI, quantize to grid, return list of bar tensors (each shape [1, 24])."""
    score = music21.converter.parse(midi_path)
    if score.parts:
        score = score.parts[0]
    score = fix_and_expand_score(score)
    if score is None:
        return None
    quantize_score_to_ticks(score)
    if not is_score_on_ticks(score, TICK_VALUES):
        return None
    score_tensor = dataset.get_tensor(score)
    if score_tensor is None:
        return None
    bars = dataset.split_tensor_to_bars(score_tensor)  # (num_bars, 24)
    return [bars[i : i + 1] for i in range(bars.size(0))]


def main():
    parser = argparse.ArgumentParser(description="Test MIDI encode -> decode (morphing)")
    parser.add_argument("midi_path", nargs="?", default=None, help="Optional: path to a .mid file")
    parser.add_argument("--out", default=None, help="Output MIDI path (default: auto)")
    parser.add_argument("--seed", type=int, default=0)
    args = parser.parse_args()

    device = torch.device("cuda" if torch.cuda.is_available() else "cpu")
    ckpt_path = os.path.join(
        "models",
        "folk_MeasureVAE_r_0_b_0.001_g_1.0_d_10.0_all_",
        "folk_MeasureVAE_r_0_b_0.001_g_1.0_d_10.0_all_.pt",
    )
    if not os.path.isfile(ckpt_path):
        print("Checkpoint not found:", ckpt_path)
        return 1

    # 1) Dataset + model (same config as training)
    dataset = FolkNBarDataset(dataset_type="train", is_short=False, num_bars=1)
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
    state = torch.load(ckpt_path, map_location=device)
    model.load_state_dict(state)
    model.eval()

    bar_seq_len = dataset.beat_subdivisions * 4  # 24
    dummy_score = torch.zeros(1, bar_seq_len, device=device, dtype=torch.long)

    if args.midi_path:
        # Test with user MIDI
        if not os.path.isfile(args.midi_path):
            print("File not found:", args.midi_path)
            return 1
        bars = midi_to_bar_tensors(args.midi_path, dataset)
        if bars is None or len(bars) == 0:
            print("Could not convert MIDI to bar tensors. Need 4/4, single melody, notes on grid.")
            return 1
        bar_tensor = bars[0].to(device)  # (1, 24)
        print("Loaded first bar from", args.midi_path)
    else:
        # Test with one bar from dataset
        _, _, loader = dataset.data_loaders(batch_size=1)
        batch = next(iter(loader))
        score_t, _ = batch
        # DataLoader returns (1, 1, 24) for batch_size=1, one bar
        if score_t.dim() == 3:
            score_t = score_t.squeeze(0)  # (1, 24)
        score_t = score_t[:, :bar_seq_len]
        if score_t.size(1) < bar_seq_len:
            pad = torch.zeros(1, bar_seq_len - score_t.size(1), dtype=torch.long)
            score_t = torch.cat([score_t, pad], dim=1)
        bar_tensor = score_t.to(device)
        print("Using one bar from the folk dataset")

    # 2) Encode
    with torch.no_grad():
        z_dist = model.encoder(bar_tensor)
        z = z_dist.mean  # or z_dist.sample() for stochastic
    print("Encoded to latent z shape:", z.shape)

    # 3) Decode
    with torch.no_grad():
        _, tensor_out = model.decoder(z, dummy_score, train=False)
    score_out = dataset.tensor_to_m21score(tensor_out.cpu())
    out_path = args.out or "test_morph_output.mid"
    score_out.write("midi", fp=out_path)
    print("Decoded and saved:", out_path)

    # 4) Optional: save the *reconstructed* from same bar (encode then decode)
    with torch.no_grad():
        z_dist2 = model.encoder(bar_tensor)
        z2 = z_dist2.mean
        _, tensor_recon = model.decoder(z2, dummy_score, train=False)
    recon_score = dataset.tensor_to_m21score(tensor_recon.cpu())
    recon_path = out_path.replace(".mid", "_recon.mid")
    recon_score.write("midi", fp=recon_path)
    print("Reconstruction (encode->decode of same bar) saved:", recon_path)

    print("Done. You can open the .mid files to verify: the model can encode existing MIDI and decode (morphing).")
    return 0


if __name__ == "__main__":
    sys.exit(main())
