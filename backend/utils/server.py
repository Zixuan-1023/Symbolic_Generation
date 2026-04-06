from fastapi import FastAPI, BackgroundTasks, Depends, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from schemas import (
    CleanupHardControls,
    ControlHard,
    GenerationContext,
    GenerationRequest,
    RenderOptions,
)
from utils.gpu_memory import release_gpu_memory_best_effort
from utils.job_errors import job_failure_dict
from utils.job_response_compat import enrich_completed_job, enrich_failed_job
from utils.preview_from_midi import build_preview_payload
from utils.control_schema import map_request_to_canonical_control
from utils.musecoco_phrase_length import resolve_stage2_length_constraints
from utils.pipeline_modes import (
    effective_arvae_controls_refine,
    effective_arvae_sliders_refine,
    effective_cleanup_hard,
    effective_musecoco_generation,
    legacy_merge_final_attrs,
)
from utils.post_operation import (
    is_arvae_morph_configured,
    is_post_operation_root_configured,
    run_generation_cleanup,
    run_transformation_pipeline,
    skip_cleanup_after_musecoco,
    transformation_disable_cleanup_flag,
)
import uuid
import time
import threading
import os
import hashlib
import secrets
import shutil
import json
import subprocess
import base64
from pathlib import Path
from typing import Dict, Any, Optional, List

app = FastAPI()

# Browser / webview plugins fetch this API from a different origin; enable CORS unless disabled.
_cors = os.environ.get("BACKEND_CORS_ORIGINS", "*").strip()
if _cors and _cors != "0":
    _origins = ["*"] if _cors == "*" else [o.strip() for o in _cors.split(",") if o.strip()]
    app.add_middleware(
        CORSMiddleware,
        allow_origins=_origins,
        allow_credentials=False if "*" in _origins else True,
        allow_methods=["*"],
        allow_headers=["*"],
        expose_headers=["Content-Disposition"],
    )

jobs: Dict[str, Dict[str, Any]] = {}
jobs_lock = threading.Lock()


def _cleanup_hard_subprocess_kwargs(ch: Optional[CleanupHardControls]) -> Dict[str, Any]:
    """Maps merged ``cleanup`` / context fields to ``run_generation_cleanup`` kwargs."""
    if ch is None:
        return {}
    kw: Dict[str, Any] = {}
    if ch.bars is not None:
        kw["target_bars"] = ch.bars
        kw["time_signature"] = ch.time_signature
    if ch.bpm is not None:
        kw["target_bpm"] = ch.bpm
    if ch.key:
        kw["target_key"] = ch.key.strip()
        kw["tonal_snap"] = ch.tonal_snap
    if ch.track_alignment is not None:
        kw["track_alignment"] = ch.track_alignment
    if ch.timing_cleanup is not None:
        kw["timing_cleanup"] = ch.timing_cleanup
    if ch.timing_strength is not None:
        kw["timing_strength"] = ch.timing_strength
    if ch.timing_grid_quarter_length is not None:
        kw["timing_grid_quarter_length"] = ch.timing_grid_quarter_length
    if ch.onset_align_threshold is not None:
        kw["onset_align_threshold"] = ch.onset_align_threshold
    if ch.duration_cleanup is not None:
        kw["duration_cleanup"] = ch.duration_cleanup
    if ch.overlap_cleanup is not None:
        kw["overlap_cleanup"] = ch.overlap_cleanup
    if ch.tonal_correction is not None:
        kw["tonal_correction"] = ch.tonal_correction
    if ch.preserve_track_metadata is not None:
        kw["preserve_track_metadata"] = ch.preserve_track_metadata
    return kw


def _env_int(name: str, default: int) -> int:
    try:
        return int(os.environ.get(name, str(default)).strip())
    except ValueError:
        return default


def _max_prompt_chars() -> int:
    return max(256, _env_int("MUSECOCO_MAX_PROMPT_CHARS", 8000))


def _max_midi_bytes() -> int:
    return max(4096, _env_int("MUSECOCO_MAX_MIDI_BYTES", 8 * 1024 * 1024))


async def verify_optional_generate_api_key(request: Request) -> None:
    """
    If MUSECOCO_API_KEY is set, POST /v1/generate must send the same value in
    header X-MuseCoco-Key or Authorization: Bearer <key>.
    """
    expected = os.environ.get("MUSECOCO_API_KEY", "").strip()
    if not expected:
        return
    got = (request.headers.get("X-MuseCoco-Key") or "").strip()
    if not got:
        auth = request.headers.get("Authorization") or ""
        if auth.lower().startswith("bearer "):
            got = auth[7:].strip()
    if got != expected:
        raise HTTPException(status_code=401, detail="invalid or missing API key")


def validate_untrusted_generation_request(request: GenerationRequest) -> None:
    """
    Bound work from network clients: prompt size, MIDI payload size, and block
    server filesystem paths unless explicitly enabled (midi.path is dangerous).
    """
    max_prompt = _max_prompt_chars()
    if request.prompt is not None and len(request.prompt) > max_prompt:
        raise HTTPException(
            status_code=400,
            detail=f"prompt too long (max {max_prompt} characters)",
        )

    if request.midi is None:
        return

    max_mid = _max_midi_bytes()

    if request.midi.input_type == "path":
        if os.environ.get("MUSECOCO_ALLOW_MIDI_PATH", "0").strip() != "1":
            raise HTTPException(
                status_code=403,
                detail=(
                    "midi.input_type=path is disabled: clients must send midi as base64/bytes "
                    "so the server does not read arbitrary filesystem paths. "
                    "For local trusted automation only, set MUSECOCO_ALLOW_MIDI_PATH=1 on the server."
                ),
            )
        allow = os.environ.get("MUSECOCO_MIDI_PATH_ALLOW_DIR", "").strip()
        if allow and request.midi.path:
            base = Path(allow).expanduser().resolve()
            p = Path(request.midi.path).expanduser().resolve()
            if str(p) != str(base) and not str(p).startswith(str(base) + os.sep):
                raise HTTPException(
                    status_code=400,
                    detail=f"midi.path must be under MUSECOCO_MIDI_PATH_ALLOW_DIR ({base})",
                )
        return

    if request.midi.input_type == "base64":
        if not request.midi.base64:
            raise HTTPException(status_code=400, detail="midi.base64 is required")
        try:
            data = base64.b64decode(request.midi.base64, validate=True)
        except Exception:
            raise HTTPException(status_code=400, detail="invalid base64 in midi.base64")
        if len(data) > max_mid:
            raise HTTPException(
                status_code=400,
                detail=f"midi file too large (max {max_mid} bytes)",
            )
        return

    if request.midi.input_type == "bytes":
        if request.midi.bytes is None:
            raise HTTPException(status_code=400, detail="midi.bytes is required")
        if isinstance(request.midi.bytes, list):
            n = len(request.midi.bytes)
        elif isinstance(request.midi.bytes, str):
            n = len(base64.b64decode(request.midi.bytes, validate=False))
        else:
            raise HTTPException(status_code=400, detail="midi.bytes has invalid type")
        if n > max_mid:
            raise HTTPException(
                status_code=400,
                detail=f"midi file too large (max {max_mid} bytes)",
            )


def validate_generation_request_modes(request: GenerationRequest) -> None:
    """
    Product-facing checks before a job is queued (clear 400s instead of failed jobs).
    """
    raw = request.mode or "new"
    mode = "transformation" if raw == "refine" else raw
    if mode == "new":
        p = (request.prompt or "").strip()
        if not p:
            raise HTTPException(
                status_code=400,
                detail="mode=new requires a non-empty prompt (describe the music you want).",
            )
    if mode in ("continue", "transformation") and request.midi is None:
        raise HTTPException(
            status_code=400,
            detail="This mode requires a MIDI file (send midi as base64 recommended).",
        )

# ---- MuseCoco model state ----
model_lock = threading.Lock()
model_status: Dict[str, Any] = {
    "state": "idle",  # idle | loading | ready | error | disabled
    "error": None,
    "loaded_at": None,
}
stage1_model: Optional[Any] = None
stage1_tokenizer: Optional[Any] = None
stage2_model: Optional[Any] = None


def load_musecoco_models() -> None:
    """
    Load MuseCoco models on backend startup.
    This function is intentionally defensive: if deps are missing, it records the error
    but keeps the API process alive.
    """
    global stage1_model, stage1_tokenizer, stage2_model
    try:
        with model_lock:
            model_status["state"] = "loading"
            model_status["error"] = None

        # ---- Stage 1 (text -> attribute) ----
        import sys
        import json as _json

        # Avoid torchvision import for text-only models
        os.environ.setdefault("TRANSFORMERS_NO_TORCHVISION", "1")
        from transformers import AutoTokenizer

        backend_root = Path(__file__).resolve().parents[1]
        stage1_dir = backend_root / "musecoco" / "1-text2attribute_model"
        sys.path.insert(0, str(stage1_dir))
        from model import BertForAttributModel  # type: ignore

        stage1_name = os.environ.get("MUSECOCO_STAGE1_MODEL", "XinXuNLPer/MuseCoco_text2attribute")
        stage1_labels = os.environ.get("MUSECOCO_STAGE1_LABELS")
        labels_path = (
            Path(stage1_labels)
            if stage1_labels
            else stage1_dir / "num_labels.json"
        )

        with open(labels_path, "r", encoding="utf-8") as f:
            num_labels = _json.load(f)

        stage1_tokenizer = AutoTokenizer.from_pretrained(stage1_name)
        # Pass num_labels/tokenizer as positional args to avoid updating config.num_labels
        stage1_model = BertForAttributModel.from_pretrained(
            stage1_name, num_labels, stage1_tokenizer
        )
        stage1_model.eval()

        # ---- Stage 2 (attribute -> music) ----
        # Placeholder: wire in your fairseq model when ready.
        # Keep the import behind env flag to avoid crashing.
        if os.environ.get("MUSECOCO_ENABLE_STAGE2", "0") == "1":
            # TODO: load fairseq checkpoint here
            stage2_model = "loaded"

        with model_lock:
            model_status["state"] = "ready"
            model_status["loaded_at"] = time.time()
    except Exception as e:
        import traceback
        traceback.print_exc()
        with model_lock:
            model_status["state"] = "error"
            model_status["error"] = str(e)


def init_models_async() -> None:
    if os.environ.get("MUSECOCO_AUTOLOAD", "0") != "1":
        with model_lock:
            model_status["state"] = "disabled"
        return
    t = threading.Thread(target=load_musecoco_models, daemon=True)
    t.start()


@app.on_event("startup")
def on_startup():
    init_models_async()

@app.get("/health")
def health():
    """Liveness + quick capability flags for testers and load balancers."""
    with model_lock:
        ms = model_status.copy()
    caps = {
        "musecoco_python_configured": bool(musecoco_python()),
        "post_operation_configured": is_post_operation_root_configured(),
        "api_key_required": bool(os.environ.get("MUSECOCO_API_KEY", "").strip()),
    }
    return {"status": "ok", "model": ms, "capabilities": caps}


@app.get("/v1/model/status")
def model_state():
    with model_lock:
        return model_status.copy()


def run_cmd(cmd: List[str], cwd: Path, env: Optional[Dict[str, str]] = None) -> None:
    subprocess.run(cmd, cwd=str(cwd), env=env, check=True)


def _set_job_progress(job_id: str, progress: int, stage: str) -> None:
    """Best-effort UX for polling UIs (ignored if job entry missing)."""
    progress = max(0, min(100, int(progress)))
    with jobs_lock:
        j = jobs.get(job_id)
        if j is None:
            return
        j["status"] = "running"
        j["progress"] = progress
        j["stage"] = stage


def backend_root() -> Path:
    return Path(__file__).resolve().parents[1]


def musecoco_root() -> Path:
    return Path(os.environ.get("MUSECOCO_ROOT", backend_root() / "musecoco"))


def musecoco_python() -> str:
    return os.environ.get("MUSECOCO_PYTHON", "")


def run_stage1_predict(prompt: str, job_dir: Path) -> Path:
    mc_root = musecoco_root()
    py = musecoco_python()
    if not py:
        raise RuntimeError("MUSECOCO_PYTHON is not set")

    stage1_dir = mc_root / "1-text2attribute_model"
    data_dir = job_dir / "data"
    tmp_dir = job_dir / "tmp"
    data_dir.mkdir(parents=True, exist_ok=True)
    tmp_dir.mkdir(parents=True, exist_ok=True)

    # write predict.json for this job
    predict_path = data_dir / "predict.json"
    predict_path.write_text(
        f'[{json.dumps({"text": prompt})}]', encoding="utf-8"
    )

    # copy att_key.json for stage2_pre
    att_key_src = stage1_dir / "data" / "att_key.json"
    att_key_dst = data_dir / "att_key.json"
    att_key_dst.write_bytes(att_key_src.read_bytes())

    # run stage1 predict
    cmd = [
        py,
        "main.py",
        "--do_predict",
        "--model_name_or_path=XinXuNLPer/MuseCoco_text2attribute",
        f"--test_file={predict_path.resolve()}",
        f"--attributes={att_key_dst.resolve()}",
        f"--num_labels={(stage1_dir / 'num_labels.json').resolve()}",
        f"--output_dir={tmp_dir.resolve()}",
        "--overwrite_output_dir",
        "--report_to=none",
    ]
    env = os.environ.copy()
    env.setdefault("TRANSFORMERS_NO_TORCHVISION", "1")
    env.setdefault("WANDB_DISABLED", "true")
    env.setdefault("HF_HUB_DISABLE_TELEMETRY", "1")
    run_cmd(cmd, stage1_dir, env=env)
    return tmp_dir


def _continue_stage1_stub_dir() -> Path:
    """Packaged Stage1 outputs (predict_attributes + softmax) compatible with ``stage2_pre.py``."""
    return Path(__file__).resolve().parent / "musecoco_continue_stub"


def materialize_continue_stage1_outputs(job_dir: Path, prompt: str) -> Path:
    """
    Build ``data/{predict.json,att_key.json}`` and ``tmp/{predict_attributes,softmax}.json``
    without running Stage1 BERT — used for ``continue`` mode to save latency.

    Attributes are neutral placeholders; continuation semantics come from REMI prefix + Stage2.
    Set env ``MUSECOCO_CONTINUE_RUN_STAGE1=1`` to force full Stage1 for continue instead.
    """
    mc_root = musecoco_root()
    stage1_dir = mc_root / "1-text2attribute_model"
    data_dir = job_dir / "data"
    tmp_dir = job_dir / "tmp"
    data_dir.mkdir(parents=True, exist_ok=True)
    tmp_dir.mkdir(parents=True, exist_ok=True)

    att_key_src = stage1_dir / "data" / "att_key.json"
    if not att_key_src.is_file():
        raise RuntimeError(f"Missing {att_key_src}")
    (data_dir / "att_key.json").write_bytes(att_key_src.read_bytes())

    (data_dir / "predict.json").write_text(
        f'[{json.dumps({"text": prompt})}]', encoding="utf-8"
    )

    stub = _continue_stage1_stub_dir()
    for name in ("predict_attributes.json", "softmax_probs.json"):
        src = stub / name
        if not src.is_file():
            raise RuntimeError(
                f"Missing continue Stage1 stub {src} (copy from musecoco "
                "1-text2attribute_model/tmp/ after a predict run)."
            )
        (tmp_dir / name).write_bytes(src.read_bytes())

    return tmp_dir


def run_stage2_pre(job_dir: Path, tmp_dir: Path) -> Path:
    mc_root = musecoco_root()
    py = musecoco_python()
    if not py:
        raise RuntimeError("MUSECOCO_PYTHON is not set")

    stage1_dir = mc_root / "1-text2attribute_model"
    stage2_pre_src = stage1_dir / "stage2_pre.py"
    stage2_pre_dst = job_dir / "stage2_pre.py"
    stage2_pre_dst.write_bytes(stage2_pre_src.read_bytes())

    # place expected files in job_dir
    (job_dir / "data").mkdir(exist_ok=True)
    (job_dir / "tmp").mkdir(exist_ok=True)
    (job_dir / "tmp" / "predict_attributes.json").write_bytes(
        (tmp_dir / "predict_attributes.json").read_bytes()
    )
    (job_dir / "tmp" / "softmax_probs.json").write_bytes(
        (tmp_dir / "softmax_probs.json").read_bytes()
    )

    cmd = [py, str(stage2_pre_dst.resolve())]
    run_cmd(cmd, job_dir)
    return job_dir / "infer_test.bin"


def run_extract_continuation_remi(
    midi_path: Path, out_txt: Path, num_bars: int = 4
) -> None:
    """Last N measures -> REMIGEN2 token line for interactive_dict continuation prefix."""
    mc = musecoco_root() / "2-attribute2music_model"
    script = mc / "extract_continuation_remi.py"
    if not script.is_file():
        raise RuntimeError(f"Missing {script}")
    py = musecoco_python()
    if not py:
        raise RuntimeError("MUSECOCO_PYTHON is not set")
    cmd = [
        py,
        str(script),
        "--input",
        str(midi_path.resolve()),
        "--out",
        str(out_txt.resolve()),
        "--bars",
        str(num_bars),
    ]
    env = os.environ.copy()
    env.setdefault("PYTHONPATH", str(mc.resolve()))
    if "PYTHONPATH" in env and str(mc.resolve()) not in env["PYTHONPATH"]:
        env["PYTHONPATH"] = str(mc.resolve()) + os.pathsep + env["PYTHONPATH"]
    run_cmd(cmd, mc, env=env)


def _job_id_to_seed_mix(job_id: str) -> int:
    """32-bit mix derived from job id so each job folder gets a distinct XOR mask."""
    h = hashlib.sha256(job_id.encode("utf-8")).digest()
    return int.from_bytes(h[:4], "little") & 0x7FFFFFFF


def _musecoco_sampling_seed(request: GenerationRequest, job_id: str) -> int:
    """
    Seed for fairseq stage-2 sampling.

    - Omit ``render.seed`` (or null): new random seed every job, XOR-mixed with ``job_id``
      so different jobs never share the same effective seed by accident.
    - Set ``render.seed`` to an integer: reproducible runs (same infer_test + same seed → same MIDI).

    Many frontends send ``seed: 0`` as a placeholder. Unless ``MUSECOCO_HONEST_SEED_ZERO=1`` is set,
    ``0`` is treated as "unset" and randomized (set the env var if you truly need pinned seed 0).
    """
    r = secrets.randbelow(1 << 31)
    mixed = (r ^ _job_id_to_seed_mix(job_id)) & 0x7FFFFFFF
    if request.render is None or request.render.seed is None:
        return mixed
    s = int(request.render.seed)
    if s == 0 and os.environ.get("MUSECOCO_HONEST_SEED_ZERO", "0").strip() != "1":
        print(
            f"[job {job_id}] musecoco: render.seed=0 treated as random "
            "(frontend placeholder). Set MUSECOCO_HONEST_SEED_ZERO=1 to pin seed 0."
        )
        return mixed
    return s & 0x7FFFFFFF


def run_stage2_generate(
    infer_bin: Path,
    job_dir: Path,
    continuation_remi_path: Optional[Path] = None,
    *,
    sampling_seed: int,
    min_len: float = 512.0,
    max_len_b: int = 2560,
) -> Path:
    mc_root = musecoco_root()
    py = musecoco_python()
    if not py:
        raise RuntimeError("MUSECOCO_PYTHON is not set")

    stage2_dir = mc_root / "2-attribute2music_model"
    linear_mask_dir = stage2_dir / "linear_mask"

    data_bin = os.environ.get(
        "MUSECOCO_A2M_DATA_BIN",
        str(stage2_dir / "data" / "truncated_2560" / "data-bin"),
    )
    checkpoint = os.environ.get(
        "MUSECOCO_A2M_CHECKPOINT",
        str(stage2_dir / "checkpoints" / "linear_mask-1billion" / "checkpoint_2_280000.pt"),
    )
    save_root = job_dir / "generation"
    # Avoid reusing remi/midi from a previous run in the same folder (interactive_dict skips if .txt exists).
    if save_root.exists():
        shutil.rmtree(save_root)
    save_root.mkdir(parents=True, exist_ok=True)

    # Optional global override (debug / A/B); tier mapping in resolve_stage2_length_constraints otherwise.
    _ml = os.environ.get("MUSECOCO_A2M_MIN_LEN", "").strip()
    _mx = os.environ.get("MUSECOCO_A2M_MAX_LEN_B", "").strip()
    if _ml:
        min_len = float(_ml)
    if _mx:
        max_len_b = int(_mx)

    cmd = [
        py,
        "-u",
        "interactive_dict_v5_1billion.py",
        data_bin,
        "--task", "language_modeling_control",
        "--path", checkpoint,
        "--ctrl_command_path", str(infer_bin),
        "--save_root", str(save_root),
        "--need_num", "1",
        "--start", "0",
        "--end", "1",
        "--max-len-b", str(int(max_len_b)),
        "--min-len", str(float(min_len)),
        "--sampling",
        "--beam", "1",
        "--sampling-topk", "15",
        "--temperature", "1.0",
        "--no-repeat-ngram-size", "0",
        "--buffer-size", "1",
        "--batch-size", "1",
        "--seed",
        str(int(sampling_seed)),
    ]
    # MuseCoco fairseq 默认 command_mask_prob=0.4：每个属性 token 有 40% 被随机换成 NA，
    # 旋钮会被「冲掉」，听感上像 prompt 赢了。默认改为 0，保证 infer_test.bin 里的控制进模型。
    # 需要论文里的随机掩码时再设 MUSECOCO_COMMAND_MASK_PROB=0.4
    cmd_mask = os.environ.get("MUSECOCO_COMMAND_MASK_PROB", "0").strip()
    cmd.extend(["--command_mask_prob", cmd_mask])
    # Stage2 1B 模型占显存大；OOM 时可设 MUSECOCO_A2M_CPU=1 走 CPU（较慢但能跑完）
    if os.environ.get("MUSECOCO_A2M_CPU", "0") == "1":
        cmd.append("--cpu")
    if continuation_remi_path is not None:
        cmd.extend(
            ["--continuation_remi_path", str(continuation_remi_path.resolve())]
        )
    env = os.environ.copy()
    if "CUDA_VISIBLE_DEVICES" in os.environ:
        env["CUDA_VISIBLE_DEVICES"] = os.environ["CUDA_VISIBLE_DEVICES"]
    run_cmd(cmd, linear_mask_dir, env=env)

    # find generated midi
    midi_files = list(save_root.rglob("*.mid"))
    if not midi_files:
        raise RuntimeError("No MIDI files generated")
    return midi_files[0]

@app.post("/v1/generate")
async def generate_music(
    request: GenerationRequest,
    background_tasks: BackgroundTasks,
    _: None = Depends(verify_optional_generate_api_key),
):
    validate_untrusted_generation_request(request)
    validate_generation_request_modes(request)
    request_payload = request.dict()
    midi_payload = request_payload.get("midi")
    if isinstance(midi_payload, dict):
        if midi_payload.get("base64"):
            midi_payload["base64"] = "<base64>"
        if midi_payload.get("bytes"):
            midi_payload["bytes"] = "<bytes>"
    print("[generate] called:", request_payload)
    job_id = str(uuid.uuid4())

    with jobs_lock:
        jobs[job_id] = {"status": "queued", "progress": 0, "stage": "queued"}

    # BackgroundTasks is better for sync functions (avoid async + time.sleep)
    background_tasks.add_task(dummy_generation_process, job_id, request)

    status_path = f"/v1/jobs/{job_id}"
    out: Dict[str, Any] = {
        "status": "accepted",
        "job_id": job_id,
        "status_url": status_path,
        "message": f"Poll GET {status_path} until status is done or error.",
    }
    pub = os.environ.get("BACKEND_PUBLIC_BASE_URL", "").strip().rstrip("/")
    if pub:
        out["status_full_url"] = f"{pub}{status_path}"
    return out

@app.get("/v1/jobs/{job_id}")
async def get_job_status(job_id: str):
    with jobs_lock:
        job = jobs.get(job_id)

    if job is None:
        raise HTTPException(status_code=404, detail="job not found")

    return job


def _job_run_dir(job_id: str) -> Path:
    return (backend_root() / "musecoco" / "runs" / job_id).resolve()


def _safe_under(base: Path, p: Path) -> Path:
    base = base.resolve()
    p = p.resolve()
    if str(p).startswith(str(base) + os.sep) or p == base:
        return p
    raise HTTPException(status_code=400, detail="invalid path")


@app.get("/v1/jobs/{job_id}/midi")
async def download_job_midi(job_id: str):
    """
    Download the generated MIDI for a job.
    Frontend should use this instead of parsing server-local filesystem paths.
    """
    with jobs_lock:
        job = jobs.get(job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="job not found")
    if job.get("status") != "done":
        raise HTTPException(status_code=409, detail="job not done")

    variations = job.get("variations") or []
    if not variations or not isinstance(variations, list):
        raise HTTPException(status_code=500, detail="job has no variations")
    midi_path_str = variations[0].get("midi_path")
    if not midi_path_str:
        raise HTTPException(status_code=500, detail="job has no midi_path")

    run_dir = _job_run_dir(job_id)
    midi_path = _safe_under(run_dir, Path(midi_path_str))
    if not midi_path.exists():
        raise HTTPException(status_code=404, detail="midi not found")

    return FileResponse(
        path=str(midi_path),
        media_type="audio/midi",
        filename=f"{job_id}.mid",
    )


@app.get("/v1/jobs/{job_id}/preview")
async def download_job_preview(job_id: str):
    with jobs_lock:
        job = jobs.get(job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="job not found")
    if job.get("status") != "done":
        raise HTTPException(status_code=409, detail="job not done")
    variations = job.get("variations") or []
    preview_path_str = variations[0].get("preview_path") if variations else None
    if not preview_path_str:
        raise HTTPException(status_code=404, detail="preview not found")

    run_dir = _job_run_dir(job_id)
    preview_path = _safe_under(run_dir, Path(preview_path_str))
    if not preview_path.exists():
        raise HTTPException(status_code=404, detail="preview not found")
    return FileResponse(path=str(preview_path), media_type="application/json")

def dummy_generation_process(job_id: str, request: GenerationRequest):
    try:
        from pathlib import Path
        import json

        raw_mode = request.mode or "new"
        mode = "transformation" if raw_mode == "refine" else raw_mode
        if mode in {"continue", "transformation"} and request.midi is None:
            raise RuntimeError("midi is required for continue/transformation mode")
        # Continue mode should rely on MIDI REMI prefix; we don't require users
        # to provide new attributes/controls. Prompt falls back to a default
        # if empty.

        if os.environ.get("MUSECOCO_TEST_MODE", "0") == "1":
            with jobs_lock:
                jobs[job_id] = {
                    "status": "done",
                    "message": "connection ok",
                }
            return

        _set_job_progress(job_id, 5, "starting")

        run_dir = (backend_root() / "musecoco" / "runs" / job_id).resolve()
        run_dir.mkdir(parents=True, exist_ok=True)

        midi_input_path = resolve_midi_input(request, run_dir)
        if midi_input_path is not None:
            print(f"[job {job_id}] midi_input={midi_input_path}")

        prompt = request.prompt or ""
        if mode == "continue" and not prompt.strip():
            prompt = os.environ.get(
                "MUSECOCO_CONTINUE_DEFAULT_PROMPT", "Continue the music."
            )
        print(f"[job {job_id}] mode={mode} prompt={prompt}")

        cleanup_skipped_no_root = False
        mc_seed: Optional[int] = None
        transformation_debug: Optional[Dict[str, Any]] = None
        continue_skipped_stage1 = False
        rule_layer_stats: Optional[Dict[str, Any]] = None
        stage2_min_len: Optional[float] = None
        stage2_max_len_b: Optional[int] = None
        stage2_length_source: Optional[str] = None

        # ---------- transformation: AR-VAE morph + generation_cleanup ----------
        if mode == "transformation":
            _set_job_progress(job_id, 18, "transformation_arvae")
            if midi_input_path is None:
                raise RuntimeError("transformation mode requires midi (base64/path/bytes)")
            if not is_arvae_morph_configured():
                raise RuntimeError(
                    "AR-VAE morph is not available (missing ar-vae/scripts/arvae_morph_midi.py)."
                )
            sliders = effective_arvae_sliders_refine(request)
            midi_path = run_dir / "transformation_output.mid"
            ck = _cleanup_hard_subprocess_kwargs(effective_cleanup_hard(request))
            transformation_debug = run_transformation_pipeline(
                midi_input_path.resolve(),
                midi_path.resolve(),
                sliders,
                cleanup_kwargs=ck,
                disable_cleanup=transformation_disable_cleanup_flag(),
            )
            cinfo = (transformation_debug or {}).get("cleanup") or {}
            if cinfo.get("skipped") and "POST_OPERATION_ROOT" in str(
                cinfo.get("reason", "")
            ):
                cleanup_skipped_no_root = True
            print(f"[job {job_id}] transformation AR-VAE + cleanup: {cinfo}")
            _set_job_progress(job_id, 72, "transformation_done")
            final_attrs: Dict[str, Any] = {}
        else:
            # ---------- new / continue: MuseCoco then generation_cleanup ----------
            predicted_attrs: Dict[str, Any] = {}
            final_attrs = legacy_merge_final_attrs(request, predicted_attrs)
            print("Final attributes:", final_attrs)

            continuation_txt: Optional[Path] = None
            if mode == "continue":
                if midi_input_path is None:
                    raise RuntimeError("continue mode requires midi (base64/path/bytes)")
                _set_job_progress(job_id, 12, "continuation_prefix")
                continuation_txt = run_dir / "continuation_remi.txt"
                nbars = int(os.environ.get("MUSECOCO_CONTINUE_BARS", "4"))
                run_extract_continuation_remi(
                    midi_input_path.resolve(), continuation_txt, nbars
                )

            # Continue: skip Stage1 BERT (neutral stub attrs); continuation is carried by REMI prefix.
            # Set MUSECOCO_CONTINUE_RUN_STAGE1=1 to run full text-to-attribute for continue.
            if mode == "continue" and os.environ.get(
                "MUSECOCO_CONTINUE_RUN_STAGE1", "0"
            ).strip() != "1":
                _set_job_progress(job_id, 28, "prepare_infer_stub")
                tmp_dir = materialize_continue_stage1_outputs(run_dir, prompt)
                continue_skipped_stage1 = True
                print(
                    f"[job {job_id}] continue: skipping Stage1 BERT (stub infer attrs); "
                    "set MUSECOCO_CONTINUE_RUN_STAGE1=1 for full text-to-attribute."
                )
            else:
                _set_job_progress(job_id, 12, "text_to_attributes")
                tmp_dir = run_stage1_predict(prompt, run_dir)

            _set_job_progress(job_id, 38, "prepare_generation")
            infer_bin = run_stage2_pre(run_dir, tmp_dir).resolve()
            from utils.musecoco_infer_overrides import apply_generation_overrides_infer_bin

            gen_eff = effective_musecoco_generation(request)
            if (
                request.generation is not None
                and gen_eff is None
                and (request.mode or "new") == "continue"
            ):
                print(
                    f"[job {job_id}] WARN: generation controls are NOT applied to infer_test.bin "
                    "in continue mode (only REMI prefix + stub Stage1); UI sliders won't affect Stage2 attrs."
                )
            apply_generation_overrides_infer_bin(infer_bin.resolve(), gen_eff)
            mc_seed = _musecoco_sampling_seed(request, job_id)
            stage2_min_len, stage2_max_len_b, stage2_length_source = (
                resolve_stage2_length_constraints(request)
            )
            print(
                f"[job {job_id}] musecoco stage2 infer_bin={infer_bin} sampling_seed={mc_seed} "
                f"min_len={stage2_min_len} max_len_b={stage2_max_len_b} ({stage2_length_source})"
            )
            _set_job_progress(job_id, 52, "neural_generate")
            midi_path = run_stage2_generate(
                infer_bin,
                run_dir,
                continuation_txt,
                sampling_seed=mc_seed,
                min_len=float(stage2_min_len),
                max_len_b=int(stage2_max_len_b),
            )

            # Product UX: avoid frustrating "drum-only" outputs.
            # If MuseCoco generates MIDI with zero pitched notes in non-drum parts,
            # automatically resample with a fresh seed a few times.
            max_drum_only_tries = int(
                os.environ.get("BACKEND_DRUM_ONLY_REGEN_MAX_TRIES", "2").strip()
            )
            attempt = 0
            while attempt <= max_drum_only_tries:
                try:
                    pitched_notes = _count_non_drum_pitched_notes(midi_path)
                except Exception:
                    pitched_notes = 1  # don't block generation on analysis failure
                if pitched_notes > 0:
                    break

                attempt += 1
                if attempt > max_drum_only_tries:
                    break

                mc_seed = _musecoco_sampling_seed(
                    request, f"{job_id}_drum_retry{attempt}"
                )
                print(
                    f"[job {job_id}] drum-only detected (pitched_notes=0); retry "
                    f"{attempt}/{max_drum_only_tries} with seed={mc_seed}"
                )
                midi_path = run_stage2_generate(
                    infer_bin,
                    run_dir,
                    continuation_txt,
                    sampling_seed=mc_seed,
                    min_len=float(stage2_min_len),
                    max_len_b=int(stage2_max_len_b),
                )

            if not skip_cleanup_after_musecoco():
                if is_post_operation_root_configured():
                    cleaned = run_dir / "musecoco_cleaned.mid"
                    run_generation_cleanup(
                        midi_path.resolve(),
                        cleaned.resolve(),
                        **_cleanup_hard_subprocess_kwargs(
                            effective_cleanup_hard(request)
                        ),
                    )
                    midi_path = cleaned
                else:
                    cleanup_skipped_no_root = True
                    print(
                        f"[job {job_id}] WARN: POST_OPERATION_ROOT unset; "
                        "skipping generation_cleanup (returning raw MuseCoco MIDI)."
                    )

            # Phase-2 deterministic rule layer (key, density, pitch range). Opt-in: BACKEND_RULE_LAYER=1.
            if os.environ.get("BACKEND_RULE_LAYER", "0").strip() == "1":
                _set_job_progress(job_id, 74, "rule_layer")
                try:
                    from post_operation.rules.run import apply_rule_layer

                    canon = map_request_to_canonical_control(request)
                    key_raw = (
                        request.generation.key
                        if request.generation is not None
                        else None
                    )
                    dens = canon.get("density")
                    prm = canon.get("pitch_range_midi")
                    pl_m = None
                    ph_m = None
                    if isinstance(prm, dict):
                        pl_m = prm.get("min")
                        ph_m = prm.get("max")
                    ruled_mid = run_dir / "rule_layer.mid"
                    rule_layer_stats = apply_rule_layer(
                        str(midi_path.resolve()),
                        str(ruled_mid.resolve()),
                        key_str=key_raw,
                        density_01=float(dens) if dens is not None else None,
                        pitch_low_midi=pl_m,
                        pitch_high_midi=ph_m,
                    )
                    midi_path = ruled_mid
                    print(f"[job {job_id}] rule_layer applied -> {ruled_mid}")
                except Exception as _e:
                    from post_operation.rules.run import rule_layer_failure

                    rule_layer_stats = rule_layer_failure(
                        str(_e), str(midi_path.resolve())
                    )
                    print(f"[job {job_id}] rule_layer skipped: {_e}")

        _set_job_progress(job_id, 80, "finalizing")

        preview_path = run_dir / "take_A.preview.json"
        context = request.context or GenerationContext(
            bpm=120, time_signature="4/4", start_bar=0, length_bars=8
        )
        preview_payload = build_preview_payload(
            midi_path.resolve(), default_bpm=context.bpm
        )
        preview_path.write_text(
            json.dumps(preview_payload, ensure_ascii=False),
            encoding="utf-8",
        )
        _set_job_progress(job_id, 92, "preview_ready")

        hard_controls = None
        if request.controls is not None:
            hard_controls = request.controls.hard
        elif request.attributes is not None:
            hard_controls = request.attributes
        else:
            hard_controls = ControlHard(density=0.5, tempo=0.5, bass_energy=0.5)

        def _model_dump(obj, exclude_none: bool = True):
            if obj is None:
                return None
            if hasattr(obj, "model_dump"):
                return (
                    obj.model_dump(exclude_none=True)
                    if exclude_none
                    else obj.model_dump()
                )
            return (
                obj.dict(exclude_none=True) if exclude_none else obj.dict()
            )

        used_musecoco = mode in ("new", "continue")
        used_transformation = mode == "transformation"
        cleanup_info = (transformation_debug or {}).get("cleanup") if used_transformation else None
        transformation_applied_cleanup = bool(
            used_transformation
            and isinstance(cleanup_info, dict)
            and cleanup_info.get("applied") is True
        )
        used_post_cleanup = (
            used_musecoco
            and not skip_cleanup_after_musecoco()
            and is_post_operation_root_configured()
        ) or transformation_applied_cleanup
        used_arvae = used_transformation
        generation_applied = (
            effective_musecoco_generation(request) if used_musecoco else None
        )
        arvae_applied = (
            effective_arvae_controls_refine(request) if used_transformation else None
        )
        cleanup_ctrl = effective_cleanup_hard(request)
        cleanup_hard_echo = (
            _model_dump(cleanup_ctrl, exclude_none=True) if cleanup_ctrl else None
        )

        # ---------- Return result ----------
        midi_url = f"/v1/jobs/{job_id}/midi"
        preview_url = f"/v1/jobs/{job_id}/preview"
        public_base = os.environ.get("BACKEND_PUBLIC_BASE_URL", "").strip().rstrip("/")
        midi_download_url = f"{public_base}{midi_url}" if public_base else None
        preview_download_url = f"{public_base}{preview_url}" if public_base else None

        result = {
            "status": "done",
            "completed": True,
            "job_id": job_id,
            "midi_url": midi_url,
            "preview_url": preview_url,
            "midi_download_url": midi_download_url,
            "preview_download_url": preview_download_url,
            "mode": mode,
            "midi_path": str(midi_path.resolve()),
            "used_musecoco": used_musecoco,
            "musecoco_stage1_skipped": bool(continue_skipped_stage1),
            "used_arvae": used_arvae,
            "used_post_cleanup": used_post_cleanup,
            "used_transformation": used_transformation,
            "used_post_operation_refine": used_transformation,
            "generation": _model_dump(generation_applied, exclude_none=True),
            "cleanup_hard": cleanup_hard_echo,
            "arvae": _model_dump(arvae_applied, exclude_none=False)
            if used_arvae
            else None,
            "generation_ignored": used_transformation and request.generation is not None,
            "generation_overrides_ignored": mode == "continue" and request.generation is not None,
            "cleanup_ignored": False,
            "arvae_ignored": mode in ("new", "continue") and request.arvae is not None,
            "preview_note_count": preview_payload.get("note_count", 0),
            "variations": [
                {
                    "name": "A",
                    "midi_path": str(midi_path.resolve()),
                    "preview_path": str(preview_path.resolve()),
                    "midi_url": midi_url,
                    "preview_url": preview_url,
                    "midi_download_url": midi_download_url,
                    "preview_download_url": preview_download_url,
                }
            ],
            "used_controls": {
                "density": hard_controls.density,
                "tempo": hard_controls.tempo,
                "bass_energy": hard_controls.bass_energy,
                "rhy_complexity": getattr(hard_controls, "rhy_complexity", None),
                "pitch_range": getattr(hard_controls, "pitch_range", None),
                "note_density": getattr(hard_controls, "note_density", None),
                "contour": getattr(hard_controls, "contour", None),
            },
            "final_attrs": final_attrs,
            "musecoco_stage2_length": (
                {
                    "min_len": stage2_min_len,
                    "max_len_b": stage2_max_len_b,
                    "source": stage2_length_source,
                }
                if used_musecoco
                else None
            ),
            # Phase-1 canonical control trace (thesis / evaluation); safe to ignore by clients.
            "canonical_control": map_request_to_canonical_control(request),
            "rule_layer": rule_layer_stats,
            "transformation_debug": transformation_debug if used_transformation else None,
            "refine_debug": transformation_debug if used_transformation else None,
            "seed": mc_seed
            if mc_seed is not None
            else (request.render.seed if request.render else None),
        }
        if cleanup_skipped_no_root:
            result["post_operation_notice"] = (
                "generation_cleanup skipped: set POST_OPERATION_ROOT to enable post-processing"
            )
        mode_label = {
            "new": "new piece",
            "continue": "continue",
            "transformation": "transformation",
        }.get(mode, mode)
        result["user_message"] = (
            f"Ready — {mode_label}. Use midi_url / preview_url to download."
        )
        enrich_completed_job(result)

        with jobs_lock:
            jobs[job_id] = result

    except Exception as e:
        import traceback

        traceback.print_exc()
        err = job_failure_dict(job_id, e)
        enrich_failed_job(err)
        with jobs_lock:
            jobs[job_id] = err
        print(f"[job {job_id}] ERROR: {err.get('error_code')}: {e}")
    finally:
        release_gpu_memory_best_effort()

if __name__ == "__main__":
    import uvicorn
    uvicorn.run("utils.server:app", host="127.0.0.1", port=8000, reload=True)


def resolve_midi_input(request: GenerationRequest, job_dir: Path) -> Optional[Path]:
    if request.midi is None:
        return None

    max_mid = _max_midi_bytes()
    input_type = request.midi.input_type
    if input_type == "path":
        if os.environ.get("MUSECOCO_ALLOW_MIDI_PATH", "0").strip() != "1":
            raise RuntimeError(
                "midi.input_type=path is disabled (set MUSECOCO_ALLOW_MIDI_PATH=1 for trusted use)."
            )
        if not request.midi.path:
            raise RuntimeError("midi.path is required when input_type=path")
        allow = os.environ.get("MUSECOCO_MIDI_PATH_ALLOW_DIR", "").strip()
        p = Path(request.midi.path).expanduser().resolve()
        if allow:
            base = Path(allow).expanduser().resolve()
            if str(p) != str(base) and not str(p).startswith(str(base) + os.sep):
                raise RuntimeError(
                    f"midi.path must be under MUSECOCO_MIDI_PATH_ALLOW_DIR ({base})"
                )
        if not p.is_file():
            raise RuntimeError(
                f"midi file not found on the API server: {p}. "
                "If the MIDI is on another computer (e.g. plugin sends a local Mac path but the "
                "backend runs on Linux), use midi.input_type=\"base64\" with the file bytes instead "
                "of input_type=\"path\"."
            )
        return p

    if input_type in {"base64", "bytes"}:
        data = None
        if input_type == "base64":
            if not request.midi.base64:
                raise RuntimeError("midi.base64 is required when input_type=base64")
            data = base64.b64decode(request.midi.base64)
        else:
            if request.midi.bytes is None:
                raise RuntimeError("midi.bytes is required when input_type=bytes")
            if isinstance(request.midi.bytes, list):
                data = bytes(request.midi.bytes)
            elif isinstance(request.midi.bytes, str):
                data = base64.b64decode(request.midi.bytes)
            else:
                raise RuntimeError("midi.bytes must be list[int] or base64 string")

        if len(data) > max_mid:
            raise RuntimeError(f"midi file too large (max {max_mid} bytes)")

        midi_path = job_dir / "input.mid"
        midi_path.write_bytes(data)
        return midi_path

    raise RuntimeError(f"Unsupported midi.input_type: {input_type}")


def _is_drum_part_music21(part: Any) -> bool:
    """Heuristic used to detect percussion parts for drum-only regeneration."""
    part_name = f"{getattr(part, 'partName', '') or ''} {getattr(part, 'id', '') or ''}".lower()
    if "drum" in part_name or "perc" in part_name:
        return True

    try:
        import music21
        from music21 import instrument

        for inst in part.recurse().getElementsByClass(instrument.Instrument):
            # Channel 10 is often used for drums in MIDI.
            if isinstance(inst, music21.instrument.UnpitchedPercussion):
                return True
            if getattr(inst, "midiChannel", None) == 9:
                return True
    except Exception:
        # If parsing fails, be conservative and treat it as non-drum.
        return False

    return False


def _count_non_drum_pitched_notes(midi_path: Path) -> int:
    """
    Count Note/Chord events in non-drum parts (pitched audio content).
    Used for an auto-resample guard when the model outputs drum-only MIDI.
    """
    import music21
    from music21 import chord, note

    score = music21.converter.parse(str(midi_path.resolve()))
    count = 0
    for part in score.parts:
        if _is_drum_part_music21(part):
            continue
        for el in part.recurse():
            if isinstance(el, (note.Note, chord.Chord)):
                count += 1
    return count