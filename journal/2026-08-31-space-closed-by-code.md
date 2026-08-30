# 2026-08-31 · 놓친 9개를 전부 판별했고, 이번엔 코드가 공간이 비었다고 말한다

`journal/2026-08-31-search-space-was-mine-to-get-wrong.md` 가 "손으로 세다 9개를 놓쳤다"
고 적고 `searchable_classes()` 를 만들었다. 이 항목은 **그 9개를 다 돌린 결과**다.

## 1. 놓쳤던 9개 — 전부 편입 불가

| 테마 | pool | 확신도 | 결과 |
|---|---:|---:|---|
| `food_retail_distribution` | 0.79 | 0.35 | 편입 불가 |
| `business_services` | 0.71 | 0.45 | 편입 불가 |
| `medtech_devices` | 0.67 | — | 편입 불가 |
| `waste_services` | 0.65 | — | 편입 불가 |
| `food_beverage` | 0.61 | — | 편입 불가 |
| `household_products` | 0.58 | 0.35 | 편입 불가 |
| `railroads` | 0.58 | 0.30 | 편입 불가 |
| `auto_parts` | 0.54 | — | 편입 불가 |
| `software_vertical` | 0.51 | — | 편입 불가 |

`railroads` 와 `auto_parts` 는 앞 라운드에서 증거 신뢰도 미달로 저장조차 안 됐던 것들인데,
**순차로 다시 돌리니 저장됐다** — 병렬 실행이 원인이었다는 것을 다시 확인한 셈이다.

## 2. 최종 — 판별 25건 · 편입 가능 2건 · 통과 0건

| | |
|---|---:|
| 저장된 thesis | **25** |
| 편입 가능 | **2** (`cement_aggregates` 0.65 · `specialty_chem` 0.85) |
| 여섯 관문 통과 | **0** |

둘 다 ④ 에서 걸렸다 — `cement_aggregates` `balanced` · `specialty_chem` `loosening`.

## 3. 이번엔 코드가 공간이 비었다고 말한다

```
⑤ 통과 가능 유형: capex_program · commodity_supply · inventory · secular_growth
★ 남은 미판별 후보: 0
```

`sector.searchable_classes(regime_doc)` 가 낸 집합으로 스코어보드를 걸러 센 결과다.
**손으로 세지 않았다** — 앞 항목이 손으로 세다 틀렸기 때문이다.

이 숫자는 재현 가능하다:

```python
from msa import sector
ok = sector.searchable_classes(yaml.safe_load(open("state/regime/2026-W35.yaml")))
left = sb[(sb.pool >= 0.5) & (sb.cls.isin(ok)) & (~sb.theme.isin(judged))]
```

## 4. 그래서 "오늘 살 섹터가 없다" 의 정확한 뜻

**이번 주 레짐(2026-W35) 아래에서, `pool ≥ 0.5` 이면서 거시 역풍이 아닌 테마를 전부
판별했고, 그중 여섯 관문을 통과한 것이 없다.**

통과가 나오려면 다음 중 하나가 바뀌어야 한다:

1. **레짐이 바뀐다** — 역풍 넷(`credit_rate`·`discretionary_demand`·`policy_program`·
   `secular_risk`)이 열리면 탐색 공간이 크게 넓어진다. `msa regime` 은 주간이다.
2. **`pool` 이 오른다** — 잊혀지지 않은 테마가 잊혀지면 ① 이 열린다. 이건 시간이 한다.
3. **수급이 바뀐다** — 편입 가능 2개의 ④ 판정이 뒤집히는 조건은 각 테마의 수급 조사
   `invalidations` 에 적혀 있고, 리포트의 **재진입 트리거** 절이 그것을 든다.
4. **`docs/27` 의 축 1 문제가 풀린다** — 판별 25건 중 축 1 이 `not_applicable` 인 것이
   대부분이었다. **그러나 "통과가 안 나오니까" 고치는 것은 금지다** (`docs/27` §6).

## 5. 이 라운드가 남긴 것

- **판별 25건**(이 세션에서 20건 추가) · **수급 조사 6건**
- 관문 체인이 12 테마를 표로 낸다
- 리포트가 투자 판단 → 근거 → 재진입 트리거 → 오늘 할 일 순으로 결론을 낸다
- 고친 버그 셋: 작업 디렉터리 파이널라이저 경쟁 · 리포트의 거짓 사유 · 탐색 공간 손 계산

이전 항목: `journal/2026-08-31-search-space-was-mine-to-get-wrong.md`
