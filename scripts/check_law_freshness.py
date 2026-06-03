"""관심 세법 현행본 변경 감지 및 manifest 갱신.

예:
  uv run python scripts/check_law_freshness.py
  uv run python scripts/check_law_freshness.py --update-manifest
  uv run python scripts/check_law_freshness.py --rebuild-links
"""
from __future__ import annotations

import argparse
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from core.law_freshness import (  # noqa: E402
    compare_with_manifest,
    load_manifest,
    refresh_manifest,
)
from core.special_tax_hints import reload_indexes  # noqa: E402


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--update-manifest",
        action="store_true",
        help="API 현행본으로 data/law-snapshot-manifest.json 갱신",
    )
    parser.add_argument(
        "--rebuild-links",
        action="store_true",
        help="변경 감지 시 조특법 연결 JSON 재생성 (명시 인용 파싱)",
    )
    parser.add_argument(
        "--report",
        default="",
        help="변경 요약 마크다운 저장 경로 (예: docs/law-freshness-report.md)",
    )
    args = parser.parse_args()

    if args.update_manifest:
        path = refresh_manifest()
        print(f"manifest 갱신: {path}")
        reload_indexes()
        return

    manifest = load_manifest()
    if not manifest.get("laws"):
        print("manifest 없음. 먼저 --update-manifest 실행.")
        sys.exit(2)

    changes = compare_with_manifest()
    if not changes:
        print(f"변경 없음 (기준일 {manifest.get('checked_at', '?')})")
        return

    lines = [
        "# 법령 현행본 변경 감지",
        "",
        f"기준 manifest: `{manifest.get('checked_at', '')}`",
        "",
        "| 법령 | 상태 | 내용 |",
        "| --- | --- | --- |",
    ]
    for ch in changes:
        lines.append(f"| {ch['name']} | {ch['status']} | {ch['detail']} |")
        print(f"[{ch['status']}] {ch['name']}: {ch['detail']}")

    lines.extend([
        "",
        "## 권장 조치",
        "",
        "1. `uv run python scripts/check_law_freshness.py --update-manifest`",
        "2. `uv run python scripts/build_special_tax_links.py`",
        "3. 확정 병행 매핑·매뉴얼 수동 검토",
        "4. Streamlit 앱 재시작",
        "",
    ])

    if args.report:
        report_path = ROOT / args.report
        report_path.parent.mkdir(parents=True, exist_ok=True)
        report_path.write_text("\n".join(lines), encoding="utf-8")
        print(f"리포트 저장: {report_path}")

    if args.rebuild_links:
        subprocess.run(
            [sys.executable, str(ROOT / "scripts" / "build_special_tax_links.py")],
            cwd=ROOT,
            check=True,
        )
        reload_indexes()
        print("조특법 연결 JSON 재생성 완료")

    sys.exit(1)


if __name__ == "__main__":
    main()
