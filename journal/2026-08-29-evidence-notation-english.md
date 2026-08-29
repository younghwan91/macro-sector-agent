# 2026-08-29 · 증거 실사가 영문 표기를 못 따라가 오탐 7건을 냈다

`journal/2026-08-29-evidence-layer-closed.md` 가 닫은 증거 계층의 **후속**이다. 그 항목은
사람이 원문을 대조해 판정을 뒤집었고, 이 항목은 **왜 사람이 그걸 대조해야 했는지**를 고친다.

## 무엇이 틀렸나

`evidence_audit` 은 claim 에서 숫자를 뽑아 원문에서 찾는다. 한글 `만`·`억`·`조` ↔ 영문
`million` 변환은 2026-08-26 에 넣었는데, **영문 원문이 숫자를 숫자로 안 쓰는 경우**가 남아
있었다. 사람이 원문을 대조한 결과 `partial` 13건 중 6건이 이것이었다.

| claim | 원문 | 왜 못 찾았나 |
|---|---|---|
| `12`척 (shipping [6]·[49]) | *"only **twelve** ships"* | 낱말 숫자 |
| `11`척 (shipping [49]) | *"only **eleven** cellular vessels"* | 낱말 숫자 |
| `4,300` TEU (shipping [12]) | *"rates for **4.3k** TEU"* | 소수 + 붙여 쓴 약어 |
| `60`만 TEU (shipping [50]) | *"totaling **0.6 million** TEU"* | 소수 + 낱말 단위 |
| `3,400`만 명 (managed_care [22]) | *"to **34.0 million** on June 30"* | 소수 + 낱말 단위 |
| `12` (shipping [4]·managed_care [26]) | — | **`2025년 12월` 의 `12` 였다.** 측정값이 아니다 |

앞의 다섯은 **같은 수를 다르게 적은 것**이고, 마지막은 애초에 확인할 대상이 아니었다.
둘 다 "원문에 없는 숫자" 로 올라와 사람의 실사 대상을 부풀렸다.

## 무엇을 고쳤나

1. **영문 낱말 숫자** — `zero`~`twenty` · `thirty`~`ninety` · `one hundred/thousand/million/
   billion` 의 **작은 표**만 둔다. 임의의 복합 수사 파서는 만들지 않았다 (새 자유도이고
   유지비가 크다). `twenty-one`·`one hundred eighty-five` 는 **여전히 못 읽는다.**
2. **영문 축약 단위** — 본문의 `4.3k`·`1.8M`·`2.5bn`·`0.6 million` 을 편 값으로 옮겨
   덧붙인다. claim 쪽 후보(`_alternates`)만으로는 소수 + 단위를 못 만난다 — `60만` 의
   후보는 `600000`·`600` 인데 본문에는 `0.6` 만 있기 때문이다.
3. **날짜** — `_DATE_LIKE` 에 `YYYY년 M월[ D일]` 을 넣었다.

### 넓히면서 검사를 끄지 않은 자리

이 모듈의 지배적 위험은 **오탐을 줄이려다 미탐을 만드는 것**이다. 세 군데를 막았다.

- **단어 경계** — `one` 이 `money`·`phone`, `ten` 이 `tenant` 안에서 걸리면 안 된다.
- **맨 단위 낱말은 값이 아니다** — `hundred`·`million` 을 100·1,000,000 으로 두면
  *"five hundred ships"* 가 claim 의 `100` 을 통과시킨다. `one hundred` 만 둔다.
- **한 글자 약어는 붙여 쓴 것만** — `1.8M` 은 받고 `40 M` 은 안 받는다. 후자는 미터일 수
  있고, 그러면 원문에 없는 4,000만이 생긴다.

임계값은 만들지 않았다 (`CLAUDE.md` §1). 판정 규칙은 그대로 **"뽑은 숫자를 전부 찾았을
때만 `verified`"** 다.

## 실측

`msa ops audit-evidence` 두 테마, 같은 논지 스냅샷(`state/theses/2026-08-24/`) 기준.

| | 고치기 전 | 고친 뒤 |
|---|---|---|
| `managed_care` | partial 7 · verified 11 | **partial 5 · verified 13** |
| `shipping_container` | partial 6 · verified 12 | **partial 1 · verified 17** |
| 합계 | partial 13 | **partial 6** |

`unreachable`·`unsupported`·`no_numbers` 는 양쪽 다 그대로다 —
**`verified` 가 `partial` 로 뒤집힌 건은 없다.**

## 여전히 못 잡는 것 — 이게 이 항목의 절반이다

- **반올림·근사.** `managed_care [8]` 의 "3,500만 명 이상" 은 원문 KFF 의 `35.2 million`
  과 **숫자로는 안 맞는다.** 표기 차이가 아니라 실제로 다른 수다. 이걸 잡으려면 "몇 % 안에
  들면 같다" 는 임계가 필요한데 그건 근거 없이 고른 값이다 (`CLAUDE.md` §1). **남긴다.**
- **영문 복합 수사** — `twenty-one`·`one hundred eighty-five`.
- **문맥** — 숫자가 문서에 있어도 claim 의 뜻과 다를 수 있다. 이건 원래부터 못 한다.
- 남은 `partial` 6건: `managed_care [1]·[8]·[10]·[17]·[21]` · `shipping [46]`.
  `[1]`·`[10]`·`[17]`·`[21]`·`[46]` 은 표기 문제가 아니라 **원문에 정말 없다**
  (JS 로 그리는 표이거나 페이지가 바뀌었거나 — 사람이 열어야 한다).

## 코드가 어디에 들어갔는지 — 기록해 둔다

이 변경(`src/msa/l3/evidence_audit.py` · `tests/test_l3_evidence_audit.py`)은 같은 작업
트리에서 동시에 돌던 다른 작업의 `git commit -a` 에 **휩쓸려** `8f286d5`·`5fcf0ee` 로
들어갔다. 커밋 메시지(`msa balance`·문서)와 내용이 맞지 않는다. 히스토리를 다시 쓰지 않고
여기에 적어 둔다 — 나중에 `git log` 로 이 변경을 찾으면 저 두 커밋이다.

links: `journal/2026-08-29-evidence-layer-closed.md`
