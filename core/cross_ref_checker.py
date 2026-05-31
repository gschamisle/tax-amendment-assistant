"""병행 법령 교차 인용 검사 (GPT 의미 매칭)."""
import functools
import json
import re
from concurrent.futures import ThreadPoolExecutor, as_completed
from openai import OpenAI
from config import LAW_API_KEY, OPENAI_API_KEY, KEYWORD_SYNONYMS
from core.law_api import get_law_text
from core.law_network import all_law_scope_entries, related_law_names, resolve_law_entries

# "제33조의2" (표준) 또는 "제33의2조" (법령 API 형식) 모두 파싱
_JO_RE = re.compile(r"제(\d+)의(\d+)조|제(\d+)조(?:의(\d+))?")
_JO_HO_RE = re.compile(r"제(?:(\d+)의(\d+)조|(\d+)조(?:의(\d+))?)(?:제(\d+)항)?(?:제(\d+)호)?")

_CORE_PARALLEL_TERMS: frozenset[str] = frozenset({
    "손금불산입",
    "손금산입",
    "필요경비불산입",
    "필요경비산입",
    "익금불산입",
    "총수입금액불산입",
    "결손금",
    "이월결손금",
    "기부금",
    "기업업무추진비",
    "접대비",
    "업무무관비용",
    "업무와관련없는비용",
    "업무용승용차",
    "재해손실세액공제",
})

_PHRASE_SYNONYMS: dict[str, list[str]] = {
    "손금에산입하지아니한다": ["필요경비에산입하지아니한다"],
    "손금에산입하지아니한": ["필요경비에산입하지아니한"],
    "필요경비에산입하지아니한다": ["손금에산입하지아니한다"],
    "필요경비에산입하지아니한": ["손금에산입하지아니한"],
    "각사업연도": ["과세기간"],
    "과세기간": ["각사업연도", "사업연도"],
    "업무와관련없는비용": ["업무무관비용"],
    "업무무관비용": ["업무와관련없는비용"],
    "접대비": ["기업업무추진비"],
    "기업업무추진비": ["접대비"],
}

_PARALLEL_ARTICLE_HINTS: dict[tuple[str, str, str], list[dict[str, str]]] = {
    ("법인세법", "소득세법", "13"): [
        {
            "article": "제45조",
            "reason": "법인세법 제13조의 이월결손금 공제는 소득세법 제45조 결손금 및 이월결손금 공제와 병행 검토 필요",
        }
    ],
    ("법인세법", "소득세법", "21"): [
        {
            "article": "제33조제1항제12호",
            "reason": "법인세법 제21조의 손금불산입 항목은 소득세법 제33조 필요경비 불산입 항목과 병행 검토 필요",
        }
    ],
    ("법인세법", "소득세법", "24"): [
        {
            "article": "제34조",
            "reason": "법인세법 제24조의 기부금 손금불산입은 소득세법 제34조 기부금 필요경비 불산입과 병행 검토 필요",
        }
    ],
    ("법인세법", "소득세법", "25"): [
        {
            "article": "제35조",
            "reason": "법인세법 제25조의 기업업무추진비 손금불산입은 소득세법 제35조 기업업무추진비 필요경비 불산입과 병행 검토 필요",
        }
    ],
    ("법인세법", "소득세법", "27"): [
        {
            "article": "제33조제1항제13호",
            "reason": "법인세법 제27조의 업무와 관련 없는 비용 손금불산입은 소득세법 제33조제1항제13호 업무무관 경비 필요경비 불산입과 병행 검토 필요",
        }
    ],
    ("법인세법", "소득세법", "27의2"): [
        {
            "article": "제33조의2",
            "reason": "법인세법 제27조의2의 업무용승용차 관련비용 손금불산입 특례는 소득세법 제33조의2와 병행 검토 필요",
        }
    ],
    ("법인세법", "소득세법", "58"): [
        {
            "article": "제58조",
            "reason": "법인세법 제58조의 재해손실 세액공제는 소득세법 제58조 재해손실세액공제와 병행 검토 필요",
        }
    ],
    ("소득세법", "법인세법", "45"): [
        {
            "article": "제13조",
            "reason": "소득세법 제45조의 결손금 및 이월결손금 공제는 법인세법 제13조 이월결손금 공제와 병행 검토 필요",
        }
    ],
    ("소득세법", "법인세법", "33"): [
        {
            "article": "제21조",
            "reason": "소득세법 제33조의 필요경비 불산입 항목은 법인세법 제21조 손금불산입 항목과 병행 검토 필요",
        }
    ],
    ("소득세법", "법인세법", "33의2"): [
        {
            "article": "제27조의2",
            "reason": "소득세법 제33조의2의 업무용승용차 관련 비용 필요경비 불산입 특례는 법인세법 제27조의2와 병행 검토 필요",
        }
    ],
    ("소득세법", "법인세법", "34"): [
        {
            "article": "제24조",
            "reason": "소득세법 제34조의 기부금 필요경비 불산입은 법인세법 제24조 기부금 손금불산입과 병행 검토 필요",
        }
    ],
    ("소득세법", "법인세법", "35"): [
        {
            "article": "제25조",
            "reason": "소득세법 제35조의 기업업무추진비 필요경비 불산입은 법인세법 제25조 기업업무추진비 손금불산입과 병행 검토 필요",
        }
    ],
    ("소득세법", "법인세법", "58"): [
        {
            "article": "제58조",
            "reason": "소득세법 제58조의 재해손실세액공제는 법인세법 제58조 재해손실 세액공제와 병행 검토 필요",
        }
    ],
}

_CROSSREF_SYSTEM = """당신은 대한민국 법령 개정 전문가입니다.
A 법령의 조문이 개정될 때, 동일 취지의 B 법령 조문도 함께 개정해야 하는지 판단하세요.

판단 기준:
- 두 조문이 동일한 정책 목적(예: 업무용승용차 손금 한도, 접대비 한도 등)을 규정하는 경우 → match: true
- A 법령이 법인세, B 법령이 소득세이고 동일 항목을 규율하는 경우 → match: true
- B 법령이 A 법령의 시행령·시행규칙 등 하위법령이고, A 조문의 위임·적용요건·세부기준을 규정하는 경우 → match: true
- 단순히 같은 세법 분야에 속하는 경우만으로는 match: true 아님 — 반드시 동일 취지의 규정이어야 함

응답 형식 (JSON만, 설명 없이):
{
  "match": true 또는 false,
  "article": "제OO조제O항 (조번호 정확히 기재)",
  "reason": "동일 취지인 이유 한 줄"
}
match가 false이면 article과 reason은 빈 문자열로."""


def _call_gpt(client: OpenAI, user_content: str) -> dict[str, str]:
    response = client.chat.completions.create(
        model="gpt-5.4-nano",
        messages=[
            {"role": "system", "content": _CROSSREF_SYSTEM},
            {"role": "user", "content": user_content},
        ],
        temperature=0,
        response_format={"type": "json_object"},
    )
    raw = response.choices[0].message.content or "{}"
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        return {"match": "false", "article": "", "reason": ""}


def _extract_article_content(
    parallel_data: dict,
    article_str: str,
) -> str:
    """GPT가 반환한 조문 번호 문자열에서 내용 추출.

    두 형식 처리:
    - "제33의2조" (법령 API 조번호 형식)
    - "제33조의2" (표준 법령 표기 형식)
    """
    m = _JO_RE.search(article_str)
    if not m:
        return ""
    if m.group(1) is not None:  # "제33의2조" 형식
        jo, jo_sub = m.group(1), m.group(2)
    else:  # "제33조의2" 또는 "제33조" 형식
        jo, jo_sub = m.group(3), m.group(4) or ""
    target = f"{jo}의{jo_sub}" if jo_sub else jo
    # 표준 표기 (제33조의2) — API 형식(33의2) 아님
    jo_display = f"제{jo}조의{jo_sub}" if jo_sub else f"제{jo}조"
    for a in parallel_data.get("조문목록", []):
        a_jo = str(a.get("조번호", ""))
        if a_jo == target or (not jo_sub and a_jo == jo):
            title = a.get("제목", "")
            content = a.get("내용", "")
            return f"{jo_display}({title})\n{content}" if title else f"{jo_display}\n{content}"
    return ""


def _extract_article_ref_parts(article_str: str) -> tuple[str, str, str, str] | None:
    m = _JO_HO_RE.search(article_str)
    if not m:
        return None
    if m.group(1) is not None:
        jo, jo_sub = m.group(1), m.group(2) or ""
    else:
        jo, jo_sub = m.group(3), m.group(4) or ""
    return jo, jo_sub, m.group(5) or "", m.group(6) or ""


def _format_article_ref(jo: str, jo_sub: str = "", hang: str = "", ho: str = "") -> str:
    ref = f"제{jo}조" + (f"의{jo_sub}" if jo_sub else "")
    if hang:
        ref += f"제{hang}항"
    if ho:
        ref += f"제{ho}호"
    return ref


def _normalize_article_ref(article_ref: str, law_name: str) -> str:
    """GPT가 조문 앞에 법령명을 붙여도 조문 표기만 남긴다."""
    ref = str(article_ref).strip()
    if law_name and ref.startswith(law_name):
        ref = ref[len(law_name):].strip()
    return re.sub(r'제(\d+)의(\d+)조', r'제\1조의\2', ref)


def _article_ref_from_text(article_text: str) -> str:
    first_line = article_text.strip().splitlines()[0] if article_text.strip() else ""
    parts = _extract_article_ref_parts(first_line)
    if parts:
        return _format_article_ref(*parts)
    return ""


def _known_parallel_hints(
    law_name: str,
    article_text: str,
    parallel_law_name: str,
) -> list[dict[str, str]]:
    ref = _article_ref_from_text(article_text)
    parts = _extract_article_ref_parts(ref)
    if not parts:
        return []
    jo, jo_sub, _hang, _ho = parts
    jo_key = f"{jo}의{jo_sub}" if jo_sub else jo
    return _PARALLEL_ARTICLE_HINTS.get((law_name, parallel_law_name, jo_key), [])


# 범용 세법 용어: 많은 조문에 공통으로 쓰여 검색 키워드로 부적합
_GENERIC_TAX_TERMS: frozenset[str] = frozenset(
    (
        set(KEYWORD_SYNONYMS.keys())
        | {s for syns in KEYWORD_SYNONYMS.values() for s in syns}
    ) - _CORE_PARALLEL_TERMS
)


def _extract_keywords(article_text: str) -> list[str]:
    """조문 제목·본문에서 주제 특화 키워드 추출.

    1. 제목 괄호 내 특화 용어 (3자 이상, 범용어 제외)
    2. 제목 키워드가 2개 미만이면 본문 빈도 기반 보강 (4자 이상, 2회 이상 출현)
    """
    lines = article_text.strip().splitlines()
    if not lines:
        return []

    first_line = lines[0]
    m = re.search(r'[（(]([^）)]{2,})[）)]', first_line)
    title = m.group(1) if m else first_line

    title_words = [w for w in re.findall(r'[가-힣]{3,}', title) if w not in _GENERIC_TAX_TERMS]

    if len(title_words) >= 2:
        return title_words

    # 제목 키워드 부족 → 본문에서 자주 등장하는 고유 용어 보강
    body = "\n".join(lines[1:]) if len(lines) > 1 else ""
    body_freq: dict[str, int] = {}
    for w in re.findall(r'[가-힣]{4,}', body):
        if w not in _GENERIC_TAX_TERMS:
            body_freq[w] = body_freq.get(w, 0) + 1
    # 2회 이상 출현, 빈도 상위 3개
    top_body = sorted(
        (w for w, c in body_freq.items() if c >= 2),
        key=lambda w: -body_freq[w],
    )[:3]

    core_terms = [term for term in _CORE_PARALLEL_TERMS if term in article_text.replace(" ", "")]
    combined = list(dict.fromkeys(core_terms + title_words + top_body))
    return combined if combined else [w for w in re.findall(r'[가-힣]{3,}', title)]


def _expand_keywords(keywords: list[str]) -> list[str]:
    """키워드 + 세법 동의어 확장 (법인세↔소득세 개념 대응)."""
    expanded = list(keywords)
    for kw in keywords:
        expanded.extend(KEYWORD_SYNONYMS.get(kw, []))
    # 복합어 포함 확장: "손금불산입" → "손금" 접두어 매칭용
    for kw in list(keywords):
        for base, syns in KEYWORD_SYNONYMS.items():
            if base in kw:
                for syn in syns:
                    expanded.append(kw.replace(base, syn))
    return list(dict.fromkeys(expanded))  # 순서 유지 중복 제거


def _normalized_text(text: str) -> str:
    normalized = re.sub(r"\s+", "", text)
    for old, replacements in _PHRASE_SYNONYMS.items():
        for replacement in replacements:
            normalized += " " + normalized.replace(old, replacement)
    return normalized


def _filter_articles(articles: list[dict], keywords: list[str], max_n: int = 20) -> list[dict]:
    """키워드(+동의어) 포함 조문 필터링. 매칭 없으면 빈 리스트 반환.

    공백 정규화 후 비교 — "필요경비 불산입" / "필요경비불산입" 모두 매칭.
    키워드 미매칭 시 fallback 없음 — 무관 조문을 GPT에 넘겨 hallucination 유발 방지.
    """
    if not keywords:
        return []
    expanded = _expand_keywords(keywords)
    expanded_nsp = [kw.replace(" ", "") for kw in expanded]

    def _matches(a: dict) -> bool:
        text = a.get("제목", "") + a.get("내용", "")
        text_nsp = _normalized_text(text)
        return any(
            kw in text or kw_nsp in text_nsp
            for kw, kw_nsp in zip(expanded, expanded_nsp)
        )

    matched = [a for a in articles if _matches(a)]
    return matched[:max_n]


def _prepend_hint_articles(
    articles: list[dict],
    hints: list[dict[str, str]],
) -> list[dict]:
    if not hints:
        return articles
    result: list[dict] = []
    seen: set[str] = set()
    for hint in hints:
        parts = _extract_article_ref_parts(hint.get("article", ""))
        if not parts:
            continue
        jo, jo_sub, _hang, _ho = parts
        target = f"{jo}의{jo_sub}" if jo_sub else jo
        for article in articles:
            if str(article.get("조번호", "")) == target and target not in seen:
                result.append(article)
                seen.add(target)
                break
    for article in articles:
        jo_no = str(article.get("조번호", ""))
        if jo_no not in seen:
            result.append(article)
            seen.add(jo_no)
    return result


def _hint_match_result(
    parallel_data: dict,
    hints: list[dict[str, str]],
) -> dict[str, str] | None:
    for hint in hints:
        content = _extract_article_content(parallel_data, hint.get("article", ""))
        if content:
            return {
                "match": "true",
                "article": hint.get("article", ""),
                "reason": hint.get("reason", "코드 병행 매핑"),
                "내용": content,
            }
    return None


@functools.lru_cache(maxsize=32)
def _cached_get_law_text(mst: str, law_api_key: str) -> dict:
    """키워드 매칭용 법령 텍스트 캐시. OCR 스킵(openai_key 미전달) — 이미지 표는 alt 텍스트로 대체."""
    return get_law_text(mst, law_api_key, "")


def find_parallel_articles(
    law_name: str,
    article_text: str,
    parallel_law_name: str,
    parallel_law_mst: str,
    api_key: str = "",
    law_api_key: str = "",
) -> dict[str, str]:
    """병행 법령에서 동일 취지 조문 찾기.

    Returns: {"match": "true"/"false", "article": "제OO조...", "reason": "...", "내용": "..."}
    """
    key = api_key or OPENAI_API_KEY
    l_key = law_api_key or LAW_API_KEY
    client = OpenAI(api_key=key)

    _no_match: dict[str, str] = {"match": "false", "article": "", "reason": "", "내용": ""}

    parallel_data: dict = {}
    try:
        parallel_data = _cached_get_law_text(parallel_law_mst, l_key)
        keywords = _extract_keywords(article_text)
        hints = _known_parallel_hints(law_name, article_text, parallel_law_name)
        hint_result = _hint_match_result(parallel_data, hints)
        if hint_result:
            return hint_result
        relevant = _filter_articles(parallel_data.get("조문목록", []), keywords)
        relevant = _prepend_hint_articles(relevant, hints)
        if not relevant:
            # 키워드 매칭 조문 없음 → GPT 호출 없이 즉시 no-match
            return _no_match
        parallel_text = "\n".join(
            f"제{a['조번호']}조({a['제목']})\n{a['내용']}"
            for a in relevant
        )
    except Exception:
        return _no_match

    user_content = f"""[{law_name} 개정 조문]
{article_text}

[{parallel_law_name} 관련 조문]
{parallel_text}

{law_name}의 위 조문 개정 시, {parallel_law_name}에서 함께 개정해야 할 동일 취지 조문이 있습니까?
JSON으로만 답하세요."""

    # temperature=0 → 결정론적 출력, 1회 호출로 충분
    result = _call_gpt(client, user_content)
    if str(result.get("match", "false")).lower() != "true":
        return _no_match

    # 매칭된 조문 내용 추가 + hallucination 필터 (내용 없으면 날조 조문 → no-match)
    article_content = _extract_article_content(parallel_data, result.get("article", ""))
    if not article_content:
        return _no_match

    result["내용"] = article_content
    return result


def check_all_parallel_laws(
    law_name: str,
    article_text: str,
    law_api_key: str = "",
    openai_api_key: str = "",
    scope: str = "related",
    max_all_pages: int = 10,
) -> list[dict[str, str]]:
    """law_name에 대응하는 모든 병행 법령 검사. ThreadPoolExecutor로 병렬 실행.

    Returns: [{"법령명": ..., "조문": ..., "이유": ..., "MST": ..., "내용": ...}]
    """
    if scope == "all":
        candidate_entries = [
            entry for entry in all_law_scope_entries(law_api_key, max_pages=max_all_pages)
            if entry.get("법령명") != law_name
        ]
    else:
        candidate_entries = [
            entry for entry in resolve_law_entries(related_law_names(law_name), law_api_key)
            if entry.get("법령명") != law_name
        ]

    if not candidate_entries:
        return []

    def _check_one(entry: dict[str, str]) -> dict[str, str] | None:
        pname = entry.get("법령명", "")
        try:
            mst = entry["MST"]
            result = find_parallel_articles(
                law_name, article_text, pname, mst, openai_api_key, law_api_key
            )
            if str(result.get("match", "false")).lower() == "true":
                article_norm = _normalize_article_ref(result.get("article", ""), pname)
                return {
                    "법령명": pname,
                    "조문": article_norm,
                    "이유": result.get("reason", ""),
                    "MST": mst,
                    "내용": result.get("내용", ""),
                    "분류": "하위/병행 후보" if scope != "all" else "전체 법령 검색",
                }
        except Exception:
            pass
        return None

    suggestions: list[dict[str, str]] = []
    max_workers = min(len(candidate_entries), 4)
    with ThreadPoolExecutor(max_workers=max_workers) as pool:
        futures = {pool.submit(_check_one, entry): entry for entry in candidate_entries}
        for future in as_completed(futures):
            result = future.result()
            if result:
                suggestions.append(result)

    return suggestions
