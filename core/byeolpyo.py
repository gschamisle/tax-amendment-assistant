"""별표(別表) 연관 검토 — 개정 조문이 영향을 주는 별표를 찾는다 (Tier 1, OCR 없음).

법령 XML의 별표제목에 '(제7조제4호 관련)'처럼 관련 조문이 명시돼 있어, get_law_text가
추출해 둔 law_data['별표목록']에서 역방향으로 '이 조문을 관련 조문으로 둔 별표'를 찾는다.
본문 표(HWP/PDF)는 다루지 않는다 — 그건 Tier 2(파일 추출·OCR) 영역.
"""
from __future__ import annotations

from typing import Any


def _same_law(ref_law_name: str, law_name: str) -> bool:
    """별표제목의 인용이 같은 법령을 가리키는지. 낫표 법령명이 없으면 같은 법으로 본다."""
    if not ref_law_name:
        return True
    norm = lambda s: str(s).replace(" ", "").replace("ㆍ", "").replace("·", "").strip()
    return norm(ref_law_name) == norm(law_name)


def related_byeolpyo(
    law_data: dict[str, Any],
    target_jo: str,
    target_jo_sub: str = "",
) -> list[dict[str, Any]]:
    """target 조문을 '관련 조문'으로 둔 별표 목록 (조 단위 매칭).

    조 단위로 매칭한다(항·호는 표기용) — 역인용·병행과 동일하게 과소포착을 막는 설계.
    """
    law_name = str(law_data.get("법령명", "")).strip()
    hits: list[dict[str, Any]] = []
    for bp in law_data.get("별표목록", []):
        matched = [
            r for r in bp.get("관련조문", [])
            if str(r.get("jo", "")) == str(target_jo)
            and (not target_jo_sub or str(r.get("jo_sub", "")) == str(target_jo_sub))
            and _same_law(r.get("law_name", ""), law_name)
        ]
        if matched:
            hits.append({
                "구분": bp.get("구분", "별표"),
                "번호": bp.get("번호", ""),
                "제목": bp.get("제목", ""),
                "관련": matched,
                "hwp": bp.get("hwp", ""),
                "pdf": bp.get("pdf", ""),
            })
    return hits


def byeolpyo_label(bp: dict[str, Any]) -> str:
    """'별표 1' / '서식 2의3' 형태의 표기."""
    return f"{bp.get('구분', '별표')} {bp.get('번호', '')}".strip()
