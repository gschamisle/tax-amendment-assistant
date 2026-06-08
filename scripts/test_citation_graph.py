"""인용 그래프 스모크·129조 역인용 테스트."""
from __future__ import annotations

import sys

from core.citation_graph import back_citation_hits, graph_available, graph_meta


def main() -> int:
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
