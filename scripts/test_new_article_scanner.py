"""신설 조문 검토 오프라인 테스트 — ○○세액공제(제29조~제29조의8) 시나리오."""
from __future__ import annotations

import sys

from core.citation_graph import graph_available
from core.new_article_scanner import (
    forward_citations,
    parse_jo_tokens,
    proxy_checklist,
    review_new_articles,
    stale_citation_conflicts,
)

DRAFT = (
    "제29조(○○세액공제) ① 내국인이 「소득세법」 제19조에 따른 사업소득 또는 "
    "「법인세법」 제4조에 따른 각 사업연도 소득이 있는 경우로서 대상 물품을 "
    "국내에서 생산하여 판매하는 경우에는 제29조의2에 따라 계산한 금액을 "
    "같은 법 제55조에 따른 세율을 적용한 산출세액의 범위에서 공제한다.\n"
    "제29조의2(공제금액의 계산) ① 법 제29조제1항의 공제금액은 생산량에 "
    "단위당 공제액을 곱하여 계산한다."
)


def test_parse_jo_tokens() -> None:
    assert parse_jo_tokens("24") == [("24", "")]
    assert parse_jo_tokens("29의8") == [("29", "8")]
    assert parse_jo_tokens("제29조의2") == [("29", "2")]
    assert parse_jo_tokens("24, 25의6") == [("24", ""), ("25", "6")]

    expanded = parse_jo_tokens("29~29의8")
    assert expanded[0] == ("29", "") and expanded[-1] == ("29", "8")
    # 본조 + 의2~의8 ('제29조의1'은 존재하지 않는 형식이므로 제외)
    assert len(expanded) == 8, expanded
    assert ("29", "1") not in expanded

    assert parse_jo_tokens("제29조부터 제29조의8까지") == expanded


def test_forward_citations() -> None:
    jo_list = parse_jo_tokens("29~29의8")
    rows = forward_citations(DRAFT, "조세특례제한법", jo_list)

    by_ref = {(r["법령명"], r["조문"]): r for r in rows}
    assert ("소득세법", "제19조") in by_ref
    assert ("법인세법", "제4조") in by_ref
    # "같은 법 제55조" → 직전 명시 법령(법인세법)으로 해석
    assert ("법인세법", "제55조") in by_ref

    # 신설 범위 내 상호 인용 표시: 제29조의2, "법 제29조제1항"(조특법 자기참조)
    internal = [r for r in rows if r["신설범위내"]]
    internal_refs = {r["조문"] for r in internal}
    assert "제29조의2" in internal_refs, internal_refs
    assert any(r["조문"].startswith("제29조제1항") for r in internal), internal
    # 외부 인용은 신설범위내 플래그가 없어야 한다
    assert not by_ref[("소득세법", "제19조")]["신설범위내"]


def test_stale_conflicts() -> None:
    assert graph_available(), "data/law-citation-graph.json 필요"
    jo_list = parse_jo_tokens("29~29의8")
    rows = stale_citation_conflicts("조세특례제한법", jo_list)
    assert rows, "구 제29조대 잔존 인용이 있어야 한다"

    sources = {(r["법령명"], str(r["조번호"])) for r in rows}
    # 열거형 조문(중복지원 배제·최저한세)은 구 조문 인용이 남아 있다
    assert ("조세특례제한법", "127") in sources, sources
    assert ("조세특례제한법", "132") in sources, sources

    # 신설 범위 내부 조문은 소스에서 제외된다
    range_keys = {f"{jo}의{sub}" if sub else jo for jo, sub in jo_list}
    assert not any(
        law == "조세특례제한법" and jo in range_keys for law, jo in sources
    ), sources

    # 대상·인용 구문이 채워져 있다
    sample = next(r for r in rows if str(r["조번호"]) == "127")
    assert sample["대상"] and sample["인용"], sample


def test_proxy_checklist() -> None:
    rows = proxy_checklist("조세특례제한법", parse_jo_tokens("24"))
    sources = {(r["법령명"], str(r["조번호"])) for r in rows}
    # 세액공제 신설 체크리스트의 정형 항목들
    assert ("조세특례제한법", "127") in sources, sources   # 중복지원 배제
    assert ("조세특례제한법", "132") in sources, sources   # 최저한세
    assert ("조세특례제한법", "144") in sources, sources   # 이월공제
    # 프록시 자기 자신은 제외
    assert ("조세특례제한법", "24") not in sources


def test_review_bundle() -> None:
    result = review_new_articles("조세특례제한법", "29~29의8", DRAFT, "24")
    assert result["graph_ok"]
    assert len(result["jo_list"]) == 8
    assert result["forward"] and result["stale"] and result["proxy"]
    # 조문안·프록시 미입력 시에도 죽지 않는다
    empty = review_new_articles("조세특례제한법", "29", "", "")
    assert empty["forward"] == [] and empty["proxy"] == []


def main() -> int:
    test_parse_jo_tokens()
    test_forward_citations()
    test_stale_conflicts()
    test_proxy_checklist()
    test_review_bundle()
    print("ALL OK")
    return 0


if __name__ == "__main__":
    sys.exit(main())
