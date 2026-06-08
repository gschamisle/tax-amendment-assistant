"""간접 연쇄 개정 유형 분류 (그래프로 잡히지 않는 축)."""
from __future__ import annotations

import re

RELATION_TYPES: dict[str, str] = {
    "rate_application": "세율 적용 축",
    "definition_scope": "정의→대상",
    "calculation_rule": "산출 규정",
    "law_to_decree": "법률 위임→시행령",
    "parallel_tax_law": "병행 세법",
}

_KEYWORD_RULES: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("rate_application", ("세율", "원천징수세율", "100분의")),
    ("definition_scope", ("정의", "범위", "대상", "포함")),
    ("calculation_rule", ("산출", "계산", "산정", "적용하여")),
    ("law_to_decree", ("시행령", "위임", "대통령령")),
    ("parallel_tax_law", ("병행", "동일 취지")),
)


def classify_relation(
    law_name: str,
    article_ref: str,
    reason: str,
    explicit: str = "",
) -> str:
    """힌트·GPT 사유 문구에서 연쇄 유형 라벨 추정."""
    if explicit and explicit in RELATION_TYPES:
        return explicit
    text = f"{law_name} {article_ref} {reason}"
    for rel_type, keywords in _KEYWORD_RULES:
        if any(kw in text for kw in keywords):
            return rel_type
    if "시행령" in law_name and "법" in reason and "시행령" not in reason.split()[0]:
        return "law_to_decree"
    return ""


def relation_label(relation_type: str) -> str:
    return RELATION_TYPES.get(relation_type, relation_type)
