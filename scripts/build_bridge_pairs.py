# -*- coding: utf-8 -*-
"""다리 법령 기반 짝조문 후보 목록 생성 (Markdown).

  uv run python -m scripts.build_bridge_pairs
  uv run python -m scripts.build_bridge_pairs --bridges 국제조세조정에 관한 법률 --out docs/x.md

인용 그래프만 쓰므로 API 키·비용이 없다.
"""
from __future__ import annotations

import argparse
import sys
from collections import Counter
from datetime import date
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8")

from core.bridge_pairs import (
    DEFAULT_BRIDGES,
    DEFAULT_SIDES,
    MAX_REFS_PER_SIDE,
    already_in_matrix,
    article_titles,
    extract,
    jo_label,
)

ROOT = Path(__file__).resolve().parents[1]


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--bridges", nargs="+", default=list(DEFAULT_BRIDGES))
    ap.add_argument("--sides", nargs=2, default=list(DEFAULT_SIDES))
    ap.add_argument("--max-refs", type=int, default=MAX_REFS_PER_SIDE)
    ap.add_argument("--out", default="docs/bridge-parallel-pairs.md")
    args = ap.parse_args()

    law_a, law_b = args.sides
    pairs = extract(tuple(args.bridges), (law_a, law_b), args.max_refs)
    if not pairs:
        print("도출된 짝이 없습니다. 인용 그래프에 다리 법령이 들어 있는지 확인하세요.")
        return 1

    titles_a, titles_b = article_titles(law_a), article_titles(law_b)
    known = {id(p): already_in_matrix(p) for p in pairs}
    n_new = sum(1 for p in pairs if not known[id(p)])
    by_bridge = Counter(b for p in pairs for b, _ in p.bridges)

    lines = [
        f"# 다리 법령 기반 짝조문 후보 — {law_a} ↔ {law_b}",
        "",
        f"- 생성: {date.today().isoformat()} · `scripts/build_bridge_pairs.py`",
        f"- 다리 법령: {', '.join(args.bridges)}",
        f"- 짝 후보 **{len(pairs)}쌍** (매트릭스 기수록 {len(pairs) - n_new} / **신규 {n_new}**)",
        f"- 다리 조문 인용 수: " + ", ".join(f"{b} {n}건" for b, n in by_bridge.most_common()),
        "",
        "## 무엇을 근거로 뽑았나",
        "",
        f"다리 법령의 **한 조문이 {law_a}과 {law_b} 조문을 나란히 인용**하면, 그 둘은",
        "개인↔법인으로 대응하는 짝일 가능성이 높다. 그렇게 판단한 것은 추정 알고리즘이",
        "아니라 **입법자 자신**이다 — 한 문장 안에 둘을 함께 적었기 때문이다.",
        "",
        f"한 조문이 한쪽 법을 {args.max_refs}개 넘게 인용하면 '나열'로 보고 제외했다",
        "(조특법에는 감면 대상 조문을 수십 개 늘어놓는 조문이 있어 신호가 희석된다).",
        "",
        "인용 그래프만 사용하므로 LLM 비용이 없다. 다만 **후보**이지 확정이 아니다 —",
        "신고·납부 같은 절차 조문끼리 나란히 인용되는 경우도 걸리므로, 개정 시 함께",
        "봐야 하는 짝인지는 세제 판단이 필요하다.",
        "",
        "## 목록",
        "",
        "`다리`는 근거가 된 다리 법령 조문 수. 클수록 여러 곳에서 함께 인용됐다는 뜻이다.",
        "",
        f"| # | 다리 | {law_a} | {law_b} | 매트릭스 | 근거(다리 조문) |",
        "|--:|--:|---|---|:--:|---|",
    ]

    for i, p in enumerate(pairs, 1):
        ta = titles_a.get(p.jo_a, "")
        tb = titles_b.get(p.jo_b, "")
        cells_a = f"{jo_label(p.jo_a)} {ta}".strip()
        cells_b = f"{jo_label(p.jo_b)} {tb}".strip()
        mark = "기수록" if known[id(p)] else "**신규**"
        ev = ", ".join(
            f"{b.replace('국제조세조정에 관한 법률', '국조법').replace('조세특례제한법', '조특법')} {jo_label(j)}"
            for b, j in sorted(set(p.bridges))[:4]
        )
        if len(set(p.bridges)) > 4:
            ev += f" 외 {len(set(p.bridges)) - 4}건"
        lines.append(f"| {i} | {p.weight} | {cells_a} | {cells_b} | {mark} | {ev} |")

    lines += [
        "",
        "## 다음 단계",
        "",
        "1. 위 목록에서 실제 병행으로 볼 쌍을 골라낸다 (세제 판단).",
        "2. 확정분은 `core/parallel_golden.py`의 골든 매핑에 넣거나,",
        "   `source=\"bridge_hint\"`로 매트릭스에 등재한다.",
        "3. 그러면 `scripts/scan_parallel_omissions.py`가 개정안 검토 때 자동으로 대조한다.",
        "",
    ]

    out = ROOT / args.out
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text("\n".join(lines), encoding="utf-8")
    print(f"짝 후보 {len(pairs)}쌍 (신규 {n_new}) → {out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
