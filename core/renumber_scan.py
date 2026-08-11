"""번호 밀림(이동) 누락 검토 — 개정문이 항·호·목 번호를 밀었는데,
그 번호를 인용하던 조문의 인용 정비가 개정안에 빠졌는지 찾는다.

내용상 누락(제도 취지상 함께 고쳤어야 할 조문)이 아니라, 기계적으로 확정되는 누락만 본다:
    개정안: 소득세법 제17조제5항·제6항 → 제6항·제7항
    현행:   조세특례제한법 제○조가 "소득세법 제17조제5항"을 인용
    ⇒ 이 인용은 이제 다른 항을 가리킨다. 개정안에 정비가 없으면 누락.

판정 재료는 전부 결정적이다(지시문 regex + 사전 빌드 인용 그래프). LLM을 쓰지 않는다.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field

from core.citation_graph import _parse_target_ref, back_citation_edges, graph_meta
from core.citation_parser import base_law_name, parse_citations
from core.draft_bill_parser import _is_directive, manual_amendment_targets

_QUOTED_RE = re.compile(r"[“”‘’\"'].*?[“”‘’\"']")
_JO_HEAD_RE = re.compile(r"제\s*(\d+)\s*조(?:\s*의\s*(\d+))?")
def _is_directive_line(line: str) -> bool:
    """지시문 줄인가. 판정은 draft_bill_parser 하나로 모은다.

    한때 이 모듈이 자체 규칙(줄머리가 조번호인가)을 썼는데, 그러면 같은 개정문을
    두 파서가 다르게 읽는다 — 실측에서 조특법안 기준 6개 조가 어긋났고
    (신설 조문 본문 '제121조의36(제목) ① …'을 지시문으로 오인),
    개정 조문 목록이 갈리면 covered/missing 판정이 통째로 흔들린다.
    """
    return _is_directive(line) is not None

# 단위별 기호. 조·호는 가지번호("제1호의2")를 가질 수 있다.
# PDF 개행 복원 과정에서 "제2 항"처럼 공백이 끼므로 공백을 허용한다.
_UNIT_RE = {
    "조": re.compile(r"제\s*(\d+)\s*조(?:\s*의\s*(\d+))?"),
    "항": re.compile(r"제\s*(\d+)\s*항"),
    "호": re.compile(r"제\s*(\d+)\s*(?:의\s*(\d+))?\s*호"),
    "목": re.compile(r"([가-힣])\s*목"),
}
# "…을/를 [각각] …으로/로 한다|하고|하며|하되"
_MOVE_RE = re.compile(
    r"(?P<src>[^,;]{2,90}?)(?:을|를)\s*(?:각각\s*)?"
    r"(?P<dst>[^,;]{2,90}?)(?:으로|로)\s*(?:한다|하고|하며|하되)"
)
_RANGE_HINT_RE = re.compile(r"부터.*까지")
_MOK_ORDER = "가나다라마바사아자차카타파하거너더러머버서어저처커터퍼허"


@dataclass
class RenumberEvent:
    """한 조에서 일어난 번호 이동."""

    jo_key: str                       # 대상 조 ("17", "18의2")
    unit: str                         # "조" | "항" | "호" | "목"
    moved: dict[str, str] = field(default_factory=dict)   # 구번호 → 신번호
    raw: str = ""

    def label(self) -> str:
        pairs = ", ".join(f"{k}→{v}" for k, v in self.moved.items())
        return f"제{_jo_label(self.jo_key)} {self.unit} {pairs}"


def _jo_label(jo_key: str) -> str:
    parts = str(jo_key).split("의")
    return f"{parts[0]}조" + (f"의{parts[1]}" if len(parts) > 1 else "")


def _syms(text: str, unit: str) -> list[str]:
    out: list[str] = []
    for m in _UNIT_RE[unit].finditer(text):
        if unit == "목":
            out.append(m.group(1))
        else:
            sub = m.group(2) if m.lastindex and m.lastindex >= 2 else ""
            out.append(f"{m.group(1)}의{sub}" if sub else m.group(1))
    return out


def _expand(syms: list[str], unit: str, ranged: bool) -> list[str]:
    """'제2항부터 제10항까지' → 2..10. 범위 표기가 아니면 그대로."""
    if not ranged or len(syms) != 2:
        return syms
    a, b = syms
    if unit == "목":
        i, j = _MOK_ORDER.find(a), _MOK_ORDER.find(b)
        return list(_MOK_ORDER[i : j + 1]) if 0 <= i <= j else syms
    if "의" in a or "의" in b:
        return syms
    try:
        return [str(n) for n in range(int(a), int(b) + 1)]
    except ValueError:
        return syms


def renumber_events(body: str) -> list[RenumberEvent]:
    """개정문 지시문에서 번호 이동 사건 목록."""
    events: list[RenumberEvent] = []
    for line in body.splitlines():
        # 신설 조문 '본문'에도 "제7항을 적용할 때 …로 한다" 꼴이 나온다 → 지시문 줄만 본다
        if not _is_directive_line(line):
            continue
        clean = _QUOTED_RE.sub(" ", line.strip())  # 문구 치환은 번호 이동이 아니다
        head = _JO_HEAD_RE.search(clean)
        if not head:
            continue
        head_key = f"{head.group(1)}의{head.group(2)}" if head.group(2) else head.group(1)

        for m in _MOVE_RE.finditer(clean):
            src, dst = m.group("src"), m.group("dst")
            # '같은 조'는 이 지점 앞에서 마지막으로 거론된 조를 가리킨다
            prior = [j for j in _JO_HEAD_RE.finditer(clean) if j.start() < m.end()]
            jo_key = head_key
            if prior:
                last = prior[-1]
                jo_key = f"{last.group(1)}의{last.group(2)}" if last.group(2) else last.group(1)

            for unit in ("조", "항", "호", "목"):
                a = _expand(_syms(src, unit), unit, bool(_RANGE_HINT_RE.search(src)))
                b = _expand(_syms(dst, unit), unit, bool(_RANGE_HINT_RE.search(dst)))
                if not a or not b or a == b:
                    continue
                if unit == "조":
                    # 좌변의 조는 '대상 조' 표기일 뿐이고 우변에 조가 없으면 이동이 아니다.
                    # 조 이동은 좌·우 개수가 맞아야 한다.
                    if len(a) != len(b):
                        continue
                if len(a) != len(b):
                    # 개수가 안 맞으면 대응을 확정할 수 없다 → 경계만 기록(보수적)
                    moved = {a[0]: b[0]}
                else:
                    moved = dict(zip(a, b))
                moved = {k: v for k, v in moved.items() if k != v}
                if not moved:
                    continue
                events.append(RenumberEvent(
                    jo_key=jo_key if unit != "조" else jo_key,
                    unit=unit,
                    moved=moved,
                    raw=m.group(0).strip(),
                ))
    return events


def directive_texts(body: str) -> dict[str, str]:
    """조별 지시문 원문(같은 조를 여러 줄이 건드리면 이어 붙임)."""
    out: dict[str, str] = {}
    for line in body.splitlines():
        s = line.strip()
        if not _is_directive_line(s):
            continue
        m = _JO_HEAD_RE.match(s)
        if not m:
            continue
        key = f"{m.group(1)}의{m.group(2)}" if m.group(2) else m.group(1)
        out[key] = (out.get(key, "") + "\n" + s).strip()
    return out


def _unit_ref(jo_key: str, unit: str, num: str) -> str:
    """'제95조제4항' 꼴 인용 표기. 공백은 지운 형태로 맞춘다."""
    base = f"제{_jo_label(jo_key)}"
    if unit == "조":
        return base
    if unit == "목":
        return f"{base}{num}목"
    return f"{base}제{num}{unit}"


def citation_fixed(directive: str, jo_key: str, unit: str, old: str, new: str) -> bool:
    """지시문이 그 인용을 실제로 정비했는지 — 구·신 표기가 함께 등장하면 정비로 본다.

    개정문의 인용 정비는 "…제95조제4항"을 "…제95조제11항"으로 한다 형태라
    구 표기와 신 표기가 같은 지시문에 함께 나온다. 조를 건드렸다는 사실만으로는
    그 인용이 고쳐졌다고 볼 수 없어(다른 사유의 개정일 수 있다) 표기 대조까지 한다.
    """
    if not directive:
        return False
    flat = re.sub(r"\s+", "", directive)
    return (
        _unit_ref(jo_key, unit, old) in flat
        and _unit_ref(jo_key, unit, new) in flat
    )


def _cited_units(edge: dict, jo: str, jo_sub: str, unit: str) -> tuple[set[str], bool]:
    """엣지가 대상 조에서 짚은 하위 번호 집합과 '조를 짚었는지' 여부.

    반환 (번호집합, matched). '' = 하위 번호 미지정(조 전체 인용).
    matched=False는 대상 조를 특정하지 못했다는 뜻 — 판정 불가라 확인 대상으로 남긴다.

    1차 근거는 그래프가 이미 해석해 둔 target_ref다. cite_raw만 보면
    "같은 조 제7항"처럼 조가 생략된 조각은 어느 조인지 알 수 없다.
    2차로 cite_raw를 파싱해 항 범위(제1항부터 제5항까지)를 보충한다 —
    빌더의 target_ref는 항 범위에서 시작 항만 남기기 때문이다.
    """
    if unit == "조":                       # 조 이동 — 조를 짚었다면 무조건 영향
        return {"*"}, True

    found: set[str] = set()
    matched = False

    ref_jo, ref_sub, ref_hang, ref_ho = _parse_target_ref(str(edge.get("target_ref", "")))
    if ref_jo == jo and (ref_sub or "") == (jo_sub or ""):
        matched = True
        if unit == "항":
            found.add(ref_hang or "")
        elif unit == "호":
            found.add(ref_ho or "")
        # 목은 target_ref에 실리지 않는다 → cite_raw 파싱에 맡긴다

    attr = {"항": "hang", "호": "ho", "목": "mok"}[unit]
    for c in parse_citations(str(edge.get("cite_raw", ""))):
        if c.jo != jo or (c.jo_sub or "") != (jo_sub or ""):
            continue
        matched = True
        val = getattr(c, attr) or ""
        if unit == "항" and val and c.hang_end:
            try:
                found |= {str(n) for n in range(int(val), int(c.hang_end) + 1)}
                continue
            except ValueError:
                pass
        found.add(val)

    return (found or {""}), matched


def scan_renumber_omissions(law_name: str, body: str) -> dict:
    """번호 밀림 → 역인용 대조 결과.

    Returns:
        {
          "graph_ok", "graph_meta", "events": [...],
          "hits": [ {법령명, 조번호, 제목, 인용, 대상, 영향번호, 상태} ],
        }
        상태: "covered"(같은 개정안이 그 조문도 개정) | "missing"(정비 없음)
              | "decree"(같은 모법의 시행령·규칙 → 후속개정) | "other_law"(타법 → 별도 개정)
    """
    meta = graph_meta()
    covered_laws = set(meta.get("laws", []))
    events = renumber_events(body)
    manual = set(manual_amendment_targets(body))
    directives = directive_texts(body)
    amended_base = base_law_name(law_name)

    rows: dict[tuple, dict] = {}
    for ev in events:
        jo, jo_sub = (ev.jo_key.split("의", 1) + [""])[:2]
        for edge in back_citation_edges(law_name, jo, jo_sub):
            if edge.get("type") == "byeolpyo":
                continue
            raw = str(edge.get("cite_raw", ""))
            via_range = bool(edge.get("via_range"))
            cited, matched = _cited_units(edge, jo, jo_sub, ev.unit)

            if ev.unit == "조":
                affected = ["*"]
            else:
                affected = sorted(set(cited) & set(ev.moved))
                if not affected:
                    # 조 전체를 인용한 건("제33조부터 제39조까지") 항·호·목 이동과 무관하다.
                    # 다만 파싱이 대상 조를 짚지 못한 경우(matched=False)는 판정 불가 →
                    # 누락 방지 원칙에 따라 확인 대상으로 남긴다.
                    if matched:
                        continue
                    affected = ["(인용 형태 판정 불가 — 확인 필요)"]

            src_law = str(edge.get("source_law", ""))
            src_jo = str(edge.get("source_jo", ""))
            if src_law == law_name and src_jo == ev.jo_key:
                continue  # 이동 대상 조 자기 자신

            if base_law_name(src_law) != amended_base:
                status = "other_law"
            elif src_law != law_name:
                status = "decree"
            elif src_jo not in manual:
                status = "missing"
            elif _fixed_here(directives.get(src_jo, ""), ev, affected):
                status = "covered"
            else:
                # 그 조를 개정하긴 했으나 이 인용의 구·신 표기 대조가 안 된다
                status = "touched"

            key = (src_law, src_jo, ev.jo_key, ev.unit)
            row = rows.get(key)
            if row is None:
                row = {
                    "법령명": src_law,
                    "조번호": src_jo,
                    "제목": edge.get("source_title", ""),
                    "대상": ev.label(),
                    "대상조": ev.jo_key,
                    "단위": ev.unit,
                    "이동": ev.moved,
                    "영향번호": [],
                    "인용": [],
                    "범위인용": False,
                    "상태": status,
                }
                rows[key] = row
            for a in affected:
                if a not in row["영향번호"]:
                    row["영향번호"].append(a)
            if raw and raw not in row["인용"]:
                row["인용"].append(raw)
            row["범위인용"] = row["범위인용"] or via_range

    return {
        "graph_ok": bool(covered_laws),
        "graph_covered": law_name in covered_laws,
        "graph_meta": meta,
        "events": events,
        "manual_targets": sorted(manual),
        "directives": directives,
        "hits": sort_hits(rows.values()),
    }


def _fixed_here(directive: str, ev: RenumberEvent, affected: list[str]) -> bool:
    """영향받은 번호 전부에 대해 구·신 표기 정비가 확인되면 True."""
    nums = [a for a in affected if a in ev.moved]
    if not nums:
        return False
    return all(
        citation_fixed(directive, ev.jo_key, ev.unit, old, ev.moved[old])
        for old in nums
    )


_STATUS_ORDER = {
    "missing": 0, "missing_other": 1, "touched": 2, "touched_other": 3,
    "other_law": 4, "decree": 5, "covered_other": 6, "covered": 7,
}


def sort_hits(hits) -> list[dict]:
    return sorted(
        hits,
        key=lambda r: (_STATUS_ORDER.get(r["상태"], 9), r["법령명"], str(r["조번호"])),
    )


def apply_batch_coverage(results: list[dict]) -> None:
    """같은 입법예고 묶음의 다른 법안이 그 조문을 정비했는지로 'other_law'를 가른다.

    타법 인용이라도 그 타법 개정안이 같은 회차에 함께 예고됐다면 정비가 거기 있을 수 있다.
    묶음 안에서 확인되면 covered_other, 확인되지 않으면 missing_other(진짜 누락 후보)로 본다.
    묶음에 그 법의 개정안 자체가 없으면(시행령·규칙 등) 판단 근거가 없어 other_law로 남긴다.
    """
    batch = {r["law_name"]: r["directives"] for r in results if r.get("law_name")}
    for r in results:
        for h in r["hits"]:
            if h["상태"] != "other_law":
                continue
            directives = batch.get(h["법령명"])
            if directives is None:
                continue          # 묶음에 그 법의 개정안이 없음 → 판단 보류
            if str(h["조번호"]) not in directives:
                h["상태"] = "missing_other"
                continue
            text = directives[str(h["조번호"])]
            nums = [a for a in h["영향번호"] if a in h["이동"]]
            fixed = bool(nums) and all(
                citation_fixed(text, h["대상조"], h["단위"], old, h["이동"][old])
                for old in nums
            )
            h["상태"] = "covered_other" if fixed else "touched_other"
        r["hits"] = sort_hits(r["hits"])
