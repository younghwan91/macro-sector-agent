def test_trailing_commas_do_not_throw_away_a_finished_round() -> None:
    """**모델이 흔히 내는 표기 사고로 12분짜리 판별을 버리지 않는다.**

    2026-08-29 실측: `life_science_tools` 판별이 12분 돌다 `referee` 의 꼬리 쉼표 하나로
    두 번 다 죽었다 (`Illegal trailing comma`). 내용이 아니라 문법 장식 때문이다.

    **잘못된 값을 받아들이는 것이 아니다** — 쉼표를 지운 뒤에도 나머지가 유효한 JSON 이어야
    통과한다. 진짜로 깨진 것은 여전히 거부한다.
    """
    import pytest

    from msa.l3.providers import ProviderError, _parse_json

    assert _parse_json('{"a": [1, 2,], "b": {"c": 1,},}') == {"a": [1, 2], "b": {"c": 1}}
    assert _parse_json('앞말\n```json\n{"x": 1,}\n```\n뒷말') == {"x": 1}

    for broken in ('{"a": }', "{not json at all", '{"a": 1 "b": 2}'):
        with pytest.raises(ProviderError):
            _parse_json(broken)
