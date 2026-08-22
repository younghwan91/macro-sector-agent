# journal/ — 결정 저널 (append-only)

이 디렉터리의 파일은 **한 번 커밋되면 수정·삭제하지 않는다** (`CLAUDE.md` §6). 생각이 바뀌면
새 항목을 추가하고 이전 항목을 `links` 에 적는다. 이 저장소에서 성과를 검증하는 유일한 데이터가
여기 있으므로, 사후 편집은 검증 자체를 파괴한다.

- 항목 만들기: `msa journal template <type>` → YAML 채움 → `msa journal new --from file.yaml`
  (필수 필드가 비면 거부된다 — `docs/09-operations.md` §2)
- 검사: `msa journal verify` (커밋된 파일이 바뀌었으면 실패) · `msa journal install-hook` 으로 pre-commit 에 건다
- 논지 표류: `msa journal diff <theme>` — 최근 두 thesis 스냅샷의 필드 단위 diff

파일명 규약: `YYYY-MM-DD-<theme>-<entry|check|add2|add3|tp1|tp2|runner|exit|reject>.md`
(+ 진입·기각·재실행 점검은 `.thesis.yaml` 스냅샷).
