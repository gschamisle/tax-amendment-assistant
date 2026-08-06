"""인용 파서 오프라인 테스트 — 지시적(법/영/규칙 제X조) 참조 중심."""
from __future__ import annotations

import sys

from core.citation_parser import (
    Citation,
    _article_range_covers,
    base_law_name,
    effective_law_name,
    find_back_citations,
    parse_citations,
    resolve_deictic_law,
)
from core.law_network import _choose_entry, _citation_matches, related_law_names


def _one(text: str, **attrs) -> Citation:
    cites = parse_citations(text)
    matched = [c for c in cites if all(getattr(c, k) == v for k, v in attrs.items())]
    assert matched, f"{attrs} not found in {[(c.raw, c.law_name, c.relative) for c in cites]}"
    return matched[0]


def test_deictic_parsing() -> None:
    # 시행령 → 모법: "법 제127조제1항제3호"
    c = _one("법 제127조제1항제3호에서 \"대통령령으로 정하는 사업소득\"이란 ...", jo="127")
    assert c.relative == "법" and c.law_name == "법", (c.law_name, c.relative)
    assert (c.hang, c.ho) == ("1", "3")

    # 시행규칙 → 시행령: "영 제184조"
    c = _one("영 제184조에 따른 소득을 말한다.", jo="184")
    assert c.relative == "영"

    # 자기 참조: "이 영 제15조의2"
    c = _one("이 영 제15조의2를 준용한다.", jo="15")
    assert c.relative == "이영" and c.jo_sub == "2"

    # 명시 법령명은 지시적으로 오인하지 않는다 (끝글자 '법')
    c = _one("소득세법 제127조에 따라 ...", jo="127")
    assert c.law_name == "소득세법" and c.relative == "", (c.law_name, c.relative)
    assert not any(x.relative == "법" for x in parse_citations("소득세법 제127조"))

    # 산문 뒤 단독 지시어(이 경우 법 / 이란 법 / 및 영)는 명시 법령명이 아니라 지시참조
    c = _one("이 경우 법 제5조를 적용한다", jo="5")
    assert c.relative == "법" and effective_law_name(c, "법인세법 시행령") == "법인세법", c.law_name
    c = _one('"외국법인"이란 법 제2조에 따른', jo="2")
    assert c.relative == "법" and effective_law_name(c, "소득세법 시행령") == "소득세법"
    c = _one("제3항 및 영 제5조", jo="5")
    assert c.relative == "영" and effective_law_name(c, "법인세법") == "법인세법 시행령"
    # 진짜 법령명(지시어 앞에 내용 음절)은 그대로 명시 인용
    c = _one("상속세 및 증여세법 제60조", jo="60")
    assert c.law_name == "상속세 및 증여세법" and c.relative == ""

    # 낫표 인용도 그대로
    c = _one("「부가가치세법」 제26조제1항제5호 ...", jo="26")
    assert c.law_name == "부가가치세법" and c.relative == ""

    # '같은 법'은 기존 SAME_LAW 경로 유지
    c = _one("「소득세법」 제20조 및 같은 법 제27조 ...", jo="27")
    assert c.relative == "같은법" and c.law_name == "소득세법"


def test_deictic_resolution() -> None:
    assert base_law_name("소득세법 시행령") == "소득세법"
    assert base_law_name("소득세법 시행규칙") == "소득세법"
    assert base_law_name("소득세법") == "소득세법"

    assert resolve_deictic_law("법", "소득세법 시행령") == "소득세법"
    assert resolve_deictic_law("법", "소득세법") == "소득세법"
    assert resolve_deictic_law("영", "소득세법 시행규칙") == "소득세법 시행령"
    assert resolve_deictic_law("이영", "소득세법 시행령") == "소득세법 시행령"
    assert resolve_deictic_law("규칙", "소득세법 시행령") == "소득세법 시행규칙"

    c = parse_citations("법 제129조제1항에 따라 ...")[0]
    assert effective_law_name(c, "소득세법 시행령") == "소득세법"


def test_citation_matches_cross_law() -> None:
    c = parse_citations("법 제129조제1항의 세율을 적용한다.")[0]
    # 시행령 조문 안의 '법 제129조' → 소득세법 제129조 인용으로 매칭
    assert _citation_matches(c, "소득세법 시행령", "소득세법", "129", "", "1")
    # 시행령 자신의 제129조 인용으로는 매칭되지 않아야 한다
    assert not _citation_matches(c, "소득세법 시행령", "소득세법 시행령", "129")


def test_find_back_citations_deictic() -> None:
    decree = {
        "법령명": "소득세법 시행령",
        "조문목록": [
            {"조번호": "184", "제목": "사업소득", "내용": "법 제127조제1항제3호에 따른 소득."},
            {"조번호": "20", "제목": "내부인용", "내용": "제5조제1항을 준용한다."},
        ],
    }
    # '법 제127조'는 모법 인용 — 시행령 내부 127조 역인용으로 잡히면 안 됨
    assert find_back_citations(decree, "127") == []
    # 내부 인용은 그대로 탐지
    hits = find_back_citations(decree, "5")
    assert len(hits) == 1 and hits[0]["조번호"] == "20"

    law = {
        "법령명": "소득세법",
        "조문목록": [
            {"조번호": "144", "제목": "원천징수", "내용": "제129조에 따른 원천징수세율을 적용한다."},
            {"조번호": "90", "제목": "타법", "내용": "「법인세법」 제129조에 따른다."},
        ],
    }
    hits = find_back_citations(law, "129")
    # 명시 타법(법인세법) 인용은 제외, 본법 내부 인용만
    assert [h["조번호"] for h in hits] == ["144"], hits


def test_naeji_range_parsing() -> None:
    # 구식 조 범위 '내지' — 단일 범위 인용으로 파싱되고 양끝 조문은 따로 안 잡힘
    cites = parse_citations("제2조 내지 제8조의 규정을 준용한다.")
    ranges = [c for c in cites if c.is_range and c.range_end_jo]
    assert len(ranges) == 1, [(c.raw, c.jo, c.range_end_jo) for c in cites]
    r = ranges[0]
    assert (r.jo, r.range_end_jo) == ("2", "8"), (r.jo, r.range_end_jo)
    # 끝점이 DIRECT로 중복 포착되지 않음 (범위 1건뿐)
    assert len([c for c in cites if c.jo in ("2", "8")]) == 1

    # 가지번호 내지: 제3조의2 내지 제3조의5
    c = _one("제3조의2 내지 제3조의5까지 적용한다.", jo="3", is_range=True)
    assert (c.jo_sub, c.range_end_jo, c.range_end_jo_sub) == ("2", "3", "5")

    # 항 범위 내지: 제1항 내지 제3항 → hang/hang_end
    c = _one("제127조제1항 제2호 및 제1항 내지 제3항", hang="1", hang_end="3")
    assert c.is_range and c.hang == "1" and c.hang_end == "3"

    # 부칙 앞 '내지' 범위는 본문 조문으로 잡지 않음
    assert not any(
        c.is_range and c.range_end_jo
        for c in parse_citations("법률 제6538호 부칙 제2조 내지 제8조")
    )


def test_article_range_covers() -> None:
    # 기준조 단위 범위: 제2조~제8조는 제5조, 그 사이 가지번호(제5조의2)도 포함
    r = Citation(raw="", jo="2", is_range=True, range_end_jo="8")
    assert _article_range_covers(r, "5")
    assert _article_range_covers(r, "5", "2")   # 제5조의2도 사이값 → 포함
    assert not _article_range_covers(r, "9")
    assert not _article_range_covers(r, "1")

    # 동일 기준조 가지번호 범위: 제3조의2~제3조의5
    sub = Citation(raw="", jo="3", jo_sub="2", is_range=True,
                   range_end_jo="3", range_end_jo_sub="5")
    assert _article_range_covers(sub, "3", "3")
    assert not _article_range_covers(sub, "3", "6")
    assert not _article_range_covers(sub, "4")

    # 범위가 아니면 False
    assert not _article_range_covers(Citation(raw="", jo="2"), "2")


def test_range_expansion_back_citations() -> None:
    law = {
        "법령명": "조세특례제한법",
        "조문목록": [
            {"조번호": "10", "제목": "부터까지", "내용": "제2조부터 제8조까지의 규정에 따른다."},
            {"조번호": "11", "제목": "내지", "내용": "제2조 내지 제8조를 준용한다."},
            {"조번호": "12", "제목": "무관", "내용": "제20조에 따른다."},
        ],
    }
    # target 제5조는 두 범위(부터까지·내지) 안에 있으므로 10·11이 잡혀야 한다
    hits = find_back_citations(law, "5")
    nums = sorted(h["조번호"] for h in hits)
    assert nums == ["10", "11"], nums
    # 범위로 잡힌 건 via_range 플래그가 선다
    for h in hits:
        assert any(cite["via_range"] for cite in h["인용"]), h

    # target 제20조는 단일 인용(12)만, 범위(10·11)에는 미포함
    hits20 = find_back_citations(law, "20")
    assert [h["조번호"] for h in hits20] == ["12"], hits20
    assert not hits20[0]["인용"][0]["via_range"]


def test_citation_matches_range_subarticle() -> None:
    # P1①: 통조 범위(제2조~제8조)가 가지번호 타깃(제5조의2)도 포함 — law_network 일관성
    c = parse_citations("제2조부터 제8조까지를 준용한다.")[0]
    assert _citation_matches(c, "소득세법", "소득세법", "5", "2")
    assert _citation_matches(c, "소득세법", "소득세법", "5")
    assert not _citation_matches(c, "소득세법", "소득세법", "9")
    # 내지 표현도 동일하게 동작
    c2 = parse_citations("제2조 내지 제8조")[0]
    assert _citation_matches(c2, "소득세법", "소득세법", "5", "2")
    # 비범위 단일 인용은 정확 일치만
    c3 = parse_citations("제5조")[0]
    assert _citation_matches(c3, "소득세법", "소득세법", "5")
    assert not _citation_matches(c3, "소득세법", "소득세법", "5", "2")


def test_range_inherits_cross_law_name() -> None:
    # 회귀: '「법인세법」 제13조부터 제54조까지'의 범위가 source 법령(조특법)으로
    # 오귀속되면 안 됨 — 조특법 제104조의10(해운기업) 잔존인용 오탐 사례.
    text = "비해운소득에 대해서는 「법인세법」 제13조부터 제54조까지의 규정에 따라 계산한 금액"
    rng = _one(text, is_range=True, range_end_jo="54")
    assert rng.law_name == "법인세법", rng.law_name
    assert effective_law_name(rng, "조세특례제한법") == "법인세법"

    # 법령명이 없는 범위는 종전대로 source 법령으로 해석(과소포착 방지)
    plain = parse_citations("제3조부터 제9조까지의 규정에도 불구하고")[0]
    assert plain.law_name == "" and effective_law_name(plain, "조세특례제한법") == "조세특례제한법"

    # '같은 법' 범위는 relative를 물려받아 선행 명시 법령으로 해석된다
    same = _one("「소득세법」 제20조 및 같은 법 제5조부터 제8조까지", is_range=True)
    assert same.relative == "같은법" and same.law_name == "소득세법"

    # find_back_citations: 타법 범위는 동일법령 역인용으로 잡히면 안 됨
    law = {
        "법령명": "조세특례제한법",
        "조문목록": [
            {"조번호": "104의10", "제목": "해운기업",
             "내용": "「법인세법」 제13조부터 제54조까지의 규정에 따라 계산한 금액"},
        ],
    }
    assert find_back_citations(law, "29") == []
    assert find_back_citations(law, "24") == []


def test_enumerated_cross_law_name() -> None:
    # 회귀: '「부가가치세법」 제9조 및 제10조'의 제10조가 source(조특법)로 새면 안 됨
    text = "「부가가치세법」 제9조 및 제10조에 따른 재화의 공급으로 보지 아니한다."
    c10 = _one(text, jo="10")
    assert effective_law_name(c10, "조세특례제한법") == "부가가치세법", c10.law_name

    # 콤마·및 혼합 연쇄 전파: 제20조·제21조 모두 소득세법
    cites = parse_citations("「소득세법」 제19조, 제20조 및 제21조")
    for jo in ("19", "20", "21"):
        c = next(x for x in cites if x.jo == jo)
        assert effective_law_name(c, "조세특례제한법") == "소득세법", (jo, c.law_name)

    # 지시참조도 전파: 시행령 '법 제9조 및 제10조' → 둘 다 모법
    c = _one("법 제9조 및 제10조", jo="10")
    assert effective_law_name(c, "소득세법 시행령") == "소득세법"

    # 연결어 앞에 위치어(본문·전단·후단·단서·각 호)가 껴도 전파한다
    c = _one("「부가가치세법」 제48조제3항 본문 및 제66조제1항", jo="66")
    assert effective_law_name(c, "조세특례제한법") == "부가가치세법", c.law_name
    c = _one("「소득세법」 제162조의2제4항 후단ㆍ제162조의3제6항", jo="162", jo_sub="3")
    assert effective_law_name(c, "조세특례제한법") == "소득세법", c.law_name

    # 중간에 항 열거('제3항ㆍ제4항')가 껴도 jo 앵커를 건너짚어 전파한다
    c = _one("법 제33조제3항ㆍ제4항 및 제34조제4항", jo="34")
    assert effective_law_name(c, "법인세법 시행령") == "법인세법", c.law_name
    c = _one("「부가가치세법」 제32조제1항ㆍ제7항 및 제35조제1항", jo="35")
    assert effective_law_name(c, "조세특례제한법") == "부가가치세법", c.law_name

    # 범위 인용 뒤 콤마 열거도 전파 ('제64조제2항부터 제4항까지, 제66조')
    c = _one("「소득세법 시행령」 제62조제1항 후단, 제64조제2항부터 제4항까지, 제66조", jo="66")
    assert effective_law_name(c, "조세특례제한법 시행령") == "소득세법 시행령", c.law_name

    # 자기 법령 정의 참조 '(이하 이 조 및 제95조의2에서 같다)'는 전파 안 함(산문)
    c = _one("분양권(이하 이 조 및 제95조의2에서 같다)", jo="95", jo_sub="2")
    assert effective_law_name(c, "법인세법") == "법인세법", c.law_name

    # 연결어가 아니라 다른 텍스트가 끼면 전파하지 않는다(과탐 방지)
    c = _one("「소득세법」 제19조에 따른 사업소득 및 제20조", jo="20")
    assert effective_law_name(c, "조세특례제한법") == "조세특례제한법", c.law_name
    c = _one("「소득세법」 제19조에 따른 본문 및 제20조", jo="20")
    assert effective_law_name(c, "조세특례제한법") == "조세특례제한법", c.law_name

    # find_back_citations: 타법 열거의 뒤 조문은 동일법 역인용으로 잡히면 안 됨
    law = {
        "법령명": "조세특례제한법",
        "조문목록": [
            {"조번호": "104의7", "제목": "정비사업조합",
             "내용": "「부가가치세법」 제9조 및 제10조에 따른 재화의 공급으로 보지 아니한다."},
        ],
    }
    assert find_back_citations(law, "10") == []
    assert find_back_citations(law, "9") == []


def test_enumeration_chain_survives_fillers() -> None:
    """열거 체인이 부스러기(항·호 범위, 괄호 한정, 호 가지번호)에서 끊기면 안 된다.

    끊기면 뒤 조문이 출처법으로 오귀속돼, 존재하지도 않는 자기 조문을 가리키는
    유령 엣지가 인용 그래프에 실린다 (농어촌특별세법 시행령 제4조에서 실제 발생).
    """
    # ① 앞 인용에 딸린 호 범위('제93조제4호부터 제7호까지')를 건너뛴다
    text = ("「관세법」 제88조, 제92조, 제93조제4호부터 제7호까지 및 "
            "제9호부터 제14호까지, 제94조, 제96조부터 제101조까지의 규정")
    for jo in ("92", "94", "96"):
        c = _one(text, jo=jo)
        assert effective_law_name(c, "농어촌특별세법 시행령") == "관세법", (jo, c.law_name)

    # ② 괄호·대괄호 한정어구를 건너뛴다
    text = ("「조세특례제한법」 제66조부터 제70조까지, "
            "제72조제1항(제1호, 제5호 및 제8호의 법인은 제외한다), "
            "제77조[「조세특례제한법」 제69조제1항 본문에 따른 토지로 한정한다] 및 제102조")
    for jo in ("77", "102"):
        c = _one(text, jo=jo)
        assert effective_law_name(c, "농어촌특별세법 시행령") == "조세특례제한법", (jo, c.law_name)

    # ③ 호 가지번호 꼬리('제1호의2')를 건너뛴다
    text = "「지방세특례제한법」 제13조제2항제1호의2, 제15조제2항, 제16조제1항, 제17조"
    for jo in ("15", "16", "17"):
        c = _one(text, jo=jo)
        assert effective_law_name(c, "농어촌특별세법 시행령") == "지방세특례제한법", (jo, c.law_name)

    # ④ 항 범위 인용 자체도 법령명을 물려받고, 뒤 열거의 앵커가 된다
    text = "「지방세법」 제9조제3항부터 제5항까지, 제15조제1항제1호부터 제4호까지 및 제26조제2항"
    for jo in ("9", "15", "26"):
        c = _one(text, jo=jo)
        assert effective_law_name(c, "농어촌특별세법 시행령") == "지방세법", (jo, c.law_name)

    # ⑤ '각 호 외의 부분'도 부스러기
    c = _one("「법인세법」 제10조제1항 각 호 외의 부분 및 제20조", jo="20")
    assert effective_law_name(c, "소득세법 시행령") == "법인세법", c.law_name

    # ⑥ 과탐 방지는 유지 — 실질 어구가 끼면 전파하지 않는다
    c = _one("「법인세법」 제10조를 적용할 때 상시근로자의 범위 및 제20조", jo="20")
    assert effective_law_name(c, "소득세법 시행령") == "소득세법 시행령", c.law_name
    c = _one("「법인세법」 제10조에 따른 소득과 이 영 제20조에 따른 금액", jo="20")
    assert effective_law_name(c, "소득세법 시행령") == "소득세법 시행령", c.law_name


def test_related_law_names_normalized() -> None:
    # P1③: 공백 없는 법령명 표기로도 병행 법령군이 채워진다
    rel = {n.replace(" ", "") for n in related_law_names("상속세및증여세법")}
    assert "법인세법" in rel and "소득세법" in rel, rel
    # 정상 표기도 동일하게 동작
    rel2 = {n.replace(" ", "") for n in related_law_names("상속세 및 증여세법")}
    assert "법인세법" in rel2 and "소득세법" in rel2, rel2


def test_choose_entry_fuzzy() -> None:
    # P2: 정확매칭이 있으면 fuzzy=False
    results = [{"법령명": "소득세법 시행령", "MST": "1"}, {"법령명": "소득세법", "MST": "2"}]
    chosen, fuzzy = _choose_entry(results, "소득세법")
    assert chosen["MST"] == "2" and fuzzy is False
    # 정확매칭이 없으면 첫 결과를 쓰되 fuzzy=True (침묵 폴백 방지 신호)
    chosen, fuzzy = _choose_entry(results, "없는법")
    assert chosen["MST"] == "1" and fuzzy is True
    # 결과 없음
    assert _choose_entry([], "x") == (None, False)


def main() -> int:
    test_deictic_parsing()
    test_deictic_resolution()
    test_citation_matches_cross_law()
    test_find_back_citations_deictic()
    test_naeji_range_parsing()
    test_article_range_covers()
    test_range_expansion_back_citations()
    test_citation_matches_range_subarticle()
    test_range_inherits_cross_law_name()
    test_enumerated_cross_law_name()
    test_related_law_names_normalized()
    test_choose_entry_fuzzy()
    print("ALL OK")
    return 0


if __name__ == "__main__":
    sys.exit(main())
