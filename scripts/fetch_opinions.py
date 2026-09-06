"""입법예고 의견 수집 — 국민참여입법센터 크롤링 또는 저장 파일 읽기.

사용:
  # 0) 사이트 구조 확인 (최초 1회) — 1페이지 원문 HTML을 저장한다
  uv run python scripts/fetch_opinions.py --bill 87936 --probe

  # 1) 수집
  uv run python scripts/fetch_opinions.py --bill 87936
  uv run python scripts/fetch_opinions.py --bill 87936 --pages 5 --delay 1.5

  # 2) 크롤링이 막히면 — 브라우저에서 저장한 HTML/CSV로 대체
  uv run python scripts/fetch_opinions.py --bill 87936 --from-files saved/*.html

산출물: data/opinions/{bill_id}.json  (gitignore — 수집 원문은 커밋하지 않는다)

주의: 작성자 실명은 저장하지 않는다(수집 시점에 마스킹). 요청 간격 기본 1초,
robots.txt를 확인하고 금지 시 중단한다.
"""
from __future__ import annotations

import argparse
import sys
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")
    sys.stderr.reconfigure(encoding="utf-8")

from core.opinion_source import (  # noqa: E402
    DEFAULT_DELAY,
    DEFAULT_MAX_PAGES,
    cache_path,
    dedupe_records,
    fetch_opinions,
    list_url,
    load_from_files,
    load_selectors,
    probe,
    save_records,
)


def _parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="입법예고 의견 수집")
    parser.add_argument("--bill", required=True, help="입법예고 ID (URL의 /ogLmPp/{ID}/ 부분)")
    parser.add_argument("--pages", type=int, default=DEFAULT_MAX_PAGES, help="최대 페이지 수")
    parser.add_argument("--delay", type=float, default=DEFAULT_DELAY, help="요청 간격(초)")
    parser.add_argument("--page-param", default="pageIndex", help="페이지 쿼리 파라미터명")
    parser.add_argument("--selectors", help="셀렉터 JSON 경로 (기본: data/opinion-selectors.json)")
    parser.add_argument("--probe", action="store_true", help="1페이지 원문만 저장하고 종료")
    parser.add_argument("--from-files", nargs="+", metavar="PATH", help="저장한 HTML/CSV/JSON에서 읽기")
    parser.add_argument("--no-robots", action="store_true", help="robots.txt 확인 생략")
    parser.add_argument(
        "--append", action="store_true",
        help="증분 수집 — 이미 가진 의견은 건너뛰고, 아는 지점에 닿으면 멈춘다"
             " (접수기간 중 반복 실행용)",
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = _parse_args(argv)
    bill_id = str(args.bill)

    if args.probe:
        try:
            path = probe(bill_id, page_param=args.page_param)
        except Exception as exc:
            print(f"probe 실패: {exc}", file=sys.stderr)
            print(f"요청 URL: {list_url(bill_id, 1, page_param=args.page_param)}", file=sys.stderr)
            return 1
        print(f"1페이지 원문 저장: {path}")
        print("이 HTML에서 의견 1건을 감싸는 요소를 찾아 data/opinion-selectors.json 에 XPath를 적으세요.")
        print('예: {"row": "//ul[@class=\\"opn-list\\"]/li", "body": ".//p[@class=\\"cont\\"]//text()"}')
        return 0

    if args.from_files:
        paths = [Path(p) for p in args.from_files]
        try:
            records = load_from_files(paths, bill_id)
        except Exception as exc:
            print(f"파일 읽기 실패: {exc}", file=sys.stderr)
            return 1
        source_note = f"files:{len(paths)}"
        warnings: list[str] = []
        if not records:
            print("파싱 결과 0건입니다. 저장한 HTML 구조가 예상과 다를 수 있습니다.", file=sys.stderr)
            print("→ data/opinion-selectors.json 에 XPath를 지정해 보세요.", file=sys.stderr)
            return 1
        if args.append and cache_path(bill_id).exists():
            from core.opinion_source import load_records

            records = dedupe_records(load_records(bill_id) + records)
            print(f"기존 수집분과 병합 — 누적 {len(records):,}건")
    else:
        selectors = load_selectors(args.selectors) if args.selectors else load_selectors()

        def on_page(page: int, fresh: int, total: int) -> None:
            print(f"  page {page:>3}: +{fresh:>3}건 (누적 {total:,}건)")

        # 증분 수집: 이미 가진 의견을 깔고 시작해 아는 지점에서 멈춘다
        previous: list = []
        if args.append and cache_path(bill_id).exists():
            from core.opinion_source import load_records

            previous = load_records(bill_id)
            print(f"기존 수집분 {len(previous):,}건 — 새 의견만 받아옵니다")

        print(f"수집 시작: {list_url(bill_id, 1, page_param=args.page_param)}")
        try:
            report = fetch_opinions(
                bill_id,
                max_pages=args.pages,
                delay=args.delay,
                page_param=args.page_param,
                selectors=selectors,
                check_robots=not args.no_robots,
                on_page=on_page,
                known=previous,
            )
        except Exception as exc:
            print(f"수집 실패: {exc}", file=sys.stderr)
            return 1
        records = report.records
        warnings = report.warnings
        source_note = f"http:{report.pages_fetched}pages"
        if report.stopped_reason:
            print(f"중단 사유: {report.stopped_reason}")
        print(f"새 의견 {len(records):,}건")
        if not records and not previous:
            print("수집된 의견이 0건입니다.", file=sys.stderr)
            print("→ `--probe`로 1페이지 HTML을 저장해 셀렉터를 확인하세요.", file=sys.stderr)
            return 1
        if previous:
            # previous를 known으로 넘겼으므로 대상 개정항목은 이미 병합돼 있다
            records = dedupe_records(previous + records)
            print(f"누적 {len(records):,}건")

    for warning in warnings:
        print(f"[경고] {warning}", file=sys.stderr)

    path = save_records(
        bill_id,
        records,
        meta={
            "collected_at": datetime.now().isoformat(timespec="seconds"),
            "source": source_note,
        },
    )
    print(f"\n의견 {len(records):,}건 저장: {path}")
    print(f"다음: uv run python scripts/analyze_opinions.py --bill {bill_id} --top 20")
    return 0


if __name__ == "__main__":
    sys.exit(main())
