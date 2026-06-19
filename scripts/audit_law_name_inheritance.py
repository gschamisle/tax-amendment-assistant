"""법령명 오귀속 감사 — '「타법」 제X조 <연결> 제Y조'에서 제Y조가 source 법령으로
샌(법령명 전파 실패) 후보를 전 법령에서 찾는다.

각 조문을 파싱한 뒤, 같은 문장에서 '앞에 타법 인용이 있는데 법령명 없이 source로
귀속된 맨 조번호 인용'을 모은다. 두 인용 사이의 연결어구(gap)로 분류해
  - 순수 연결어/범위(이미 수정됨)  → 0이어야 정상(회귀 감시)
  - 그 밖의 어구                  → 남은 오탐 후보(사람 판단 필요)
를 구분한다. 읽기 전용 진단(네트워크로 법령 조회).

  uv run python scripts/audit_law_name_inheritance.py
"""
from __future__ import annotations

import re
import sys

from core.citation_parser import (
    _is_connective,
    _norm_law,
    _sentence_start,
    base_law_name,
    effective_law_name,
    parse_citations,
)
from scripts.build_law_citation_graph import _manifest_law_names, _resolve_mst
from core.law_api import get_law_text


def _gap_kind(gap: str) -> str:
    # 파서가 전파에 쓰는 판정과 동일한 기준. 연결성 gap은 이미 parse 단계에서 전파되므로
    # 여기서 '연결'로 잡히면 회귀(전파 누락)다.
    return "연결(전파 대상)" if _is_connective(gap) else "산문(정상 추정)"


def _is_bare_source(cite, source_law: str) -> bool:
    """법령명 없이(맨 제X조) source 법령으로 귀속된 인용인가."""
    if not cite.jo or cite.byeolpyo:
        return False
    if cite.law_name or cite.relative:
        return False
    return effective_law_name(cite, source_law) == source_law


def audit_article(text: str, source_law: str) -> list[dict]:
    cites = [c for c in parse_citations(text) if c.jo]
    flags: list[dict] = []
    for idx, cur in enumerate(cites):
        if not _is_bare_source(cur, source_law):
            continue
        sent_start = _sentence_start(text, cur.span[0])
        # 같은 문장의 직전 인용
        prev = None
        for p in reversed(cites[:idx]):
            if p.span[0] >= sent_start:
                prev = p
                break
        if prev is None:
            continue
        prev_law = effective_law_name(prev, source_law)
        if _norm_law(prev_law) == _norm_law(source_law):
            continue  # 앞도 source 법령 — 정상적인 본법 인용
        gap = text[prev.span[1]:cur.span[0]]
        flags.append({
            "prev": prev.raw,
            "prev_law": prev_law,
            "cur": cur.raw,
            "gap": gap,
            "kind": _gap_kind(gap),
        })
    return flags


def main() -> int:
    from config import LAW_API_KEY

    scope = {_norm_law(n) for n in _manifest_law_names()}
    scope |= {_norm_law(base_law_name(n)) for n in _manifest_law_names()}

    kinds: dict[str, int] = {}
    actionable: list[dict] = []  # 스코프 내 타법 + 연결어/연결어+위치어 = 진짜 누락 후보

    for law_name in _manifest_law_names():
        mst = _resolve_mst(law_name, LAW_API_KEY)
        if not mst:
            print(f"SKIP {law_name}: MST 없음")
            continue
        data = get_law_text(mst, LAW_API_KEY)
        for art in data.get("조문목록", []):
            for f in audit_article(str(art.get("내용", "")), law_name):
                kinds[f["kind"]] = kinds.get(f["kind"], 0) + 1
                in_scope = _norm_law(f["prev_law"]) in scope
                if in_scope and f["kind"] != "산문(정상 추정)":
                    f["law"] = law_name
                    f["jo"] = art.get("조번호")
                    actionable.append(f)

    print("\n=== gap 유형별 후보 수 (전체) ===")
    for k, n in sorted(kinds.items(), key=lambda x: -x[1]):
        print(f"  {n:5}  {k}")
    print(f"\n=== 조치 가능 후보(스코프 내 타법 + 연결어류) {len(actionable)}건 ===")
    for s in actionable:
        print(f"  [{s['kind']}] {s['law']} 제{s['jo']}조: {s['prev']}({s['prev_law']}) ‖{re.sub(chr(10),' ',s['gap'])!r}‖ {s['cur']}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
