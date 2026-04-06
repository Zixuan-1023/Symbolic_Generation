# Controllable Symbolic AI System for Music Composition

This repository contains the implementation and supporting code for the thesis
**"A Controllable Symbolic AI System for Music Composition"** (Zixuan Guo, NYU
Steinhardt, 2026). The project provides a DAW-integrated symbolic music system
that separates probabilistic generation from deterministic control, enabling
interactive, user-driven composition workflows.

## Overview

The system combines:
- **Generative backbone**: MuseCoco (Transformer-based symbolic generation).
- **Control layer**: deterministic symbolic operators (density, pitch range,
  timing, tonal constraints, etc.).
- **Cleanup layer**: post-processing to fix timing, overlap, duration, and tonal
  inconsistencies.
- **Transformation mode**: AR-VAE latent-space editing for flexible variation.
- **DAW integration**: JUCE plugin frontend with asynchronous backend inference.

The pipeline supports three interaction modes:
1. **New**: generate from text + controls.
2. **Continue**: extend an existing MIDI context.
3. **Transform**: apply symbolic control or latent-space edits to existing MIDI.

## Repository Structure

- `ControlableSymbolicMusic/` — JUCE plugin project (frontend UI).
- `backend/` — Backend services, models, control/cleanup, and evaluation code.
  - `backend/utils/` — FastAPI server, control mapping, job handling.
  - `backend/musecoco/` — MuseCoco model code, preprocessing, evaluation.
  - `backend/post_operation/` — control layer and cleanup layer implementations.
  - `backend/ar-vae/` — AR-VAE transformation model.

## System Architecture (Summary)

User input (prompt/MIDI/controls) flows through:
1. **Generation / Continuation** via MuseCoco (probabilistic sequence).
2. **Control layer** applying explicit symbolic constraints.
3. **Cleanup layer** to stabilize timing, duration, overlaps, and tonality.
4. **DAW plugin** displays MIDI and supports iterative interaction.

This design keeps the generative model unchanged while achieving controllability
through post-hoc symbolic manipulation.

## Backend (FastAPI)

The backend exposes a job-based API:
- `POST /v1/generate` — submit a generation request.
- `GET /v1/jobs/{job_id}` — poll job status and results.

The backend currently supports a full request/response pipeline and can be
connected to MuseCoco inference when checkpoints are available.

## Frontend (JUCE Plugin)

The JUCE plugin:
- collects user input (prompt + sliders),
- submits requests to the backend,
- polls job status asynchronously,
- renders MIDI output in a piano-roll preview.

The UI state machine includes **Idle / Generating / Success / Error**.

## Notes on Models and Checkpoints

Model checkpoints are large and are not included in this repository. You must
download MuseCoco and (optionally) AR-VAE checkpoints separately and place them
in the expected paths under `backend/`.

## Thesis Context

This implementation reflects a **decoupled controllability framework** where
stochastic generation is followed by deterministic symbolic control. It is
designed for **interactive DAW workflows** rather than one-shot generation.

For full details, see the thesis document:
**"A Controllable Symbolic AI System for Music Composition"**.
