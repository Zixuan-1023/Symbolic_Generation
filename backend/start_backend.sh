# get current backend path
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"

# cd to current path
cd "$SCRIPT_DIR" || exit 1

# for debug usage
mkdir -p "$SCRIPT_DIR/logs"

# don't create more than 1 backend
if lsof -i :8000 >/dev/null 2>&1; then
    echo "Backend already running on port 8000"
    exit 0
fi

# pick python: prefer explicit BACKEND_PYTHON, then MUSECOCO_PYTHON, then active venv, then conda, then .venv
PYTHON_BIN="${BACKEND_PYTHON:-}"
if [ -z "$PYTHON_BIN" ] && [ -n "$MUSECOCO_PYTHON" ]; then
    PYTHON_BIN="$MUSECOCO_PYTHON"
fi
if [ -z "$PYTHON_BIN" ] && [ -n "$VIRTUAL_ENV" ]; then
    PYTHON_BIN="$VIRTUAL_ENV/bin/python"
fi
if [ -z "$PYTHON_BIN" ] && [ -n "$CONDA_PREFIX" ]; then
    PYTHON_BIN="$CONDA_PREFIX/bin/python"
fi
if [ -z "$PYTHON_BIN" ]; then
    PYTHON_BIN="$SCRIPT_DIR/.venv/bin/python"
fi

# fail fast if uvicorn isn't installed in the selected python
if ! "$PYTHON_BIN" -c "import uvicorn" >/dev/null 2>&1; then
    echo "ERROR: uvicorn is not installed for: $PYTHON_BIN"
    echo "Fix: install deps in that environment, e.g.:"
    echo "  $PYTHON_BIN -m pip install -U fastapi uvicorn"
    exit 1
fi

# Subprocess jobs (MuseCoco pipeline) read MUSECOCO_PYTHON from the environment
if [ -z "${MUSECOCO_PYTHON:-}" ]; then
    export MUSECOCO_PYTHON="$PYTHON_BIN"
fi

# ---- post_operation（cleanup 的源码目录；transformation 另需 Backend/ar-vae）----
# 后端在服务器本机调用: python -m generation_cleanup；AR-VAE: ar-vae/scripts/arvae_morph_midi.py
# 处理完的 .mid 仍写在 musecoco/runs/<job_id>/ 下，通过 GET /v1/jobs/<id>/midi 给前端下载。
# 解析顺序: POST_OPERATION_ROOT；否则若存在目录 $SCRIPT_DIR/post_operation 则用它（可把论文工程软链到这里）。
# new/continue 若两者都无: 跳过 cleanup 并返回原始 MIDI；transformation 无 POST_OPERATION_ROOT 时仍返回 AR-VAE 输出。
# 仅测 MuseCoco: POST_OP_SKIP_CLEANUP_AFTER_MUSECOCO=1
# 例: export POST_OPERATION_ROOT="$HOME/your-repo/post_operation"
# Optional: POST_OPERATION_PYTHON, ARVAE_PYTHON, POST_OP_CLEANUP_*, POST_TRANSFORMATION_DISABLE_CLEANUP
# AR-VAE 默认权重: ar-vae/models/folk_MeasureVAE_r_0_b_0.001_g_1.0_d_10.0_all_/folk_MeasureVAE_….pt
# 或: export ARVAE_CKPT="/path/to/your.pt"
# 训练日志若用 tee/nohup 重定向，文件在「执行训练时的当前目录」；常见为 ar-vae/train_folk_ar4.log（勿在 Backend 根目录 tail 同名文件）。
if [ -n "${POST_OPERATION_ROOT:-}" ]; then
    export POST_OPERATION_ROOT
    echo "POST_OPERATION_ROOT=$POST_OPERATION_ROOT"
fi

# Frontend absolute download URLs (optional): e.g. http://192.168.x.x:8000 or http://[ipv6]:8000
# export BACKEND_PUBLIC_BASE_URL="http://127.0.0.1:8000"

# ---- Untrusted clients (browser / remote plugin): do NOT let them pick server file paths ----
# Default: midi.input_type=path is REJECTED (403). Plugins must send midi as base64/bytes.
# Local automation only: export MUSECOCO_ALLOW_MIDI_PATH=1
# Optional: restrict paths to one tree: export MUSECOCO_MIDI_PATH_ALLOW_DIR="$HOME/safe_midi_inbox"
# Optional: require shared secret on POST /v1/generate: export MUSECOCO_API_KEY="..."
#   Client sends header: X-MuseCoco-Key: ...   or   Authorization: Bearer ...
# Optional limits: MUSECOCO_MAX_PROMPT_CHARS (default 8000), MUSECOCO_MAX_MIDI_BYTES (default 8MiB)

echo "Backend (uvicorn) Python: $PYTHON_BIN"

# avoid importing torchvision in transformers (not needed for text models)
export TRANSFORMERS_NO_TORCHVISION=1

# Post–MuseCoco deterministic rule layer (key / density / pitch range); see post_operation/rules/.
# Default on for user tests. Disable for raw MuseCoco: BACKEND_RULE_LAYER=0 bash start_backend.sh
export BACKEND_RULE_LAYER="${BACKEND_RULE_LAYER:-1}"

# Stage2: default command_mask_prob=0 (no random NA on control tokens). Paper-style random
# masking: MUSECOCO_COMMAND_MASK_PROB=0.4

# allow overriding bind host/port for server deployment
BACKEND_HOST="${BACKEND_HOST:-127.0.0.1}"
BACKEND_PORT="${BACKEND_PORT:-8000}"

# start the backend
nohup "$PYTHON_BIN" -m uvicorn utils.server:app \
    --host "$BACKEND_HOST" \
    --port "$BACKEND_PORT" \
    > "$SCRIPT_DIR/logs/backend.out" 2>&1 &

echo "Backend started"
exit 0
