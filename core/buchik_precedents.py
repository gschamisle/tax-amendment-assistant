"""부칙 선례 기반 적용례 생성.

현재는 소규모 seed 데이터로 시작하고, 선례가 없으면 기존 템플릿으로 fallback한다.
"""
from __future__ import annotations

import json
from functools import lru_cache
from pathlib import Path
from typing import Any


_DATA_PATH = Path(__file__).resolve().parents[1] / "data" / "buchik_precedents.json"

_FALLBACK_TEMPLATES: dict[str, str] = {
    "장래효": "{law_ref} 시행 이후 최초로 개시하는 사업연도 분부터 적용한다.",
    "부진정소급효": "{law_ref} 시행 이후 과세표준을 신고하는 경우부터 적용한다.",
}

_BASIS_FALLBACK_TEMPLATES: dict[str, str] = {
    "사업연도": "{law_ref} 시행 이후 최초로 개시하는 사업연도 분부터 적용한다.",
    "과세기간": "{law_ref} 시행 이후 개시하는 과세기간 분부터 적용한다.",
    "신고": "{law_ref} 시행 이후 과세표준을 신고하는 경우부터 적용한다.",
    "지급/수령": "{law_ref} 시행 이후 지급하거나 수령하는 분부터 적용한다.",
    "양도/취득": "{law_ref} 시행 이후 양도하거나 취득하는 분부터 적용한다.",
    "공급": "{law_ref} 시행 이후 공급하는 분부터 적용한다.",
    "발생/거래": "{law_ref} 시행 이후 발생하는 소득ㆍ거래분부터 적용한다.",
}

_BASIS_TO_EFFECT: dict[str, str] = {
    "신고": "부진정소급효",
}


@lru_cache(maxsize=1)
def load_precedents() -> list[dict[str, Any]]:
    """부칙 선례 데이터를 로드한다."""
    if not _DATA_PATH.exists():
        return []
    with _DATA_PATH.open("r", encoding="utf-8") as f:
        data = json.load(f)
    return data if isinstance(data, list) else []


def law_ref(law_name: str) -> str:
    if "시행규칙" in law_name:
        return "이 규칙"
    if "시행령" in law_name:
        return "이 영"
    return "이 법"


def _score_precedent(
    precedent: dict[str, Any],
    law_name: str,
    article_title: str,
    outline: str,
    effect_type: str,
    application_basis: str = "자동 추천",
) -> int:
    precedent_basis = str(precedent.get("application_basis", "")).strip()
    if application_basis != "자동 추천" and precedent_basis != application_basis:
        return -1
    if application_basis == "자동 추천" and precedent.get("effect_type") != effect_type:
        # 법리 유형은 자동 추천 시 약한 필터로만 사용한다.
        score = -1
    else:
        score = 0

    if precedent_basis and application_basis != "자동 추천":
        score += 5

    precedent_law = str(precedent.get("law_name", "")).strip()
    if precedent_law:
        if precedent_law == law_name:
            score += 4
        else:
            score -= 2

    for keyword in precedent.get("article_title_keywords", []):
        if keyword and keyword in article_title:
            score += 3

    for keyword in precedent.get("outline_keywords", []):
        if keyword and keyword in outline:
            score += 2

    return score


def find_best_precedent(
    law_name: str,
    article_title: str,
    outline: str,
    effect_type: str,
    application_basis: str = "자동 추천",
) -> dict[str, Any] | None:
    """현재 개정 조문에 가장 가까운 부칙 선례를 찾는다."""
    scored = [
        (_score_precedent(p, law_name, article_title, outline, effect_type, application_basis), p)
        for p in load_precedents()
    ]
    scored = [(score, p) for score, p in scored if score > 0]
    if not scored:
        return None
    scored.sort(key=lambda item: item[0], reverse=True)
    return scored[0][1]


def build_buchik_from_precedent(
    *,
    law_name: str,
    jo_label: str,
    article_title: str,
    outline: str,
    effect_type: str,
    application_basis: str = "자동 추천",
) -> tuple[str, dict[str, Any] | None]:
    """선례를 우선 사용해 부칙을 만들고, 없으면 기존 템플릿으로 생성한다."""
    ref = law_ref(law_name)
    effective_type = _BASIS_TO_EFFECT.get(application_basis, effect_type)
    precedent = find_best_precedent(
        law_name,
        article_title,
        outline,
        effective_type,
        application_basis,
    )

    if precedent:
        suffix = str(precedent.get("article_title_suffix", "에 관한 적용례"))
        sentence_template = str(precedent.get("application_sentence", ""))
    else:
        suffix = "에 관한 적용례"
        sentence_template = _BASIS_FALLBACK_TEMPLATES.get(application_basis)
        if not sentence_template:
            sentence_template = _FALLBACK_TEMPLATES.get(effective_type, _FALLBACK_TEMPLATES["장래효"])
        sentence_template = "{jo_label}의 개정규정은 " + sentence_template

    application_sentence = sentence_template.format(
        law_ref=ref,
        jo_label=jo_label,
        article_title=article_title,
    )
    text = "\n".join([
        f"제1조(시행일) {ref}은 공포한 날부터 시행한다.",
        f"제2조({article_title}{suffix}) {application_sentence}",
    ])
    return text, precedent
