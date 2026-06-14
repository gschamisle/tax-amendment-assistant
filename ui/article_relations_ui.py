"""1단계 '개정조문 직접 입력' 모드 — 연관 조문 4분류 패널."""
import re

import streamlit as st

from core.article_relations import analyze_article_relations

_JO_URL_RE = re.compile(r"제(\d+)조(?:의(\d+))?")


def _law_url(law_name: str, jo_ref: str = "") -> str:
    base = f"https://www.law.go.kr/법령/{law_name}"
    m = _JO_URL_RE.search(str(jo_ref))
    if m:
        article = f"제{m.group(1)}조" + (f"의{m.group(2)}" if m.group(2) else "")
        return f"{base}/{article}"
    parts = str(jo_ref).split("의")
    if parts and parts[0].isdigit():
        return f"{base}/제{parts[0]}조" + (f"의{parts[1]}" if len(parts) > 1 else "")
    return base


def _fmt_jo(jo_key: str) -> str:
    parts = str(jo_key).split("의")
    if parts and parts[0].isdigit():
        return f"제{parts[0]}조" + (f"의{parts[1]}" if len(parts) > 1 else "")
    return str(jo_key)


def _forward_table(rows: list[dict]) -> None:
    st.dataframe(
        [
            {
                "법령": r["법령명"],
                "조문": r["조문"],
                "원문": r["원문"],
                "범위": "O" if r["범위"] else "",
                "원문 링크": _law_url(r["법령명"], r["조문"]),
            }
            for r in rows
        ],
        column_config={"원문 링크": st.column_config.LinkColumn("원문 링크", display_text="바로가기")},
        use_container_width=True,
    )


def render(law_api_key: str, openai_api_key: str) -> None:
    """조문 직접 입력 → 인용/준용/역인용/병행개정 4분류."""
    st.caption(
        "개정되는 조문 본문을 직접 입력하면 ① 인용 ② 준용 ③ 역인용(이 조문을 인용하는 조항) "
        "④ 병행개정(짝 세법 대응 조문)으로 구분해 연관 조문만 찾습니다. "
        "GPT 초안 생성 없이 결정적 분석(파서·인용그래프·병행매트릭스)만 사용합니다."
    )

    # 1단계에서 이미 법령·조문을 선택했으면 자동 채움
    sel_law = st.session_state.get("s1_selected_law", {})
    sel_article = st.session_state.get("s1_article", {})
    default_law = sel_law.get("법령명", "") if isinstance(sel_law, dict) else ""
    default_jo = str(sel_article.get("조번호", "")) if isinstance(sel_article, dict) else ""
    default_text = str(sel_article.get("내용", "")) if isinstance(sel_article, dict) else ""

    with st.container(border=True):
        col1, col2 = st.columns([3, 1])
        with col1:
            law_name = st.text_input("법령명", value=default_law, key="ar_law")
        with col2:
            jo = st.text_input("조번호", value=default_jo, key="ar_jo", help="예: 127 또는 27의2")
        article_text = st.text_area(
            "개정 조문 본문 (선택한 조문이 있으면 자동 채워집니다 — 개정안으로 수정 가능)",
            value=default_text,
            height=220,
            key="ar_text",
        )
        if st.button("연관 조문 분석", key="ar_run", type="primary"):
            if not law_name.strip() or not jo.strip():
                st.error("법령명과 조번호를 입력하세요.")
            else:
                st.session_state["ar_result"] = analyze_article_relations(
                    law_name.strip(), jo.strip(), article_text
                )

    result = st.session_state.get("ar_result")
    if not result:
        return

    st.markdown(f"**분석 대상**: {result['law_name']} {_fmt_jo(result['jo'])}")
    if not result["graph_ok"]:
        st.warning("인용 그래프가 없어 역인용을 건너뜁니다. `build_law_citation_graph.py --all` 후 재시도.")
    if not result["matrix_ok"]:
        st.warning("병행 매트릭스가 없어 병행개정을 건너뜁니다. `build_parallel_matrix.py` 후 재시도.")

    # ── ① 인용 ───────────────────────────────────────────────────────────────
    with st.container(border=True):
        st.markdown('<div class="mofe-subheader">📎 ① 인용 조문 (이 조문이 끌어쓰는 조문)</div>', unsafe_allow_html=True)
        if result["cited"]:
            _forward_table(result["cited"])
            st.caption("정의·요건을 차용하는 의존 관계입니다. 인용 대상의 현행 문구와 정합성을 확인하세요.")
        else:
            st.info("인용 조문 없음 (본문을 입력했는지 확인)")

    # ── ② 준용 ───────────────────────────────────────────────────────────────
    with st.container(border=True):
        st.markdown('<div class="mofe-subheader">🔗 ② 준용 조문 ("준용한다"로 끌어쓴 조문)</div>', unsafe_allow_html=True)
        if result["junyong"]:
            _forward_table(result["junyong"])
            st.caption("준용 대상이 개정되면 이 조문의 적용 결과도 함께 바뀝니다.")
        else:
            st.info("준용 조문 없음")

    # ── ③ 역인용 ─────────────────────────────────────────────────────────────
    with st.container(border=True):
        st.markdown('<div class="mofe-subheader">↩️ ③ 역인용 조문 (이 조문을 인용하는 다른 조항)</div>', unsafe_allow_html=True)
        back = result["back_cited"]
        if not result["graph_ok"]:
            st.info("그래프 빌드 후 사용 가능합니다.")
        elif back:
            st.warning(f"⚠️ {len(back)}건 — 이 조문 개정 시 영향받을 수 있어 검토 필요")
            for r in back:
                url = _law_url(r["법령명"], r["조번호"])
                with st.expander(f"{r['법령명']} {_fmt_jo(r['조번호'])} {r['제목']}"):
                    st.markdown(f"[📄 법령 원문 바로가기]({url})")
                    for raw in r["인용"]:
                        st.markdown(f"**인용 구문**: `{raw}`")
        else:
            st.success("이 조문을 인용하는 다른 조항 없음")

    # ── ④ 병행개정 ───────────────────────────────────────────────────────────
    with st.container(border=True):
        st.markdown('<div class="mofe-subheader">⚖️ ④ 병행개정 조문 (짝 세법의 대응 조문)</div>', unsafe_allow_html=True)
        par = result["parallel"]
        if not result["matrix_ok"]:
            st.info("매트릭스 빌드 후 사용 가능합니다.")
        elif par:
            st.warning(f"⚠️ {len(par)}건 — 동일 취지로 함께 개정할지 검토 필요")
            st.dataframe(
                [
                    {
                        "법령": r["법령명"],
                        "조문": r["조문"],
                        "확신도": r["확신도"],
                        "근거": r["근거"],
                        "원문 링크": _law_url(r["법령명"], r["조문"]),
                    }
                    for r in par
                ],
                column_config={"원문 링크": st.column_config.LinkColumn("원문 링크", display_text="바로가기")},
                use_container_width=True,
            )
        else:
            st.success("병행개정 대상 없음")
