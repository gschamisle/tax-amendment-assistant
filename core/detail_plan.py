"""세제개편안 상세본 파싱 + 법률안 대조.

상세본은 **개정안이 어느 조문을 건드리는지 입안자가 직접 밝혀 둔 문서**다.
세부항목 제목에 근거 조문이 박혀 있다.

    - ① 국내생산세액공제 요건 및 적용기한(조특법 §29①)
    - (2) 친환경 업무용 승용차 감가상각비 한도 조정(소득법 §33의2, 법인법 §27의2)

법률안(일부개정법률안)은 '무엇이 바뀌었는지'를 조문 순서로 적고, 상세본은
'왜·어느 조문을' 바꾸는지를 정책 항목 순서로 적는다. 둘을 대조하면 기존 두
스캐너(번호 밀림·병행개정)가 못 보는 각도가 열린다 —
**정책은 정해졌는데 조문이 안 만들어진 경우**.

문서 한계는 docs/세제개편안-상세본-구조.md 참조. 사람이 쓰고 보고 과정에서
검토자 스타일이 반영돼 표기가 흔들리므로, 파싱 실패를 조용히 넘기지 않고
'조문 표기 없음'으로 남겨 눈에 보이게 한다.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field

from core import law_abbrev

# 제목 줄: '- ① 제목(조특법 §29①)' / '(2) 제목(소득법 §33의2, 법인법 §27의2)'
_HEADING_RE = re.compile(
    r"^[-\s]*(?P<mark>[①-⑳]|\(\d+\))\s*(?P<title>.+?)\s*$", re.M
)
# 제목 끝 괄호 — 근거 표기. 조문 표기가 다음 줄로 넘어간 경우까지 잡으려고
# 제목 전체에서 마지막 괄호를 취한다.
_PAREN_RE = re.compile(r"\(([^()]*)\)\s*$")
# '§29', '§29의3' (뒤따르는 항 기호 ①·② 는 조 단위 비교에 쓰지 않는다)
_ARTICLE_RE = re.compile(r"§\s*(\d+)\s*(?:의\s*(\d+))?")
# 세그먼트 앞머리의 법령명 (약칭·정식 모두)
_LAW_HEAD_RE = re.compile(r"^\s*([가-힣][가-힣\s·ㆍ]*?)\s*(?=§)")

_REASON_RE = re.compile(r"^<개정이유>\s*(.+?)\s*$", re.M)
_TIMING_RE = re.compile(r"^<적용시기>\s*(.+?)\s*$", re.M)

# 상세본 약칭 → 정식 법령명 (law_abbrev의 역방향)
_LONG: dict[str, str] = {}
for _full in (
    "관세법", "국세기본법", "국세징수법", "국제조세조정에 관한 법률",
    "농어촌특별세법", "법인세법", "부가가치세법", "상속세 및 증여세법",
    "소득세법", "조세특례제한법", "종합부동산세법",
):
    for _suffix in ("", " 시행령", " 시행규칙"):
        _LONG[law_abbrev.law(_full + _suffix)] = _full + _suffix


def to_full_law(short: str) -> str:
    """'조특령' → '조세특례제한법 시행령'. 모르면 원문 그대로."""
    return _LONG.get(str(short).strip(), str(short).strip())


@dataclass
class PlanItem:
    """상세본의 개정 항목 하나."""

    title: str
    refs: list[tuple[str, str]] = field(default_factory=list)   # (정식 법령명, 조 키)
    raw_ref: str = ""
    reason: str = ""
    timing: str = ""

    @property
    def has_refs(self) -> bool:
        return bool(self.refs)


def parse_refs(text: str) -> list[tuple[str, str]]:
    """'소득법 §33의2, 법인법 §27의2' → [('소득세법','33의2'), ('법인세법','27의2')].

    쉼표로 법령이 갈리고, 한 법령 안에서 '·'나 '§'가 여러 조를 잇는다
    ('조특법 §132·§144'). 법령명이 생략된 세그먼트는 앞 법령을 잇는다.
    """
    out: list[tuple[str, str]] = []
    current = ""
    for segment in str(text).split(","):
        head = _LAW_HEAD_RE.search(segment)
        if head:
            current = to_full_law(head.group(1).replace(" ", ""))
        if not current:
            continue
        for m in _ARTICLE_RE.finditer(segment):
            key = f"{m.group(1)}의{m.group(2)}" if m.group(2) else m.group(1)
            pair = (current, key)
            if pair not in out:
                out.append(pair)
    return out


def parse_items(md_text: str) -> list[PlanItem]:
    """상세본 Markdown → 개정 항목 목록.

    목차는 본문과 같은 번호 체계를 쓰고 표로 뭉개져 들어오므로 본문 시작
    ('Ⅰ.' 대분류) 이후만 본다.
    """
    # 본문 시작 = 대분류가 **단독 줄**로 나오는 지점. 그냥 'Ⅰ.'을 찾으면 목차
    # 안의 표 셀에 걸린다(목차도 같은 번호 체계를 쓴다).
    m0 = re.search(r"^\s*Ⅰ\.\s*\S.*$", md_text, re.M)
    while m0 and ("···" in m0.group(0) or "<td" in m0.group(0) or "|" in m0.group(0)):
        m0 = re.search(r"^\s*Ⅰ\.\s*\S.*$", md_text, re.M | re.S) if False else \
            re.compile(r"^\s*Ⅰ\.\s*\S.*$", re.M).search(md_text, m0.end())
    body = md_text[m0.start():] if m0 else md_text

    # 목차 잔재는 점선(···)이나 끝의 쪽번호(' · 21')로 알아본다. 표 블록도 제외.
    def _is_toc(line: str) -> bool:
        return ("···" in line
                or re.search(r"[·.]\s*\d{1,3}\s*$", line) is not None
                or line.lstrip().startswith(("<t", "|")))

    body = "\n".join(ln for ln in body.splitlines() if not _is_toc(ln))

    items: list[PlanItem] = []
    matches = list(_HEADING_RE.finditer(body))
    for i, m in enumerate(matches):
        title = m.group("title").strip()
        if len(title) < 4 or title.startswith("|"):
            continue
        paren = _PAREN_RE.search(title)
        raw = paren.group(1).strip() if paren else ""
        refs = parse_refs(raw) if "§" in raw else []
        # 항목 본문 = 다음 제목 전까지. 개정이유·적용시기를 여기서 찾는다
        end = matches[i + 1].start() if i + 1 < len(matches) else len(body)
        chunk = body[m.end():end]
        reason = _REASON_RE.search(chunk)
        timing = _TIMING_RE.search(chunk)
        items.append(PlanItem(
            title=title,
            refs=refs,
            raw_ref=raw,
            reason=reason.group(1) if reason else "",
            timing=timing.group(1) if timing else "",
        ))
    return items


def scan(items: list[PlanItem], bills: list) -> dict:
    """상세본 항목 ↔ 법률안 개정 조문 대조.

    상태:
      covered        — 상세본에 있고 법률안도 그 조를 개정함
      missing_in_bill— 상세본에 있는데 법률안에 없음 (정책은 정해졌는데 조문 미반영)
      no_bill        — 그 법의 법률안이 이번 묶음에 없어 판단 보류
      no_refs        — 상세본에 조문 표기 자체가 없음 (사람 확인 필요)
    """
    by_law = {b.law_name: b for b in bills if getattr(b, "law_name", "")}
    rows: list[dict] = []
    for item in items:
        if not item.has_refs:
            rows.append({
                "제목": item.title, "법령명": "", "조번호": "", "raw": item.raw_ref,
                "개정이유": item.reason, "적용시기": item.timing, "상태": "no_refs",
            })
            continue
        for law, jo in item.refs:
            bill = by_law.get(law)
            if bill is None:
                status = "no_bill"
            elif jo in bill.targets:
                status = "covered"
            else:
                status = "missing_in_bill"
            rows.append({
                "제목": item.title, "법령명": law, "조번호": jo, "raw": item.raw_ref,
                "개정이유": item.reason, "적용시기": item.timing, "상태": status,
            })

    # 반대 방향 — 법률안에는 있는데 상세본이 언급하지 않은 조.
    #
    # 이쪽을 '상세본 누락'으로 부르면 안 된다. 상당수는 **의도적으로 빼 둔 것**이다:
    #   · 단순 조문 정비(번호 밀림에 따른 인용 정비 등) — 발표할 내용이 아니다
    #   · 외부에 알리지 않고 조용히 바로잡는 오류 수정
    # 그래서 상태 이름을 'undisclosed'로 둔다. 오류 목록이 아니라
    # **공표 자료에 드러나지 않은 개정** 목록이고, 내부 검토에서는 오히려 이쪽이
    # 먼저 눈여겨볼 대상일 수 있다.
    #
    # 번호 밀림 스캐너가 잡는 기술적 정비와 겹치므로, 겹치지 않는 것만 남기면
    # '설명 없이 실체가 바뀐 조문'에 가까워진다(구분은 호출부 몫).
    planned: set[tuple[str, str]] = {(law, jo) for it in items for law, jo in it.refs}
    extra: list[dict] = []
    for bill in bills:
        for jo in sorted(bill.targets, key=_jo_sort):
            if (bill.law_name, jo) not in planned:
                extra.append({
                    "법령명": bill.law_name,
                    "조번호": jo,
                    "지시문": bill.directives.get(jo, ""),
                })

    order = {"missing_in_bill": 0, "no_refs": 1, "no_bill": 2, "covered": 3}
    rows.sort(key=lambda r: (order.get(r["상태"], 9), r["법령명"], _jo_sort(r["조번호"])))
    return {"rows": rows, "undisclosed": extra, "item_count": len(items)}


def _jo_sort(jo: str) -> tuple:
    parts = str(jo).split("의")
    try:
        return (int(parts[0]), int(parts[1]) if len(parts) > 1 else 0)
    except ValueError:
        return (10**9, 0)
