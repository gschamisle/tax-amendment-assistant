"""Stage 2: 인용·준용 규정 검출."""
import re
import streamlit as st
from core.citation_parser import Citation, parse_citations, detect_number_shift, find_back_citations
from core.law_network import all_law_scope_entries, candidate_scope_entries, scan_back_citations

_JO_URL_RE = re.compile(r"제(?:(\d+)의(\d+)조|(\d+)조(?:의(\d+))?)")


def _parse_jo_ref(jo_ref: str) -> tuple[str, str] | None:
    text = str(jo_ref).strip()
    m = _JO_URL_RE.search(text)
    if m:
        if m.group(1) is not None:
            return m.group(1), m.group(2) or ""
        return m.group(3), m.group(4) or ""
    parts = text.split("의")
    if parts and parts[0].isdigit():
        return parts[0], parts[1] if len(parts) > 1 and parts[1].isdigit() else ""
    return None


def _format_jo_ref(jo_ref: str) -> str:
    parsed = _parse_jo_ref(jo_ref)
    if not parsed:
        return str(jo_ref)
    jo, jo_sub = parsed
    return f"제{jo}조의{jo_sub}" if jo_sub else f"제{jo}조"


def _law_url(law_name: str, jo_ref: str = "") -> str:
    """법제처 한글 주소 생성."""
    base = f"https://www.law.go.kr/법령/{law_name}"
    parsed = _parse_jo_ref(jo_ref) if jo_ref else None
    if parsed:
        jo, jo_sub = parsed
        article = f"제{jo}조" + (f"의{jo_sub}" if jo_sub else "")
        return f"{base}/{article}"
    return base


def _format_cite_ref(c: Citation) -> str:
    """Citation → '제N조의M제P항제Q호제R목' 형식 문자열."""
    parts: list[str] = []
    if c.jo:
        parts.append(f"제{c.jo}조" + (f"의{c.jo_sub}" if c.jo_sub else ""))
    if c.hang:
        parts.append(f"제{c.hang}항")
    if c.ho:
        parts.append(f"제{c.ho}호")
    if c.mok:
        parts.append(f"제{c.mok}목")
    return "".join(parts) if parts else c.raw


def _first_changed_hang(text: str) -> str:
    """개정안에서 <u>/<del>가 들어간 첫 항 번호를 추정한다."""
    current = ""
    for line in text.splitlines():
        m = re.match(r"\s*[①②③④⑤⑥⑦⑧⑨⑩⑪⑫⑬⑭⑮⑯⑰⑱⑲⑳]", line)
        if m:
            current = str("①②③④⑤⑥⑦⑧⑨⑩⑪⑫⑬⑭⑮⑯⑰⑱⑲⑳".index(m.group(0).strip()) + 1)
        if ("<u>" in line or "<del>" in line) and current:
            return current
    return ""


def render(law_api_key: str, openai_api_key: str) -> None:
    st.markdown('<div class="mofe-section-header">2단계: 인용·준용 규정 확인</div>', unsafe_allow_html=True)

    if "s1_sections" not in st.session_state:
        st.info("1단계에서 먼저 초안을 생성하세요.")
        return

    amended = st.session_state.get("final_amended", "")

    # ── 개정안 내 인용 규정 ────────────────────────────────────────────────────
    with st.container(border=True):
        st.markdown('<div class="mofe-subheader">개정안 내 인용 규정</div>', unsafe_allow_html=True)
        if st.button("인용 규정 파싱", key="s2_parse"):
            citations = parse_citations(amended)
            st.session_state["s2_citations"] = citations

        if "s2_citations" in st.session_state:
            citations = st.session_state["s2_citations"]
            law_name = st.session_state.get("final_law_name", "")

            rows: list[dict] = []
            seen_keys: set = set()

            for c in citations:
                if not c.jo:
                    continue
                key = (c.law_name, c.jo, c.jo_sub, c.hang, c.ho, c.mok)
                if key in seen_keys:
                    continue
                seen_keys.add(key)

                # 법령명 결정
                if not c.law_name or c.law_name.startswith("같은"):
                    cite_law = law_name
                else:
                    cite_law = c.law_name

                jo_ref = f"제{c.jo}조" + (f"의{c.jo_sub}" if c.jo_sub else "")
                rows.append({
                    "조문 참조": _format_cite_ref(c),
                    "인용 원문": c.raw,
                    "법령": cite_law,
                    "범위": "O" if c.is_range else "",
                    "원문 링크": _law_url(cite_law, jo_ref),
                })

            if not rows:
                st.success("인용 규정 없음")
            else:
                st.write(f"총 {len(rows)}건 인용 규정 발견")
                st.dataframe(
                    rows,
                    column_config={
                        "원문 링크": st.column_config.LinkColumn("원문 링크", display_text="바로가기"),
                    },
                    use_container_width=True,
                )

            # 번호 밀림 경고
            st.markdown('<div class="mofe-subheader">조문 번호 밀림 검사</div>', unsafe_allow_html=True)
            inserted = st.number_input(
                "신설 조문 번호 (없으면 0)",
                min_value=0,
                value=0,
                key="s2_inserted_jo",
            )
            if inserted > 0:
                affected = detect_number_shift(citations, int(inserted))
                if affected:
                    st.warning(
                        f"제{inserted}조 신설 시 번호 밀림 영향 {len(affected)}건: "
                        + ", ".join(c.raw for c in affected[:5])
                    )
                else:
                    st.success("번호 밀림 영향 없음")

    # ── 인용 규정 — 이 조문을 인용하는 조항 ──────────────────────────────────
    with st.container(border=True):
        st.markdown('<div class="mofe-subheader">인용 규정 — 이 조문을 인용하는 조항</div>', unsafe_allow_html=True)
        st.caption("개정으로 영향받을 수 있는 다른 조항(인용 규정)을 검색합니다.")
        scope_label = st.selectbox(
            "역인용 탐색 범위",
            ["현재 법령 내부", "관련·하위 법령군", "전체 법령목록"],
            key="s2_back_scope",
        )
        target_hang = st.text_input(
            "대상 항 번호(선택)",
            value=_first_changed_hang(amended),
            key="s2_target_hang",
            help="비워두면 조문 전체 인용을 검색합니다.",
        ).strip()
        max_all_pages = 10
        if scope_label == "전체 법령목록":
            max_all_pages = st.number_input(
                "전체 법령목록 조회 페이지 수",
                min_value=1,
                max_value=100,
                value=10,
                key="s2_back_max_pages",
            )

        if st.button("인용 규정 검색", key="s2_back_cite"):
            law_data = st.session_state.get("s1_law_data")
            article = st.session_state.get("s1_article", {})
            law_name = st.session_state.get("final_law_name", "")
            if not law_data:
                st.error("1단계에서 조문 목록을 먼저 불러오세요.")
            else:
                jo_str = str(article.get("조번호", ""))
                jo_parts = jo_str.split("의")
                jo = jo_parts[0]
                jo_sub = jo_parts[1] if len(jo_parts) > 1 else ""
                with st.spinner("인용 규정 검색 중..."):
                    if scope_label == "현재 법령 내부":
                        back = find_back_citations(law_data, jo, jo_sub, target_hang)
                        for item in back:
                            item["법령명"] = law_name
                        st.session_state["s2_scan_errors"] = []
                    else:
                        if scope_label == "전체 법령목록":
                            entries = all_law_scope_entries(law_api_key, max_pages=int(max_all_pages))
                        else:
                            entries = candidate_scope_entries(law_name, law_api_key)
                        scan_errors: list[dict] = []
                        back = scan_back_citations(
                            entries,
                            target_law_name=law_name,
                            target_jo=jo,
                            target_jo_sub=jo_sub,
                            target_hang=target_hang,
                            law_api_key=law_api_key,
                            errors=scan_errors,
                        )
                        st.session_state["s2_scan_errors"] = scan_errors
                st.session_state["s2_back_citations"] = back

        if "s2_back_citations" in st.session_state:
            scan_errors = st.session_state.get("s2_scan_errors", [])
            if scan_errors:
                names = ", ".join(e.get("법령명", "?") for e in scan_errors[:5])
                more = f" 외 {len(scan_errors) - 5}건" if len(scan_errors) > 5 else ""
                st.error(
                    f"⚠️ {len(scan_errors)}개 법령 조회 실패({names}{more}) — "
                    "해당 법령의 인용은 검색에서 빠졌습니다. 잠시 후 다시 검색하세요."
                )
            back = st.session_state["s2_back_citations"]
            if not back:
                st.success("이 조문을 인용하는 다른 조항 없음")
            else:
                st.warning(f"⚠️ 인용 규정 {len(back)}건 발견 — 개정 내용 반영 여부 검토 필요")
                for bc in back:
                    bc_jo = str(bc["조번호"])
                    law_name_back = bc.get("법령명") or st.session_state.get("final_law_name", "")
                    bc_url = _law_url(law_name_back, bc_jo)
                    with st.expander(f"{law_name_back} {_format_jo_ref(bc_jo)} {bc['제목']}  [원문]({bc_url})"):
                        st.markdown(f"[📄 법령 원문 바로가기]({bc_url})")
                        내용 = bc.get("내용", "")
                        if 내용:
                            st.text(내용)
                        for cite in bc["인용"]:
                            raw = cite["raw"] if isinstance(cite, dict) else cite
                            hang = cite.get("hang", "") if isinstance(cite, dict) else ""
                            hang_end = cite.get("hang_end", "") if isinstance(cite, dict) else ""
                            jo_cite = cite.get("jo", "") if isinstance(cite, dict) else ""
                            if hang and hang_end:
                                hang_label = f" **(제{hang}항~제{hang_end}항 인용)**"
                            elif hang:
                                hang_label = f" **(제{hang}항 인용)**"
                            else:
                                hang_label = ""
                            if isinstance(cite, dict) and cite.get("via_range"):
                                hang_label += " 🔎 **범위 인용 전개 — 포함 검토 필요**"
                            if jo_cite:
                                cite_url = _law_url(law_name_back, f"제{jo_cite}조")
                            else:
                                cite_url = _law_url(law_name_back, bc_jo)
                            st.markdown(
                                f"**인용 구문**: `{raw}`{hang_label} &nbsp; "
                                f"[원문 확인]({cite_url})"
                            )
