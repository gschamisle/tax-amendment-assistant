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


def build_compare_report_hwpx(
    cmp_result: dict,
    output_path: str,
) -> None:
    """결정적 대조 결과만 담는 검토결과 HWPX (LLM·외부 전송 없음).

    화면의 업로드 검토 결과(①순방향 ②잔존 인용 ③유사 제도 체크리스트)를 그대로
    문서로 떨군다. 발표 전 내부망에서 과금·외부 전송 없이 쓸 수 있는 출력 경로.
    """
    doc = HwpxDocument.new()
    p = lambda text="": doc.add_paragraph(text, section_index=0)

    law_name = cmp_result.get("law_name", "")
    jo_labels = ", ".join(
        f"제{jo}조의{sub}" if sub else f"제{jo}조" for jo, sub in cmp_result.get("jo_list", [])
    )

    p(f"{law_name} 일부개정법률안 연동 검토 결과 (자동 분석)")
    p()
    p(f"□ 검토 대상 법령: {law_name}")
    if cmp_result.get("file"):
        p(f"□ 검토 대상 파일: {cmp_result['file']}")
    if not cmp_result.get("range_matched", True):
        p("□ 적용 범위: ⚠ 입력 범위가 개정안 지시문과 하나도 일치하지 않음 — 아래 결과가 비어도 '문제 없음'이 아니라 범위 불일치")
    elif cmp_result.get("auto_range"):
        p(f"□ 적용 범위(자동 감지): {jo_labels}")
    else:
        p(f"□ 적용 범위: {jo_labels}")
    new_articles = cmp_result.get("new_articles", [])
    if new_articles:
        na = ", ".join(f"제{jo}조의{sub}" if sub else f"제{jo}조" for jo, sub in new_articles)
        p(f"□ '조 신설'로 감지된 조문: {na}")
    manual = cmp_result.get("manual_targets", [])
    p(f"□ 수기 병행개정 대상 {len(manual)}건: {', '.join(_jo_label(j) for j in manual)}")
    p()

    fwd = cmp_result.get("forward", {})
    external = fwd.get("external", [])
    internal = fwd.get("internal", [])
    p(f"① 신설 본문이 인용하는 조문 — 외부 {len(external)}건 · 신설 범위 내 상호 인용 {len(internal)}건")
    for r in external:
        mark = " [범위]" if r.get("범위") else ""
        p(f"  - {r['법령명']} {r['조문']}{mark}  인용: {r['인용 원문']}")
    if not external:
        p("  - 외부 인용 없음")
    if internal:
        p(f"  (신설 범위 내 상호 인용 {len(internal)}건 — 번호 정합성 확인용)")
        for r in internal:
            p(f"    · {r['조문']}  인용: {r['인용 원문']}")
    p("  ※ \"A법 제X조 및 제Y조\" 연결 열거의 두 번째 항목은 법령명이 자기 법령으로 표시될 수 있어 원문 확인 필요")
    p()

    s = cmp_result.get("stale", {})
    missing = s.get("missing", [])
    hang = s.get("missing_hang", [])
    covered = s.get("covered", [])
    decree = s.get("decree", [])
    p("② 재사용 조번호 잔존 인용 — 수기 개정과 대조")
    p(f"  ❌ 수기 개정안에 없는 잔존 인용 {len(missing)}건 (정비 또는 부칙 경과조치 검토)")
    for row in missing:
        p(f"    - {row['법령명']} {_jo_label(row['조번호'])} {row.get('제목', '')}  대상: {', '.join(row.get('대상', []))}")
        for raw in row.get("인용", []):
            p(f"        인용 구문: {raw}")
    if not missing:
        p("    - 해당 없음")
    if hang:
        p(f"  ℹ 개정 대상 외 항만 인용 {len(hang)}건 (참고 — 항 신설·삭제로 번호가 밀리면 재검토)")
        for row in hang:
            p(f"    - {row['법령명']} {_jo_label(row['조번호'])} {row.get('제목', '')}  대상: {', '.join(row.get('대상', []))}")
    if covered:
        p(f"  ✅ 수기 개정에 이미 반영된 잔존 인용 {len(covered)}건")
        for row in covered:
            p(f"    - {_jo_label(row['조번호'])} {row.get('제목', '')}  대상: {', '.join(row.get('대상', []))}")
    if decree:
        p(f"  📋 시행령 잔존 인용 {len(decree)}건 (법률 공포 후 시행령 개정에 반영)")
        for row in decree:
            p(f"    - {row['법령명']} {_jo_label(row['조번호'])} {row.get('제목', '')}  대상: {', '.join(row.get('대상', []))}")
    p()

    px = cmp_result.get("proxy", {})
    px_missing = px.get("missing", [])
    px_covered = px.get("covered", [])
    p("③ 유사 제도 체크리스트 — 수기 개정과 대조")
    if not (px_missing or px_covered):
        p("  - 유사 기존 제도 조문 미입력 (체크리스트 없음)")
    else:
        p(f"  ❌ 수기 개정안에 없는 체크리스트 조문 {len(px_missing)}건 (신설 조번호 추가 여부 검토)")
        for r in px_missing:
            p(f"    - {r['법령명']} {_jo_label(r['조번호'])} {r.get('제목', '')}  인용: {', '.join(r.get('인용', [])[:2])}")
        if not px_missing:
            p("    - 해당 없음")
        if px_covered:
            p(f"  ✅ 수기 개정에 이미 반영 {len(px_covered)}건")
            for r in px_covered:
                p(f"    - {r['법령명']} {_jo_label(r['조번호'])} {r.get('제목', '')}")
    p()
    p("※ 본 검토결과는 인용 그래프 기반 결정적 자동 분석이며 외부 LLM·전송을 거치지 않습니다. 최종 판단은 검토자가 합니다.")

    doc.save_to_path(output_path)
    _patch_font_in_hwpx(output_path)
