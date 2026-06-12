# -*- coding: utf-8 -*-
"""업로드된 개정법률안 분석 — 신설 29조대 검토 + 수기 병행개정 대조."""
from __future__ import annotations

import re
import sys

sys.stdout.reconfigure(encoding="utf-8")

from core.new_article_scanner import (
    forward_citations,
    parse_jo_tokens,
    proxy_checklist,
    stale_citation_conflicts,
)

LAW = "조세특례제한법"
DRAFT_PATH = r"data\uploaded_draft.txt"

_DIRECTIVE_RE = re.compile(r"^제(\d+)조(?:의(\d+))?")
_VERBS = ("신설한다", "개정한다", "삭제한다", "로 한다", "같이 한다", "각각 한다")


def load_body() -> str:
    text = open(DRAFT_PATH, encoding="utf-8").read()
    start = text.index("조세특례제한법 일부를 다음과 같이 개정한다")
    end = text.find("신ㆍ구조문대비표", start)
    return text[start:end if end > 0 else len(text)]


def manual_amendment_targets(body: str) -> list[str]:
    """지시문 라인에서 수기 병행개정 대상 조번호 추출."""
    targets: list[str] = []
    for line in body.splitlines():
        s = line.strip()
        if not s:
            continue
        m = _DIRECTIVE_RE.match(s)
        if not m:
            continue
        if not any(v in s for v in _VERBS):
            continue
        # 신설 조문 본문(제X조(제목) ① ...)은 제외 — 지시문은 "제X조제N항 중 ..." 형태
        if re.match(r"^제\d+조(의\d+)?\(", s):
            continue
        jo = m.group(1) + (f"의{m.group(2)}" if m.group(2) else "")
        if jo not in targets:
            targets.append(jo)
    return targets


def new_article_block(body: str) -> str:
    """제29조대 신설 본문 구간 (첫 29조 지시문 ~ 제60조 지시문 직전)."""
    start = body.index("제29조 앞에 절 번호")
    end = body.index("제60조제2항")
    return body[start:end]


def main() -> int:
    body = load_body()
    block = new_article_block(body)
    jo_list = parse_jo_tokens("29~29의8")
    range_keys = {f"{jo}의{sub}" if sub else jo for jo, sub in jo_list}

    manual = manual_amendment_targets(body)
    manual_set = set(manual)

    print("=" * 70)
    print("수기 병행개정 대상 조문 (지시문 기준):", len(manual), "건")
    print("  ", ", ".join(f"제{j}조" for j in manual))

    # ① 신설 본문 순방향 인용
    print("\n" + "=" * 70)
    fwd = forward_citations(block, LAW, jo_list)
    ext = [r for r in fwd if not r["신설범위내"]]
    internal = [r for r in fwd if r["신설범위내"]]
    print(f"① 신설 29조대 본문의 순방향 인용 — 외부 {len(ext)}건 / 내부 {len(internal)}건")
    for r in ext:
        print(f"   {r['법령명']} {r['조문']}  ← \"{r['인용 원문']}\"")

    # ② 잔존 인용 충돌 vs 수기 개정
    print("\n" + "=" * 70)
    stale = stale_citation_conflicts(LAW, jo_list)
    law_stale = [r for r in stale if r["법령명"] == LAW]
    decree_stale = [r for r in stale if r["법령명"] != LAW]
    covered, missing = [], []
    for r in law_stale:
        (covered if r["조번호"] in manual_set else missing).append(r)
    print(f"② 재사용 번호 잔존 인용 {len(stale)}건")
    print(f"   └ 법률 내 {len(law_stale)}건 중 수기 개정에 포함 {len(covered)}건 / 미포함 {len(missing)}건")
    print(f"   └ 시행령 {len(decree_stale)}건 (후속 시행령 개정 필요 목록)")
    if missing:
        print("\n   ⚠️ 수기 개정안에 없는 잔존 인용 조문 (검토 필요):")
        for r in missing:
            print(f"      제{r['조번호']}조 {r['제목']} — 대상: {', '.join(r['대상'])}")
            for raw in r["인용"][:3]:
                print(f"         인용: {raw}")
    print("\n   시행령 잔존 인용 (법률 공포 후 시행령 개정에 반영):")
    for r in decree_stale:
        print(f"      {r['법령명']} 제{r['조번호']}조 {r['제목']} — 대상: {', '.join(r['대상'])}")

    # ③ 프록시(제24조 통합투자세액공제) 체크리스트 vs 수기 개정
    print("\n" + "=" * 70)
    proxy = proxy_checklist(LAW, parse_jo_tokens("24"))
    law_proxy = [r for r in proxy if r["법령명"] == LAW and r["조번호"] not in range_keys]
    not_in_manual = [r for r in law_proxy if r["조번호"] not in manual_set]
    print(f"③ 유사 제도(제24조) 기준 체크리스트 — 법률 내 {len(law_proxy)}건")
    print(f"   └ 수기 개정에 포함: {len(law_proxy) - len(not_in_manual)}건 / 미포함: {len(not_in_manual)}건")
    if not_in_manual:
        print("\n   ⚠️ 수기 개정안에 없는 체크리스트 조문 (신설 조번호 추가 여부 검토):")
        for r in not_in_manual:
            print(f"      제{r['조번호']}조 {r['제목']} — 제24조 인용: {', '.join(r['인용'][:2])}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
