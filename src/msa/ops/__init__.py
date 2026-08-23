"""운영 계층 (M8, `docs/09-operations.md`).

| 모듈 | 역할 |
|---|---|
| `journal` | 결정 저널 — append-only · 필수 필드 누락 시 작성 거부 · thesis 스냅샷 diff |
| `state_files` | `state/positions.yaml` · `watchlist.yaml` · `rejections.yaml` 타입 로드/저장 |
| `check` | `msa check` — 트리거·무효화·Tier-2·사다리·시간 스탑·TP 점검 (주문은 내지 않는다) |
| `alerts` | 알림 6종 + 문구 규약(측정값만, 권유 금지) + 텔레그램 배달 |
| `scheduler` | 케이던스 → crontab / systemd 타이머 텍스트 생성 (설치는 사람이) |
| `calibration` | `cycle_confidence` 캘리브레이션 (Brier · 구간 적중률 · 기울기 → λ 근거) |
| `rejections` | 기각 대장 12·24M 수익률 갱신 + 사전 고정 세 질문 집계 |
| `reproduce` | 저장된 `state/scans/<date>/` 스냅샷에서 리포트 재생성 (재계산 없음) |

이 계층의 산출물은 측정값과 사실이다. 주문을 내지 않고(`CLAUDE.md` §8), 성과 수치를
광고하지 않는다(§7). L3~L5 산출물과의 연결은 파일 계약(`positions.yaml` · thesis 스냅샷 ·
`state/scans/` · `state/cache/l1_*.parquet`)으로만 한다 — L3~L5 패키지를 import 하지 않는다.
L1 에 대해서만 **읽기 전용 리더**를 쓴다: `reproduce` 가 `msa.l1.scan.render_report` 로 리포트를
다시 그리고, `rejections` 가 L1 패널·지표 캐시를 읽는다
(`msa.l1.panel.load_cached_panel` · `msa.l1.scan.scan_dirs`).
가격은 `msa.data.store.Store` 를 `check.StorePriceSource` 가 감싼다.
"""
