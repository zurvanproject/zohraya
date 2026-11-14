#!/usr/bin/env bash
# Manual preparation only. Does not alter Awake, GitHub bridge, or systemd timers.
set -Eeuo pipefail
umask 077
(( EUID == 0 )) || { echo 'Run as root on Ubuntu 24.04' >&2; exit 1; }
. /etc/os-release
[[ "$ID" == ubuntu ]] || { echo 'Ubuntu required' >&2; exit 1; }
ROOT=/opt/nasuraya-local-llm
MODEL_DIR=/var/lib/nasuraya/models
MODEL="$MODEL_DIR/Qwen3-1.7B-Q8_0.gguf"
SOURCE=https://huggingface.co/Qwen/Qwen3-1.7B-GGUF/resolve/main/Qwen3-1.7B-Q8_0.gguf
mkdir -p "$ROOT" "$MODEL_DIR"
apt-get update
DEBIAN_FRONTEND=noninteractive apt-get install -y --no-install-recommends \
  build-essential cmake git curl ca-certificates libcurl4-openssl-dev
if [[ ! -d "$ROOT/llama.cpp/.git" ]]; then
  git clone --depth=1 https://github.com/ggml-org/llama.cpp.git "$ROOT/llama.cpp"
fi
cmake -S "$ROOT/llama.cpp" -B "$ROOT/llama.cpp/build" \
  -DGGML_NATIVE=OFF -DCMAKE_BUILD_TYPE=Release
cmake --build "$ROOT/llama.cpp/build" --config Release -j 4 --target llama-cli
if [[ ! -s "$MODEL" ]]; then
  curl -fL --retry 3 --connect-timeout 20 -C - -o "$MODEL.download" "$SOURCE"
  mv "$MODEL.download" "$MODEL"
fi
chmod 0644 "$MODEL"
BIN="$ROOT/llama.cpp/build/bin/llama-cli"
[[ -x "$BIN" && -s "$MODEL" ]]
{
  printf 'model_sha256='; sha256sum "$MODEL" | awk '{print $1}'
  printf 'llama_cpp_commit='; git -C "$ROOT/llama.cpp" rev-parse HEAD
  printf 'model_file=%s\n' "$MODEL"
  date -u +'%Y-%m-%dT%H:%M:%SZ'
} > "$ROOT/install-manifest.txt"
set +e
timeout 240 "$BIN" --model "$MODEL" --threads 4 --ctx-size 2048 \
  --n-predict 80 --prompt 'Reply in one sentence: why must backups be test-restored?' \
  > "$ROOT/smoke-test.log" 2>&1
RESULT=$?
set -e
printf 'SMOKE_TEST_EXIT=%s\n' "$RESULT"
(( RESULT == 0 )) || { echo 'Model test FAILED; do not enable timer.' >&2; exit "$RESULT"; }
echo 'LOCAL_MODEL_SMOKE_TEST=PASS;NO_AUTOMATIC_RUNTIME_ENABLED'
