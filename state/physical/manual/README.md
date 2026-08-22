# 수동 갱신 드라이버 (L2 `manual` · `agent` provider)

`msa macro` 가 여기서 읽는다. 없으면 해당 드라이버는 `missing` 으로 보고된다 (조용히 0 이 되지 않는다).

| 파일 | 드라이버 | 열 | 뜻 |
|---|---|---|---|
| `china_credit_impulse.csv` | `china_credit_impulse` (measure `level`) | `date,value[,available]` | TSF 12개월 변화 / GDP (비율, 예 0.012) |
| `china_property.csv` | `china_property` (measure `yoy`) | `date,value[,available]` | 착공·판매 면적 **수준** — YoY 는 코드가 계산 |
| `policy_events.csv` | `policy_events` | `date,theme,effect,description,confirmed` | `effect` = 해당 테마에 +1 유리 / −1 불리. `confirmed=Y` 만 센다 |

- `date` 는 관측 기간(월간은 1일 또는 말일 아무거나). `available` 이 없으면 **다음 달 말**부터 보이는 것으로 간주한다.
- 이 디렉터리의 CSV 는 커밋해도 된다 — 사람이 쓴 데이터이고 출처를 `description` 또는 커밋 메시지에 남긴다.
