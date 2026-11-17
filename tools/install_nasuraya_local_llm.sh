#!/usr/bin/env bash
# One-time, local-only inference bootstrap for the Ubuntu VPS.
# This deliberately does NOT import credentials, modify Awake, or expose a port.
set -Eeuo pipefail
umask 027

MODEL='qwen3:4b'
URL='https://ollama.com/install.sh'

fail() { printf 'BLOCKED: %s\n' "$*" >&2; exit 1; }
[ "$(id -u)" -eq 0 ] || fail 'run as root in the VPS terminal'
[ "$(uname -m)" = 'x86_64' ] || fail 'this installer expects x86_64 Linux'
[ -d /opt/zohraya/.git ] || fail 'missing canonical /opt/zohraya repository'
for executable in curl python3 awk df systemctl sha256sum; do
  command -v "$executable" >/dev/null 2>&1 || fail "missing prerequisite: $executable"
done

memory_kib=$(awk '/^MemTotal:/ {print $2}' /proc/meminfo)
[ "${memory_kib:-0}" -ge 10485760 ] || fail 'need at least 10 GiB RAM'
disk_kib=$(df -Pk / | awk 'NR==2 {print $4}')
[ "${disk_kib:-0}" -ge 10485760 ] || fail 'need at least 10 GiB free disk'

if ! command -v ollama >/dev/null 2>&1 && ! command -v zstd >/dev/null 2>&1; then
  command -v apt-get >/dev/null 2>&1 || fail 'zstd needed for Ollama package'
  DEBIAN_FRONTEND=noninteractive apt-get update -qq
  DEBIAN_FRONTEND=noninteractive apt-get install -y --no-install-recommends zstd
fi

if ! command -v ollama >/dev/null 2>&1; then
  tmpdir=$(mktemp -d)
  trap 'rm -rf "$tmpdir"' EXIT
  curl --proto '=https' --tlsv1.2 --fail --show-error --silent --location \
    --connect-timeout 15 --retry 2 --max-time 180 \
    "$URL" -o "$tmpdir/install-ollama.sh"
  sh -n "$tmpdir/install-ollama.sh" || fail 'vendor installer syntax invalid'
  printf 'HTTPS-fetched vendor installer SHA256 (unpinned, audit only): '
  sha256sum "$tmpdir/install-ollama.sh"
  # Installer is from the official Ollama distribution. Do not substitute URLs.
  sh "$tmpdir/install-ollama.sh"
fi

command -v ollama >/dev/null 2>&1 || fail 'Ollama binary still absent'
systemctl cat ollama.service >/dev/null || fail 'Ollama systemd unit missing'

# Config only affects Ollama, not Nasuraya Bridge, Awake, or stored memory.
install -d -o root -g root -m 0755 /etc/systemd/system/ollama.service.d
config='/etc/systemd/system/ollama.service.d/zz-nasuraya-local.conf'
tmpconfig=$(mktemp /etc/systemd/system/ollama.service.d/.nasuraya-XXXXXX)
trap 'rm -f "$tmpconfig"; if [ -n "${tmpdir:-}" ]; then rm -rf "$tmpdir"; fi' EXIT
cat > "$tmpconfig" <<'CONF'
[Service]
Environment="OLLAMA_HOST=127.0.0.1:11434"
Environment="OLLAMA_NO_CLOUD=1"
Environment="OLLAMA_NUM_PARALLEL=1"
Environment="OLLAMA_MAX_LOADED_MODELS=1"
Environment="OLLAMA_CONTEXT_LENGTH=2048"
MemoryMax=12G
CONF
chmod 0644 "$tmpconfig"
mv -f "$tmpconfig" "$config"
systemctl daemon-reload
systemctl enable --now ollama.service
systemctl restart ollama.service

ready='false'
for attempt in $(seq 1 30); do
  if curl --fail --silent --max-time 3 http://127.0.0.1:11434/api/version >/dev/null; then
    ready='true'
    break
  fi
  sleep 2
done
[ "$ready" = 'true' ] || fail 'Ollama service failed to answer on localhost'

# Pull weights while international Internet is available; model then runs offline.
ollama pull "$MODEL"
ollama show "$MODEL" >/dev/null || fail 'downloaded model unavailable'

python3 - "$MODEL" <<'PY'
import json, sys, urllib.request
model = sys.argv[1]
body = json.dumps({
    'model': model,
    'prompt': 'Reply with the word READY.',
    'stream': False,
    'think': False,
    'options': {'num_ctx': 2048, 'num_predict': 40},
}).encode('utf-8')
req = urllib.request.Request('http://127.0.0.1:11434/api/generate',
                             data=body, headers={'Content-Type': 'application/json'})
with urllib.request.urlopen(req, timeout=240) as response:
    result = json.load(response)
if not result.get('done') or not (result.get('response') or '').strip():
    raise SystemExit('BLOCKED: local inference smoke test produced no answer')
print(json.dumps({'status': 'LOCAL_INFERENCE_OK', 'model': model,
                  'answer_length': len(result['response']),
                  'done': result['done'], 'cloud': 'disabled',
                  'listener': '127.0.0.1:11434'}, sort_keys=True))
PY
printf 'SAFE: existing /var/lib/nasuraya memory and workloads were not changed.\n'
