"""신설 조문 검토 탭 — 조문안 입력 → 연동 개정 후보 3종 출력."""
import re

import streamlit as st

from core.new_article_scanner import parse_jo_tokens, review_new_articles

_JO_URL_RE = re.compile(r"제(\d+)조(?:의(\d+))?")


def _law_url(law_name: str, jo_ref: str = "") -> str:
    base = f"https://www.law.go.kr/법령/{law_name}"
    m = _JO_URL_RE.search(str(jo_ref))
    if m:
        article = f"제{m.group(1)}조" + (f"의{m.group(2)}" if m.group(2) else "")
        return f"{base}/{article}"
    parts = str(jo_ref).split("의")
    if parts and parts[0].isdigit():
        article = f"제{parts[0]}조" + (f"의{parts[1]}" if len(parts) > 1 else "")
        return f"{base}/{article}"
    return base


def _format_jo_label(jo_key: str) -> str:
    parts = str(jo_key).split("의")
    if parts and parts[0].isdigit():
        return f"제{parts[0]}조" + (f"의{parts[1]}" if len(parts) > 1 else "")
    return str(jo_key)


def render(law_api_key: str, openai_api_key: str) -> None:
    st.markdown('<div class="mofe-section-header">신설 조문 검토</div>', unsafe_allow_html=True)
    st.caption(
        "신설 조문안을 입력하면 ① 조문안이 인용하는 조문(순방향) "
        "② 재사용 조번호를 아직 인용 중인 현행 조문(잔존 인용 충돌) "
        "③ 유사 기존 제도 기준 연동 개정 체크리스트를 찾습니다."
    )

    with st.container(border=True):
        col1, col2, col3 = st.columns([2, 1, 1])
        with col1:
            law_name = st.text_input("신설 대상 법령", value="조세특례제한법", key="na_law")
        with col2:
            jo_range_text = st.text_input(
                "신설 조번호 범위", value="", key="na_range",
                placeholder="예: 29~29의8",
                help="쉼표 나열(29, 29의2) 또는 범위(29~29의8, 제29조부터 제29조의8까지)",
            )
        with col3:
            proxy_text = st.text_input(
                "유사 기존 제도 조문(선택)", value="", key="na_proxy",
                placeholder="예: 24",
                help="성격이 비슷한 기존 제도의 조번호. 그 제도를 인용하는 열거형 조문이 신설 시 검토 대상이 됩니다.",
            )
        draft_text = st.text_area(
            "신설 조문안",
            height=300,
            key="na_draft",
            placeholder="제29조(○○세액공제) ① 내국인이 ...",
        )

        if st.button("신설 검토 실행", key="na_run", type="primary"):
            if not jo_range_text.strip():
                st.error("신설 조번호 범위를 입력하세요.")
            else:
                st.session_state["na_result"] = review_new_articles(
                    law_name.strip(), jo_range_text, draft_text, proxy_text,
                )

    result = st.session_state.get("na_result")
    if not result:
        return

    law_name = st.session_state.get("na_law", "조세특례제한법").strip()
    jo_labels = ", ".join(f"제{jo}조의{sub}" if sub else f"제{jo}조" for jo, sub in result["jo_list"])
    st.markdown(f"**검토 대상**: {law_name} {jo_labels}")

    if not result["graph_ok"]:
        st.warning(
            "인용 그래프(data/law-citation-graph.json)가 없어 잔존 인용·프록시 검토를 건너뜁니다. "
            "`uv run python scripts/build_law_citation_graph.py --all` 실행 후 다시 시도하세요."
        )

    # ── ① 순방향 인용 ─────────────────────────────────────────────────────────
    with st.container(border=True):
        st.markdown('<div class="mofe-subheader">① 신설 조문안이 인용하는 조문</div>', unsafe_allow_html=True)
        forward = result["forward"]
        if not st.session_state.get("na_draft", "").strip():
            st.info("조문안을 입력하면 인용 조문을 파싱합니다.")
        elif not forward:
            st.success("인용 조문 없음")
        else:
            external = [r for r in forward if not r["신설범위내"]]
            internal = [r for r in forward if r["신설범위내"]]
            st.write(f"외부 인용 {len(external)}건 · 신설 범위 내 상호 인용 {len(internal)}건")
            if external:
                st.dataframe(
                    [
                        {
                            "법령": r["법령명"],
                            "조문": r["조문"],
                            "인용 원문": r["인용 원문"],
                            "범위": "O" if r["범위"] else "",
                            "원문 링크": _law_url(r["법령명"], r["조문"]),
                        }
                        for r in external
                    ],
                    column_config={
                        "원문 링크": st.column_config.LinkColumn("원문 링크", display_text="바로가기"),
                    },
                    use_container_width=True,
                )
                st.caption("외부 인용 조문은 정의·요건을 차용하는 의존 관계입니다. 인용 대상의 현행 문구와 정합성을 확인하세요.")
            if internal:
                with st.expander(f"신설 범위 내 상호 인용 {len(internal)}건 (번호 정합성 확인용)"):
                    st.dataframe(
                        [{"조문": r["조문"], "인용 원문": r["인용 원문"]} for r in internal],
                        use_container_width=True,
                    )

    # ── ② 잔존 인용 충돌 ──────────────────────────────────────────────────────
    with st.container(border=True):
        st.markdown('<div class="mofe-subheader">② 재사용 조번호 잔존 인용 충돌</div>', unsafe_allow_html=True)
        st.caption(
            "구 조문이 삭제됐어도 이월공제·경과규정 때문에 인용이 남아 있으면, "
            "같은 번호에 새 제도가 들어가는 순간 그 인용이 신설 조문을 가리키게 됩니다. "
            "신설 전 정비 또는 부칙 경과조치가 필요합니다."
        )
        stale = result["stale"]
        if not result["graph_ok"]:
            st.info("그래프 빌드 후 사용 가능합니다.")
        elif not stale:
            st.success("재사용 번호를 인용 중인 현행 조문 없음")
        else:
            st.warning(f"⚠️ 잔존 인용 {len(stale)}건 — 정비·경과조치 검토 필요")
            for row in stale:
                jo_label = _format_jo_label(row["조번호"])
                url = _law_url(row["법령명"], row["조번호"])
                with st.expander(f"{row['법령명']} {jo_label} {row['제목']} — 대상: {', '.join(row['대상'])}"):
                    st.markdown(f"[📄 법령 원문 바로가기]({url})")
                    for raw in row["인용"]:
                        st.markdown(f"**인용 구문**: `{raw}`")

    # ── ③ 유사 제도 체크리스트 ────────────────────────────────────────────────
    with st.container(border=True):
        st.markdown('<div class="mofe-subheader">③ 유사 제도 기준 연동 개정 체크리스트</div>', unsafe_allow_html=True)
        st.caption(
            "유사 기존 제도를 인용하는 조문(중복지원 배제·최저한세·이월공제 등 열거형 조문)에 "
            "신설 조번호 추가 여부를 검토합니다."
        )
        proxies = parse_jo_tokens(st.session_state.get("na_proxy", ""))
        proxy_rows = result["proxy"]
        if not proxies:
            st.info("유사 기존 제도 조문을 입력하면 체크리스트를 생성합니다. (예: 통합투자세액공제 = 24)")
        elif not result["graph_ok"]:
            st.info("그래프 빌드 후 사용 가능합니다.")
        elif not proxy_rows:
            st.success("프록시 조문을 인용하는 조문 없음")
        else:
            st.write(f"검토 대상 {len(proxy_rows)}건")
            st.dataframe(
                [
                    {
                        "법령": r["법령명"],
                        "조문": _format_jo_label(r["조번호"]),
                        "제목": r["제목"],
                        "프록시 인용": ", ".join(r["인용"][:3]),
                        "원문 링크": _law_url(r["법령명"], r["조번호"]),
                    }
                    for r in proxy_rows
                ],
                column_config={
                    "원문 링크": st.column_config.LinkColumn("원문 링크", display_text="바로가기"),
                },
                use_container_width=True,
            )
