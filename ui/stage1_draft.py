"""Stage 1: 법령 검색 → 개정 요강 입력 → GPT 초안 생성."""
import re
import streamlit as st
from core.law_api import search_laws, get_law_text
from core.amendment_agent import draft_amendment, parse_draft_sections
from core.cross_ref_checker import check_all_parallel_laws
from core.buchik_precedents import build_buchik_from_precedent
_APPLICATION_BASIS_OPTIONS = [
    "자동 추천",
    "사업연도",
    "과세기간",
    "신고",
    "지급/수령",
    "양도/취득",
    "공급",
    "발생/거래",
]
_BASIS_EFFECT_TYPES: dict[str, str] = {
    "신고": "부진정소급효",
}


@st.cache_data(ttl=3600, show_spinner=False)
def _cached_law_text(law_mst: str, law_api_key: str, openai_api_key: str) -> dict:
    return get_law_text(law_mst, law_api_key, openai_api_key)

_HANG_SYM_RE = re.compile(r"^([①②③④⑤⑥⑦⑧⑨⑩⑪⑫⑬⑭⑮⑯⑰⑱⑲⑳])")
_SYM_CHAR_RE = re.compile(r"[①②③④⑤⑥⑦⑧⑨⑩⑪⑫⑬⑭⑮⑯⑰⑱⑲⑳]")
_HANG_SYMS = "①②③④⑤⑥⑦⑧⑨⑩⑪⑫⑬⑭⑮⑯⑰⑱⑲⑳"
_JO_URL_RE = re.compile(r"제(?:(\d+)의(\d+)조|(\d+)조(?:의(\d+))?)")
def _parse_jo_ref(jo_ref: str) -> tuple[str, str] | None:
    """조문 표기를 (조번호, 가지번호)로 정규화한다."""
    text = str(jo_ref).strip()
    m = _JO_URL_RE.search(text)
    if m:
        if m.group(1) is not None:
            return m.group(1), m.group(2) or ""
        return m.group(3), m.group(4) or ""
    m = re.search(r"(?<!제)(\d+)조(?:의(\d+))?", text)
    if m:
        return m.group(1), m.group(2) or ""
    parts = text.split("의")
    if parts and parts[0].isdigit():
        return parts[0], parts[1] if len(parts) > 1 and parts[1].isdigit() else ""
    return None


def _format_jo_ref(jo_ref: str) -> str:
    """API 조번호(예: 27의2)도 법령 표준 표기(제27조의2)로 표시한다."""
    parsed = _parse_jo_ref(jo_ref)
    if not parsed:
        return str(jo_ref)
    jo, jo_sub = parsed
    return f"제{jo}조의{jo_sub}" if jo_sub else f"제{jo}조"


def _article_heading(article: dict) -> str:
    jo_label = _format_jo_ref(str(article.get("조번호", "")))
    title = str(article.get("제목", "")).strip()
    return f"{jo_label}({title})" if title else jo_label


def _article_text_for_prompt(article: dict) -> str:
    """법령 API 원문에 조문 헤더가 있으면 중복 삽입하지 않는다."""
    content = str(article.get("내용", "")).strip()
    if _parse_jo_ref(content.splitlines()[0] if content.splitlines() else ""):
        return content
    return f"{_article_heading(article)}\n{content}".strip()


def _article_from_text(jo_ref: str, article_text: str) -> dict:
    """병행 법령 텍스트 헤더에서 조번호와 제목을 추정한다."""
    first_line = article_text.splitlines()[0] if article_text.splitlines() else ""
    title_m = re.search(r"\(([^()]*)\)", first_line)
    parsed = _parse_jo_ref(jo_ref) or _parse_jo_ref(first_line)
    jo_no = ""
    if parsed:
        jo, jo_sub = parsed
        jo_no = f"{jo}의{jo_sub}" if jo_sub else jo
    return {"조번호": jo_no, "제목": title_m.group(1).strip() if title_m else ""}


def _law_ref(law_name: str) -> str:
    if "시행규칙" in law_name:
        return "이 규칙"
    return "이 영" if "시행령" in law_name else "이 법"


def _effect_type_for_basis(application_basis: str) -> str:
    return _BASIS_EFFECT_TYPES.get(application_basis, "장래효")


def _build_buchik(
    article: dict,
    law_name: str,
    application_basis: str,
    outline: str = "",
) -> tuple[str, dict | None]:
    """선택 조문 제목을 기준으로 적용례 부칙을 생성한다."""
    jo_label = _format_jo_ref(str(article.get("조번호", "")))
    title = str(article.get("제목", "")).strip() or jo_label
    return build_buchik_from_precedent(
        law_name=law_name,
        jo_label=jo_label,
        article_title=title,
        outline=outline,
        effect_type=_effect_type_for_basis(application_basis),
        application_basis=application_basis,
    )


def _article_key(article: dict) -> tuple[str, str]:
    parsed = _parse_jo_ref(str(article.get("조번호", "")))
    return parsed or ("", "")


def _clean_article_ref_for_law(law_name: str, jo_ref: str) -> str:
    """표시용 조문에서 중복 법령명 접두어를 제거한다."""
    ref = str(jo_ref).strip()
    if law_name and ref.startswith(law_name):
        ref = ref[len(law_name):].strip()
    return re.sub(r"제(\d+)의(\d+)조", r"제\1조의\2", ref)


def _find_article_by_outline(articles: list[dict], outline: str) -> dict | None:
    """개정요강에 조문번호가 있으면 해당 조문을 찾고, 항번호만 있으면 선택 조문을 유지한다."""
    parsed = _parse_jo_ref(outline)
    if not parsed:
        return None
    for article in articles:
        if _article_key(article) == parsed:
            return article
    return None


def _reset_draft_edit_state() -> None:
    """새 초안 생성 시 이전 편집 박스/체크박스 상태를 제거한다."""
    exact_keys = {
        "s1_instruction_edit",
        "s1_current_edit",
        "s1_amended_edit",
        "s1_buchik_edit",
        "s1_accepted_suggests",
        "s1_hang_overrides",
    }
    prefixes = ("s1_suggest_", "s1_hang_")
    for key in list(st.session_state.keys()):
        if key in exact_keys or key.startswith(prefixes):
            del st.session_state[key]


def _extract_target_hang(outline: str) -> str:
    m = re.search(r"제(\d+)항|(?<!제)(\d+)항", outline)
    return (m.group(1) or m.group(2)) if m else ""


def _extract_old_new(outline: str) -> tuple[str, str] | None:
    patterns = [
        r"현행\s*['\"]?([^'\"\s]+?)['\"]?에서\s*['\"]?([^'\"\s]+?)['\"]?(?:으로|로)",
        r"['\"]([^'\"]+)['\"]\s*을\s*['\"]([^'\"]+)['\"]\s*(?:으로|로)",
        r"([0-9,]+만원)\s*에서\s*([0-9,]+만원)\s*(?:으로|로)",
    ]
    for pattern in patterns:
        m = re.search(pattern, outline)
        if m:
            return m.group(1), m.group(2)
    return None


def _source_current_section(article: dict, outline: str, fallback: str) -> str:
    """현행 섹션은 실제 법령 원문에서 구성해 GPT 환각을 차단한다."""
    target_hang = _extract_target_hang(outline)
    old_new = _extract_old_new(outline)
    if not target_hang or not old_new:
        return fallback
    try:
        target_sym = _HANG_SYMS[int(target_hang) - 1]
    except (ValueError, IndexError):
        return fallback

    old_text, _new_text = old_new
    chunks = _split_hang_blocks(str(article.get("내용", "")))
    if not chunks:
        return fallback

    result: list[str] = []
    for sym, content in chunks:
        if not sym:
            result.append(content)
        elif sym == target_sym:
            marked = content.replace(old_text, f"<del>{old_text}</del>")
            result.append(marked)
        else:
            result.append(f"{sym} (생략)")

    fixed = "\n".join(part for part in result if part.strip())
    return fixed if f"<del>{old_text}</del>" in fixed else fallback


def _parse_manwon_amount(text: str) -> int | None:
    m = re.fullmatch(r"\s*([0-9,]+)만원\s*", text)
    if not m:
        return None
    return int(m.group(1).replace(",", ""))


def _format_manwon_amount(amount: float) -> str:
    rounded = round(amount)
    if abs(amount - rounded) < 0.000001:
        return f"{rounded:,}만원"
    return f"{amount:,.1f}만원"


def _deterministic_related_reviews(article: dict, outline: str) -> str:
    """동일 수치 및 직접 인용 항의 비례 수치를 항상 검토 항목으로 제시한다."""
    target_hang = _extract_target_hang(outline)
    old_new = _extract_old_new(outline)
    if not target_hang or not old_new:
        return ""
    try:
        target_sym = _HANG_SYMS[int(target_hang) - 1]
    except (ValueError, IndexError):
        return ""

    old_text, new_text = old_new
    old_amount = _parse_manwon_amount(old_text)
    new_amount = _parse_manwon_amount(new_text)
    ratio = (new_amount / old_amount) if old_amount and new_amount else None
    rows: list[str] = []
    for sym, content in _split_hang_blocks(str(article.get("내용", ""))):
        if not sym or sym == target_sym:
            continue

        directly_refs_target = f"제{target_hang}항" in content
        if old_text in content and directly_refs_target:
            reason = f"제{target_hang}항 직접 인용 및 동일 수치 포함"
            rows.append(f'[검토] {sym}항({reason}): "{old_text}" → "{new_text}" — 코드 스캔')
        elif old_text in content:
            reason = "같은 조 다른 항에 동일 현행 수치 포함"
            rows.append(f'[검토] {sym}항({reason}): "{old_text}" → "{new_text}" — 코드 스캔')

        if directly_refs_target and ratio:
            for amount_text in sorted(set(re.findall(r"[0-9,]+만원", content))):
                amount = _parse_manwon_amount(amount_text)
                if not amount or amount_text == old_text:
                    continue
                proposed = _format_manwon_amount(amount * ratio)
                if proposed == amount_text:
                    continue
                reason = f"제{target_hang}항 직접 인용, 개정 비율 {old_text}→{new_text} 적용"
                rows.append(f'[검토] {sym}항({reason}): "{amount_text}" → "{proposed}" — 비례 계산')
    return "\n".join(rows)


def _merge_related_text(gpt_related: str, deterministic_related: str) -> str:
    """GPT 연관항과 코드 스캔 연관항을 중복 없이 병합한다."""
    lines: list[str] = []
    seen: set[str] = set()
    for source in (gpt_related, deterministic_related):
        for line in source.splitlines():
            clean = line.strip()
            if not clean or clean in seen:
                continue
            seen.add(clean)
            lines.append(clean)
    return "\n".join(lines)


def _law_url(law_name: str, jo_ref: str = "") -> str:
    """법제처 한글 주소 생성."""
    base = f"https://www.law.go.kr/법령/{law_name}"
    parsed = _parse_jo_ref(jo_ref) if jo_ref else None
    if parsed:
        jo, jo_sub = parsed
        article = f"제{jo}조" + (f"의{jo_sub}" if jo_sub else "")
        return f"{base}/{article}"
    return base
_HAS_U_RE = re.compile(r"<u>|<del>")
_SUGGEST_RE = re.compile(r'\[제안\]\s*(.*?):\s*"([^"]+)"\s*[→-]\s*"([^"]+)"(?:\s*[—\-]\s*(.+))?', re.MULTILINE)
_REVIEW_RE  = re.compile(r'\[검토\]\s*(.*?):\s*"([^"]+)"\s*[→-]\s*"([^"]+)"(?:\s*[—\-]\s*(.+))?', re.MULTILINE)


def _split_hang_blocks(text: str) -> list[tuple[str, str]]:
    """텍스트를 항 단위로 분리. [(기호, 내용), ...]"""
    blocks: list[tuple[str, str]] = []
    buf: list[str] = []
    sym = ""
    for line in text.splitlines():
        m = _HANG_SYM_RE.match(line.lstrip())
        if m and buf:
            blocks.append((sym, "\n".join(buf)))
            sym = m.group(1)
            buf = [line]
        elif m:
            sym = m.group(1)
            buf = [line]
        else:
            buf.append(line)
    if buf:
        blocks.append((sym, "\n".join(buf)))
    return blocks


def _apply_hang_overrides(amended: str, overrides: dict[str, bool]) -> str:
    """overrides[sym]=False인 항을 "(현행과같음)"으로 되돌림."""
    blocks = _split_hang_blocks(amended)
    result: list[str] = []
    for sym, content in blocks:
        if sym and not overrides.get(sym, True):
            result.append(f"{sym} (현행과같음)")
        else:
            result.append(content)
    return "\n".join(result)


def _apply_suggestions(
    amended: str,
    accepted: list[tuple[str, str, str]],
    original_article: str,
) -> str:
    """[제안] 수락 목록을 개정안에 반영.

    "(현행과같음)" 항은 원문에서 해당 항 텍스트를 가져와 <u> 마크업 적용.
    """
    from collections import defaultdict
    sym_changes: dict[str, list[tuple[str, str]]] = defaultdict(list)
    for sym, old_val, new_val in accepted:
        sym_changes[sym].append((old_val, new_val))

    if not sym_changes:
        return amended

    blocks = _split_hang_blocks(amended)
    orig_blocks = dict(_split_hang_blocks(original_article))
    result: list[str] = []
    for sym, content in blocks:
        if sym in sym_changes:
            if "(현행과같음)" in content:
                base = orig_blocks.get(sym, content)
                for old_val, new_val in sym_changes[sym]:
                    base = base.replace(old_val, f"<u>{new_val}</u>")
                result.append(base)
            else:
                modified = content
                for old_val, new_val in sym_changes[sym]:
                    modified = modified.replace(old_val, f"<u>{new_val}</u>")
                result.append(modified)
        else:
            result.append(content)
    return "\n".join(result)


def render(law_api_key: str, openai_api_key: str) -> None:
    st.markdown('<div class="mofe-section-header">1단계: 개정 조문 초안 작성</div>', unsafe_allow_html=True)

    # ── 법령 검색 ────────────────────────────────────────────────────────────
    with st.container(border=True):
        st.markdown('<div class="mofe-subheader">법령 검색</div>', unsafe_allow_html=True)
        with st.form(key="s1_search_form"):
            col1, col2 = st.columns([4, 1])
            with col1:
                query = st.text_input(
                    "법령명 검색",
                    placeholder="예: 법인세법 시행령",
                    label_visibility="collapsed",
                )
            with col2:
                search_btn = st.form_submit_button("검색", use_container_width=True)

        if search_btn and query:
            with st.spinner("법제처 검색 중..."):
                try:
                    results = search_laws(query, law_api_key)
                    st.session_state["s1_search_results"] = results
                except Exception as e:
                    st.error(f"검색 실패: {e}")

        if "s1_search_results" in st.session_state:
            results = st.session_state["s1_search_results"]
            if not results:
                st.warning("검색 결과 없음")
            else:
                options = {f"{r['법령명']} ({r['종류']})": r for r in results}
                selected_label = st.selectbox("법령 선택", list(options.keys()), key="s1_law_select")
                selected = options[selected_label]
                st.session_state["s1_selected_law"] = selected

    # ── 조문 선택 ────────────────────────────────────────────────────────────
    if "s1_selected_law" in st.session_state:
        with st.container(border=True):
            st.markdown('<div class="mofe-subheader">조문 선택</div>', unsafe_allow_html=True)
            law = st.session_state["s1_selected_law"]
            if st.button("조문 목록 불러오기", key="s1_load_articles"):
                with st.spinner("조문 조회 중..."):
                    try:
                        data = _cached_law_text(law["MST"], law_api_key, openai_api_key)
                        st.session_state["s1_law_data"] = data
                    except Exception as e:
                        st.error(f"조문 조회 실패: {e}")

            if "s1_law_data" in st.session_state:
                law_data = st.session_state["s1_law_data"]
                articles = law_data["조문목록"]
                article_labels = [
                    f"{_format_jo_ref(a['조번호'])} {a['제목']}" for a in articles
                ]
                selected_idx = st.selectbox(
                    "개정할 조문",
                    range(len(article_labels)),
                    format_func=lambda i: article_labels[i],
                    key="s1_article_idx",
                )
                selected_article = articles[selected_idx]
                with st.expander("현행 조문 전문 보기"):
                    st.text(selected_article["내용"])
                st.session_state["s1_article"] = selected_article

    # ── 개정 요강 + GPT 생성 ─────────────────────────────────────────────────
    with st.container(border=True):
        st.markdown('<div class="mofe-subheader">개정 요강</div>', unsafe_allow_html=True)
        outline = st.text_area(
            "개정 내용을 입력하세요",
            height=120,
            placeholder="예: 법인세율을 현행 20%에서 19%로 인하",
            key="s1_outline",
        )

        application_basis = st.selectbox(
            "부칙 적용 기준",
            _APPLICATION_BASIS_OPTIONS,
            key="s1_application_basis",
            help="자동 추천은 조문 제목·개정요강과 부칙 선례를 기준으로 적용 기준을 고릅니다.",
        )

        if st.button("GPT 초안 생성", type="primary", key="s1_generate"):
            if not outline:
                st.error("개정 요강을 입력하세요.")
                return
            if "s1_article" not in st.session_state:
                st.error("개정할 조문을 선택하세요.")
                return
            if not openai_api_key:
                st.error("OpenAI API 키가 없습니다.")
                return

            article = st.session_state["s1_article"]
            law_data = st.session_state.get("s1_law_data", {})
            outline_article = _find_article_by_outline(law_data.get("조문목록", []), outline)
            if outline_article and _article_key(outline_article) != _article_key(article):
                article = outline_article
                st.session_state["s1_article"] = article
                st.info(f"개정요강의 조문번호에 맞춰 개정 대상을 {_article_heading(article)}로 자동 보정했습니다.")
            law = st.session_state.get("s1_selected_law", {})

            with st.spinner("초안 생성 중..."):
                try:
                    _reset_draft_edit_state()
                    article_text = _article_text_for_prompt(article)
                    draft = draft_amendment(
                        law_name=law.get("법령명", ""),
                        article_text=article_text,
                        outline=outline,
                        buchik_type=_effect_type_for_basis(application_basis),
                        api_key=openai_api_key,
                    )
                    sections = parse_draft_sections(draft)
                    if not any(sections.values()):
                        st.error("GPT 응답 파싱 실패 — 아래 원문을 확인하세요.")
                        with st.expander("GPT 원문"):
                            st.code(draft)
                    else:
                        buchik_text, precedent = _build_buchik(
                            article,
                            law.get("법령명", ""),
                            application_basis,
                            outline,
                        )
                        sections["현행"] = _source_current_section(
                            article,
                            outline,
                            sections.get("현행", ""),
                        )
                        sections["연관항"] = _merge_related_text(
                            sections.get("연관항", ""),
                            _deterministic_related_reviews(article, outline),
                        )
                        sections["부칙"] = buchik_text
                        st.session_state["s1_draft"] = draft
                        st.session_state["s1_sections"] = sections
                        st.session_state["s1_buchik_precedent"] = precedent
                except Exception as e:
                    st.error(f"생성 실패: {e}")

    # ── 초안 표시 ─────────────────────────────────────────────────────────────
    if "s1_sections" in st.session_state:
        with st.container(border=True):
            sections = st.session_state["s1_sections"]
            st.markdown('<div class="mofe-subheader">생성된 초안</div>', unsafe_allow_html=True)

            # 연관 항 검토 — [제안]·[검토] 모두 설명 텍스트 + 체크박스 표시
            related = sections.get("연관항", "").strip()
            accepted_suggests: list[tuple[str, str, str]] = []

            if related:
                st.warning("⚠️ **연관 항 검토 필요**")

                # 공통 그룹 빌더
                def _build_groups(matches: list[tuple]) -> dict:
                    groups: dict[str, dict] = {}
                    for m in matches:
                        sym_label, old_val, new_val = m[0], m[1], m[2]
                        reason = m[3].strip() if len(m) > 3 and m[3] else ""
                        char_m = _SYM_CHAR_RE.search(sym_label)
                        sym_char = char_m.group(0) if char_m else sym_label.strip()
                        if sym_char not in groups:
                            groups[sym_char] = {"desc": sym_label, "reason": reason, "changes": []}
                        groups[sym_char]["changes"].append((old_val, new_val))
                    return groups

                suggest_matches = _SUGGEST_RE.findall(related)
                review_matches  = _REVIEW_RE.findall(related)

                if suggest_matches or review_matches:
                    st.markdown("**연관 항 — 체크 시 개정안에 반영됩니다**")

                for prefix, matches in (("[제안]", suggest_matches), ("[검토]", review_matches)):
                    if not matches:
                        continue
                    groups = _build_groups(matches)
                    for sym_char, info in groups.items():
                        desc   = info["desc"]
                        reason = info["reason"]
                        changes = info["changes"]
                        caption = f"{prefix} {desc}"
                        if reason:
                            caption += f" — {reason}"
                        st.caption(caption)
                        label_parts = [f'"{o}" → "{n}"' for o, n in changes]
                        label = f"{sym_char}항: " + ", ".join(label_parts) + " 적용"
                        key = f"s1_suggest_{prefix.strip('[]')}_{sym_char}"
                        if st.checkbox(label, key=key):
                            for old_val, new_val in changes:
                                accepted_suggests.append((sym_char, old_val, new_val))

                # 파싱 안 된 나머지 텍스트 표시
                remaining = _SUGGEST_RE.sub("", _REVIEW_RE.sub("", related)).strip()
                if remaining:
                    st.code(remaining, language="")

            st.session_state["s1_accepted_suggests"] = accepted_suggests

            st.markdown("**개정지시문**")
            instruction = st.text_area(
                "수정 가능",
                value=sections.get("지시문", ""),
                height=100,
                key="s1_instruction_edit",
            )
            st.session_state["final_instruction"] = instruction

            # ── 항별 변경 확인 ─────────────────────────────────────────────────
            amended_raw = sections.get("개정안", "")
            hang_blocks = _split_hang_blocks(amended_raw)
            changed_hangs = [
                (sym, content) for sym, content in hang_blocks
                if sym and _HAS_U_RE.search(content) and "(현행과같음)" not in content
            ]

            if changed_hangs:
                st.markdown("**변경된 항 확인 — 적용 여부를 선택하세요**")
                st.caption("⚠️ 체크 해제 시 해당 항은 '(현행과같음)'으로 되돌아갑니다.")
                overrides: dict[str, bool] = {}
                for sym, content in changed_hangs:
                    # 연관 항 검토 안내 포함 여부 확인
                    is_related = "연관 항 검토" in content or "연동 검토" in content
                    label = f"{sym}항 변경 적용"
                    if is_related:
                        label += " ⚠️ (연관 수치 — 검토 필요)"
                    checked = st.checkbox(label, value=True, key=f"s1_hang_{sym}")
                    overrides[sym] = checked
                st.session_state["s1_hang_overrides"] = overrides
            else:
                st.session_state["s1_hang_overrides"] = {}

            # overrides 적용
            saved_overrides = st.session_state.get("s1_hang_overrides", {})
            effective_amended = _apply_hang_overrides(amended_raw, saved_overrides)

            # [제안] 연관항 수락 반영
            effective_amended = _apply_suggestions(
                effective_amended,
                st.session_state.get("s1_accepted_suggests", []),
                st.session_state.get("s1_article", {}).get("내용", ""),
            )

            col_a, col_b = st.columns(2)
            with col_a:
                st.markdown("**현행**")
                current_text = st.text_area(
                    "",
                    value=sections.get("현행", ""),
                    height=200,
                    key="s1_current_edit",
                    label_visibility="collapsed",
                )
            with col_b:
                st.markdown("**개정안**")
                st.session_state["s1_amended_edit"] = effective_amended
                amended_text = st.text_area(
                    "",
                    height=200,
                    key="s1_amended_edit",
                    label_visibility="collapsed",
                )

            st.session_state["final_current"] = current_text
            st.session_state["final_amended"] = amended_text

            st.markdown("**부칙**")
            buchik_text = st.text_area(
                "수정 가능",
                value=sections.get("부칙", ""),
                height=80,
                key="s1_buchik_edit",
            )
            st.session_state["final_buchik"] = buchik_text
            precedent = st.session_state.get("s1_buchik_precedent")
            if precedent:
                st.caption(f"참조 부칙 선례: {precedent.get('source', precedent.get('id', '선례'))}")
            else:
                st.caption("참조 부칙 선례 없음: 기본 템플릿을 사용했습니다.")

            law = st.session_state.get("s1_selected_law", {})
            st.session_state["final_law_name"] = law.get("법령명", "")

    # ── 병행 법령 검사 + 초안 생성 ────────────────────────────────────────────
    if "s1_sections" in st.session_state:
        with st.container(border=True):
            st.markdown('<div class="mofe-subheader">병행 법령 동일 취지 검사</div>', unsafe_allow_html=True)
            st.caption("⚠️ GPT 추론 기반 — 반드시 검토 후 적용하세요")
            law_name = st.session_state.get("final_law_name", "")
            scope_label = st.selectbox(
                "탐색 범위",
                ["관련·하위 법령군", "전체 법령목록"],
                key="s1_parallel_scope",
                help="전체 법령목록은 법제처 API 호출량이 커서 시간이 오래 걸릴 수 있습니다.",
            )
            max_all_pages = 10
            if scope_label == "전체 법령목록":
                max_all_pages = st.number_input(
                    "전체 법령목록 조회 페이지 수",
                    min_value=1,
                    max_value=100,
                    value=10,
                    key="s1_parallel_max_pages",
                    help="1페이지당 최대 100개 법령을 조회합니다.",
                )

            if st.button("병행 법령 검사", key="s1_parallel_check"):
                if not law_name:
                    st.error("법령명 정보가 없습니다.")
                else:
                    with st.spinner("GPT 병행 법령 분석 중..."):
                        try:
                            suggestions = check_all_parallel_laws(
                                law_name=law_name,
                                article_text=st.session_state.get("final_amended", ""),
                                law_api_key=law_api_key,
                                openai_api_key=openai_api_key,
                                scope="all" if scope_label == "전체 법령목록" else "related",
                                max_all_pages=int(max_all_pages),
                            )
                            st.session_state["s1_parallel_suggestions"] = suggestions
                            st.session_state["s2_extra_amendments"] = []
                        except Exception as e:
                            st.error(f"분석 실패: {e}")

            suggestions = st.session_state.get("s1_parallel_suggestions", [])
            if not suggestions:
                if "s1_parallel_suggestions" in st.session_state:
                    st.success("병행 개정 필요 법령 없음")
            else:
                st.write(f"병행 개정 검토 필요: {len(suggestions)}건")
                extra: list[dict] = []
                for i, s in enumerate(suggestions):
                    clean_ref = _clean_article_ref_for_law(s["법령명"], s["조문"])
                    with st.expander(f"{s['법령명']} {clean_ref}"):
                        url = _law_url(s["법령명"], clean_ref)
                        st.markdown(f"[📄 법령 원문 바로가기]({url})")
                        if s.get("분류"):
                            st.write(f"**분류**: {s['분류']}")
                        st.write(f"**이유**: {s['이유']}")
                        내용 = s.get("내용", "")
                        if 내용:
                            st.markdown("**해당 조항 내용**")
                            st.text(내용)
                        if st.checkbox("이 조문도 개정 목록에 포함", value=True, key=f"s1_include_{i}"):
                            extra.append({"법령명": s["법령명"], "조문": clean_ref, "MST": s["MST"]})
                st.session_state["s2_extra_amendments"] = extra

                # 포함된 병행 법령 초안 생성
                if extra and st.button("병행 법령 초안 생성", key="s1_parallel_draft"):
                    outline = st.session_state.get("s1_outline", "")
                    application_basis = st.session_state.get("s1_application_basis", "자동 추천")
                    buchik_type = _effect_type_for_basis(application_basis)
                    parallel_sections: list[dict] = []
                    for entry in extra:
                        with st.spinner(f"{entry['법령명']} {entry['조문']} 초안 생성 중..."):
                            try:
                                from core.amendment_agent import parse_draft_sections as _pds
                                from ui.stage3_output import _fetch_parallel_article, _build_comparison_rows
                                article_text = _fetch_parallel_article(entry, law_api_key, openai_api_key)
                                if not article_text:
                                    st.warning(f"{entry['법령명']} {entry['조문']} 조문 조회 실패")
                                    continue
                                # 병행 법령의 실제 조문 번호를 outline에 명시
                                # (원본 outline에 원법령 항 번호가 고정돼 있어 GPT가 그대로 사용하는 버그 방지)
                                parallel_outline = (
                                    outline
                                    + f"\n\n※ 이 병행 법령의 개정 대상 조문은 {entry['조문']}입니다. "
                                    f"개정지시문의 조문·항 번호는 반드시 {entry['조문']} 기준으로 작성할 것. "
                                    f"원법령의 항 번호를 그대로 사용하지 말 것."
                                )
                                draft = draft_amendment(
                                    law_name=entry["법령명"],
                                    article_text=article_text,
                                    outline=parallel_outline,
                                    buchik_type=buchik_type,
                                    api_key=openai_api_key,
                                )
                                secs = _pds(draft)
                                parallel_buchik, _precedent = _build_buchik(
                                    _article_from_text(entry["조문"], article_text),
                                    entry["법령명"],
                                    application_basis,
                                    outline,
                                )
                                parallel_sections.append({
                                    "법령명": entry["법령명"],
                                    "조문": entry["조문"],
                                    "instruction": secs.get("지시문", ""),
                                    "rows": _build_comparison_rows(secs.get("현행", ""), secs.get("개정안", "")),
                                    "buchik": parallel_buchik,
                                })
                            except Exception as e:
                                st.error(f"{entry['법령명']} 초안 생성 실패: {e}")
                    st.session_state["s3_parallel_sections"] = parallel_sections
                    st.success(f"병행 법령 초안 {len(parallel_sections)}건 생성 완료")

                # 기존 캐시 미리보기
                for ps in st.session_state.get("s3_parallel_sections", []):
                    ps_ref = _clean_article_ref_for_law(ps["법령명"], ps["조문"])
                    with st.expander(f"{ps['법령명']} {ps_ref} 초안"):
                        st.markdown("**개정지시문**"); st.code(ps["instruction"], language="")
                        if ps.get("rows") and len(ps["rows"]) > 1:
                            st.markdown("**신구조문대비표**")
                            st.dataframe(
                                [{"현 행": r[0], "개 정 안": r[1]} for r in ps["rows"][1:]],
                                use_container_width=True,
                                hide_index=True,
                            )
                        st.markdown("**부칙**"); st.code(ps["buchik"], language="")
