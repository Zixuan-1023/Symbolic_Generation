# Refine sliders: recommended defaults & backend mapping

## Recommended default (demo / thesis / UI initial state)

| Control | Value |
|--------|-------|
| `rhythm_complexity` | `0.5` |
| `pitch_range` | `0.5` |
| `note_density` | `0.5` |
| `contour` | `0.5` |
| `tonal_mode` | `scale_only` (always from `map_controls_to_refine_params`) |
| `humanize` | `0.0` (always) |

Code: `refine/control_mapping.py` exports `DEFAULT_RHYTHM_COMPLEXITY`, `DEFAULT_PITCH_RANGE`, `DEFAULT_NOTE_DENSITY`, `DEFAULT_CONTOUR`, `DEFAULT_TONAL_MODE`, `DEFAULT_HUMANIZE`.

---

## `min_pitch` / `max_pitch` depend on `center_pitch`

`center_pitch` comes from structure detection on the input MIDI (mean of note MIDI in the melody part). The table below uses **Flower Dance** (`center_pitch ≈ 80.59` → rounded **81** for clamp window), so `min_pitch`/`max_pitch` are representative for that file only. Re-map with `map_controls_to_refine_params(..., center_pitch=your_value)` if the piece differs.

---

## Slider → `mapped_params` (reference rows)

**Sensitivity check (only `rhythm_complexity` moves):**

| rc | pr | nd | ct | Notes |
|----|----|----|-----|-------|
| 0.2 | 0.5 | 0.5 | 0.5 | Lower `motif_variation`, `rhythm_variation`, `merge_strength` |
| 0.8 | 0.5 | 0.5 | 0.5 | Higher `motif_variation`, `rhythm_variation`, `merge_strength` |

**Flower Dance, `center_pitch ≈ 80.59`:**

| Label | rc | pr | nd | ct | `pitch_variation` | `min`–`max` | `merge_strength` | `motif_variation` |
|-------|----|----|----|-----|-------------------|-------------|------------------|-------------------|
| rc=0.2 | 0.2 | 0.5 | 0.5 | 0.5 | 0.225 | 72–90 | 0.004 | 0.076 |
| rc=0.8 | 0.8 | 0.5 | 0.5 | 0.5 | 0.225 | 72–90 | 0.016 | 0.244 |
| A baseline | 0.5 | 0.5 | 0.5 | 0.5 | 0.225 | 72–90 | 0.01 | 0.16 |
| B contour↑ | 0.5 | 0.5 | 0.5 | **0.8** | **0.33** | 72–90 | 0.01 | 0.16 |
| C range↓ | 0.5 | **0.2** | 0.5 | 0.5 | 0.225 | **75–87** | 0.01 | 0.16 |
| D density↓ | 0.5 | 0.5 | **0.2** | 0.5 | 0.225 | 72–90 | **0.04** | 0.16 |

**Quick read:**

- **`contour`** → directly moves **`pitch_variation`** (clearest single-knob effect on pitch edits).
- **`pitch_range`** → moves **`min_pitch` / `max_pitch`** only (narrow window on C).
- **`rhythm_complexity`** → moves **`motif_variation`**, **`rhythm_variation`**, and **`merge_strength`** together.
- **`note_density`** → mainly **`merge_strength`** (and `enable_note_merge` flips when `nd ≥ 0.6`).

---

## Listening batch A–D (Flower Dance, `--disable-cleanup`)

Outputs: `refine_experiments/listening_abcd/*.mid`

| Run | `num_merge` | `num_motif_variations` | `merge_strength_applied` | `num_pitch_changed` |
|-----|-------------|-------------------------|---------------------------|---------------------|
| A baseline | 0 | 0 | 0.01 | 7 |
| B contour 0.8 | 0 | 0 | 0.01 | **8** |
| C pr 0.2 | 0 | 0 | 0.01 | 7 |
| D nd 0.2 | 0 | 0 | **0.04** | 7 |

**Reminder:** If `num_merge` and `num_motif_variations` stay **0**, rhythm/density sliders may change **mapped** values but **not** audible merge/motif — always check `merge_strength_applied` and transform stats before judging by ear.
