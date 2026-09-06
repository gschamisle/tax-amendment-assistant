"""세법 관계도 탭 — 법령 은하(3D)와 조문 관계도(2D).

발표 후 공개된 정보만 다루므로 LLM도 API 키도 필요 없다. 인용 그래프만 읽는다.
"""
from __future__ import annotations

import streamlit as st
import streamlit.components.v1 as components

from core import law_abbrev


@st.cache_data(show_spinner=False)
def _galaxy(min_edge: int, max_articles: int) -> str:
    from core.law_galaxy import build, render_html, render_page

    data = build(min_edge=min_edge, max_articles_per_law=max_articles)
    return render_html(data, height=680), render_page(data)


@st.cache_data(show_spinner=False)
def _flat_map(min_edge: int, cross_only: bool) -> tuple[str, list]:
    from core.law_map import build, render_svg, top_pairs

    data = build(min_edge=min_edge, cross_family_only=cross_only)
    return render_svg(data), top_pairs(data, 15)


def render(law_api_key: str = "", openai_api_key: str = "") -> None:
    st.markdown('<div class="mofe-section-header">세법 관계도</div>', unsafe_allow_html=True)
    st.caption(
        "인용 그래프(32개 법령·29,302건)를 그대로 그립니다. 배치는 결정적이라 "
        "같은 데이터면 항상 같은 그림이 나옵니다. API 키·LLM이 필요 없습니다."
    )

    view = st.radio(
        "보기", ["법령 은하 (3D)", "법령 관계도 (평면)"],
        horizontal=True, key="lm_view", label_visibility="collapsed",
    )

    if view.startswith("법령 은하"):
        c1, c2 = st.columns(2)
        min_edge = c1.slider("표시할 최소 인용 건수", 2, 60, 8, key="lm_g_min",
                             help="낮출수록 선이 늘어 촘촘해집니다")
        max_arts = c2.slider("법령당 조문 점 수", 40, 450, 220, step=10, key="lm_g_arts",
                             help="많을수록 성운이 짙어지지만 뭉칩니다")
        with st.spinner("좌표 계산 중..."):
            frag, page = _galaxy(min_edge, max_arts)
        components.html(frag, height=700, scrolling=False)
        st.download_button(
            "은하 HTML 내려받기 (파일 하나, 오프라인 동작)",
            data=page.encode("utf-8"), file_name="법령은하.html",
            mime="text/html", key="lm_g_dl",
        )
        st.caption(
            "드래그로 회전, 휠로 확대, 법령을 클릭하면 그 법령의 인용만 남습니다. "
            "시행령→모법 인용은 위임 구조상 당연해 제외했습니다."
        )
    else:
        c1, c2 = st.columns([1, 2])
        min_edge = c1.slider("표시할 최소 인용 건수", 2, 80, 8, key="lm_f_min")
        cross = c2.checkbox(
            "법령군 간 인용만 (시행령→모법 제외)", value=True, key="lm_f_cross",
            help="끄면 조특령→조특법(2,728건) 같은 당연한 관계가 화면을 덮습니다",
        )
        svg, pairs = _flat_map(min_edge, cross)
        st.markdown(svg, unsafe_allow_html=True)
        st.download_button("관계도 SVG 내려받기", data=svg.encode("utf-8"),
                           file_name="법령관계도.svg", mime="image/svg+xml", key="lm_f_dl")
        with st.expander(f"인용이 많은 법령쌍 {len(pairs)}건"):
            for a, b, n in pairs:
                st.markdown(f"- **{a} → {b}** · {n:,}건")

    st.divider()
    # 조문 단위 관계도(조문 연관 조회)는 지금 숨겨 둔 탭이라 여기서 안내하지 않는다 —
    # 없는 탭으로 보내는 문구가 되기 때문. ENABLE_WIP_TABS를 켜면 다시 살릴 것.
    st.caption(
        "법령 약칭은 재정경제부 세제개편안 상세본의 공식 약어를 따릅니다 "
        f"(예: {law_abbrev.law('소득세법 시행령')} {law_abbrev.article('제73조의2')})."
    )
