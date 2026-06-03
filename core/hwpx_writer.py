"""HWPX 문서 생성 (개정지시문 + 신구조문대비표)."""
import io
import re
import zipfile
from hwpx.document import HwpxDocument
from hwpx.oxml.document import HwpxOxmlTableCell, HwpxOxmlParagraph

# 마크업 태그 파싱:
#   <del>...</del> → 현행 삭제 문구 (빨간색)
#   <u>...</u>    → 개정안 신규 문구 (파란색)
_MARKUP_RE = re.compile(r"(<del>.*?</del>|<u>.*?</u>)", re.DOTALL)

_HP_NS = "http://www.hancom.co.kr/hwpml/2011/paragraph"
_HP = f"{{{_HP_NS}}}"

# 빌드 단계에서 사용하는 sentinel charPr ID.
# _patch_font_in_hwpx()가 실제 position(기존 charPr 수 기반)으로 교체한다.
_BLUE_SENTINEL = "9997"
_RED_SENTINEL = "9998"
_BLUE_PR_ID = _BLUE_SENTINEL
_RED_U_PR_ID = _RED_SENTINEL

# 색상: hwpx 라이브러리와 동일한 #RRGGBB hex 포맷 사용
_COLOR_BLUE = "#0000FF"
_COLOR_RED = "#FF0000"
_COLOR_BLACK = "#000000"
_COLOR_GRAY = "#C0C0C0"

# 조사: </u> 직후 무공백으로 붙어있어도 대시 처리해야 할 한국어 조사 목록
_JOSA: frozenset[str] = frozenset([
    "이", "가", "을", "를", "은", "는", "의", "와", "과", "에", "도", "만", "로", "나",
    "에서", "으로", "부터", "까지", "마다", "처럼", "이나", "이며", "이고", "이면",
    "이라", "이라도", "이지만", "이라면", "이어서", "이어도",
    "와서", "와는", "와도", "과는", "과도", "는데", "은데",
    "에도", "에만", "로서", "로는", "로도", "로만",
    "에게", "에서는", "으로서", "부터는", "까지는", "이라는",
])


def _is_josa_or_punct(s: str) -> bool:
    """조사 또는 구두점 시작 텍스트 판별. True이면 대시 처리(보존 안 함)."""
    if not s:
        return False
    if s[0] in "([{.,;:·!?）)":
        return True
    return s in _JOSA


def _make_char_pr(pr_id: str, text_color: str, underline_color: str, ns: str = "hh") -> str:
    """charPr XML 생성. ID, 색상, 네임스페이스 prefix를 파라미터로 받음."""
    return (
        f'<{ns}:charPr id="{pr_id}" height="1000" textColor="{text_color}" shadeColor="none" '
        f'useFontSpace="0" useKerning="0" symMark="NONE" borderFillIDRef="2">'
        f'<{ns}:fontRef hangul="1" latin="1" hanja="1" japanese="1" other="1" symbol="1" user="1" />'
        f'<{ns}:ratio hangul="100" latin="100" hanja="100" japanese="100" other="100" symbol="100" user="100" />'
        f'<{ns}:spacing hangul="0" latin="0" hanja="0" japanese="0" other="0" symbol="0" user="0" />'
        f'<{ns}:relSz hangul="100" latin="100" hanja="100" japanese="100" other="100" symbol="100" user="100" />'
        f'<{ns}:offset hangul="0" latin="0" hanja="0" japanese="0" other="0" symbol="0" user="0" />'
        f'<{ns}:underline type="SOLID" shape="SOLID" color="{underline_color}" />'
        f'<{ns}:strikeout shape="NONE" color="{_COLOR_BLACK}" />'
        f'<{ns}:outline type="NONE" />'
        f'<{ns}:shadow type="NONE" color="{_COLOR_GRAY}" offsetX="10" offsetY="10" />'
        f'</{ns}:charPr>'
    )


_HANG_START_RE = re.compile(r"^([①②③④⑤⑥⑦⑧⑨⑩⑪⑫⑬⑭⑮⑯⑰⑱⑲⑳]\s*)")
_U_SPLIT_RE = re.compile(r"(<u>.*?</u>)", re.DOTALL)
_HANG_SPLIT_RE = re.compile(r"(?<!\n)(?<!∼)([①②③④⑤⑥⑦⑧⑨⑩⑪⑫⑬⑭⑮⑯⑰⑱⑲⑳])")


def _cjk_visual_len(s: str) -> int:
    """한글/CJK=2, 기타=1 기준 시각적 너비 반환."""
    n = 0
    for ch in s:
        cp = ord(ch)
        if (0xAC00 <= cp <= 0xD7A3 or  # 한글 음절
                0x1100 <= cp <= 0x11FF or  # 한글 자모
                0x3400 <= cp <= 0x9FFF):   # CJK 한자
            n += 2
        else:
            n += 1
    return n


def _segment_to_dashes(text: str) -> str:
    """순수 텍스트 → 대시 문자열. 앞뒤 공백 보존. 2자 미만은 그대로."""
    if not text or not text.strip():
        return text
    leading = len(text) - len(text.lstrip())
    trailing_start = len(text.rstrip())
    stripped = text.strip()
    if len(stripped) < 2:
        return text
    dash_count = max(3, _cjk_visual_len(stripped) // 2)
    dashes = ("- " * dash_count).rstrip()
    return text[:leading] + dashes + text[trailing_start:]


def _dash_unchanged_segments(line: str) -> str:
    """개정안 줄: <u> 밖의 미변경 텍스트를 모두 대시로 치환.

    - 항 기호(①②...) 는 항상 보존
    - <u> 태그 앞뒤에 공백 없이 붙어있는 텍스트 중 '같은 단어의 일부'는 그대로 유지.
      단, 조사(에, 을, 는 …)나 구두점·괄호로 시작하는 경우는 대시 처리.
      예: <u>1,000</u>만원 → "만원"은 <u> 직후 무공백 복합어 → 유지
          <u>1,000만원</u>에  → "에"는 조사 → 대시 처리
          <u>1,000만원</u>(해당 → "("으로 시작 → 대시 처리
    """
    # 개정안 셀: <del>...</del> 태그는 구문 통째로 제거 (개정안에 구문 불필요)
    line = re.sub(r"<del>.*?</del>", "", line, flags=re.DOTALL)
    if "<u>" not in line:
        return line

    parts = _U_SPLIT_RE.split(line)
    result: list[str] = []

    for i, part in enumerate(parts):
        if part.startswith("<u>"):
            result.append(part)
            continue

        if not part:
            continue

        prev_is_u = i > 0 and parts[i - 1].startswith("<u>")
        next_is_u = i < len(parts) - 1 and parts[i + 1].startswith("<u>")

        inner = part

        # 항 기호 분리 (이전 <u> 없는 구간 선두에서만)
        hang_sym = ""
        if not prev_is_u:
            clean = re.sub(r"<[^>]+>", "", part)
            m = _HANG_START_RE.match(clean.lstrip())
            if m:
                sym = m.group(1).rstrip()
                pos = part.find(sym)
                if pos >= 0:
                    hang_sym = part[:pos + len(sym)]
                    inner = part[pos + len(sym):]

        # </u> 직후 무공백 텍스트 — 조사·구두점이면 대시, 복합어 일부면 유지
        head = ""
        if prev_is_u and inner and not inner[0].isspace():
            m = re.match(r"^(\S+)", inner)
            if m:
                candidate = m.group(1)
                if not _is_josa_or_punct(candidate):
                    head = candidate
                    inner = inner[len(head):]

        # <u> 직전 무공백 텍스트 = 같은 단어 → 유지
        tail = ""
        if next_is_u and inner and not inner[-1].isspace():
            m = re.search(r"(\S+)$", inner)
            if m:
                tail = m.group(1)
                inner = inner[:m.start()]

        result.append(hang_sym + head + _segment_to_dashes(inner) + tail)

    return "".join(result)


def _normalize_hang_newlines(text: str) -> str:
    """항 기호(①②...) 앞에 줄바꿈 삽입 — 여러 항이 한 줄로 붙어있는 경우 분리."""
    return _HANG_SPLIT_RE.sub(r"\n\1", text).lstrip("\n")


def _simplify_unchanged_hang(text: str) -> str:
    """현행 셀: <del>가 없는 항 라인을 '항기호 (생략)'으로 단순화."""
    result = []
    for line in _normalize_hang_newlines(text).split("\n"):
        m = _HANG_START_RE.match(line.lstrip())
        if m and "<del>" not in line and "(생략)" not in line:
            result.append(f"{m.group(1).rstrip()} (생략)")
        else:
            result.append(line)
    return "\n".join(result)


def _process_kajeong_an(text: str) -> str:
    """개정안 셀 완전 처리:
    1. 항 기호 앞 줄바꿈 삽입
    2. <u> 없는 항 라인 → '항기호 (현행과같음)' (GPT 미준수 강제 보정)
    3. <u> 있는 항 라인 → _dash_unchanged_segments
    4. 변경된 항 블록 내 하위 호/목 줄 (no <u>) → _segment_to_dashes
    """
    lines = _normalize_hang_newlines(text).split("\n")
    hangs_with_sub_u: set[str] = set()
    current_sym = ""
    for line in lines:
        m = _HANG_START_RE.match(line.lstrip())
        if m:
            current_sym = m.group(1).rstrip()
        elif current_sym and "<u>" in line:
            hangs_with_sub_u.add(current_sym)

    result: list[str] = []
    in_changed_hang = False

    for line in lines:
        lstripped = line.lstrip()
        m = _HANG_START_RE.match(lstripped)
        if m:
            sym = m.group(1).rstrip()
            if "<u>" in line or sym in hangs_with_sub_u:
                in_changed_hang = True
                if "<u>" in line:
                    result.append(_dash_unchanged_segments(line))
                else:
                    body = lstripped[len(sym):]
                    if body.strip():
                        leading = line[: len(line) - len(lstripped)]
                        result.append(leading + sym + _segment_to_dashes(body))
                    else:
                        result.append(line)
            elif "(현행과같음)" in line:
                in_changed_hang = False
                result.append(line)
            else:
                in_changed_hang = False
                result.append(f"{sym} (현행과같음)")
        else:
            if in_changed_hang and line.strip():
                if "<u>" in line:
                    result.append(_dash_unchanged_segments(line))
                else:
                    result.append(_segment_to_dashes(line))
            else:
                result.append(line)

    return "\n".join(result)


def _fill_para_runs(
    para: HwpxOxmlParagraph,
    line: str,
    del_id: str = "0",
    u_id: str = "0",
) -> None:
    """단락에 <del>/<u> 마크업 처리하여 run 삽입."""
    if "<del>" not in line and "<u>" not in line:
        if line:
            para.add_run(line)
        return

    pos = 0
    for m in _MARKUP_RE.finditer(line):
        before = line[pos:m.start()]
        if before:
            para.add_run(before)

        tag = m.group(0)
        if tag.startswith("<del>"):
            inner = tag[5:-6]
            char_id = del_id
        else:
            inner = tag[3:-4]
            char_id = u_id
        para.add_run(inner, char_pr_id_ref=char_id)
        pos = m.end()

    remainder = line[pos:]
    if remainder:
        para.add_run(remainder)


def _fill_cell_with_markup(
    cell: HwpxOxmlTableCell,
    text: str,
    del_id: str = "0",
    u_id: str = "0",
) -> None:
    """셀에 텍스트 삽입. 줄바꿈→별도 단락, <del>/<u>→색상/밑줄."""
    lines = text.split("\n")
    paras = cell.paragraphs
    first_para = paras[0] if paras else cell.add_paragraph()
    first_para.clear_text()

    for idx, line in enumerate(lines):
        para = first_para if idx == 0 else cell.add_paragraph()
        _fill_para_runs(para, line, del_id=del_id, u_id=u_id)


def build_comparison_table(
    doc: HwpxDocument,
    rows: list[tuple[str, str]],
) -> None:
    """신·구조문대비표 테이블 추가.

    rows: [(현행 셀 텍스트, 개정안 셀 텍스트), ...]
    첫 행이 헤더(현 행 | 개 정 안)이면 그대로 헤더로 처리.
    charPr ID는 _patch_font_in_hwpx에서 동적으로 주입.
    """
    n = len(rows)
    tbl = doc.add_table(n, 2, section_index=0, width=46000)

    pos_el = tbl.element.find(f"{_HP}pos")
    if pos_el is not None:
        pos_el.set("treatAsChar", "0")
        pos_el.set("flowWithText", "0")

    for r_idx, (left_text, right_text) in enumerate(rows):
        left_cell = tbl.cell(r_idx, 0)
        right_cell = tbl.cell(r_idx, 1)

        if r_idx == 0:
            left_cell.text = left_text
            right_cell.text = right_text
        else:
            # 현행: unchanged 항 → (생략), <del> → 빨간색 밑줄
            left_processed = _simplify_unchanged_hang(left_text)
            _fill_cell_with_markup(left_cell, left_processed, del_id=_RED_U_PR_ID, u_id=_RED_U_PR_ID)
            # 개정안: unchanged항→(현행과같음), 호/목 대시, <u>→파란색 밑줄
            transformed = _process_kajeong_an(right_text)
            _fill_cell_with_markup(right_cell, transformed, del_id=_RED_U_PR_ID, u_id=_BLUE_PR_ID)


def _patch_font_in_hwpx(path: str, font: str = "신명조") -> None:
    """HWPX ZIP 후처리: 폰트 교체 + 색상 charPr 주입.

    1. header.xml: 폰트 교체, 정렬, charPr(파랑/빨강 밑줄) 동적 주입
    2. section*.xml: sentinel charPrIDRef(9997/9998) → 실제 position ID로 교체

    네임스페이스 prefix는 header.xml에서 자동 감지 (hp: / hh: 등 버전별 상이).
    """
    # 1패스: header.xml 읽어서 namespace prefix 및 실제 charPr 위치 계산
    with zipfile.ZipFile(path, "r") as zin:
        header_raw = zin.read("Contents/header.xml").decode("utf-8")

    # 실제 prefix 감지 (hp:charPr, hh:charPr 등)
    m_ns = re.search(r'<(\w+):charPr\b', header_raw)
    ns = m_ns.group(1) if m_ns else "hh"

    existing_count = len(re.findall(rf'<{re.escape(ns)}:charPr\b', header_raw))
    blue_id = str(existing_count)        # 기존 마지막 다음 위치
    red_id = str(existing_count + 1)

    # 2패스: 파일 교체
    buf = io.BytesIO()
    with zipfile.ZipFile(path, "r") as zin:
        with zipfile.ZipFile(buf, "w", compression=zipfile.ZIP_DEFLATED) as zout:
            for item in zin.infolist():
                data = zin.read(item.filename)
                name = item.filename

                if name == "Contents/header.xml":
                    text = data.decode("utf-8")
                    # 폰트 교체
                    text = re.sub(r'face="[^"]*"', f'face="{font}"', text)
                    # 왼쪽 정렬
                    text = text.replace('horizontal="JUSTIFY"', 'horizontal="LEFT"')
                    # charPr 주입 (중복 방지: charPr 태그 기준 확인)
                    if f'<{ns}:charPr id="{blue_id}"' not in text:
                        blue_pr = _make_char_pr(blue_id, _COLOR_BLUE, _COLOR_BLUE, ns)
                        red_pr = _make_char_pr(red_id, _COLOR_RED, _COLOR_RED, ns)
                        text = re.sub(
                            rf'(<{re.escape(ns)}:charProperties itemCnt=")(\d+)(")',
                            lambda m: f'{m.group(1)}{int(m.group(2)) + 2}{m.group(3)}',
                            text,
                        )
                        text = text.replace(
                            f'</{ns}:charProperties>',
                            blue_pr + red_pr + f'</{ns}:charProperties>',
                        )
                    data = text.encode("utf-8")

                elif name.startswith("Contents/section") and name.endswith(".xml"):
                    # sentinel ID → 실제 position ID 교체
                    text = data.decode("utf-8")
                    text = text.replace(
                        f'charPrIDRef="{_BLUE_SENTINEL}"',
                        f'charPrIDRef="{blue_id}"',
                    )
                    text = text.replace(
                        f'charPrIDRef="{_RED_SENTINEL}"',
                        f'charPrIDRef="{red_id}"',
                    )
                    data = text.encode("utf-8")

                zout.writestr(item, data)
    buf.seek(0)
    with open(path, "wb") as f:
        f.write(buf.read())
