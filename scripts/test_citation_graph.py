"""인용 그래프 스모크·129조 역인용 테스트."""
from __future__ import annotations

import sys

from core.citation_graph import back_citation_hits, graph_available, graph_meta
from core.citation_parser import Citation
from scripts.build_law_citation_graph import _expand_target_refs


def test_expand_target_refs() -> None:
    # 비범위 인용은 단일 ref, via_range=False
    assert _expand_target_refs(Citation(raw="", jo="45")) == [("제45조", False)]

    # 기준조 단위 범위: 제2조~제8조 → 제2조..제8조 전부, via_range=True
    rng = Citation(raw="", jo="2", is_range=True, range_end_jo="8")
    refs = _expand_target_refs(rng)
    assert [r for r, _ in refs] == [f"제{j}조" for j in range(2, 9)], refs
    assert all(v for _, v in refs)

    # 동일 기준조 가지번호 범위: 제3조의2~제3조의5 → 의2..의5
    sub = Citation(raw="", jo="3", jo_sub="2", is_range=True,
                   range_end_jo="3", range_end_jo_sub="5")
    assert [r for r, _ in _expand_target_refs(sub)] == [f"제3조의{s}" for s in range(2, 6)]

    # 병적으로 큰 범위는 전개하지 않고 시작 ref만 (방어)
    big = Citation(raw="", jo="1", is_range=True, range_end_jo="500")
    assert _expand_target_refs(big) == [("제1조", False)]


def main() -> int:
    test_expand_target_refs()
    if not graph_available():
        print("SKIP: law-citation-graph.json 없음 — build_law_citation_graph.py 실행 필요")
        return 0

    meta = graph_meta()
    assert meta.get("edge_count", 0) > 0, meta
    assert "소득세법" in meta.get("laws", []), meta

    hits = back_citation_hits("소득세법", "129", "", "1", "3")
    # 제129조제1항제3호를 직접 인용하는 조문이 그래프에 있으면 역인용 1건 이상
    if hits:
        laws = {h.get("법령명") for h in hits}
        assert "소득세법" in laws or "소득세법 시행령" in laws, hits

    print(f"ALL OK (edges={meta.get('edge_count')}, back_hits_129={len(hits)})")
    return 0


if __name__ == "__main__":
    sys.exit(main())
