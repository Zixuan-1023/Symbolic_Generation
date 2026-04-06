from pydantic import BaseModel, Field
from typing import Optional, Literal

# ---------- MuseCoco generation (New / Continue) — becomes pred_labels in infer_test.bin ----------

class GenerationControls(BaseModel):
    """
    MuseCoco-only controls (New). After Stage1, these fields **overwrite** the BERT
    predictions in ``infer_test.bin`` — higher priority than prompt text for the same
    attributes. (``continue`` mode does not apply these overrides; see server.)
    """

    instrument: Optional[str] = None
    """I1s2 family: prefer exact lowercase tokens (``piano``, ``strings``, ``guitar``, ``bass``, ``drums``, …) or a substring of a family name (e.g. ``violin``). Sets that family to *yes* in ``I1s2``."""
    key: Optional[str] = None
    tempo: Optional[float] = Field(None, ge=0.0, le=1.0)
    time_signature: Optional[str] = None
    bars: Optional[int] = Field(
        None,
        ge=1,
        le=512,
        description="Cleanup / B1s1 bucket; not MuseCoco Stage2 token length (use phrase_length).",
    )
    phrase_length: Optional[Literal["short", "medium", "long"]] = Field(
        None,
        description=(
            "Stage2 REMI length tier → fairseq --min-len / --max-len-b (approximate phrase duration). "
            "If omitted, bars maps heuristically to a tier; if both absent, legacy long-window defaults."
        ),
    )
    danceability: Optional[float] = Field(None, ge=0.0, le=1.0)
    rhythm_intensity: Optional[float] = Field(None, ge=0.0, le=1.0)


# ---------- Transformation (AR-VAE latent morph + cleanup; four knobs) ----------


class ArvaeControls(BaseModel):
    """
    **Transformation** mode: four sliders in ``[0,1]`` drive AR-VAE latent dims (see ``ar-vae/scripts/arvae_morph_midi.py``);
    output is passed through ``generation_cleanup``. Not used for MuseCoco ``infer_test.bin``.
    """

    rhy_complexity: float = Field(0.5, ge=0.0, le=1.0)
    pitch_range: float = Field(0.5, ge=0.0, le=1.0)
    note_density: float = Field(0.5, ge=0.0, le=1.0)
    contour: float = Field(0.5, ge=0.0, le=1.0)
    humanize: Optional[float] = Field(
        None,
        ge=0.0,
        le=1.0,
        description="Reserved / legacy; AR-VAE morph does not use this field.",
    )
    seed: Optional[int] = Field(
        None,
        description="Reserved for future AR-VAE reproducibility; current morph is deterministic given weights.",
    )
    melody_part_index: int = Field(
        0,
        ge=0,
        le=31,
        description="Reserved / legacy; AR-VAE script operates on expanded single-line material.",
    )
    tonal_triad_snap: bool = Field(
        False,
        description="Reserved / legacy; use cleanup ``tonal_snap`` + ``key`` for tonal hard constraints.",
    )


# ---------- Controls (legacy wrapper; prefer generation + arvae above) ----------

class ControlHard(BaseModel):
    density: float = Field(ge=0.0, le=1.0)
    tempo: float = Field(ge=0.0, le=1.0)
    bass_energy: float = Field(ge=0.0, le=1.0)
    # AR-VAE (MUSIC_REG_TYPE dims 0–3); 0.5 = no delta. Optional for legacy clients.
    rhy_complexity: Optional[float] = Field(None, ge=0.0, le=1.0)
    pitch_range: Optional[float] = Field(None, ge=0.0, le=1.0)
    note_density: Optional[float] = Field(None, ge=0.0, le=1.0)
    contour: Optional[float] = Field(None, ge=0.0, le=1.0)


class ControlSoft(BaseModel):
    use_text2attr: bool = True
    temperature: float = Field(ge=0.0, le=2.0, default=1.0)
    topk: int = Field(ge=1, le=10, default=3)


class Constraints(BaseModel):
    key: Optional[str] = None
    instrument_id: Optional[int] = None


class Controls(BaseModel):
    hard: ControlHard
    soft: ControlSoft
    constraints: Optional[Constraints] = None


# ---------- Context ----------

class GenerationContext(BaseModel):
    """
    Session / UI context. When set, ``bpm``, ``length_bars``, and ``time_signature`` are merged
    into the cleanup hard-constraint pipeline (exact BPM, bar count, meter) unless overridden
    by ``cleanup`` or ``generation`` (see server merge rules).
    """

    bpm: int = Field(ge=20, le=300)
    time_signature: Literal["4/4", "3/4", "6/8"] = "4/4"
    start_bar: int = Field(ge=0)
    length_bars: int = Field(ge=1, le=512)


# ---------- Cleanup hard constraints (post_operation generation_cleanup; after MuseCoco) ----------

class CleanupHardControls(BaseModel):
    """
    Optional overrides for the same hard cleanup rules fed by ``context`` / ``generation``.
    Non-null fields here override merged defaults (e.g. pin BPM while keeping context bars).

    Pipeline fields (``track_alignment``, ``timing_*``, …) tune ``generation_cleanup`` after
    MuseCoco: single-track auto skips cross-part onset alignment unless you force it on.
    """

    bars: Optional[int] = Field(None, ge=1, le=512)
    bpm: Optional[float] = Field(None, ge=20, le=300)
    key: Optional[str] = None
    time_signature: str = Field("4/4", description='Meter for bar math, e.g. "4/4", "3/4"')
    tonal_snap: Literal["gentle", "strict"] = Field(
        "gentle",
        description="With `key`: gentle snaps short out-of-key notes; strict maps all pitches.",
    )

    track_alignment: Optional[bool] = Field(
        None,
        description="None=auto (skip when only one non-drum pitched track); True=always; False=never.",
    )
    timing_cleanup: Optional[bool] = Field(
        None,
        description="None=True: soft grid quantization; False disables.",
    )
    timing_strength: Optional[float] = Field(
        None,
        ge=0.0,
        le=1.0,
        description="Blend toward timing grid (1=full quantize). Default in pipeline ~0.82.",
    )
    timing_grid_quarter_length: Optional[float] = Field(
        None,
        gt=0.0,
        le=4.0,
        description="Grid step in quarter lengths (e.g. 0.25=sixteenth, 0.125=32nd).",
    )
    onset_align_threshold: Optional[float] = Field(
        None,
        gt=0.0,
        le=1.0,
        description="Track alignment cluster threshold in quarter lengths (keep small, e.g. 0.03).",
    )
    duration_cleanup: Optional[bool] = Field(
        None,
        description="None=True: extend/delete very short notes; False skips.",
    )
    overlap_cleanup: Optional[bool] = Field(
        None,
        description="None=True: trim same-pitch overlaps; False skips.",
    )
    tonal_correction: Optional[bool] = Field(
        None,
        description="None=False: optional gentle snap to detected key; True enables (no target key).",
    )
    preserve_track_metadata: Optional[bool] = Field(
        None,
        description="None=True: copy track/instrument names from input MIDI to output.",
    )


# ---------- Render Options ----------

class RenderOptions(BaseModel):
    num_variations: int = Field(ge=1, le=8, default=4)
    seed: Optional[int] = Field(
        None,
        description=(
            "Pins MuseCoco stage-2 sampling; same seed + same infer_test → reproducible MIDI. "
            "Omit (null) for a new random seed each job. "
            "Do not send 0 as a placeholder: unless MUSECOCO_HONEST_SEED_ZERO=1 on the server, "
            "seed 0 is treated as unset and randomized."
        ),
    )
    format: str = "midi"
    # MuseCoco Stage2 fairseq length (optional; mirrors PluginEditor phrase-length UX)
    min_len: Optional[float] = Field(
        None,
        ge=1.0,
        description="Stage2 --min-len (REMI tokens). Prefer sending with max_len_b from the same snapshot.",
    )
    max_len_b: Optional[int] = Field(
        None,
        ge=1,
        description="Stage2 --max-len-b (REMI token ceiling).",
    )
    phrase_length: Optional[Literal["short", "medium", "long"]] = Field(
        None,
        description="Echo of UI tier; used when min_len/max_len_b are omitted.",
    )


# ---------- Main Request ----------

class MidiInput(BaseModel):
    input_type: Literal["path", "base64", "bytes"]
    path: Optional[str] = None
    base64: Optional[str] = None
    bytes: Optional[object] = None


class GenerationRequest(BaseModel):
    # ---- New API (optional, backwards compatible) ----
    mode: Optional[Literal["continue", "new", "refine", "transformation"]] = None
    """
    ``new`` / ``continue``: MuseCoco + optional cleanup.
    ``transformation``: AR-VAE morph on user MIDI + ``generation_cleanup`` (``arvae`` sliders).
    ``refine``: deprecated alias for ``transformation`` (same behavior).
    """
    cleanup: Optional[CleanupHardControls] = None
    """Overrides for cleanup hard constraints; merged after ``context`` / ``generation`` (see pipeline)."""
    generation: Optional[GenerationControls] = None
    """MuseCoco (New / Continue). Ignored in transformation."""
    arvae: Optional[ArvaeControls] = None
    """Transformation: four AR-VAE sliders; ignored in New / Continue."""
    attributes: Optional[ControlHard] = None
    midi: Optional[MidiInput] = None

    # ---- Legacy API ----
    prompt: Optional[str] = None
    context: Optional[GenerationContext] = None
    controls: Optional[Controls] = None
    render: Optional[RenderOptions] = None