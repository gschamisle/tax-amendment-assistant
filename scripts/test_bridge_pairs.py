# -*- coding: utf-8 -*-
"""다리 법령 기반 짝조문 도출 오프라인 테스트."""
from __future__ import annotations

import json
import sys
import tempfile
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8")

import core.bridge_pairs as bp


def _with_graph(edges: list[dict]):
    """임시 그래프 파일로 _GRAPH를 갈아끼운다."""
    tmp = Path(tempfile.mkdtemp()) / "graph.json"
    tmp.write_text(json.dumps({"edges": edges}, ensure_ascii=False), encoding="utf-8")
    return tmp


def _edge(src_law, src_jo, tgt_law, tgt_ref):
    return {"source_law": src_law, "source_jo": src_jo,
            "target_law": tgt_law, "target_ref": tgt_ref}


def test_jo_key_and_label() -> None:
    assert bp.jo_key("제156조의9제1항") == "156의9"
    assert bp.jo_key("제64조") == "64"
    assert bp.jo_key("별표 1") == ""
    assert bp.jo_label("156의9") == "제156조의9"
    assert bp.jo_label("64") == "제64조"
    print("  조번호 정규화 OK")


def test_pairs_from_cocitation() -> None:
    """한 다리 조문이 양쪽을 함께 인용하면 짝이 된다."""
    orig = bp._GRAPH
    bp._GRAPH = _with_graph([
        _edge("국제조세조정에 관한 법률", "4", "소득세법", "제41조"),
        _edge("국제조세조정에 관한 법률", "4", "법인세법", "제52조"),
        # 한쪽만 인용하는 조문은 짝을 만들지 않는다
        _edge("국제조세조정에 관한 법률", "9", "법인세법", "제66조"),
        # 다리가 아닌 법의 인용은 무시
        _edge("부가가치세법", "1", "소득세법", "제1조"),
    ])
    try:
        pairs = bp.extract(("국제조세조정에 관한 법률",), ("소득세법", "법인세법"))
    finally:
        bp._GRAPH = orig

    assert len(pairs) == 1, pairs
    p = pairs[0]
    assert (p.jo_a, p.jo_b) == ("41", "52"), (p.jo_a, p.jo_b)
    assert p.bridges == [("국제조세조정에 관한 법률", "4")], p.bridges
    assert p.weight == 1
    print("  공동 인용 → 짝 도출 OK")


def test_listing_articles_are_excluded() -> None:
    """감면 대상을 수십 개 늘어놓는 조문은 짝 신호가 아니다."""
    orig = bp._GRAPH
    many = [_edge("조세특례제한법", "1", "소득세법", f"제{n}조") for n in range(1, 9)]
    many.append(_edge("조세특례제한법", "1", "법인세법", "제64조"))
    bp._GRAPH = _with_graph(many)
    try:
        pairs = bp.extract(("조세특례제한법",), ("소득세법", "법인세법"), max_refs=6)
    finally:
        bp._GRAPH = orig
    assert pairs == [], pairs                     # 8 > 6 → 제외
    print("  나열형 조문 제외 OK")


def test_weight_counts_distinct_bridges() -> None:
    orig = bp._GRAPH
    bp._GRAPH = _with_graph([
        _edge("조세특례제한법", "33", "소득세법", "제111조"),
        _edge("조세특례제한법", "33", "법인세법", "제64조"),
        _edge("조세특례제한법", "97의6", "소득세법", "제111조"),
        _edge("조세특례제한법", "97의6", "법인세법", "제64조"),
    ])
    try:
        pairs = bp.extract(("조세특례제한법",), ("소득세법", "법인세법"))
    finally:
        bp._GRAPH = orig
    assert len(pairs) == 1 and pairs[0].weight == 2, pairs
    print("  다리 개수 집계 OK")


def main() -> int:
    tests = [fn for name, fn in sorted(globals().items())
             if name.startswith("test_") and callable(fn)]
    for fn in tests:
        fn()
    print(f"ALL OK (bridge_pairs, {len(tests)} tests)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
