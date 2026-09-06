"""의견 군집화·태깅·리포트 테스트 (API 키 불필요).

핵심 계약 4가지를 검증한다:
  1. 같은 취지 의견이 같은 군집에 모이고, 다른 취지가 섞이지 않는다(purity)
  2. 완전 중복이 하나의 군집으로 접히고 건수가 보존된다
  3. 인사말만 같은 서로 다른 의견이 상투구 제거로 갈라진다
  4. 같은 입력이면 항상 같은 결과가 나온다(결정성) — 보고자료의 전제
"""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

from core.opinion_cluster import OpinionDoc, cluster_opinions  # noqa: E402
from core.opinion_normalize import (  # noqa: E402
    boilerplate_sentences,
    char_ngrams,
    norm_text,
    strip_boilerplate,
    word_terms,
)
from core.opinion_report import build_views, render_markdown, write_clusters_csv, write_members_csv  # noqa: E402
from core.opinion_source import load_from_files  # noqa: E402
from core.opinion_tagging import (  # noqa: E402
    classify_stance,
    deterministic_label,
    issue_tags,
    related_articles,
)

FIXTURES = ROOT / "data" / "opinion-fixtures"

TEMPLATES = {
    "A": "1세대 1주택자에 대한 종합부동산세는 폐지되어야 합니다. 실거주 목적으로 보유한 주택에 세금을 매기는 것은 부당합니다.",
    "B": "공정시장가액비율을 60%로 인하하여 주십시오. 공시가격 급등으로 세부담이 감당하기 어려운 수준으로 늘었습니다.",
    "C": "다주택자 중과세율은 유지되어야 합니다. 투기 억제를 위하여 종합부동산세 강화에 찬성합니다.",
}
_PREFIXES = ("", "제 생각에는 ", "국민의 입장에서 말씀드립니다. ", "다음과 같이 의견을 냅니다. ")
_SUFFIXES = ("", " 꼭 반영해 주십시오.", " 재고를 요청드립니다.", " 이상입니다.", " 살펴봐 주세요.")

NOISE = (
    "국회 심의 일정을 공개해 주시기 바랍니다.",
    "홈페이지 접속이 자꾸 끊깁니다. 개선 바랍니다.",
    "자동차세 감면도 함께 검토해 주세요.",
    "담당 공무원 여러분 고생이 많으십니다.",
    "예산 낭비를 줄이는 대책이 필요합니다.",
    "청년 주거 지원 예산을 늘려 주십시오.",
    "지방 소멸 대응 예산이 부족합니다.",
    "부동산 통계의 신뢰도를 높여야 합니다.",
    "학교 급식 예산도 확대해 주시기 바랍니다.",
    "전기요금 인상에 반대합니다.",
)


def build_corpus(per_template: int = 20) -> list[OpinionDoc]:
    """템플릿 3종 × 변형 + 노이즈로 만든 결정적 합성 코퍼스."""
    docs: list[OpinionDoc] = []
    for key, template in TEMPLATES.items():
        for i in range(per_template):
            text = f"{_PREFIXES[i % len(_PREFIXES)]}{template}{_SUFFIXES[i % len(_SUFFIXES)]}"
            docs.append(OpinionDoc(doc_id=f"{key}-{i:02d}", text=text))
    for i, text in enumerate(NOISE):
        docs.append(OpinionDoc(doc_id=f"N-{i:02d}", text=text))
    return docs


def test_normalize() -> None:
    # 구두점·감탄 자모는 잡음이라 떨어져 나가고, 약칭은 정식 명칭으로 통일된다
    assert norm_text("종부세!!!!  폐지 하라ㅋㅋㅋㅋ") == "종합부동산세 폐지 하라"
    assert norm_text("<p>제7조&nbsp;삭제</p>") == "제7조 삭제"
    assert norm_text("공정시장가액비율 60%") == "공정시장가액비율 60%", "세율의 %는 보존해야 한다"
    assert norm_text("1가구 1주택") == "1세대 1주택"
    assert norm_text("") == ""

    grams = char_ngrams("종합부동산세 폐지", 3)
    assert "종합부" in grams and "동산세" in grams, sorted(grams)

    # 조사를 떼고 약칭을 펴서 같은 단어로 모은다
    assert "종합부동산세" in word_terms("종부세를 폐지하라")
    assert "종합부동산세" in word_terms("종합부동산세는 부당하다")
    print("  normalize OK")


def test_purity_and_sizes() -> None:
    docs = build_corpus()
    result = cluster_opinions(docs)

    assert result.total == len(docs), result.total
    # 배정 누락·중복이 없어야 한다
    assigned = [mid for c in result.clusters for mid in c.member_ids]
    assert len(assigned) == len(docs), (len(assigned), len(docs))
    assert len(set(assigned)) == len(docs), "한 의견이 두 군집에 들어갔다"

    top3 = result.clusters[:3]
    for cluster in top3:
        assert cluster.size >= 18, f"군집 {cluster.cluster_id} 크기 {cluster.size}"
        prefixes = {mid.split("-")[0] for mid in cluster.member_ids}
        assert len(prefixes) == 1, f"서로 다른 취지가 섞였다: {prefixes}"
        assert prefixes.pop() in TEMPLATES, "노이즈가 대형 군집에 붙었다"

    covered = {mid.split("-")[0] for c in top3 for mid in c.member_ids}
    assert covered == set(TEMPLATES), covered
    assert result.coverage(3) > 0.8, result.coverage(3)

    # 임계값을 낮춰 병합 압력을 키워도 취지가 섞이면 안 된다.
    # (A·C 템플릿은 같은 도입·맺음 문구를 공유해 교차 유사도가 0.47까지 올라간다 —
    #  적응형 재분할이 없으면 여기서 한 덩어리로 붙는다.)
    loose = cluster_opinions(docs, threshold=0.35)
    for cluster in loose.clusters:
        prefixes = {mid.split("-")[0] for mid in cluster.member_ids}
        if len(prefixes) > 1:
            assert not (prefixes & set(TEMPLATES)), f"임계값 0.35에서 취지가 섞였다: {prefixes}"
    print(f"  purity OK (상위 3개 크기: {[c.size for c in top3]}, 커버리지 {result.coverage(3):.2f})")


def test_exact_duplicates() -> None:
    text = "종합부동산세를 즉시 폐지하여 주시기 바랍니다."
    docs = [OpinionDoc(doc_id=f"D-{i:03d}", text=text) for i in range(30)]
    docs.append(OpinionDoc(doc_id="X-000", text="근로소득공제를 확대해 주십시오."))

    result = cluster_opinions(docs)
    biggest = result.clusters[0]
    assert biggest.size == 30, biggest.size
    assert biggest.exact_dup_max == 30, biggest.exact_dup_max
    assert biggest.variant_count == 1, biggest.variant_count
    assert result.unique_texts == 2, result.unique_texts
    assert len(result.clusters) == 2, [c.size for c in result.clusters]
    print("  exact duplicate folding OK")


def test_boilerplate_split() -> None:
    greeting = "안녕하십니까. 국민의 한 사람으로서 의견 드립니다."
    closing = "적극 검토를 부탁드립니다. 감사합니다."
    pairs = [
        ("G-0", f"{greeting} 종합부동산세를 폐지해 주십시오. {closing}"),
        ("G-1", f"{greeting} 근로소득공제를 확대해 주십시오. {closing}"),
    ]

    boiler = boilerplate_sentences([t for _, t in pairs])
    assert "안녕하십니까" in boiler, sorted(boiler)
    assert "감사합니다" in boiler, sorted(boiler)
    # 실질 주장은 아무리 자주 나와도 상투구가 아니다
    assert not any("폐지" in s for s in boiler), sorted(boiler)

    raw = cluster_opinions([OpinionDoc(i, t) for i, t in pairs])
    assert len(raw.clusters) == 1, "인사말이 많아 원문 그대로는 한 군집으로 붙는다(전제 확인)"

    stripped = cluster_opinions(
        [OpinionDoc(i, strip_boilerplate(t, boiler)) for i, t in pairs]
    )
    assert len(stripped.clusters) == 2, "상투구 제거 후에는 서로 다른 의견으로 갈려야 한다"

    # 본문이 통째로 상투구여도 빈 문자열을 만들지 않는다
    assert strip_boilerplate("감사합니다.", boiler) == "감사합니다."
    print("  boilerplate split OK")


def test_determinism() -> None:
    docs = build_corpus(per_template=12)
    first = cluster_opinions(docs)
    second = cluster_opinions(list(reversed(docs)))

    def signature(result):
        return [(c.size, c.medoid_id, tuple(c.member_ids), tuple(c.top_terms)) for c in result.clusters]

    assert signature(first) == signature(second), "입력 순서가 바뀌면 결과가 달라진다"
    print("  determinism OK")


def test_tagging() -> None:
    assert related_articles("제7조를 삭제해 주십시오.", "종합부동산세법") == ["종합부동산세법 제7조"]
    assert related_articles("「소득세법」 제12조제1항", "종합부동산세법") == ["소득세법 제12조"]
    ranged = related_articles("제7조부터 제9조까지 정비가 필요합니다.", "종합부동산세법")
    assert "종합부동산세법 제7조" in ranged and "종합부동산세법 제9조" in ranged, ranged
    assert related_articles("조문 언급이 전혀 없는 의견입니다.", "종합부동산세법") == []

    assert classify_stance("이 개정안에 반대합니다.").stance == "반대"
    assert classify_stance("개정안에 찬성합니다.").stance == "찬성"
    assert classify_stance("취지에는 공감하나 찬성합니다.").stance == "조건부"
    assert classify_stance("종부세를 폐지하라").stance == "반대", "폐지 요구는 반대로 읽는다"
    assert classify_stance("오늘 날씨가 좋습니다.").stance == "불명"
    assert classify_stance("종부세를 폐지하라").demand == "폐지·철회"

    tags = issue_tags("1세대 1주택자의 공정시장가액비율을 인하해 주십시오.")
    assert "1세대 1주택" in tags and "공정시장가액비율" in tags, tags

    # 한글은 어절 경계가 없다 — '이중과세'가 '중과'/'중과세'에 부분일치하면 안 된다
    double_tax = issue_tags("재산세와의 이중과세이므로 1주택자는 제외해야 합니다.")
    assert "이중과세" in double_tax, double_tax
    assert "다주택 중과" not in double_tax, double_tax
    assert "다주택 중과" in issue_tags("다주택자 중과세율은 유지되어야 합니다."), "정상 매칭까지 막으면 안 된다"

    label = deterministic_label("종합부동산세는 폐지되어야 합니다. 부당합니다.", ["종부세", "폐지"])
    assert "폐지" in label and "[" in label, label
    print("  tagging OK")


def test_report_end_to_end(tmp_dir: Path) -> None:
    records = load_from_files([FIXTURES / "sample-opinions.csv"], "87936")
    docs = [OpinionDoc(r.opinion_id, r.body) for r in records]
    result = cluster_opinions(docs)
    views = build_views(result, records, default_law="종합부동산세법")

    assert len(views) == len(result.clusters)
    assert sum(v.size for v in views) == len(records)

    markdown = render_markdown(
        result, views, bill_id="87936", law_name="종합부동산세법", top=5, llm_used=False
    )
    assert "# 종합부동산세법 입법예고 의견 분석" in markdown
    assert "## 군집별 주요내용" in markdown
    assert f"총 의견: **{len(records):,}건**" in markdown

    clusters_csv = write_clusters_csv(tmp_dir / "clusters.csv", views)
    members_csv = write_members_csv(tmp_dir / "members.csv", views, records, default_law="종합부동산세법")
    assert clusters_csv.exists() and members_csv.exists()
    # members.csv는 전 건이 한 줄씩 있어야 감사가 된다 (헤더 1줄 + N줄)
    lines = members_csv.read_text(encoding="utf-8-sig").strip().splitlines()
    assert len(lines) == len(records) + 1, len(lines)
    print("  report end-to-end OK")


def main() -> int:
    import tempfile

    print("opinion_cluster tests")
    test_normalize()
    test_purity_and_sizes()
    test_exact_duplicates()
    test_boilerplate_split()
    test_determinism()
    test_tagging()
    with tempfile.TemporaryDirectory() as tmp:
        test_report_end_to_end(Path(tmp))
    print("ALL PASSED")
    return 0


if __name__ == "__main__":
    sys.exit(main())
