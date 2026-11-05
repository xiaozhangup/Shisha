#!/bin/sh
set -eu

CDPATH= cd -- "$(dirname -- "$0")"

if [ ! -x .venv/bin/python ]; then
    printf '正在创建 Python 虚拟环境…\n'
    python3 -m venv .venv
fi

if [ ! -f .venv/.shisha-installed ] || [ pyproject.toml -nt .venv/.shisha-installed ]; then
    printf '正在安装项目依赖…\n'
    .venv/bin/python -m pip install -e .
    touch .venv/.shisha-installed
fi

exec .venv/bin/python -m shisha
