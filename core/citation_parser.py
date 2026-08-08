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
# 구식 조 범위 표현 '내지': 제X조 내지 제Y조 (= 제X조부터 제Y조까지)
_ARTICLE_RANGE_NAEJI = r"제(\d+)조(?:의(\d+))?\s*내지\s*제(\d+)조(?:의(\d+))?"
# 구식 항·호·목 범위 표현 '내지': 제X항 내지 제Y항
_RANGE_NAEJI = r"제(\d+)(항|호|목)\s*내지\s*제(\d+)(항|호|목)"
# 별표·별지서식 인용: "별표 1", "별표 1의2", "별표 제2호", "별지 제40호서식", "[별표 3]"
_BYEOLPYO = r"(별표|별지)\s*(?:제\s*)?(\d+)(?:\s*의\s*(\d+))?\s*(?:호\s*서식|호|서식)?"
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
ARTICLE_RANGE_NAEJI_RE = re.compile(_ARTICLE_RANGE_NAEJI)
RANGE_NAEJI_RE = re.compile(_RANGE_NAEJI)
BYEOLPYO_RE = re.compile(_BYEOLPYO)
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
    byeolpyo: str = ""         # 별표·별지서식 인용 시 표기(예: "별표 1", "별지 제40호서식")


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
    """'같은 조'는 같은 문장 앞 조문으로, '같은 법'은 조문 전체에서 가장 최근 명시
    법령으로 해석한다.

    '같은 조'는 근접 참조라 문장(줄바꿈) 경계를 지킨다. 반면 '같은 법'은 줄·문장,
    심지어 계산식 표(셀이 줄바꿈으로 분리)를 넘어 같은 조문에서 직전에 명시된 법령을
    가리키므로 검색 범위를 조문 전체로 넓힌다(표 안 '「법인세법」… 같은 법 …' 누락 방지).
    """
    for idx, cite in enumerate(citations):
        if not cite.relative:
            continue
        if cite.relative == "같은조":
            sent_start = _sentence_start(text, cite.span[0])
            previous = [
                c for c in citations[:idx]
                if c.span[0] >= sent_start and c.jo
            ]
            if previous:
                anchor = previous[-1]
                cite.jo = anchor.jo
                cite.jo_sub = anchor.jo_sub
                cite.law_name = anchor.law_name
                # 앵커가 지시참조(영/법)·같은법이면 그 relative도 물려받아 effective가
                # 모법·시행령으로 해석하게 한다('영 제186조 … 같은 조 제2항' 누락 방지)
                cite.relative = anchor.relative
        elif cite.law_name.startswith("같은"):
            # 조문 전체에서 가장 최근의 명시 법령(낫표·낫표없는 타법). 지시참조(법/영)·
            # 미해석 '같은…'은 제외.
            explicit_laws = [c for c in citations[:idx] if c.law_name and not c.relative]
            if explicit_laws:
                cite.law_name = explicit_laws[-1].law_name
            else:
                # 조번호 없이 쓰인 선행 낫표 법령명도 선행 법령으로 인정
                bracket = _last_bracket_law(text, 0, cite.span[0])
                if bracket:
                    cite.law_name = bracket


def _resolve_range_law_names(citations: list[Citation]) -> None:
    """범위 인용에 선행 명시 법령명을 전파한다.

    '「법인세법」 제13조부터 제54조까지'에서 CROSS_LAW/NAMED_LAW는 '「법인세법」 제13조'만
    잡고, 범위 인용 자체는 law_name이 비어 source 법령(예: 조특법)으로 오귀속된다.
    범위의 시작 조번호와 일치하며 범위 시작('제13조')을 span으로 덮는 직전 명시 인용의
    법령명(·relative)을 물려받아 _resolve_relative_citations·effective_law_name이
    올바른 법령으로 해석하도록 한다.

    조 범위뿐 아니라 항·호 범위('「지방세법」 제9조제3항부터 제5항까지')도 같다.
    이 경우 range_end_jo는 비고 hang_end/ho만 채워지는데, 전파를 빠뜨리면 그 인용이
    출처법 자기참조가 될 뿐 아니라 뒤따르는 열거 체인의 앵커까지 무력화된다.
    """
    for cite in citations:
        if not cite.is_range or not cite.jo:
            continue
        if cite.law_name or cite.relative:
            continue
        for other in citations:
            if other is cite or not other.law_name:
                continue
            if other.jo != cite.jo or other.jo_sub != cite.jo_sub:
                continue
            # other가 범위 시작 토큰('제13조')을 덮고 있어야 함 (span 겹침)
            if other.span[0] <= cite.span[0] < other.span[1]:
                cite.law_name = other.law_name
                cite.relative = other.relative
                break


# 조문 열거 연결어와, 그 사이에 끼는 '부스러기'(앞 인용에 딸린 항·호·목·위치어).
# '「A법」 제9조 및 제10조', '제33조제3항ㆍ제4항 및 제34조', '제61조제1항 본문 및 제62조'
# 처럼 두 조문 사이가 '연결어 + (항/호/목·전단/후단/단서/본문/각 호)뿐'이면 같은 법으로 본다.
#
# '부터·까지·내지'도 부스러기다. 앞 인용에 딸린 항·호 범위('제93조제4호부터 제7호까지')가
# 끼면 열거 체인이 거기서 끊겨 뒤 조문이 출처법으로 오귀속됐다
# (농특세법 시행령 제4조: 「관세법」 제88조 … 제94조, 제96조부터 제101조까지 → 제94조 이후 단절).
_CONN_RE = re.compile(r"및|와|과|또는|,|ㆍ|·")
_CONN_FILLER_RE = re.compile(
    r"제\s*\d+\s*(?:항|호|목)|전단|후단|단서|본문|각\s*호|각\s*목|외의\s*부분|"
    r"부터|까지|내지|항|호|목|\s"
)


# 앞 인용에 딸린 호·목 가지번호 꼬리. 파서가 '제1호의2'를 '제1호'까지만 잡아
# '의2'가 간격에 남고, 그 때문에 열거 체인이 끊긴다
# (농특세령 제4조: 「지방세특례제한법」 제13조제2항제1호의2, 제15조제2항 … → 제15조 이후 단절).
_TRAILING_SUB_RE = re.compile(r"^\s*의\s*\d+")


def _is_connective(gap: str) -> bool:
    """두 인용 사이 텍스트가 '연결어 + 항/호/목·위치어 부스러기'뿐이면 True.

    실질 어구(명사·서술)가 끼면 False — 그 경우 뒤 조문은 별개 맥락일 수 있어
    법령명을 전파하지 않는다(과탐 방지). 연결어가 하나도 없어도 False.
    """
    gap = _TRAILING_SUB_RE.sub("", gap)
    if not _CONN_RE.search(gap):
        return False
    rest = _CONN_FILLER_RE.sub("", _CONN_RE.sub("", gap))
    return rest == ""


def _bracket_mask(text: str) -> tuple[str, list[tuple[int, int]]]:
    """괄호·대괄호 안을 공백으로 지운 텍스트와 그 구간 목록.

    열거 중간의 괄호는 앞 조문에 딸린 한정어구다
    ('제72조제1항(제1호…의 법인은 제외한다), 제77조'). 안의 서술이 실질 어구로 읽혀
    열거 체인을 끊고, 안에 든 인용이 앵커로 잡혀 간격 판정을 망친다.
    「」는 법령명 표기라 마스킹하지 않는다.
    """
    spans: list[tuple[int, int]] = []
    stack: list[int] = []
    for i, ch in enumerate(text):
        if ch in "([":
            stack.append(i)
        elif ch in ")]" and stack:
            start = stack.pop()
            if not stack:                       # 최외곽 괄호만 기록
                spans.append((start, i + 1))
    if not spans:
        return text, spans
    chars = list(text)
    for a, b in spans:
        for i in range(a, b):
            chars[i] = " "
    return "".join(chars), spans


def _resolve_enumerated_law_names(citations: list[Citation], text: str) -> None:
    """'「A법」 제9조 및 제10조' 열거에서 뒤따르는 맨 조번호에 앞 법령명을 전파한다.

    CROSS_LAW/NAMED_LAW는 첫 조문에만 법령명을 붙이고, 연결어(및·와·,·ㆍ·또는)로
    이어진 다음 조번호는 law_name이 비어 source 법령으로 오귀속된다('부가세법 제9조 및
    제10조'의 제10조 → 조특법 오인). 두 인용 사이가 순수 연결어뿐일 때만 앞 인용의
    법령명(·relative)을 물려준다 — 다른 텍스트가 끼면 전파하지 않는다(과탐 방지).
    좌→우로 처리해 '제9조, 제10조 및 제11조'의 연쇄 전파도 자연히 이어진다.
    _resolve_relative_citations 이후 실행해 '같은 법'·지시참조가 해석된 법령명을 쓴다.
    """
    masked, spans = _bracket_mask(text)

    def _in_bracket(pos: int) -> bool:
        return any(a <= pos < b for a, b in spans)

    for idx in range(1, len(citations)):
        cur = citations[idx]
        if cur.law_name or cur.relative or cur.byeolpyo or not cur.jo:
            continue
        # 앵커 = jo를 가진 가장 가까운 앞 인용. 중간의 jo 없는 항·호 인용
        # ('제3항ㆍ제4항'의 '제4항' 등)과 괄호 속 인용은 건너뛰어 열거 체인을 잇는다.
        prev = next(
            (p for p in reversed(citations[:idx]) if p.jo and not _in_bracket(p.span[0])),
            None,
        )
        if prev is None or not prev.law_name or prev.law_name.startswith("같은"):
            continue
        # 괄호 속 한정어구는 공백으로 지운 텍스트로 간격을 본다
        if not _is_connective(masked[prev.span[1]:cur.span[0]]):
            continue
        cur.law_name = prev.law_name
        cur.relative = prev.relative


def trim_law_name(name: str) -> str:
    """낫표 없이 쓰인 법령명에서 앞에 붙은 산문을 걷어낸다.

    _NAMED_LAW의 `[가-힣\\s]{1,40}` 부분이 공백을 포함해 탐욕적으로 잡히는 탓에
    '하지만 헌법 제38조'에서 법령명이 '하지만 헌법'으로 나온다. 의견 본문처럼
    산문이 섞인 글에서 특히 자주 나타난다.

    한국 법령명은 실제로 셋 중 하나다 — ①한 낱말('헌법', '조세특례제한법')
    ②'X에 관한 법률' ③'A 및 B법'. 앞에서부터 한 낱말씩 떼며 이 형태가 되는
    첫 지점을 법령명으로 본다.
    """
    toks = str(name).split()
    for i in range(len(toks)):
        rest = toks[i:]
        if len(rest) == 1:
            return rest[0]
        if len(rest) == 3 and rest[1] == "관한" and rest[0].endswith("에"):
            return " ".join(rest)                       # 국제조세조정에 관한 법률
        if len(rest) == 3 and rest[1] == "및" and not rest[0].endswith(("법", "법률")):
            return " ".join(rest)                       # 상속세 및 증여세법
        # 'A법 및 B법'이면 뒤엣것이 이 인용의 법령명이다 → 계속 떼어 낸다
    return toks[-1] if toks else ""


def _byeolpyo_label(kind: str, num: str, sub: str) -> str:
    """별표/별지 인용을 표준 표기로. 별지는 'N호서식', 별표는 'N(의M)'."""
    if kind == "별지":
        return f"별지 제{num}호서식"
    return f"별표 {num}" + (f"의{sub}" if sub else "")


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
        # '이 경우 법', '이란 법', '항 및 영'처럼 산문 뒤 단독 지시어(법/영/령/규칙)는
        # 명시 법령명이 아니라 지시참조 → DEICTIC_LAW_RE가 모법으로 해석하도록 건너뛴다.
        # (실제 법령명은 '증여세법'처럼 지시어 앞에 내용 음절이 붙는다)
        if re.search(r"(?:^|\s)(?:법|영|령|규칙)$", m.group(1).strip()):
            continue
        seen.add(m.span())
        results.append(Citation(
            raw=m.group(0),
            law_name=trim_law_name(m.group(1)),
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

    # 3.5. 구식 조 범위: 제X조 내지 제Y조 (= 제X조부터 제Y조까지)
    for m in ARTICLE_RANGE_NAEJI_RE.finditer(text):
        if m.span() in seen or _is_inside(m.span(), seen):
            continue
        if _preceded_by_buchik(text, m.start()):
            continue
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

    # 3.7. 조 내 항 범위: 제X조의Y제A항부터 제B항까지 (RANGE_RE보다 먼저 — 전체 span을
    #      선점해 내부 '제A항부터 제B항까지'가 항범위로 중복 포착되지 않게 한다)
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

    # 4.3. 구식 항·호·목 범위: 제X항 내지 제Y항 (= 제X항부터 제Y항까지)
    for m in RANGE_NAEJI_RE.finditer(text):
        if m.span() in seen or _is_inside(m.span(), seen):
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

    # 5.7. 별표·별지서식 인용 (INTRA보다 먼저 — '별지 제40호서식'의 '제40호' 오탐 방지)
    for m in BYEOLPYO_RE.finditer(text):
        if m.span() in seen or _is_inside(m.span(), seen):
            continue
        seen.add(m.span())
        results.append(Citation(
            raw=m.group(0).strip(),
            jo="",
            byeolpyo=_byeolpyo_label(m.group(1), m.group(2), m.group(3) or ""),
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
    _resolve_range_law_names(results)
    _resolve_relative_citations(results, text)
    _resolve_enumerated_law_names(results, text)
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


def _article_range_covers(c: "Citation", target_jo: str, target_jo_sub: str = "") -> bool:
    """조문 범위 인용(c)이 target 조(·가지번호)를 포함하는지 판정.

    - 동일 기준조의 가지번호 범위(예: 제3조의2 내지 제3조의5)면 jo_sub 범위로 판정.
    - 그 밖(기준조 단위 범위, 예: 제2조 내지 제8조)은 조 단위로 start<=tgt<=end 판정하며
      그 사이의 가지번호 조문(제5조의2 등)도 포함으로 본다.
    원칙: 애매하면 포함하고 호출부에서 via_range 플래그로 사람 검토를 유도한다.
    """
    if not (c.is_range and c.range_end_jo):
        return False
    try:
        start_jo = int(c.jo)
        end_jo = int(c.range_end_jo)
        tgt_jo = int(target_jo)
    except (ValueError, TypeError):
        return False

    # 동일 기준조의 가지번호 범위: 제N조의A ~ 제N조의B
    if start_jo == end_jo and (c.jo_sub or c.range_end_jo_sub):
        if tgt_jo != start_jo:
            return False
        if not target_jo_sub:
            return True  # 기준조 자체는 의도가 모호 — 포함으로 본다
        try:
            a = int(c.jo_sub) if c.jo_sub else 0
            b = int(c.range_end_jo_sub) if c.range_end_jo_sub else a
            t = int(target_jo_sub)
        except ValueError:
            return True
        return a <= t <= b

    # 기준조 단위 범위: 가지번호 조문도 두 기준조 사이면 포함
    return start_jo <= tgt_jo <= end_jo


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
            via_range = False
            if c.is_range and c.range_end_jo:
                # 조문 범위 인용(제X조부터/내지 제Y조)은 펼쳐서 포함 여부 판정
                if not _article_range_covers(c, target_jo, target_jo_sub):
                    continue
                via_range = True
            else:
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
                "via_range": via_range,
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
