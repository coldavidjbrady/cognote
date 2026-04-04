#!/bin/zsh

set -euo pipefail

ROOT_DIR="$(cd "$(dirname "$0")/.." && pwd)"
VENV_PYTHON="${ROOT_DIR}/.venv/bin/python"
export PYINSTALLER_CONFIG_DIR="${ROOT_DIR}/.pyinstaller"

if [[ ! -x "${VENV_PYTHON}" ]]; then
  echo "Expected virtualenv python at ${VENV_PYTHON}" >&2
  exit 1
fi

cd "${ROOT_DIR}/frontend"
npm run build

cd "${ROOT_DIR}"
"${VENV_PYTHON}" -m PyInstaller --noconfirm cognote.spec

echo ""
echo "Build complete:"
echo "  ${ROOT_DIR}/dist/Cognote.app"
