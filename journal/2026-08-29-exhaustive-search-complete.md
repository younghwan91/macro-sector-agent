# 2026-08-29 · 통과 가능한 공간을 전수로 훑었다 — 그리고 0개다

앞선 두 항목(`gates-not-loosened` · `search-widened-still-zero`)은 "탐색을 넓혔다" 고
적었다. 이 항목은 **그 공간을 닫는다.**

## 1. 탐색 공간을 먼저 정의했다

여섯 관문을 통과하려면 최소한 다음이 동시에 성립해야 한다:

| 관문 | 요구 |
|---|---|
| ① | `pool ≥ POOL_MIN`(0.5) |
| ⑤ | 그 테마의 `cycle_class` 가 이번 주 레짐에서 **`headwind` 가 아님** |

2026-W35 레짐은 순풍이 **셋**뿐이다: `capex_program` · `commodity_supply` · `inventory`
(나머지 넷은 역풍, `secular_growth` 는 중립).

두 조건을 걸면 **미판별 테마가 정확히 7개** 남는다. 그것이 통과가 나올 수 있는 공간의
전부다.

## 2. 그 7개를 전부 판별했다

| 테마 | pool | 확신도 | 결과 |
|---|---:|---:|---|
| `coatings_adhesives` | 0.63 | 0.40 | 편입 불가 |
| **`cement_aggregates`** | 0.62 | **0.65** | **편입 가능** ✅ |
| `construction_machinery` | 0.61 | 0.35 | 편입 불가 |
| `railroads` | 0.58 | — | 스키마 거부 (증거 신뢰도) |
| `agribusiness` | 0.57 | 0.45 | 편입 불가 |
| `hvac_building` | 0.56 | 0.45 | 편입 불가 |
| `auto_parts` | 0.54 | — | 스키마 거부 |

**하나가 ② 를 통과했다.** `cement_aggregates` — 대체 위협 `cycle`, 확신도 0.65.

## 3. 그리고 ④ 에서 죽었다 — `balanced`

`msa balance cement_aggregates`:

> 수요 증가율 **+0.5%/년** 과 공급 증가율 간 격차가 뚜렷하지 않다. 확정 증설은 총소비의
> 0.4% 에 불과하나 **골재는 가동률 조정으로 탄력적으로 대응**한다. 8분기 중 capex/D&A 가
> **1.23** — 구성원들이 여전히 확장 투자를 지속한다. '공급이 구조적으로 조여지는' 국면이
> 아니라 IIJA 재원 불확실성에 따라 **양쪽이 함께 오르내리는 구간**.

`tightening` 이 아니다. **④ 관문이 세 번째로 판별을 걸렀다** (앞선 둘: `shipping_container`
`loosening` · `specialty_chem` `loosening`).

## 4. 최종 — 오늘 판별받은 것 15개, 편입 가능 2개, 통과 0개

```
cement_aggregates   2/6  ③ 실사 미실행 (오늘 새로 편입 가능)
managed_care        2/6  ③ 근거 3건 반박
specialty_chem      2/6  ③ 실사 미실행
health_it 외 8      1/6  ② 판별 탈락
silver_miners       0/6  ① pool 0.269
```

수급 조사 6건: `tightening` 2 · `balanced` 1 · `loosening` 3.
**`tightening` 둘(`silver_miners`·`insurance_brokers`)은 다른 관문에서 이미 떨어져 있다.**

## 5. 이것이 "탐색 부족" 이 아니라는 증거

이번 라운드에 **판별 15건 · 수급 조사 6건**을 돌렸다. 그리고 그 15건이 아무렇게나 고른
것이 아니라 **관문 ①·⑤ 를 통과할 수 있는 후보의 전부**다.

즉 **"오늘 살 섹터가 없다" 는 검색을 덜 해서가 아니라, 검색 공간을 다 본 결과다.**

### 무엇을 더 하면 통과가 나올 수 있나 — 정직하게

1. **다음 주 레짐이 바뀌면** 역풍 넷(`credit_rate`·`discretionary_demand`·`policy_program`·
   `secular_risk`)이 열리고 탐색 공간이 크게 넓어진다. `msa regime` 은 주간이다.
2. **`docs/27` 의 축 1 문제가 풀리면** ② 통과율이 오른다. 오늘 판별 15건 중 축 1 이
   `not_applicable` 인 것이 대부분이었다. **그러나 그것을 "통과가 안 나오니까" 고치는 것은
   금지다** (`docs/27` §6).
3. **`railroads`·`auto_parts` 는 증거 신뢰도 미달로 저장조차 안 됐다.** 다시 돌리면
   나올 수 있다 — 다만 둘 다 `inventory` 라 ⑤ 는 통과한다.

## 6. 부수적으로 고친 것

**`msa research` 를 동시에 돌리면 안 된다.** 배치 둘을 병렬로 돌리자 4건이 전부
`ProviderError`(종료코드 3)로 죽었다. 순차로 돌리니 같은 테마(`hvac_building`)가 그대로
통과했다. `CLAUDE.md` 에 적었고 종료코드 뜻도 함께 남겼다 (2=스키마 거부 · 3=제공자 오류).

이전 항목: `journal/2026-08-29-search-widened-still-zero.md`
