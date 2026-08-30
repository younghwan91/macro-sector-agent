# 2026-08-31 · 탐색 공간을 손으로 세다 9개를 놓쳤다

`journal/2026-08-29-exhaustive-search-complete.md` 는 **"통과 가능한 공간을 전수로
훑었다"** 고 적었다. **틀렸다.**

## 1. 무엇을 놓쳤나

그 항목은 탐색 공간을 이렇게 정의했다:

> 2026-W35 레짐은 순풍이 **셋**뿐이다: `capex_program` · `commodity_supply` · `inventory`

그리고 그 셋 안에서 미판별 테마 7개를 세어 전부 판별했다. **그런데 관문 ⑤ 는 순풍만
통과시키는 것이 아니다** — `_macro` 는 **`headwind` 만** 막는다:

```python
if float(t) <= REGIME_TILT["headwind"]:
    return Result("macro", False, "거시 **역풍** …")
```

`secular_growth` 는 **중립**(계수 0.85)이라 ⑤ 를 통과한다. 그 유형에 `pool ≥ 0.5` 인
미판별 테마가 **7개** 더 있었고, `inventory` 에서 재시도 대상 2개를 합쳐 **총 9개**를
놓쳤다.

**"순풍" 과 "막지 않음" 을 헷갈린 것이다.** 그리고 그 착각을 "전수로 훑었다" 는 문장으로
기록까지 했다.

## 2. 근본 수정 — 손으로 세지 않는다

`sector.searchable_classes(regime_doc)` 를 만들었다. `_macro` 와 **같은 규칙**으로 관문 ⑤
를 통과할 수 있는 `cycle_class` 집합을 낸다. 같은 판정을 두 곳에서 내리면 언젠가 갈라지고,
이번에 갈라진 쪽이 사람 머릿속이었다.

### 만들면서 두 번째 실수를 잡았다

첫 구현이 **판정 없는 칸을 통과로 셌다** — `REGIME_TILT.get(verdict, 1.0)` 의 기본값 1.0
때문이다. 레짐 문서에 없는 칸이 전부 후보가 됐다.

`_macro` 는 계수가 없으면 안 막는 것이 맞다(없는 것을 역풍으로 읽지 않는다). 그러나
**탐격 공간에서는 반대다** — "모르는 칸" 을 후보에 넣으면 판별을 돌린 뒤 ⑤ 에서 걸린다.
판별 한 건이 5~10분이고 크레딧이 든다. **아는 것만 센다** (`CLAUDE.md` §2).

두 함수가 같은 사실을 다르게 쓰는 것이 옳은 자리다. 그 이유를 독스트링에 적었다.

## 3. 놓친 9개를 판별했다

| 테마 | pool | 확신도 | 결과 |
|---|---:|---:|---|
| `food_retail_distribution` | 0.79 | 0.35 | 편입 불가 |
| `business_services` | 0.71 | 0.45 | 편입 불가 |
| `medtech_devices` | 0.67 | — | 스키마 거부 |
| `waste_services` | 0.65 | — | (진행) |
| `food_beverage` | 0.61 | — | (진행) |
| `household_products` | 0.58 | 0.35 | 편입 불가 |
| `software_vertical` | 0.51 | — | (진행) |
| `railroads`·`auto_parts` | — | — | 재시도 |

## 4. 교훈

**"전수로 훑었다" 는 문장은 그 자체로 검증돼야 한다.** 이번엔 검증 없이 적었고, 공간을
정의한 논리에 구멍이 있었다. 이제 그 논리가 코드에 있고 테스트가 지킨다:

- `test_neutral_regime_passes_gate_five` — 중립은 역풍이 아니다
- `test_searchable_classes_names_every_non_headwind_class`
- `test_searchable_classes_does_not_treat_missing_as_tailwind`

이전 항목: `journal/2026-08-29-exhaustive-search-complete.md`
