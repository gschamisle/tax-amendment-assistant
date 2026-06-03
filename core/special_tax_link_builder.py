"""조세특례제한법 조문별 세법 연결 후보 생성.

1단계: 명시 인용 파싱 (GPT 없음)
2단계: 제목·키워드 기반 후보 + 선택적 GPT 배치 검토
"""
from __future__ import annotations

import json
import os
import re
from dataclasses import asdict, dataclass, field

from openai import OpenAI

from config import LAW_API_KEY, OPENAI_API_KEY
from core.citation_parser import Citation, parse_citations
from core.law_api import get_law_text, search_laws

_SOURCE_LAW = "조세특례제한법"

_TAX_LAW_KEYWORDS: frozenset[str] = frozenset({
    "소득세법",
    "법인세법",
    "부가가치세법",
    "조세특례제한법",
    "상속세",
    "증여세",
    "국제조세",
    "지방세",
    "개별소비세",
    "교통에너지환경세",
    "취득세",
    "등록세",
})

_TITLE_TOPIC_RULES: tuple[tuple[str, str, str], ...] = (
    ("법인세", "법인세법", "조특법 제목·본문에 법인세 키워드"),
    ("소득세", "소득세법", "조특법 제목·본문에 소득세 키워드"),
    ("부가가치세", "부가가치세법", "조특법 제목·본문에 부가가치세 키워드"),
    ("감면", "법인세법", "세액감면·감면 특례는 법인세 과세구조와 연동 검토"),
    ("공제", "법인세법", "세액공제 특례는 법인세·소득세 공제 조문과 연동 검토"),
    ("투자", "조세특례제한법", "투자세액공제 등 조특법 내부 연계"),
    ("연구", "조세특례제한법", "연구·인력개발비 세액공제 특례"),
    ("이월", "법인세법", "이월결손금·결손금 관련 특례"),
    ("감가상각", "법인세법", "감가상각 관련 특례"),
    ("취득", "법인세법", "자산취득·양도 관련 특례"),
)

_GPT_SYSTEM = """당신은 대한민국 세법 연결 전문가입니다.
조세특례제한법의 한 조문이 개정될 때, 함께 검토해야 할 소득세법·법인세법·부가가치세법 조문을 찾습니다.

규칙:
- 명시 인용이 이미 있으면 그 연결을 우선 존중한다.
- 조특법 내부 조문만 언급된 경우 linked_law는 비워도 된다.
- 확실한 세법 연결만 suggested에 넣고 confidence는 high/medium/low로 표시한다.
- 불확실하면 linked_law를 비우고 review_note만 적는다.

JSON 객체로만 반환:
{"results": [{"source_jo": "제10조", "linked_law": "법인세법", "linked_article": "제12조", "confidence": "high", "reason": "한 줄"}]}"""


@dataclass
class LinkedArticle:
    law_name: str
    article: str
    confidence: str
    reason: str
    source: str  # "citation" | "keyword" | "gpt"


@dataclass
class ArticleLinkRecord:
    source_law: str
    jo_no: str
    jo_label: str
    title: str
    explicit_citations: list[dict] = field(default_factory=list)
    linked_articles: list[dict] = field(default_factory=list)
    review_note: str = ""


def _jo_label(jo_no: str) -> str:
    if "의" in jo_no:
        base, sub = jo_no.split("의", 1)
        return f"제{base}조의{sub}"
    return f"제{jo_no}조"


def _format_citation(c: Citation) -> str:
    ref = f"제{c.jo}조"
    if c.jo_sub:
        ref = f"제{c.jo}조의{c.jo_sub}"
    if c.hang:
        ref += f"제{c.hang}항"
        if c.hang_end:
            ref += f"~제{c.hang_end}항"
    if c.ho:
        ref += f"제{c.ho}호"
    if c.mok:
        ref += f"제{c.mok}목"
    if c.is_range and c.range_end_jo:
        end = f"제{c.range_end_jo}조"
        if c.range_end_jo_sub:
            end = f"제{c.range_end_jo}조의{c.range_end_jo_sub}"
        ref += f"~{end}"
    return ref


def _normalize_law_name(name: str) -> str:
    n = re.sub(r"\s+", "", name.strip())
    for key in _TAX_LAW_KEYWORDS:
        if key in n:
            if "시행령" in n and "법" in key:
                return f"{key} 시행령"
            if "시행규칙" in n and "법" in key:
                return f"{key} 시행규칙"
            return key
    return n


def _is_tax_law(name: str) -> bool:
    if not name:
        return False
    n = _normalize_law_name(name)
    return any(k in n for k in ("소득세법", "법인세법", "부가가치세법", "조세특례제한법"))


def _citations_from_article(content: str) -> list[LinkedArticle]:
    text = content
    citations = parse_citations(text)
    _resolve_same_law_in_article(citations, text)

    links: list[LinkedArticle] = []
    seen: set[tuple[str, str]] = set()
    for c in citations:
        law = _normalize_law_name(c.law_name)
        if not _is_tax_law(law):
            continue
        if law == _SOURCE_LAW:
            continue
        article = _format_citation(c)
        if not c.jo and not article.startswith("제"):
            continue
        key = (law, article)
        if key in seen:
            continue
        seen.add(key)
        links.append(LinkedArticle(
            law_name=law,
            article=article,
            confidence="high",
            reason=f"명시 인용: {c.raw}",
            source="citation",
        ))
    return links


def _resolve_same_law_in_article(citations: list[Citation], text: str) -> None:
    """같은 법/조 해석을 조특법 문맥에서 보강한다."""
    for idx, cite in enumerate(citations):
        if cite.relative != "같은조" and not cite.law_name.startswith("같은"):
            continue
        sent_start = max(text.rfind(".", 0, cite.span[0]), text.rfind("\n", 0, cite.span[0]))
        sent_start = 0 if sent_start < 0 else sent_start + 1
        previous = [c for c in citations[:idx] if c.span[0] >= sent_start and c.jo]
        if not previous:
            continue
        anchor = previous[-1]
        if cite.relative == "같은조":
            cite.jo = anchor.jo
            cite.jo_sub = anchor.jo_sub
            cite.law_name = anchor.law_name
        elif cite.law_name.startswith("같은"):
            explicit = [c for c in previous if c.law_name and not c.relative]
            if explicit:
                cite.law_name = explicit[-1].law_name


def _keyword_links(title: str, content_head: str) -> list[LinkedArticle]:
    blob = f"{title} {content_head[:500]}"
    links: list[LinkedArticle] = []
    seen: set[tuple[str, str]] = set()
    for keyword, law, reason in _TITLE_TOPIC_RULES:
        if keyword not in blob:
            continue
        key = (law, "")
        if key in seen:
            continue
        seen.add(key)
        links.append(LinkedArticle(
            law_name=law,
            article="",
            confidence="low",
            reason=reason,
            source="keyword",
        ))
    return links


def _merge_links(*groups: list[LinkedArticle]) -> list[LinkedArticle]:
    merged: list[LinkedArticle] = []
    seen: set[tuple[str, str]] = set()
    priority = {"citation": 0, "gpt": 1, "keyword": 2}
    flat = [item for group in groups for item in group]
    flat.sort(key=lambda x: (priority.get(x.source, 9), x.law_name, x.article))
    for item in flat:
        key = (item.law_name, item.article)
        if key in seen and item.article:
            continue
        if not item.article:
            key = (item.law_name, item.reason)
        if key in seen:
            continue
        seen.add(key)
        merged.append(item)
    return merged


def load_special_tax_articles(law_api_key: str = "") -> list[dict]:
    results = search_laws(_SOURCE_LAW, law_api_key or LAW_API_KEY)
    entry = next((r for r in results if r.get("법령명") == _SOURCE_LAW), results[0])
    data = get_law_text(entry["MST"], law_api_key or LAW_API_KEY, "")
    return data.get("조문목록", [])


def build_records(
    articles: list[dict] | None = None,
    law_api_key: str = "",
) -> list[ArticleLinkRecord]:
    articles = articles or load_special_tax_articles(law_api_key)
    records: list[ArticleLinkRecord] = []
    for article in articles:
        jo_no = str(article.get("조번호", ""))
        title = str(article.get("제목", "")).strip()
        content = str(article.get("내용", ""))
        cite_links = _citations_from_article(content)
        kw_links = _keyword_links(title, content)
        merged = _merge_links(cite_links, kw_links)
        records.append(ArticleLinkRecord(
            source_law=_SOURCE_LAW,
            jo_no=jo_no,
            jo_label=_jo_label(jo_no),
            title=title,
            explicit_citations=[
                {"raw": c.reason.removeprefix("명시 인용: ")}
                for c in cite_links
            ],
            linked_articles=[asdict(x) for x in merged],
        ))
    return records


def _records_needing_gpt(records: list[ArticleLinkRecord], limit: int) -> list[ArticleLinkRecord]:
    """명시 인용이 적고 제목에 세법 키워드가 있는 조문만 GPT 검토."""
    candidates: list[ArticleLinkRecord] = []
    for rec in records:
        cite_count = sum(1 for x in rec.linked_articles if x.get("source") == "citation")
        title_blob = rec.title
        has_tax_topic = any(k in title_blob for k in ("세액", "감면", "공제", "소득", "법인", "부가가치"))
        if has_tax_topic and cite_count < 2:
            candidates.append(rec)
    return candidates[:limit]


def enrich_with_gpt_batches(
    records: list[ArticleLinkRecord],
    *,
    api_key: str = "",
    model: str = "",
    batch_size: int = 20,
    max_articles: int = 60,
) -> int:
    """GPT 배치 검토. 반환값은 호출한 배치 수."""
    key = api_key or OPENAI_API_KEY
    if not key:
        return 0
    model = model or os.getenv("SPECIAL_TAX_LINK_MODEL", "gpt-4o-mini")
    client = OpenAI(api_key=key)

    targets = _records_needing_gpt(records, max_articles)
    if not targets:
        return 0

    batches = 0
    rec_by_jo = {r.jo_label: r for r in records}
    for i in range(0, len(targets), batch_size):
        chunk = targets[i : i + batch_size]
        payload = []
        for rec in chunk:
            payload.append({
                "jo_label": rec.jo_label,
                "title": rec.title,
                "existing_links": [
                    x for x in rec.linked_articles if x.get("source") == "citation"
                ],
            })
        user = json.dumps(payload, ensure_ascii=False)
        try:
            resp = client.chat.completions.create(
                model=model,
                messages=[
                    {"role": "system", "content": _GPT_SYSTEM},
                    {"role": "user", "content": user},
                ],
                temperature=0,
                response_format={"type": "json_object"},
            )
            raw = resp.choices[0].message.content or "{}"
            parsed = json.loads(raw)
            items = parsed if isinstance(parsed, list) else parsed.get("results", parsed.get("items", []))
        except Exception:
            batches += 1
            continue

        for item in items:
            src = item.get("source_jo", "")
            rec = rec_by_jo.get(src)
            if not rec:
                continue
            law = item.get("linked_law", "").strip()
            article = item.get("linked_article", "").strip()
            if not law:
                rec.review_note = item.get("review_note", rec.review_note)
                continue
            gpt_links = [LinkedArticle(
                law_name=law,
                article=article,
                confidence=item.get("confidence", "medium"),
                reason=item.get("reason", "GPT 배치 검토"),
                source="gpt",
            )]
            existing = [
                LinkedArticle(**x) for x in rec.linked_articles
            ]
            rec.linked_articles = [
                asdict(x) for x in _merge_links(existing, gpt_links)
            ]
        batches += 1
    return batches


def save_records(
    records: list[ArticleLinkRecord],
    path: str,
) -> None:
    data = {
        "source_law": _SOURCE_LAW,
        "article_count": len(records),
        "records": [asdict(r) for r in records],
    }
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


def build_markdown_summary(records: list[ArticleLinkRecord]) -> str:
    lines = [
        "# 조세특례제한법 세법 연결 후보",
        "",
        "자동 생성 데이터입니다. `confidence`가 high인 명시 인용부터 코드 매핑에 반영하세요.",
        "",
    ]
    with_links = [r for r in records if r.linked_articles]
    lines.append(f"연결 후보가 있는 조문: {len(with_links)} / {len(records)}")
    lines.append("")
    for rec in with_links[:80]:
        lines.append(f"## {rec.jo_label} ({rec.title})")
        for link in rec.linked_articles[:8]:
            art = link.get("article") or "(조문 미특정)"
            lines.append(
                f"- **{link.get('law_name')}** {art} "
                f"[{link.get('confidence')}/{link.get('source')}] {link.get('reason')}"
            )
        lines.append("")
    if len(with_links) > 80:
        lines.append(f"... 외 {len(with_links) - 80}개 조문은 JSON 파일 참조")
    return "\n".join(lines)
