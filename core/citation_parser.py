"""인용·준용 규정 파싱 (regex 기반)."""
import re
from dataclasses import dataclass, field

# ── 패턴 ──────────────────────────────────────────────────────────────────
# 타법 인용: 「법령명」 제X조제Y항...  (최우선 파싱)
_CROSS_LAW = r'「([^」]+)」\s*제(\d+)조(?:의(\d+))?(?:제(\d+)항)?(?:제(\d+)호)?(?:제(\d+)목)?'
# 타법 인용: 법령명이 낫표 없이 직접 쓰인 경우 (예: 상속세 및 증여세법 제60조)
_NAMED_LAW = r'([가-힣][가-힣\sㆍ·]{1,40}(?:법률|법|영|령|규칙))\s*제(\d+)조(?:의(\d+))?(?:제(\d+)항)?(?:제(\d+)호)?(?:제(\d+)목)?'
# 같은 법/령/영/규칙 인용: 같은 법 제X조제Y항...
_SAME_LAW = r'(같은\s*(?:법|령|영|규칙))\s*제(\d+)조(?:의(\d+))?(?:제(\d+)항)?(?:제(\d+)호)?(?:제(\d+)목)?'
# 같은 조 인용: 같은 조 제X항...
_SAME_JO = r'(같은\s*조)\s*(?:제(\d+)항)?(?:제(\d+)호)?(?:제(\d+)목)?'
# 지시적 법령 인용: "법 제X조"(시행령·시행규칙→모법), "영 제X조"(시행규칙→시행령),
# "이 법/이 영/이 규칙 제X조"(자기 참조). 법령명 끝글자 오인 방지를 위해 직전 한글 금지.
_DEICTIC_LAW = r'(?<![가-힣ㆍ·」])(이\s*법|이\s*영|이\s*규칙|법|영|규칙)\s*제(\d+)조(?:의(\d+))?(?:제(\d+)항)?(?:제(\d+)호)?(?:제(\d+)목)?'
# 조 번호를 포함한 직접 인용: 제X조, 제X조의Y, 제X조제Y항, ...
_DIRECT = r"제(\d+)조(?:의(\d+))?(?:제(\d+)항)?(?:제(\d+)호)?(?:제(\d+)목)?"
# 항/호/목 범위 인용: 제X항부터 제Y항까지
_RANGE = r"제(\d+)(항|호|목)(?:부터|에서)\s*제(\d+)(항|호|목)까지"
# 조 범위 인용: 제X조부터 제Y조까지
_ARTICLE_RANGE = r"제(\d+)조(?:의(\d+))?(?:부터|에서)\s*제(\d+)조(?:의(\d+))?까지"
# 조 내 항 범위 인용: 제X조의Y제A항부터 제B항까지 (항·부터 사이 선택적 공백 허용)
_ARTICLE_HANG_RANGE = r"제(\d+)조(?:의(\d+))?제(\d+)항\s*(?:부터|에서)\s*제(\d+)항까지"
# 동일 조 내 단독 항·호 인용: "제3항", "제2항과 제3항", "각 호" 등
_INTRA = r"제(\d+)(항|호|목)(?!까지)"

CROSS_LAW_RE = re.compile(_CROSS_LAW)
NAMED_LAW_RE = re.compile(_NAMED_LAW)
SAME_LAW_RE = re.compile(_SAME_LAW)
SAME_JO_RE = re.compile(_SAME_JO)
DEICTIC_LAW_RE = re.compile(_DEICTIC_LAW)
DIRECT_RE = re.compile(_DIRECT)
RANGE_RE = re.compile(_RANGE)
ARTICLE_RANGE_RE = re.compile(_ARTICLE_RANGE)
ARTICLE_HANG_RANGE_RE = re.compile(_ARTICLE_HANG_RANGE)
INTRA_RE = re.compile(_INTRA)


@dataclass
class Citation:
    raw: str
    jo: str
    law_name: str = ""        # 타법 인용 시 법령명 (「소득세법」 or "같은 법" 등)
    jo_sub: str = ""
    hang: str = ""
    hang_end: str = ""        # 항 범위 인용 시 끝 항번호 (예: "제1항~제5항" → hang="1", hang_end="5")
    ho: str = ""
    mok: str = ""
    is_range: bool = False
    range_end_jo: str = ""
    range_end_jo_sub: str = ""
    span: tuple[int, int] = field(default_factory=lambda: (0, 0))
    relative: str = ""         # "같은법", "같은조" 등 문장 내 선행 참조 해석용
    is_junyo: bool = False     # "준용한다"로 끌어쓴 인용(준용)인지 — 단순 인용과 구분


# Citation.relative에 기록되는 지시적 참조 토큰 (공백 제거 정규화)
_DEICTIC_TOKENS = ("이법", "이영", "이규칙", "법", "영", "규칙")


def _norm_law(name: str) -> str:
    return str(name).replace(" ", "").replace("ㆍ", "").replace("·", "").strip()


def base_law_name(law_name: str) -> str:
    """시행령·시행규칙 명칭에서 모법 명칭을 얻는다. 모법이면 그대로 반환."""
    name = str(law_name).strip()
    for suffix in ("시행규칙", "시행령"):
        if name.endswith(suffix):
            return name[: -len(suffix)].strip()
    return name


def resolve_deictic_law(token: str, source_law_name: str) -> str:
    """'법 제X조'류 지시적 참조를 source 법령 기준 절대 법령명으로 해석한다."""
    t = str(token).replace(" ", "")
    base = base_law_name(source_law_name)
    if not base:
        return source_law_name
    if t in ("법", "이법"):
        return base
    if t in ("영", "이영"):
        return f"{base} 시행령"
    if t in ("규칙", "이규칙"):
        return f"{base} 시행규칙"
    return source_law_name


def effective_law_name(citation: "Citation", source_law_name: str) -> str:
    """인용이 가리키는 법령명을 source 법령 기준으로 해석해 반환한다.

    '같은 법/같은 조'는 _resolve_relative_citations에서 같은 문장의 선행 명시 법령으로
    이미 해석되어 law_name에 실제 법령명이 들어온다(예: 「법인세법」 → "법인세법").
    선행 법령을 못 찾아 미해석으로 남은 경우(law_name이 '같은…'으로 시작)에만
    source 법령으로 폴백한다.
    """
    if citation.relative in _DEICTIC_TOKENS:
        return resolve_deictic_law(citation.relative, source_law_name)
    name = citation.law_name
    if not name or name.startswith("같은"):
        return source_law_name
    return name


def _sentence_start(text: str, pos: int) -> int:
    """pos가 속한 문장의 시작 위치를 반환한다."""
    starts = [text.rfind(mark, 0, pos) for mark in (".", "?", "!", "\n", ";")]
    start = max(starts)
    return 0 if start < 0 else start + 1


def _is_inside(span: tuple[int, int], seen: set[tuple[int, int]]) -> bool:
    return any(s[0] <= span[0] and span[1] <= s[1] for s in seen)


def _preceded_by_buchik(text: str, pos: int, window: int = 8) -> bool:
    """제X조 바로 앞에 '부칙'이 있으면 본문 조문이 아니라 부칙(경과규정) 참조다.

    예: '법률 제6538호 부칙 제29조' → 옛 법률의 부칙 제29조이며 본문 제29조와 무관.
    앱은 부칙 조문을 모델링하지 않으므로 본문 인용으로 잡지 않는다.
    """
    return "부칙" in text[max(0, pos - window):pos]


_BRACKET_LAW_RE = re.compile(r"「([^」]+(?:법률|법|령|규칙))」")


def _last_bracket_law(text: str, start: int, end: int) -> str:
    """text[start:end]에서 마지막으로 등장한 낫표 법령명(「…법」)을 반환한다.

    조번호 없이 쓰인 선행 법령(예: 「법인세법」(같은 법 …))도 잡기 위함.
    """
    matches = list(_BRACKET_LAW_RE.finditer(text, start, end))
    return matches[-1].group(1) if matches else ""


def _resolve_relative_citations(citations: list[Citation], text: str) -> None:
    """'같은 법/영/칙/조'를 같은 문장 앞쪽의 명시 인용으로 해석한다."""
    for idx, cite in enumerate(citations):
        if not cite.relative:
            continue
        sent_start = _sentence_start(text, cite.span[0])
        previous = [
            c for c in citations[:idx]
            if c.span[0] >= sent_start and c.jo
        ]
        if cite.relative == "같은조":
            if previous:
                anchor = previous[-1]
                cite.jo = anchor.jo
                cite.jo_sub = anchor.jo_sub
                cite.law_name = anchor.law_name
        elif cite.law_name.startswith("같은"):
            explicit_laws = [c for c in previous if c.law_name and not c.relative]
            if explicit_laws:
                cite.law_name = explicit_laws[-1].law_name
            else:
                # 조번호 없이 쓰인 선행 낫표 법령명도 선행 법령으로 인정
                bracket = _last_bracket_law(text, sent_start, cite.span[0])
                if bracket:
                    cite.law_name = bracket


def parse_citations(text: str) -> list[Citation]:
    """텍스트에서 조문 인용 목록 추출."""
    results: list[Citation] = []
    seen: set[tuple[int, int]] = set()

    # 1. 타법 인용: 「법령명」 제X조... (가장 긴 패턴, 최우선)
    for m in CROSS_LAW_RE.finditer(text):
        if m.span() in seen:
            continue
        seen.add(m.span())
        results.append(Citation(
            raw=m.group(0),
            law_name=m.group(1),
            jo=m.group(2),
            jo_sub=m.group(3) or "",
            hang=m.group(4) or "",
            ho=m.group(5) or "",
            mok=m.group(6) or "",
            span=m.span(),
        ))

    # 1.5. 낫표 없는 타법 인용: 법령명 제X조...
    for m in NAMED_LAW_RE.finditer(text):
        if m.span() in seen or _is_inside(m.span(), seen):
            continue
        # "같은 법" 계열은 SAME_LAW_RE가, "이 법/영/규칙"은 DEICTIC_LAW_RE가 처리한다.
        name_norm = m.group(1).replace(" ", "")
        if "같은" in name_norm or name_norm in ("이법", "이영", "이규칙"):
            continue
        seen.add(m.span())
        results.append(Citation(
            raw=m.group(0),
            law_name=m.group(1).strip(),
            jo=m.group(2),
            jo_sub=m.group(3) or "",
            hang=m.group(4) or "",
            ho=m.group(5) or "",
            mok=m.group(6) or "",
            span=m.span(),
        ))

    # 2. 같은 법/령/영/규칙 제X조...
    for m in SAME_LAW_RE.finditer(text):
        if m.span() in seen:
            continue
        if any(s[0] <= m.start() and m.end() <= s[1] for s in seen):
            continue
        seen.add(m.span())
        results.append(Citation(
            raw=m.group(0),
            law_name=m.group(1).replace(" ", ""),  # 정규화: "같은법", "같은령" 등
            jo=m.group(2),
            jo_sub=m.group(3) or "",
            hang=m.group(4) or "",
            ho=m.group(5) or "",
            mok=m.group(6) or "",
            span=m.span(),
            relative=m.group(1).replace(" ", ""),
        ))

    # 2.5. 같은 조 제X항...
    for m in SAME_JO_RE.finditer(text):
        if m.span() in seen:
            continue
        if _is_inside(m.span(), seen):
            continue
        seen.add(m.span())
        results.append(Citation(
            raw=m.group(0),
            jo="",
            hang=m.group(2) or "",
            ho=m.group(3) or "",
            mok=m.group(4) or "",
            span=m.span(),
            relative="같은조",
        ))

    # 2.7. 지시적 법령 인용: 법/영/규칙 제X조 (시행령→모법 등)
    for m in DEICTIC_LAW_RE.finditer(text):
        if m.span() in seen or _is_inside(m.span(), seen):
            continue
        seen.add(m.span())
        token = m.group(1).replace(" ", "")
        results.append(Citation(
            raw=m.group(0),
            law_name=token,
            jo=m.group(2),
            jo_sub=m.group(3) or "",
            hang=m.group(4) or "",
            ho=m.group(5) or "",
            mok=m.group(6) or "",
            span=m.span(),
            relative=token,
        ))

    # 3. 조문 범위: 제X조부터 제Y조까지
    for m in ARTICLE_RANGE_RE.finditer(text):
        if m.span() in seen:
            continue
        if _preceded_by_buchik(text, m.start()):
            continue  # '부칙 제X조부터 …' — 본문 조문 아님
        seen.add(m.span())
        results.append(Citation(
            raw=m.group(0),
            jo=m.group(1),
            jo_sub=m.group(2) or "",
            is_range=True,
            range_end_jo=m.group(3),
            range_end_jo_sub=m.group(4) or "",
            span=m.span(),
        ))

    # 4. 항/호/목 범위
    for m in RANGE_RE.finditer(text):
        if m.span() in seen:
            continue
        if any(s[0] <= m.start() and m.end() <= s[1] for s in seen):
            continue
        seen.add(m.span())
        is_hang = m.group(2) == "항"
        results.append(Citation(
            raw=m.group(0),
            jo="",
            hang=m.group(1) if is_hang else "",
            hang_end=m.group(3) if is_hang else "",
            ho=m.group(1) if m.group(2) == "호" else "",
            mok=m.group(1) if m.group(2) == "목" else "",
            is_range=True,
            span=m.span(),
        ))

    # 4.5. 조 내 항 범위: 제X조의Y제A항부터 제B항까지 (DIRECT_RE보다 먼저 처리)
    for m in ARTICLE_HANG_RANGE_RE.finditer(text):
        if m.span() in seen:
            continue
        if any(s[0] <= m.start() and m.end() <= s[1] for s in seen):
            continue
        seen.add(m.span())
        results.append(Citation(
            raw=m.group(0),
            jo=m.group(1),
            jo_sub=m.group(2) or "",
            hang=m.group(3),
            hang_end=m.group(4),
            is_range=True,
            span=m.span(),
        ))

    # 5. 직접 인용 (본법 내)
    for m in DIRECT_RE.finditer(text):
        if m.span() in seen:
            continue
        if any(s[0] <= m.start() and m.end() <= s[1] for s in seen):
            continue
        if _preceded_by_buchik(text, m.start()):
            continue  # '부칙 제X조' — 본문 조문 아님
        seen.add(m.span())
        results.append(Citation(
            raw=m.group(0),
            jo=m.group(1),
            jo_sub=m.group(2) or "",
            hang=m.group(3) or "",
            ho=m.group(4) or "",
            mok=m.group(5) or "",
            span=m.span(),
        ))

    # 6. 동일 조 내 단독 항·호·목 인용 (조번호 없는 "제3항" 형태)
    for m in INTRA_RE.finditer(text):
        if m.span() in seen:
            continue
        if any(s[0] <= m.start() and m.end() <= s[1] for s in seen):
            continue
        before = text[max(0, m.start() - 3):m.start()]
        if "조" in before:
            continue
        seen.add(m.span())
        unit = m.group(2)
        results.append(Citation(
            raw=m.group(0),
            jo="",
            hang=m.group(1) if unit == "항" else "",
            ho=m.group(1) if unit == "호" else "",
            mok=m.group(1) if unit == "목" else "",
            span=m.span(),
        ))

    results.sort(key=lambda c: c.span[0])
    _resolve_relative_citations(results, text)
    _tag_junyo(results, text)
    return results


_SENT_END_RE = re.compile(r"[.?!\n;]")


def _tag_junyo(citations: list[Citation], text: str) -> None:
    """'준용'을 가장 가까운 선행 인용에 귀속시켜 is_junyo를 설정한다.

    각 인용의 끝부터 (다음 인용 시작 또는 문장 끝, 최대 25자) 사이에 '준용'이 있으면
    그 인용을 준용으로 본다 — '제27조를 준용한다', '제27조부터 제29조까지를 준용한다' 등.
    한계: '제1항 및 제2항을 준용한다'의 나열형에서는 마지막 인용만 잡힐 수 있다.
    """
    for idx, cite in enumerate(citations):
        start = cite.span[1]
        nxt = citations[idx + 1].span[0] if idx + 1 < len(citations) else len(text)
        window_end = min(nxt, start + 25)
        segment = text[start:window_end]
        sent = _SENT_END_RE.search(segment)
        if sent:
            segment = segment[:sent.start()]
        if "준용" in segment:
            cite.is_junyo = True


def find_back_citations(
    law_data: dict,
    target_jo: str,
    target_jo_sub: str = "",
    target_hang: str = "",
) -> list[dict]:
    """동일 법령 내에서 target 조문(·항)을 인용하는 다른 조항 목록 반환.

    Args:
        law_data: get_law_text() 반환값
        target_jo: 조번호 문자열 (예: "27")
        target_jo_sub: 조의 부번호 (예: "2"  → 제27조의2)
        target_hang: 항번호 — 지정 시 해당 항을 인용하는 조항만 반환

    Returns:
        [{"조번호": ..., "제목": ..., "인용": [raw_str, ...]}]
    """
    full_jo = f"{target_jo}의{target_jo_sub}" if target_jo_sub else target_jo
    source_law = str(law_data.get("법령명", "")).strip()
    results: list[dict] = []

    for article in law_data.get("조문목록", []):
        if str(article.get("조번호", "")) == full_jo:
            continue  # 자기 자신 제외
        citations = parse_citations(article.get("내용", ""))
        seen_cites: set = set()
        matching = []
        for c in citations:
            if source_law:
                cite_law = effective_law_name(c, source_law)
                # 미해석 '같은 법' 계열은 종전대로 동일 법령으로 간주
                if not cite_law.startswith("같은") and _norm_law(cite_law) != _norm_law(source_law):
                    continue
            if c.jo != target_jo:
                continue
            if target_jo_sub and c.jo_sub != target_jo_sub:
                continue
            if target_hang and c.hang:
                if c.hang_end:
                    # 항 범위 인용: target_hang이 [hang, hang_end] 안에 있는지 확인
                    try:
                        if not (int(c.hang) <= int(target_hang) <= int(c.hang_end)):
                            continue
                    except ValueError:
                        continue
                elif c.hang != target_hang:
                    continue
            key = (c.law_name, c.jo, c.jo_sub, c.hang, c.hang_end)
            if key in seen_cites:
                continue
            seen_cites.add(key)
            matching.append({
                "raw": c.raw,
                "law_name": c.law_name,
                "jo": c.jo,
                "jo_sub": c.jo_sub,
                "hang": c.hang,
                "hang_end": c.hang_end,
            })
        if matching:
            results.append({
                "조번호": article["조번호"],
                "제목": article.get("제목", ""),
                "내용": article.get("내용", ""),
                "인용": matching,
            })
    return results


def detect_number_shift(
    citations: list[Citation],
    inserted_jo: int,
) -> list[Citation]:
    """신설 조문(inserted_jo) 삽입 시 번호가 밀리는 인용 목록 반환."""
    affected: list[Citation] = []
    for c in citations:
        if not c.jo:
            continue
        try:
            jo_int = int(c.jo)
        except ValueError:
            continue
        if jo_int >= inserted_jo:
            affected.append(c)
    return affected
