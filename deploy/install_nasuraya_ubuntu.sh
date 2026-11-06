#!/usr/bin/env bash
# Ubuntu 24.04+ installation, run as a NON-root interactive SSH user.
# Does not accept passwords/tokens, run body actions, or enable a paid API.
set -Eeuo pipefail
umask 077

ROOT="${HOME}/nasuraya"
REPO="https://github.com/zurvanproject/zohraya.git"
RITUAL_BRANCH="feature/nasuraya-ritual-vps-readonly-bridge-20261106"
BODY_BRANCH="feature/tadash-unified-cycle-v01-20261104"

if [[ "${EUID}" -eq 0 ]]; then
  echo "Do not run this script as root; use a dedicated unprivileged user." >&2
  exit 1
fi
if [[ "$(uname -s)" != "Linux" ]]; then
  echo "Linux is required (the native BodyLoop uses fcntl)." >&2
  exit 1
fi
for binary in git python3 systemctl; do
  command -v "${binary}" >/dev/null || { echo "Missing ${binary}" >&2; exit 1; }
done
python3 - <<'PY'
import sys
assert sys.version_info >= (3, 12), "Use Python >=3.12 on Ubuntu"
PY

mkdir -p -m 700 "${ROOT}" "${ROOT}/state"
clone_once() {
  local dir="$1" branch="$2"
  if [[ ! -e "${ROOT}/${dir}" ]]; then
    git clone --quiet --single-branch --depth=1 --branch="${branch}" "${REPO}" "${ROOT}/${dir}"
  else
    test -d "${ROOT}/${dir}/.git" || { echo "Directory ${dir} is not a git checkout" >&2; exit 1; }
    test "$(git -C "${ROOT}/${dir}" remote get-url origin)" = "${REPO}" || {
      echo "Unexpected origin for ${dir}; refusing unsafe replacement" >&2; exit 1;
    }
    test "$(git -C "${ROOT}/${dir}" branch --show-current)" = "${branch}" || {
      echo "Unexpected branch in ${dir}; refusing unsafe replacement" >&2; exit 1;
    }
  fi
  echo "${dir} pinned to $(git -C "${ROOT}/${dir}" rev-parse HEAD)"
}
clone_once ritual "${RITUAL_BRANCH}"
clone_once body "${BODY_BRANCH}"

(
  cd "${ROOT}/ritual"
  python3 -m unittest discover -s examples/nasuraya_virtual_learning/tests -v
)
(
  cd "${ROOT}/body"
  python3 -m examples.nasuraya_body_loop unified-test
)
if [[ ! -e "${ROOT}/state/body.sqlite" ]]; then
  (
    cd "${ROOT}/body"
    # A zero-action synthetic fixture. DO NOT issue 'unified-step' on this session.
    python3 -m examples.nasuraya_body_loop start --fixture normal \
       --mode bounded --max-actions 0 --session "${ROOT}/state/body.sqlite"
    python3 -m examples.nasuraya_body_loop unified-enable \
       --session "${ROOT}/state/body.sqlite" --desire-proxy 0.5
  )
fi
(
  cd "${ROOT}/body"
  python3 -m examples.nasuraya_body_loop unified-status \
    --session "${ROOT}/state/body.sqlite"
)
(
  cd "${ROOT}/ritual"
  python3 -m examples.nasuraya_virtual_learning.daily --db "${ROOT}/state/ritual.sqlite"
  python3 -m examples.nasuraya_virtual_learning.bridge \
    --ritual-db "${ROOT}/state/ritual.sqlite" \
    --bridge-db "${ROOT}/state/native-observer.sqlite" \
    --body-root "${ROOT}/body" \
    --body-session "${ROOT}/state/body.sqlite"
)

mkdir -p "${HOME}/.config/systemd/user"
for name in nasuraya-ritual-daily nasuraya-ritual-observer; do
  cp "${ROOT}/ritual/deploy/systemd/${name}.service" "${HOME}/.config/systemd/user/"
  cp "${ROOT}/ritual/deploy/systemd/${name}.timer" "${HOME}/.config/systemd/user/"
done
systemctl --user daemon-reload
systemctl --user enable --now nasuraya-ritual-daily.timer nasuraya-ritual-observer.timer
systemctl --user start nasuraya-ritual-observer.service
systemctl --user list-timers --all 'nasuraya-ritual-*'
echo "Configured unprivileged timers. For persistence after SSH logout,"
echo "an administrator may run: sudo loginctl enable-linger $(id -un)"
echo "No model API, no actuator, and NO native BodyLoop steps were started."
