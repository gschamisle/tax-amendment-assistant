"""병행개정 골든 매핑 — docs/corporate-income-tax-parallel-manual.md의 코드화.

매뉴얼의 확정 매핑·연쇄 매핑을 데이터로 정형화한다. 두 가지 용도:
1. build_parallel_matrix.py가 confirmed 엔트리로 매트릭스에 주입
2. test_parallel_matrix.py가 recall 100% 검증의 정답셋으로 사용

매뉴얼이 갱신되면 이 파일도 함께 갱신할 것.
"""
from __future__ import annotations

import re

from core.parallel_matrix import matrix_key

GOLDEN_SOURCE = "golden_manual"

# ── 매뉴얼 §1: 법인세법 ↔ 소득세법 확정 병행 매핑 (대칭) ──────────────────────
# (법인세법 조번호, 법인세법 표기, 소득세법 조번호, 소득세법 표기, 취지)
_SECTION1: tuple[tuple[str, str, str, str, str], ...] = (
    ("13", "제13조", "45", "제45조", "결손금·이월결손금 공제 구조 병행 검토"),
    ("21", "제21조", "33", "제33조제1항제12호", "손금불산입 ↔ 필요경비 불산입 일반"),
    ("23", "제23조", "33", "제33조제1항제6호", "감가상각비 상각범위액 초과분 불산입"),
    ("24", "제24조", "34", "제34조", "기부금 손금불산입 ↔ 필요경비 불산입"),
    ("25", "제25조", "35", "제35조", "기업업무추진비·접대비 한도 및 불산입"),
    ("27", "제27조", "33", "제33조제1항제13호", "업무무관 비용 불산입"),
    ("27의2", "제27조의2", "33의2", "제33조의2", "업무용승용차 관련비용 불산입 특례"),
    ("58", "제58조", "58", "제58조", "재해손실 세액공제"),
)

# ── 매뉴얼 §2: 업무용승용차 하위법령 연쇄 매핑 ────────────────────────────────
# (기준법령, 기준 조번호, 대상법령, 대상 조문, relation_type, 취지)
_SECTION2: tuple[tuple[str, str, str, str, str, str], ...] = (
    ("법인세법", "27의2", "법인세법 시행령", "제50조의2", "law_to_decree",
     "업무용승용차 특례 세부 계산·한도"),
    ("법인세법", "27의2", "법인세법 시행규칙", "제27조의2", "law_to_decree",
     "업무용승용차 서식·세부 자료"),
    ("법인세법", "27의2", "소득세법", "제33조의2", "parallel_tax_law",
     "소득세법상 업무용승용차 필요경비 불산입 특례"),
    ("법인세법", "27의2", "소득세법 시행령", "제78조의3", "parallel_tax_law",
     "소득세법 업무용승용차 특례 세부 계산·한도"),
    ("법인세법", "27의2", "소득세법 시행규칙", "제42조", "parallel_tax_law",
     "소득세법 업무용승용차 서식·세부사항"),
    ("소득세법", "33의2", "소득세법 시행령", "제78조의3", "law_to_decree",
     "업무용승용차 특례 세부 계산·한도"),
    ("소득세법", "33의2", "소득세법 시행규칙", "제42조", "law_to_decree",
     "업무용승용차 서식·세부사항"),
    ("소득세법", "33의2", "법인세법", "제27조의2", "parallel_tax_law",
     "법인세법상 업무용승용차 손금불산입 특례"),
    ("소득세법", "33의2", "법인세법 시행령", "제50조의2", "parallel_tax_law",
     "법인세법 업무용승용차 특례 세부 계산·한도"),
    ("소득세법", "33의2", "법인세법 시행규칙", "제27조의2", "parallel_tax_law",
     "법인세법 업무용승용차 서식·세부사항"),
)

# ── 매뉴얼 §3: 감가상각비 하위법령 연쇄 조문군 ────────────────────────────────
# (법인세법 시행령 조번호들, 소득세법 시행령 조번호들, 취지)
_SECTION3_ROWS: tuple[tuple[tuple[str, ...], tuple[str, ...], str], ...] = (
    (("24", "25", "26"), ("62",), "감가상각자산 범위·계상·상각범위액 계산 구조"),
    (("28", "29"), ("63",), "내용연수·상각률·내용연수 특례"),
    (("27",), ("64", "65", "66"), "상각방법 신고·변경·계산"),
    (("26의2", "26의3", "29의2"), ("67", "68", "70", "71", "73"),
     "종전·기준 감가상각비, 중고자산, 즉시상각, 의제상각, 잔존가액, 상각시부인"),
    (("32", "33", "34"), ("73", "73의2"), "상각부인액 처리·감가상각비 명세서"),
)


# ── §4: 다리 법령 공동 인용에서 도출한 병행쌍 (docs/bridge-parallel-pairs.md) ──
# 국조법·조특법의 한 조문이 소득세법·법인세법 조문을 나란히 인용하면 그 둘은
# 개인↔법인 짝이다. 그 판단을 내린 것은 스코어링이 아니라 입법자 자신이다.
# 다리 2건 이상(여러 곳에서 반복해 함께 인용)만 확정으로 올린다.
#
# §1과 출처를 나눈 이유:
#   * 근거가 매뉴얼이 아니라 인용 구조다 — source를 섞으면 검토 화면에서
#     '매뉴얼 확정'으로 잘못 표시된다.
#   * 제목·용어 스코어링으로는 찾을 수 없는 쌍이라, 임계값 보정용 recall
#     정답셋(golden_direct_pairs)에 넣으면 '임계값 미달' 경고만 늘린다.
BRIDGE_SOURCE = "bridge_confirmed"

# (소득세법 조번호, 법인세법 조번호, 다리 건수, 취지)
_SECTION4_BRIDGE: tuple[tuple[str, str, int, str], ...] = (
    ("119", "93", 2, "비거주자의 국내원천소득 ↔ 외국법인의 국내원천소득"),
    ("57", "57", 2, "외국납부세액공제 ↔ 외국 납부 세액공제 등"),
    ("32", "36", 2, "국고보조금 취득 사업용자산 필요경비 계산 ↔ 손금산입"),
    ("5", "6", 3, "과세기간 ↔ 사업연도"),
    ("94", "44", 3, "양도소득의 범위 ↔ 합병 시 피합병법인에 대한 과세"),
    ("76", "64", 7, "확정신고납부 ↔ 납부"),
    ("111", "64", 4, "양도소득 확정신고납부 ↔ 납부"),
    ("94", "64", 3, "양도소득의 범위 ↔ 납부"),
    ("111", "44", 2, "양도소득 확정신고납부 ↔ 합병 시 피합병법인에 대한 과세"),
    ("70", "60", 2, "종합소득과세표준 확정신고 ↔ 과세표준 등의 신고"),
    ("70의2", "60", 2, "성실신고확인서 제출 ↔ 과세표준 등의 신고"),
    # 연결법인 — 신고 조문끼리의 대응. 실무상 함께 볼 짝인지는 검토 대상으로 둔다
    ("70", "76의17", 2, "종합소득과세표준 확정신고 ↔ 연결과세표준 등의 신고"),
    ("70의2", "76의17", 2, "성실신고확인서 제출 ↔ 연결과세표준 등의 신고"),
)


_ART_JO_RE = re.compile(r"제(?:(\d+)의(\d+)조|(\d+)조(?:의(\d+))?)")


def _art_jo(article_ref: str) -> str:
    m = _ART_JO_RE.search(article_ref)
    if not m:
        return ""
    if m.group(1) is not None:
        return f"{m.group(1)}의{m.group(2)}"
    jo, sub = m.group(3), m.group(4)
    return f"{jo}의{sub}" if sub else jo


def golden_direct_pairs() -> set[tuple[str, str, str, str]]:
    """§1·§2의 직접 병행쌍 — 후보 필터 보정 시 엄격 recall 대상."""
    out: set[tuple[str, str, str, str]] = set()
    for bj, _bd, ij, _id, _r in _SECTION1:
        out.add(("법인세법", bj, "소득세법", ij))
    for src_law, src_jo, tgt_law, tgt_art, _rel, _r in _SECTION2:
        out.add((src_law, src_jo, tgt_law, _art_jo(tgt_art)))
    return out


def golden_group_pairs() -> set[tuple[str, str, str, str]]:
    """§3 감가상각 조문군의 행내 교차쌍 — 그룹 검토 관계 (완화 recall 대상)."""
    out: set[tuple[str, str, str, str]] = set()
    for bj_decrees, ij_decrees, _r in _SECTION3_ROWS:
        for bd in bj_decrees:
            for sd in ij_decrees:
                out.add(("법인세법 시행령", bd, "소득세법 시행령", sd))
    return out


def _jo_display(jo_no: str) -> str:
    if "의" in jo_no:
        jo, sub = jo_no.split("의", 1)
        return f"제{jo}조의{sub}"
    return f"제{jo_no}조"


def _entry(
    target_law: str,
    target_article: str,
    relation_type: str,
    reason: str,
    source: str = GOLDEN_SOURCE,
) -> dict:
    return {
        "target_law": target_law,
        "target_article": target_article,
        "relation_type": relation_type,
        "confidence": "confirmed",
        "source": source,
        "reason": reason,
    }


def golden_entries() -> dict[str, list[dict]]:
    """매트릭스 키 → confirmed 엔트리 목록."""
    out: dict[str, list[dict]] = {}

    def add(law: str, jo: str, entry: dict) -> None:
        out.setdefault(matrix_key(law, jo), []).append(entry)

    # §1 — 대칭 등록
    for bj, bj_disp, ij, ij_disp, reason in _SECTION1:
        add("법인세법", bj, _entry("소득세법", ij_disp, "parallel_tax_law", reason))
        add("소득세법", ij, _entry("법인세법", bj_disp, "parallel_tax_law", reason))

    # §2 — 명시된 방향 그대로
    for src_law, src_jo, tgt_law, tgt_art, rel, reason in _SECTION2:
        add(src_law, src_jo, _entry(tgt_law, tgt_art, rel, reason))

    # §3 — 감가상각: 기준 법률 조문 → 양측 시행령 + 시행령 행내 교차(대칭)
    for bj_decrees, ij_decrees, reason in _SECTION3_ROWS:
        for d in bj_decrees:
            add("법인세법", "23",
                _entry("법인세법 시행령", _jo_display(d), "law_to_decree", f"감가상각 연쇄: {reason}"))
        for d in ij_decrees:
            add("소득세법", "33",
                _entry("소득세법 시행령", _jo_display(d), "law_to_decree", f"감가상각 연쇄: {reason}"))
        for bd in bj_decrees:
            for sd in ij_decrees:
                add("법인세법 시행령", bd,
                    _entry("소득세법 시행령", _jo_display(sd), "parallel_tax_law",
                           f"감가상각 병행: {reason}"))
                add("소득세법 시행령", sd,
                    _entry("법인세법 시행령", _jo_display(bd), "parallel_tax_law",
                           f"감가상각 병행: {reason}"))

    # §4 — 다리 도출 병행쌍 (대칭 등록, 출처 구분)
    for ij, bj, weight, reason in _SECTION4_BRIDGE:
        note = f"다리 공동인용 {weight}건: {reason}"
        add("소득세법", ij,
            _entry("법인세법", _jo_display(bj), "parallel_tax_law", note, BRIDGE_SOURCE))
        add("법인세법", bj,
            _entry("소득세법", _jo_display(ij), "parallel_tax_law", note, BRIDGE_SOURCE))

    return out
