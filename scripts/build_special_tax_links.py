"""조세특례제한법 조문별 세법 연결 후보 JSON/문서 생성.

사용 예:
  uv run python scripts/build_special_tax_links.py
  uv run python scripts/build_special_tax_links.py --gpt --max-gpt 40
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from core.special_tax_link_builder import (  # noqa: E402
    build_markdown_summary,
    build_records,
    enrich_with_gpt_batches,
    save_records,
)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--gpt",
        action="store_true",
        help="GPT 배치 검토 추가 (명시 인용이 적은 조문만)",
    )
    parser.add_argument(
        "--max-gpt",
        type=int,
        default=40,
        help="GPT로 검토할 최대 조문 수 (기본 40)",
    )
    parser.add_argument(
        "--model",
        default="",
        help="OpenAI 모델 (기본: SPECIAL_TAX_LINK_MODEL 또는 gpt-4o-mini)",
    )
    args = parser.parse_args()

    print("조세특례제한법 조문 로드 및 명시 인용 파싱...")
    records = build_records()
    cite_articles = sum(
        1 for r in records if any(x.get("source") == "citation" for x in r.linked_articles)
    )
    print(f"  조문 {len(records)}개, 명시 인용 연결 {cite_articles}개 조문")

    batches = 0
    if args.gpt:
        print(f"GPT 배치 검토 (최대 {args.max_gpt}조문)...")
        batches = enrich_with_gpt_batches(
            records,
            model=args.model,
            max_articles=args.max_gpt,
        )
        print(f"  GPT 배치 {batches}회 완료")

    out_json = ROOT / "data" / "special-tax-parallel-candidates.json"
    out_md = ROOT / "docs" / "special-tax-parallel-links.md"
    out_json.parent.mkdir(parents=True, exist_ok=True)
    save_records(records, str(out_json))
    out_md.write_text(build_markdown_summary(records), encoding="utf-8")
    print(f"저장: {out_json}")
    print(f"저장: {out_md}")


if __name__ == "__main__":
    main()
