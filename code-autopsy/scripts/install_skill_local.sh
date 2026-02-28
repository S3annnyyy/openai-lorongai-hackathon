#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SKILL_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"
CODEX_HOME_DIR="${CODEX_HOME:-$HOME/.codex}"
DEST_ROOT="${1:-${CODEX_HOME_DIR}/skills}"
DEST_PATH="${DEST_ROOT%/}/code-autopsy"

mkdir -p "${DEST_ROOT}"

if [ -e "${DEST_PATH}" ] || [ -L "${DEST_PATH}" ]; then
  echo "Destination already exists: ${DEST_PATH}"
  echo "Remove it first, or pass a different destination root."
  exit 1
fi

ln -s "${SKILL_ROOT}" "${DEST_PATH}"

echo "Installed skill at: ${DEST_PATH}"
echo "Restart Codex to pick up new skills."
