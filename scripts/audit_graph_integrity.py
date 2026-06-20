"""탐지 그래프 구조 감사 — 읽기 전용 진단(법령 API 조회).

네 가지 점검을 한 번에 돈다(법령은 1회씩만 로드):
  1·2. 타깃 존재 감사: 스코프 내 인용 타깃이 실제 조문목록에 없는 경우.
        - '결번/삭제 조'  = 번호는 범위 안인데 조문이 없음 → 삭제 조문 잔존 인용(누락방지 핵심)
        - '범위 초과'     = 최대 조번호보다 큼 → 파서 과추출 의심
  3.   범위 전개 이상치: '제X조부터 제Y조까지'가 비정상적으로 크거나 역전된 인용.
  4.   스코프 밖 타법 인용 빈도: 감시 15법령이 그 밖의 법을 얼마나 인용하는지(스코프 확장 후보).

  uv run python scripts/audit_graph_integrity.py
"""
from __future__ import annotations

import re
import sys

from core.citation_graph import _load_graph, _parse_target_ref
from core.citation_parser import (
    base_law_name,
    effective_law_name,
    parse_citations,
)
from core.law_api import get_law_text
from scripts.build_law_citation_graph import _manifest_law_names, _resolve_mst


def _norm(name: str) -> str:
    return str(name).replace(" ", "").replace("ㆍ", "").replace("·", "").strip()


def _base_num(jo: str) -> int | None:
    m = re.match(r"(\d+)", str(jo))
    return int(m.group(1)) if m else None


def main() -> int:
    from config import LAW_API_KEY

    laws = _manifest_law_names()
    scope = {_norm(n) for n in laws} | {_norm(base_law_name(n)) for n in laws}

    # 법령 1회 로드 → 유효 조번호 집합 + 본문(범위/스코프밖 점검용)
    valid: dict[str, set[str]] = {}      # norm(law) -> {full 조번호}
    max_base: dict[str, int] = {}
    articles: dict[str, list[tuple[str, str]]] = {}  # law -> [(조번호, 내용)]
    for law in laws:
        mst = _resolve_mst(law, LAW_API_KEY)
        if not mst:
            print(f"SKIP {law}: MST 없음")
            continue
        data = get_law_text(mst, LAW_API_KEY)
        arts = data.get("조문목록", [])
        nums = {str(a.get("조번호", "")).strip() for a in arts}
        valid[_norm(law)] = nums
        bases = [b for b in (_base_num(a.get("조번호", "")) for a in arts) if b]
        max_base[_norm(law)] = max(bases) if bases else 0
        articles[law] = [(str(a.get("조번호", "")), str(a.get("내용", ""))) for a in arts]

    # ── 1·2. 타깃 존재 감사 (그래프 엣지 기준) ──────────────────────────
    reverse, _ = _load_graph()
    seen_edge: set = set()
    missing_in_range: list[tuple] = []
    out_of_range: list[tuple] = []
    for bucket in reverse.values():
        for e in bucket:
            tl, tr = _norm(e.get("target_law", "")), e.get("target_ref", "")
            sig = (e.get("source_law"), e.get("source_jo"), e.get("target_law"), tr)
            if sig in seen_edge or tl not in valid:
                continue
            seen_edge.add(sig)
            jo, jo_sub, _, _ = _parse_target_ref(tr)
            if not jo:
                continue
            full = f"{jo}의{jo_sub}" if jo_sub else jo
            if full in valid[tl]:
                continue
            base = _base_num(jo) or 0
            row = (e.get("source_law"), e.get("source_jo"), e.get("target_law"), full, e.get("cite_raw", ""))
            (out_of_range if base > max_base.get(tl, 0) else missing_in_range).append(row)

    print(f"\n=== 1·2. 타깃 존재 감사 ===")
    print(f"  결번/삭제 조 인용(잔존 인용 후보): {len(missing_in_range)}건")
    print(f"  범위 초과 타깃(파서 과추출 의심): {len(out_of_range)}건")
    for r in sorted(out_of_range)[:25]:
        print(f"    [범위초과] {r[0]} 제{r[1]}조 → {r[2]} 제{r[3]}조  raw={r[4]!r}")
    print("  --- 결번/삭제 조 샘플 (잔존 인용) ---")
    for r in sorted(set(missing_in_range))[:25]:
        print(f"    {r[0]} 제{r[1]}조 → {r[2]} 제{r[3]}조  raw={r[4]!r}")

    # ── 3. 범위 전개 이상치 ────────────────────────────────────────────
    big: list[tuple] = []
    inverted: list[tuple] = []
    for law, arts in articles.items():
        for jo, content in arts:
            for c in parse_citations(content):
                if not (c.is_range and c.range_end_jo):
                    continue
                a, b = _base_num(c.jo), _base_num(c.range_end_jo)
                if a is None or b is None:
                    continue
                if b < a:
                    inverted.append((law, jo, c.raw))
                elif b - a >= 30:
                    big.append((b - a, law, jo, c.raw))

    print(f"\n=== 3. 범위 전개 이상치 ===")
    print(f"  역전 범위(끝<시작): {len(inverted)}건")
    for r in inverted[:15]:
        print(f"    {r[0]} 제{r[1]}조  raw={r[2]!r}")
    print(f"  큰 범위(>=30개 조 전개): {len(big)}건")
    for span, law, jo, raw in sorted(big, reverse=True)[:15]:
        print(f"    [{span}개] {law} 제{jo}조  raw={raw!r}")

    # ── 4. 스코프 밖 타법 인용 빈도 ────────────────────────────────────
    out_tally: dict[str, int] = {}
    for law, arts in articles.items():
        for jo, content in arts:
            for c in parse_citations(content):
                if not c.jo or c.byeolpyo:
                    continue
                eff = effective_law_name(c, law)
                n = _norm(eff)
                if n and n not in scope and n != _norm(law):
                    out_tally[eff] = out_tally.get(eff, 0) + 1

    print(f"\n=== 4. 스코프 밖 타법 인용 빈도 (상위 25, 스코프 확장 후보) ===")
    for name, cnt in sorted(out_tally.items(), key=lambda x: -x[1])[:25]:
        print(f"  {cnt:5}  {name}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
