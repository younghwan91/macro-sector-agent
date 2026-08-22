#!/usr/bin/env sh
# journal/ append-only 검사 (CLAUDE.md §6, docs/09 §2).
# 인덱스에 기존 저널 파일의 수정·삭제·이름변경이 있으면 커밋을 막는다. 새 파일은 통과.
# 설치: `msa journal install-hook` 이 .git/hooks/pre-commit 에서 이 스크립트를 호출하게 한다.
set -e
cd "$(git rev-parse --show-toplevel)"
if command -v uv >/dev/null 2>&1; then
  exec uv run msa journal verify --staged
else
  exec python -m msa.cli journal verify --staged
fi
