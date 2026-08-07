"""의견 태깅 — 관련 조문 · 찬반/요구사항 · 쟁점 키워드 (전부 결정적).

군집만으로는 "몇 명이 같은 말을 했는가"까지만 나온다. 보고자료가 되려면
"**어느 조문**에 대해 **무엇을 요구**하는가"가 붙어야 한다. 세 가지를 규칙으로 붙인다:

  * related_articles — `core.citation_parser` **재사용**. 의견 본문의 `제7조`,
    「종합부동산세법」 제8조, 범위·항·호 인용까지 기존 파서가 이미 처리한다.
  * classify_stance  — 찬성/반대/조건부/불명 + 요구사항(폐지·완화·강화·유지·개선)
  * issue_tags       — 세목별 쟁점 사전 매칭 (1주택, 공정시장가액비율, 세부담 상한 …)

LLM은 여기 관여하지 않는다. 규칙이 못 잡는 애매한 건 "불명"으로 남기고, 요약 단계의
Claude가 상위 군집에 한해 채운다.
"""
from __future__ import annotations

import re
from collections import Counter
from dataclasses import dataclass, field

from core.citation_parser import effective_law_name, parse_citations
from core.opinion_normalize import norm_text

# ── 관련 조문 ─────────────────────────────────────────────────────────────────


def _article_label(jo: str, jo_sub: str) -> str:
    return f"제{jo}조의{jo_sub}" if jo_sub else f"제{jo}조"


def related_articles(text: str, default_law: str = "") -> list[str]:
    """의견 본문이 지목한 조문 라벨 목록 (예: '종합부동산세법 제7조').

    법령명이 명시되지 않은 `제7조`는 입법예고 대상 법률(default_law)로 해석한다.
    범위 인용(`제7조부터 제9조까지`)은 시작·끝 조문을 모두 라벨로 남긴다.
    """
    if not text:
        return []
    labels: list[str] = []
    seen: set[str] = set()
    for c in parse_citations(str(text)):
        if not c.jo:
            continue
        law = effective_law_name(c, default_law) if default_law else c.law_name
        law = "" if law.startswith("같은") else law
        for jo, jo_sub in [(c.jo, c.jo_sub)] + (
            [(c.range_end_jo, c.range_end_jo_sub)] if c.is_range and c.range_end_jo else []
        ):
            label = f"{law} {_article_label(jo, jo_sub)}".strip()
            if label not in seen:
                seen.add(label)
                labels.append(label)
    return labels


def article_distribution(texts: list[str], default_law: str = "") -> Counter[str]:
    """의견 목록 → 조문별 언급 건수 (한 의견 안의 중복 언급은 1회로 센다)."""
    dist: Counter[str] = Counter()
    for text in texts:
        dist.update(set(related_articles(text, default_law)))
    return dist


# ── 찬반 · 요구사항 ───────────────────────────────────────────────────────────

STANCE_LEXICON: dict[str, tuple[str, ...]] = {
    "반대": (
        "반대합니다", "반대한다", "반대의견", "반대입니다", "결사반대", "절대반대",
        "동의할 수 없", "동의하지 않", "찬성할 수 없", "부당합니다", "부당하다",
        "위헌", "철회", "백지화", "재고", "졸속", "세금폭탄", "이중과세",
    ),
    "찬성": (
        "찬성합니다", "찬성한다", "찬성의견", "찬성입니다", "적극 찬성", "적극찬성",
        "동의합니다", "동의한다", "환영", "바람직", "타당합니다", "타당하다",
        "지지합니다", "지지한다",
    ),
}

# 요구사항 — 의견이 정부에 요구하는 조치. 찬반보다 실무에 직접 쓰인다.
DEMAND_LEXICON: dict[str, tuple[str, ...]] = {
    "폐지·철회": ("폐지", "철폐", "없애", "철회", "백지화", "전면 재검토", "원점"),
    # '확대'는 그 자체로 방향이 없다(과세 확대 ↔ 공제 확대). 공제·감면과 붙은 형태만
    # 완화로 읽고, 홀로 쓰인 '확대'는 어느 쪽으로도 세지 않는다.
    "완화·인하": (
        "완화", "인하", "낮춰", "낮추", "축소", "감면", "경감", "줄여", "줄이",
        "공제 확대", "공제를 확대", "공제확대", "공제를 확대해", "감면 확대",
        "면제", "상한", "유예", "환원",
    ),
    "강화·인상": ("강화", "인상", "높여", "높이", "확대 과세", "중과", "올려", "올리"),
    "유지·존치": ("유지", "존치", "그대로", "현행 유지"),
    "개선·보완": ("개선", "보완", "합리화", "정비", "명확", "예외", "단서", "조정"),
}

_CONDITIONAL_MARKERS: tuple[str, ...] = (
    "다만", "조건부", "단서", "일부는", "원칙적으로 찬성", "취지에는 공감",
    "방향은 맞", "찬성하나", "찬성하지만", "동의하나", "동의하지만",
)


@dataclass
class StanceTag:
    stance: str                                  # 찬성 · 반대 · 조건부 · 불명
    demand: str                                  # 폐지·철회 / 완화·인하 / … / 불명
    matched: list[str] = field(default_factory=list)


def _hits(text: str, words: tuple[str, ...]) -> list[str]:
    return [w for w in words if w in text]


def classify_stance(text: str) -> StanceTag:
    """규칙 기반 찬반·요구사항 분류. 애매하면 '불명'으로 남긴다."""
    if not text:
        return StanceTag("불명", "불명")
    norm = norm_text(text)
    raw = str(text)

    against = _hits(norm, STANCE_LEXICON["반대"]) + _hits(raw, STANCE_LEXICON["반대"])
    favor = _hits(norm, STANCE_LEXICON["찬성"]) + _hits(raw, STANCE_LEXICON["찬성"])
    against = sorted(set(against))
    favor = sorted(set(favor))

    conditional = any(m in norm or m in raw for m in _CONDITIONAL_MARKERS)

    if favor and against:
        stance = "조건부"
    elif favor:
        stance = "조건부" if conditional else "찬성"
    elif against:
        stance = "반대"
    else:
        stance = "불명"

    demand = "불명"
    demand_hits: list[str] = []
    best = 0
    for label, words in DEMAND_LEXICON.items():
        found = _hits(norm, words)
        if len(found) > best:
            best, demand, demand_hits = len(found), label, found

    # 찬반 신호가 없어도 요구사항이 뚜렷하면 방향을 읽을 수 있다.
    if stance == "불명" and demand == "폐지·철회":
        stance = "반대"

    return StanceTag(stance, demand, sorted(set(favor + against + demand_hits)))


def stance_distribution(texts: list[str]) -> Counter[str]:
    return Counter(classify_stance(t).stance for t in texts)


# ── 쟁점 키워드 ───────────────────────────────────────────────────────────────
# 세목별 대표 쟁점. 표면형이 여러 개인 것은 하나의 canonical 쟁점으로 접는다.
ISSUE_LEXICON: dict[str, tuple[str, ...]] = {
    "1세대 1주택": ("1세대1주택", "1세대 1주택", "1주택", "일세대일주택", "실거주"),
    "다주택 중과": ("다주택", "2주택", "3주택", "중과세율", "중과"),
    "공정시장가액비율": ("공정시장가액비율", "공정시장가액", "공시가격 현실화", "공시가격"),
    "세부담 상한": ("세부담상한", "세부담 상한", "부담상한"),
    "고령자·장기보유 공제": ("고령자", "장기보유", "연령공제", "보유기간"),
    "합산배제·임대주택": ("합산배제", "임대주택", "등록임대", "매입임대", "건설임대"),
    "기본공제 금액": ("기본공제", "공제금액", "과세기준금액", "11억", "12억", "9억"),
    "법인 과세": ("법인", "법인세", "법인 소유"),
    "이중과세": ("이중과세", "재산세와 중복", "중복과세"),
    "미실현이득 과세": ("미실현", "실현되지 않은", "실현이익"),
    "지방세 전환": ("지방세", "재산세로 통합", "국세 폐지"),
    "세율 조정": ("세율", "누진", "구간"),
    "과세표준": ("과세표준", "과표"),
    "종부세 자체": ("종부세", "종합부동산세"),
    "소득세 과표구간": ("과표구간", "소득세 과표", "누진세율"),
    "근로소득공제": ("근로소득공제", "근로소득 공제"),
    "금융투자소득": ("금융투자소득", "금투세"),
    "상속·증여": ("상속", "증여"),
    "부칙·시행시기": ("부칙", "시행일", "경과조치", "소급"),
}


def issue_tags(text: str, lexicon: dict[str, tuple[str, ...]] | None = None) -> list[str]:
    """의견 본문에 등장하는 쟁점 태그 목록."""
    if not text:
        return []
    table = lexicon or ISSUE_LEXICON
    norm = norm_text(text)
    tags = [issue for issue, forms in table.items() if any(norm_text(f) in norm for f in forms)]
    return sorted(tags)


def issue_distribution(
    texts: list[str], lexicon: dict[str, tuple[str, ...]] | None = None
) -> Counter[str]:
    dist: Counter[str] = Counter()
    for text in texts:
        dist.update(issue_tags(text, lexicon))
    return dist


# ── 요약 라벨 (LLM 없이 쓰는 폴백) ────────────────────────────────────────────

_SENTENCE_END_RE = re.compile(r"(?<=[.!?])\s+|[\r\n]+")


def deterministic_label(text: str, top_terms: list[str], limit: int = 60) -> str:
    """LLM 없이 만드는 군집 라벨 — 대표의견 첫 문장 + 핵심 키워드."""
    first = ""
    for part in _SENTENCE_END_RE.split(str(text or "")):
        cleaned = part.strip()
        if len(norm_text(cleaned)) >= 4:
            first = cleaned
            break
    if not first:
        first = str(text or "").strip()
    if len(first) > limit:
        first = first[: limit - 1].rstrip() + "…"
    terms = ", ".join(top_terms[:3])
    return f"{first} [{terms}]" if terms else first
