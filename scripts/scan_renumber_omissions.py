# -*- coding: utf-8 -*-
"""번호 밀림 누락 검토 CLI — 개정안 파일(들)을 받아 인용 정비 누락 후보를 뽑는다.

사용 예:
  uv run python -m scripts.scan_renumber_omissions "docs/입법예고/*.pdf"
  uv run python -m scripts.scan_renumber_omissions bill.hwpx --all
"""
from __future__ import annotations

import argparse
import glob
import sys
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8")

from core.draft_bill_parser import find_amendment_body
from core.document_text import extract as extract_document
from core.pdf_bill_text import unwrap
from core.renumber_scan import _jo_label, apply_batch_coverage, scan_renumber_omissions

_STATUS_LABEL = {
    "missing": "⚠️ 누락 — 같은 법인데 이 조문은 개정안에 없음",
    "missing_other": "⚠️ 누락 — 그 법 개정안도 이번에 예고됐는데 이 조문은 안 건드림",
    "touched": "⚠️ 확인 필요 — 그 조문을 개정하긴 했으나 이 인용의 구·신 표기 정비가 안 보임",
    "touched_other": "⚠️ 확인 필요 — 타법 개정안이 그 조문을 건드렸으나 이 인용 정비는 확인 안 됨",
    "other_law": "→ 타법 — 별도 개정 필요(이번 묶음에 해당 법 개정안 없음)",
    "decree": "→ 위임법령(시행령·규칙) — 후속 개정",
    "covered_other": "✓ 같은 묶음의 타법 개정안이 이 인용을 정비함",
    "covered": "✓ 같은 개정안이 이 인용을 정비함",
}
_MISSING = ("missing", "missing_other", "touched", "touched_other")


def _read(path: Path) -> str:
    return extract_document(path)


def analyze(path: Path) -> dict | None:
    law_name, body = find_amendment_body(unwrap(_read(path)))
    if not body:
        print(f"[skip] {path.name} — 개정문 본문을 찾지 못했습니다.")
        return None
    r = scan_renumber_omissions(law_name, body)
    r["law_name"] = law_name
    r["path"] = path
    return r


def report(r: dict, show_all: bool) -> None:
    print("=" * 78)
    print(f"■ {r['law_name']}   ({r['path'].name})")
    if not r["graph_covered"]:
        print(f"   ※ 인용 그래프 미수록 법령 — 역인용 대조 불가 "
              f"(수록: {', '.join(r['graph_meta'].get('laws', []))})")
    print(f"   번호 이동 {len(r['events'])}건")
    for ev in r["events"]:
        print(f"     · {ev.label()}    | {ev.raw[:64]}")
    if not r["hits"]:
        print("   → 이동 번호를 인용하는 조문 없음(그래프 기준)")
        return
    skip = ("covered", "covered_other")
    shown = r["hits"] if show_all else [h for h in r["hits"] if h["상태"] not in skip]
    print(f"   영향 조문 {len(r['hits'])}건 "
          f"(누락 {sum(1 for h in r['hits'] if h['상태'] in _MISSING)})")
    for h in shown:
        rng = " [범위인용]" if h["범위인용"] else ""
        print(f"     {_STATUS_LABEL[h['상태']]}")
        print(f"       {h['법령명']} 제{_jo_label(h['조번호'])} {h['제목']}{rng}")
        print(f"       대상: {h['대상']} / 인용된 번호: {', '.join(h['영향번호'])}")
        for raw in h["인용"][:3]:
            print(f"       인용원문: \"{raw}\"")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("patterns", nargs="+", help="개정안 파일/글롭 (.pdf/.hwpx/.hwp/.md/.txt)")
    ap.add_argument("--all", action="store_true", help="개정안이 이미 반영한 건도 표시")
    args = ap.parse_args()

    paths = sorted({Path(p) for pat in args.patterns for p in glob.glob(pat)})
    if not paths:
        print("대상 파일이 없습니다.")
        return 1

    results = [r for r in (analyze(p) for p in paths) if r]
    apply_batch_coverage(results)   # 묶음 안 타법 개정안이 정비했는지 대조
    for r in results:
        report(r, args.all)

    total_missing = sum(
        1 for r in results for h in r["hits"] if h["상태"] in _MISSING
    )
    print("=" * 78)
    print(f"합계: 개정안 {len(results)}건 / 번호 이동 "
          f"{sum(len(r['events']) for r in results)}건 / 정비 누락 후보 {total_missing}건")
    return 0


if __name__ == "__main__":
    sys.exit(main())
