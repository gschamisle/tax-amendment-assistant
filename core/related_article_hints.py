"""개정 대상 조문별 연관 조문 힌트 (원천징수세율 등 연쇄 규정)."""
from __future__ import annotations

# (기준법령, 조번호, 항, 호) → 연관 검토 대상
# 조번호: "129", "27의2" / 항·호: "" 이면 해당 수준 전체
_RELATED_HINTS: dict[tuple[str, str, str, str], list[dict[str, str]]] = {
    ("소득세법", "129", "1", "3"): [
        {
            "law_name": "소득세법",
            "article": "제127조제1항제3호",
            "reason": "원천징수대상 사업소득(제129조제1항제3호 세율 적용 소득)에 대한 원천징수 의무",
            "relation_type": "rate_application",
        },
        {
            "law_name": "소득세법",
            "article": "제144조제1항",
            "reason": "원천징수세율을 적용하여 원천징수세액을 산출하는 규정",
            "relation_type": "calculation_rule",
        },
        {
            "law_name": "소득세법",
            "article": "제73조제1항제4호",
            "reason": "제127조 원천징수 사업소득과 연동되는 종합과세 적용 판정",
            "relation_type": "definition_scope",
        },
        {
            "law_name": "소득세법 시행령",
            "article": "제137조제1항",
            "reason": "제73조제1항제4호 사업소득 범위(원천징수·연말정산 연동)",
            "relation_type": "law_to_decree",
        },
        {
            "law_name": "소득세법 시행령",
            "article": "제184조",
            "reason": "제127조제1항제3호 사업소득 정의(원천징수 세율 적용 소득과 동일 축)",
            "relation_type": "law_to_decree",
        },
    ],
}

def lookup_related_hints(
    law_name: str,
    jo: str,
    hang: str = "",
    ho: str = "",
) -> list[dict[str, str]]:
    """정확·상위 키로 등록된 연관 조문 힌트를 반환."""
    jo = str(jo).strip()
    hang = str(hang).strip()
    ho = str(ho).strip()
    keys = [
        (law_name, jo, hang, ho),
        (law_name, jo, hang, ""),
        (law_name, jo, "", ""),
    ]
    merged: list[dict[str, str]] = []
    seen: set[tuple[str, str]] = set()
    for key in keys:
        for hint in _RELATED_HINTS.get(key, []):
            ident = (hint.get("law_name", ""), hint.get("article", ""))
            if ident in seen:
                continue
            seen.add(ident)
            merged.append(hint)
    return merged
