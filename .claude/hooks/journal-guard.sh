#!/usr/bin/env bash
# journal/ append-only (CLAUDE.md §6) — HEAD 에 커밋된 저널 파일을 Edit/Write 로 고치는 것을 막는다.
# 새 파일은 통과한다. 판정 기준은 `msa journal verify`(src/msa/ops/journal.py verify_append_only)와 같다.
set -euo pipefail
path=$(python3 -c 'import sys,json; print(json.load(sys.stdin).get("tool_input",{}).get("file_path",""))')
case "$path" in */journal/*) ;; *) exit 0 ;; esac
dir=$(dirname "$path")
[ -d "$dir" ] || exit 0
root=$(git -C "$dir" rev-parse --show-toplevel 2>/dev/null) || exit 0
rel=${path#"$root"/}
if git -C "$root" cat-file -e "HEAD:$rel" 2>/dev/null; then
  echo "journal/ 은 append-only 다 (CLAUDE.md §6). 커밋된 $rel 은 고치지 않는다 — 새 항목을 만들고 이전 항목을 링크하라." >&2
  exit 2
fi
exit 0
