"""`msa.thesis` 의 PIT·읽기 실패 규칙 (2026-09 리뷰 회귀).

전체 케이던스/스키마 테스트는 다른 파일에 있다 — 이 파일은 코드 리뷰에서 나온 두 결함의
회귀만 지킨다.
"""

from __future__ import annotations

from pathlib import Path

from msa.thesis import all_theses, dump_thesis_yaml, find_thesis, thesis_head


def test_unreadable_thesis_is_untrusted_not_a_false_rejection(tmp_path: Path) -> None:
    """파일을 못 읽으면 '판별 결과 편입 불가' 로 세탁되면 안 된다 (2026-09 리뷰).

    `trusted=False` 가 아니면 하류(`sector._not_a_trap`)가 이걸 진짜 가치함정
    판별로 읽어 "가치 함정 혐의를 못 벗었다" 를 찍는다 — 파일을 읽은 적도 없는데.
    """
    root = tmp_path / "theses"
    bad = root / "2026-08-10" / "broken.thesis.yaml"
    bad.parent.mkdir(parents=True)
    bad.write_text("not: [valid, yaml, - structure", encoding="utf-8")

    h = thesis_head("broken", "2026-08-14", root)
    assert h.found  # 파일은 있다 — 읽기만 실패했다
    assert not h.trusted
    assert "읽지 못했다" in h.claim
    assert not h.eligible  # trusted=False 면 편입으로 세지 않는다


def test_all_theses_skips_non_date_round_directories(tmp_path: Path) -> None:
    """`all_theses` 는 `find_thesis` 와 **같은 PIT 규칙**이어야 한다.

    `.partial`·`<date>-rerun` 같은 비-날짜 디렉터리는 문자열 비교로는 `asof` 보다
    작게 정렬될 수 있다 — `find_thesis` 처럼 `parse_date` 로 걸러야 한다. 안 그러면
    한쪽만 그 라운드를 라운드로 인정해 두 함수가 다른 테마 집합을 낸다.
    """
    root = tmp_path / "theses"
    dump_thesis_yaml(
        root / "2026-08-25-rerun" / "only_in_rerun_dir.thesis.yaml",
        {"theme_id": "only_in_rerun_dir", "claim": "c", "invalidations": [{"observable": "x"}]},
    )
    dump_thesis_yaml(
        root / "2026-08-20" / "normal.thesis.yaml",
        {"theme_id": "normal", "claim": "c", "invalidations": [{"observable": "x"}]},
    )

    # `find_thesis` 는 비-날짜 디렉터리를 건너뛴다 — 못 찾는다.
    assert find_thesis("only_in_rerun_dir", "2026-08-30", root) is None
    # `all_theses` 도 **같은 결론**이어야 한다 — 여기 있으면 표류다.
    themes = {h.theme for h in all_theses("2026-08-30", root)}
    assert "only_in_rerun_dir" not in themes
    assert "normal" in themes
