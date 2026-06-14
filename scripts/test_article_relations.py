# -*- coding: utf-8 -*-
"""개정 조문 연관 4분류(article_relations) 오프라인 테스트.

역인용·병행은 커밋된 그래프/매트릭스(공개 현행법)에 대해 검증한다.
"""
from __future__ import annotations

import sys

from core.article_relations import analyze_article_relations


def test_forward_split_cited_vs_junyo() -> None:
    text = (
        "내국인이 「소득세법」 제19조에 따른 사업소득이 있는 경우 제24조에 따라 계산하며, "
        "이 경우 「법인세법」 제55조를 준용한다."
    )
    r = analyze_article_relations("조세특례제한법", "29", text)
    cited = {(x["법령명"], x["조문"]) for x in r["cited"]}
    junyong = {(x["법령명"], x["조문"]) for x in r["junyong"]}
    assert ("소득세법", "제19조") in cited, cited
    assert ("조세특례제한법", "제24조") in cited, cited
    assert ("법인세법", "제55조") in junyong, junyong
    # 준용은 인용 박스에 중복 노출되지 않는다
    assert ("법인세법", "제55조") not in cited, cited


def test_back_citation_real_graph() -> None:
    r = analyze_article_relations("소득세법", "127", "")
    assert r["graph_ok"]
    # 현행법에서 소득세법 제127조를 인용하는 조문들이 잡힌다
    assert r["back_cited"], "역인용 0건 — 그래프 회귀 의심"
    # 자기 자신은 제외
    assert not any(
        x["법령명"] == "소득세법" and x["조번호"] == "127" for x in r["back_cited"]
    )


def test_parallel_real_matrix() -> None:
    r = analyze_article_relations("소득세법", "127", "")
    assert r["matrix_ok"]
    # 소득세법 제127조 ↔ 법인세법 제73조 (원천징수 병행) 가 매트릭스에 있음
    pairs = {(x["법령명"], x["조문"]) for x in r["parallel"]}
    assert ("법인세법", "제73조") in pairs, pairs
    # 병행 박스는 parallel_tax_law만 — 역인용/citation 섞이지 않음
    assert all(x.get("근거") for x in r["parallel"])


def test_target_label() -> None:
    r = analyze_article_relations("소득세법", "10", "", hang="1", ho="2")
    assert r["target_label"] == "제10조제1항제2호", r["target_label"]
    r2 = analyze_article_relations("조세특례제한법", "27의2", "")
    assert r2["target_label"] == "제27조의2", r2["target_label"]


def test_enum_prefix_strip() -> None:
    from ui.article_relations_ui import _strip_enum_prefix

    assert _strip_enum_prefix("2. 블라블라") == "블라블라"
    assert _strip_enum_prefix("② 블라블라") == "블라블라"
    assert _strip_enum_prefix("가. 블라블라") == "블라블라"
    assert _strip_enum_prefix("제2호 블라블라") == "블라블라"
    # 번호 없이 내용만 — 그대로
    assert _strip_enum_prefix("블라블라") == "블라블라"
    # 본문 중간의 숫자는 건드리지 않음
    assert _strip_enum_prefix("「소득세법」 제19조에 따른") == "「소득세법」 제19조에 따른"


def test_empty_text_no_forward() -> None:
    r = analyze_article_relations("소득세법", "55", "")
    assert r["cited"] == [] and r["junyong"] == []
    # 본문 없이도 역인용·병행은 조회된다
    assert isinstance(r["back_cited"], list) and isinstance(r["parallel"], list)


def main() -> int:
    test_forward_split_cited_vs_junyo()
    test_back_citation_real_graph()
    test_parallel_real_matrix()
    test_target_label()
    test_enum_prefix_strip()
    test_empty_text_no_forward()
    print("ALL OK")
    return 0


if __name__ == "__main__":
    sys.exit(main())
