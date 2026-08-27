"""근거 레지스트리 — **테스트가 §1 을 집행한다.**

`CLAUDE.md` §1 은 "임계값은 도메인 근거에서 오거나, 없으면 그렇다고 적는다" 를 요구한다.
그동안 그것은 규약일 뿐이었고 아무것도 강제하지 않았다 — 2026-08-27 실측에서 58개 수치
상수 중 코드에 근거가 붙은 것이 0개였다.

여기서 막는 것은 둘이다:

1. 판정을 만드는 상수를 **근거 없이 추가**하는 것
2. **값만 바꾸고 근거를 안 고치는** 것 — 근거가 조용히 거짓말이 된다

(2)가 오버피팅의 실행 형태다. 값을 옮기는 순간 테스트가 "근거도 같이 고쳐라" 라고 말한다.
"""

from __future__ import annotations

import pytest

from msa.basis import (
    BASES,
    FILTER_CONSTANTS,
    Citation,
    Derived,
    NoBasis,
    live_value,
    missing,
)


def test_every_filter_constant_has_a_basis() -> None:
    """판정을 만드는 상수는 **빠짐없이** 근거 항목이 있어야 한다.

    새 필터를 근거 없이 추가하면 여기서 막힌다. `NoBasis` 도 통과한다 — 없다고 적는 것이
    §1 이 요구하는 것이고, 없는 근거를 지어내는 것이 그 반대다.
    """
    assert missing() == (), f"근거 항목이 없는 필터 상수: {missing()}"
    assert set(BASES) == set(FILTER_CONSTANTS), (
        f"레지스트리에만 있는 것: {set(BASES) - set(FILTER_CONSTANTS)} · "
        f"필수인데 없는 것: {set(FILTER_CONSTANTS) - set(BASES)}"
    )


@pytest.mark.parametrize("name", sorted(FILTER_CONSTANTS))
def test_registry_value_matches_the_live_constant(name: str) -> None:
    """**값만 바꾸고 근거를 안 고치면 실패한다.**

    이것이 이 파일의 존재 이유다. 근거가 값을 따라오지 않으면 문서가 코드와 갈라지던 것과
    같은 일이 레지스트리에서 반복된다.
    """
    e = BASES[name]
    got = live_value(e.module, name)
    assert got == e.value, (
        f"{name}: 실제 값 {got!r} 인데 레지스트리는 {e.value!r} 이라고 적었다. "
        f"값을 바꿨다면 근거도 같이 고쳐라 — 왜 그 값인지가 바뀌었다."
    )


@pytest.mark.parametrize("name", sorted(FILTER_CONSTANTS))
def test_basis_carries_what_it_claims(name: str) -> None:
    """근거의 종류마다 **비어 있으면 안 되는 칸**이 있다.

    `Citation` 인데 인용문이 없으면 그것은 인용이 아니라 이름 대기다.
    """
    b = BASES[name].basis
    if isinstance(b, Citation):
        assert b.source.strip(), f"{name}: 출처 이름이 비었다"
        assert b.url.startswith("http"), f"{name}: URL 이 없다 — {b.url!r}"
        assert len(b.quote.strip()) >= 10, f"{name}: 인용문이 없거나 너무 짧다"
        assert b.match.strip(), f"{name}: 값이 왜 그 값인지(match)가 비었다"
    elif isinstance(b, Derived):
        assert b.frm.strip() and b.why.strip(), f"{name}: 무엇에서 어떻게 나왔는지가 비었다"
    else:
        assert isinstance(b, NoBasis)
        assert b.note.strip(), f"{name}: 근거가 없다면 **왜 없는지**는 적어야 한다"


def test_role_says_whether_it_cuts() -> None:
    """모든 항목이 **자르는지 아닌지**를 말해야 한다.

    이 저장소에서 가장 흔한 오해가 "감점이 종목을 없앤다" 는 것이다. 근거를 물었을 때
    "무엇을 하는 값인가" 가 같이 나와야 그 오해가 생기지 않는다.
    """
    for name, e in BASES.items():
        assert e.role.strip(), f"{name}: role 이 비었다 — 이 값이 무엇을 하는지 적어야 한다"


def test_unsearched_is_distinguishable_from_searched_and_empty() -> None:
    """**안 찾아본 것과 찾아도 없는 것은 다르다.**

    `searched` 가 비면 아직 조사하지 않았다는 뜻이고, 그것은 할 일이 남았다는 표시다.
    날짜가 있으면 찾아봤고 없었다는 기록이며 그 자체로 완결된 근거다.
    """
    unsearched = sorted(
        n for n, e in BASES.items() if isinstance(e.basis, NoBasis) and not e.basis.searched
    )
    # 이 목록이 줄어드는 것이 진척이다. 늘어나면 새 상수를 조사 없이 넣은 것이다.
    assert unsearched == [
        "CAPEX_BELOW1_QTRS",
        "CASE_DEATH_FACTOR",
        "CONF_CAP_ON_DEATH",
        "DEBT_24M_TO_MCAP_MAX",
        "PRICE_MIN",
        "STREAK_YEARS",
    ], f"미조사 목록이 바뀌었다: {unsearched}"


def test_every_citation_was_checked_against_the_source() -> None:
    """**출처 이름을 아는 것과 그 문장이 거기 있는 것은 다르다.**

    2026-08-27 에 인용 7건을 전부 원문 대조했다. 그 과정에서 `MDD_K` 의 URL 이 **완전히
    다른 논문**(Hubbard 모형 물리학 arXiv)을 가리키고 있는 것을 잡았다 — 대조하지 않았으면
    그대로 실렸을 것이다. 새 인용을 대조 없이 추가하면 여기서 막힌다.
    """
    unchecked = sorted(
        n for n, e in BASES.items() if isinstance(e.basis, Citation) and not e.basis.verified
    )
    assert unchecked == [], (
        f"원문 대조를 안 한 인용: {unchecked}. "
        f"URL 을 열어 인용문이 실제로 있는지 확인하고 verified 날짜를 적어라."
    )
