"""키·데이터 없이 L3 리서치 한 라운드를 재생한다 (합성 입력 + 손으로 쓴 녹화 픽스처).

입력 스캔과 에이전트 응답은 모두 형식 시연용 합성값이다 — 실제 시장 데이터도, 실제 모델 산출도 아니다.
임시 디렉터리에서만 돌고 `state/` 는 건드리지 않는다.
"""

from __future__ import annotations

import os
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "tests"))


def main() -> int:
    from _l3_synth import write_scan_dir
    from typer.testing import CliRunner

    with tempfile.TemporaryDirectory() as tmp:
        write_scan_dir(Path(tmp))
        prev = os.environ.get("MSA_STATE")
        os.environ["MSA_STATE"] = tmp
        try:
            from msa.cli import app

            r = CliRunner().invoke(
                app, ["research", "uranium", "--provider", "fixture", "--no-store", "--no-write"]
            )
        finally:
            if prev is None:
                os.environ.pop("MSA_STATE", None)
            else:
                os.environ["MSA_STATE"] = prev
    print("[합성 데모] 스캔 입력·에이전트 응답 모두 가짜입니다. 투자 판단에 쓰지 마세요.\n")
    print(r.output)
    return r.exit_code


if __name__ == "__main__":
    raise SystemExit(main())
