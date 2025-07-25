#!/bin/bash
# This file is @generated by <https://github.com/liblaf/copier-python>.
# DO NOT EDIT!
set -o errexit
set -o nounset
set -o pipefail

function replace-mirrors() {
  local file="$1"
  if [[ -f $file ]]; then
    sd 'https://(\S+)/simple' 'https://pypi.org/simple' "$file"
    sd 'https://(\S+)/packages' 'https://files.pythonhosted.org/packages' "$file"
  fi
}

if [[ -f "pixi.lock" ]]; then
  pixi install
  replace-mirrors 'pixi.lock'
fi

if [[ -f "uv.lock" ]]; then
  uv sync --all-extras --all-groups
  replace-mirrors 'uv.lock'
fi
