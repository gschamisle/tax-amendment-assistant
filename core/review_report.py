"""신설 조문 검토의견서 HWPX 생성 — LLM 삼분류 + 결정적 대조 결과를 문서로."""
from __future__ import annotations

from hwpx.document import HwpxDocument

from core.hwpx_writer import _patch_font_in_hwpx

_ORDER = {"누락": 0, "판단필요": 1, "조치불요": 2}
_LABEL = {"누락": "누락 (개정 필요)", "판단필요": "판단 필요", "조치불요": "조치 불요"}


def _jo_label(jo_key: str) -> str:
    parts = str(jo_key).split("의")
    if parts and parts[0].isdigit():
        return f"제{parts[0]}조" + (f"의{parts[1]}" if len(parts) > 1 else "")
    return str(jo_key)


def build_review_report_hwpx(
    law_name: str,
    cmp_result: dict,
    llm_result: dict,
    output_path: str,
    source_file: str = "",
) -> None:
    """검토의견서 HWPX 작성.

    구성: 표제 → 종합 검토의견 → Ⅰ.누락 Ⅱ.판단필요 Ⅲ.조치불요(요약)
          → Ⅳ.반영 확인 → Ⅴ.시행령 후속개정 목록
    """
    doc = HwpxDocument.new()
    p = lambda text="": doc.add_paragraph(text, section_index=0)

    structure = llm_result.get("구조", {})
    review = llm_result.get("검토", {})
    items = sorted(review.get("항목", []), key=lambda x: (_ORDER.get(x["구분"], 9), x["확신도"] != "높음"))

    jo_labels = ", ".join(
        f"제{jo}조의{sub}" if sub else f"제{jo}조" for jo, sub in cmp_result["jo_list"]
    )

    p(f"{law_name} 일부개정법률안 검토의견 (신설 조문 연동 검토)")
    p()
    p(f"□ 신설 제도: {structure.get('제도명', '')}")
    p(f"□ 신설 조번호: {jo_labels}")
    if source_file:
        p(f"□ 검토 대상 파일: {source_file}")
    p()

    p("1. 종합 검토의견")
    for line in str(review.get("종합의견", "")).splitlines():
        p(f"  {line}" if line else "")
    p()

    sections = [("누락", "2. 누락 — 개정 반영 필요"), ("판단필요", "3. 판단 필요 사항"), ("조치불요", "4. 조치 불요 (검토 완료)")]
    for category, heading in sections:
        group = [it for it in items if it["구분"] == category]
        p(heading + f" ({len(group)}건)")
        if not group:
            p("  - 해당 없음")
        for it in group:
            p(f"  □ {it['법령명']} {_jo_label(it['조번호'])} [확신도: {it['확신도']}]")
            p(f"    - 쟁점: {it['쟁점']}")
            p(f"    - 조치: {it['권고조치']}")
        p()

    covered = cmp_result.get("stale", {}).get("covered", [])
    p(f"5. 개정안에 이미 반영된 연동 ({len(covered)}건)")
    for row in covered:
        p(f"  - {row['법령명']} {_jo_label(row['조번호'])} {row.get('제목', '')} (대상: {', '.join(row.get('대상', []))})")
    p()

    decree = cmp_result.get("stale", {}).get("decree", [])
    p(f"6. 시행령 후속개정 목록 ({len(decree)}건)")
    for row in decree:
        p(f"  - {row['법령명']} {_jo_label(row['조번호'])} {row.get('제목', '')} (대상: {', '.join(row.get('대상', []))})")
    p()
    p("※ 본 검토의견은 인용 그래프 기반 자동 분석과 AI 판단을 결합한 참고자료이며, 최종 판단은 검토자가 한다.")

    doc.save_to_path(output_path)
    _patch_font_in_hwpx(output_path)
