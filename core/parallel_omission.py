"""병행개정 누락 검토 — 한 법을 고쳤는데 대응 조문을 안 고쳤는지 본다.

번호 밀림(renumber_scan)이 기계적으로 확정되는 누락을 다룬다면, 이쪽은
**판단이 필요한 후보**를 추린다. 매트릭스가 "이 조문을 고치면 저 조문도 고쳐야
한다"는 관계를 사전에 확정해 두었으므로 후보 추출 자체는 결정적이지만,
그 관계가 **이번 개정 내용에도 해당하는지**는 사람이 봐야 한다.

  법인세법 제24조: 특례기부금 대상에 14)를 신설      ← 개정함
  소득세법 제34조: 대응하는 기부금 필요경비 조항       ← 안 고침
  ⇒ 기부금 대상을 한쪽에만 추가한 것인지 확인 필요

그래서 산출물은 '누락'이 아니라 '검토 후보'다. 판별을 돕도록 원 조문의
**개정 지시문을 함께 싣는다** — 지시문만 보면 대응이 필요한 개정인지 아닌지가
대개 몇 초 만에 갈린다(약칭 정리처럼 파급이 없는 개정이 상당수다).
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field

from core.draft_bill_parser import find_amendment_body, manual_amendment_targets
from core.parallel_matrix import matrix_available, matrix_meta, parallel_hits
from core.pdf_bill_text import unwrap
from core.renumber_scan import _jo_label, directive_texts

# 병행 관계만 본다. citation·back_citation은 단순 인용이라 renumber_scan이 담당한다
# (여기 섞으면 인용 한 건마다 후보가 쏟아져 판단할 수 있는 양을 넘는다).
PARALLEL_SOURCES: frozenset[str] = frozenset({
    "golden_manual",    # 매뉴얼 확정 매핑 — 신뢰도 최상
    "semantic_llm",     # 쌍별 판별로 확정된 동일 취지
    "code_hint",        # config의 코드 매핑 힌트
    "related_hint",     # 연관 조문 힌트(같은 법 안의 관련 조문 포함)
})

_JO_IN_REF_RE = re.compile(r"제\s*(\d+)\s*조(?:\s*의\s*(\d+))?")


def ref_to_jo_key(ref: str) -> str:
    """'제104조의31제1항' → '104의31'. 조 단위로 비교하기 위한 정규화."""
    m = _JO_IN_REF_RE.match(str(ref).strip())
    if not m:
        return ""
    return f"{m.group(1)}의{m.group(2)}" if m.group(2) else m.group(1)


@dataclass
class Bill:
    """개정안 하나에서 뽑아낸, 대조에 필요한 것 전부."""

    law_name: str
    targets: set[str] = field(default_factory=set)      # 개정 대상 조 (조 단위 키)
    directives: dict[str, str] = field(default_factory=dict)
    path: str = ""


def load_bill(text: str, path: str = "") -> Bill | None:
    """개정안 원문(PDF 변환본·HWPX 추출문 등) → Bill. 개정문이 없으면 None."""
    law_name, body = find_amendment_body(unwrap(text))
    if not body:
        return None
    return Bill(
        law_name=law_name,
        targets=set(manual_amendment_targets(body)),
        directives=directive_texts(body),
        path=path,
    )


def scan(bills: list[Bill]) -> dict:
    """개정안 묶음 → 병행 대응 조문 대조 결과.

    상태:
      missing  — 그 법 개정안이 이번 묶음에 있는데 대응 조문은 안 건드림 (검토 후보)
      covered  — 대응 조문도 같은 묶음에서 개정됨
      pending  — 그 법 개정안이 묶음에 없어 판단 보류 (시행령·미상정 법률 등)
    """
    by_law = {b.law_name: b for b in bills if b.law_name}
    rows: list[dict] = []

    for bill in bills:
        for jo in sorted(bill.targets, key=_jo_sort):
            for hit in parallel_hits(bill.law_name, jo):
                if hit.get("source") not in PARALLEL_SOURCES:
                    continue
                target_law = str(hit.get("target_law", ""))
                target_ref = str(hit.get("target_article", ""))
                target_jo = ref_to_jo_key(target_ref)
                if target_law == bill.law_name and target_jo == jo:
                    continue                      # 자기 자신
                other = by_law.get(target_law)
                if other is None:
                    status = "pending"
                elif target_jo and target_jo in other.targets:
                    status = "covered"
                else:
                    status = "missing"
                rows.append({
                    "법령명": bill.law_name,
                    "조번호": jo,
                    "조문": f"제{_jo_label(jo)}",
                    "개정지시문": bill.directives.get(jo, ""),
                    "대상법령": target_law,
                    "대상조문": target_ref,
                    "근거": str(hit.get("source", "")),
                    "사유": str(hit.get("reason", "")),
                    "상태": status,
                })

    order = {"missing": 0, "pending": 1, "covered": 2}
    # 근거 신뢰도 순: 매뉴얼 확정 → 쌍별 판별 → 힌트
    src_order = {"golden_manual": 0, "semantic_llm": 1, "code_hint": 2, "related_hint": 3}
    rows.sort(key=lambda r: (
        order.get(r["상태"], 9), src_order.get(r["근거"], 9), r["법령명"], _jo_sort(r["조번호"]),
    ))
    return {
        "matrix_ok": matrix_available(),
        "matrix_meta": matrix_meta(),
        "laws": sorted(by_law),
        "rows": rows,
    }


def laws_with_parallel_relations() -> set[str]:
    """병행 관계가 하나라도 있는 법령.

    matrix에 '등재됐는지'로 판단하면 안 된다 — 인용 레이어 덕에 32개 법령이 모두
    들어 있지만, 그중 병행 상대가 있는 것은 소득·법인·부가·상증·조특 5개 군뿐이다.
    종부세법처럼 병행 항목이 비어 있는 것은 도구의 공백이 아니라 실체에 가깝다
    (병행 상대인 재산세는 지방세법이라 추적 밖).
    """
    from core.parallel_matrix import _load

    entries, _ = _load()
    laws: set[str] = set()
    for key, hits in entries.items():
        rows = [h for h in hits if h.get("source") in PARALLEL_SOURCES]
        if not rows:
            continue
        laws.add(key.rsplit("|", 1)[0])
        laws.update(str(h.get("target_law", "")) for h in rows)
    laws.discard("")
    return laws


def _jo_sort(jo: str) -> tuple:
    parts = str(jo).split("의")
    try:
        return (int(parts[0]), int(parts[1]) if len(parts) > 1 else 0)
    except ValueError:
        return (10**9, 0)


def group_by_source_article(rows: list[dict]) -> list[dict]:
    """같은 원 조문에 걸린 대응들을 묶는다 — 지시문을 한 번만 읽으면 되도록."""
    grouped: dict[tuple[str, str], dict] = {}
    for r in rows:
        key = (r["법령명"], r["조번호"])
        g = grouped.get(key)
        if g is None:
            g = {k: r[k] for k in ("법령명", "조번호", "조문", "개정지시문")}
            g["대응"] = []
            grouped[key] = g
        g["대응"].append({k: r[k] for k in ("대상법령", "대상조문", "근거", "상태", "사유")})
    return list(grouped.values())
