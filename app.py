"""세법개정 AI 어시스턴트 — 메인 앱."""
import base64
import os
import streamlit as st
from config import LAW_API_KEY, OPENAI_API_KEY, ENABLE_HWPX_OUTPUT
from ui import new_article_ui, opinion_ui, stage1_draft, stage2_crossref, stage3_output
from ui.styles import inject_global_css

st.set_page_config(
    page_title="세법개정 AI 어시스턴트",
    page_icon="📋",
    layout="wide",
)

inject_global_css()

# ── 앱 헤더 ──────────────────────────────────────────────────────────────────
_logo_html = ""
if os.path.exists("logo.png"):
    with open("logo.png", "rb") as _f:
        _b64 = base64.b64encode(_f.read()).decode()
    _logo_html = f'<img src="data:image/png;base64,{_b64}" class="mofe-header-logo" />'

st.markdown(f"""
<div class="mofe-header-card">
  {_logo_html}
  <div class="mofe-app-title">
    <h1>세법개정 AI 어시스턴트</h1>
  </div>
</div>
""", unsafe_allow_html=True)

law_api_key = LAW_API_KEY
openai_api_key = OPENAI_API_KEY

if not law_api_key or not openai_api_key:
    st.warning(".env 파일에 LAW_API_KEY, OPENAI_API_KEY를 설정하세요.")

# 현행본 대조는 추적 법령(32건) 전체를 API로 조회해 1분 넘게 걸린다.
# 기동 때 자동으로 돌리면 그동안 화면이 백지라, 사용자가 원할 때만 실행한다.
_fresh_col, _btn_col = st.columns([5, 1])
with _btn_col:
    _check = st.button("현행본 대조", width="stretch",
                       help="추적 중인 법령 32건의 현행본을 조회해 저장된 스냅샷과 비교합니다 (약 1분)")
if _check and law_api_key:
    with _fresh_col, st.spinner("법제처에서 현행본을 조회하는 중... (약 1분)"):
        try:
            from core.law_freshness import compare_with_manifest, load_manifest

            _mf = load_manifest()
            st.session_state["law_freshness_changes"] = (
                compare_with_manifest(law_api_key) if _mf.get("laws") else []
            )
            st.session_state["law_freshness_done"] = True
        except Exception as _exc:
            st.session_state["law_freshness_changes"] = []
            st.session_state["law_freshness_error"] = str(_exc)

with _fresh_col:
    _freshness = st.session_state.get("law_freshness_changes", [])
    if st.session_state.get("law_freshness_error"):
        st.warning(f"현행본 대조 실패: {st.session_state['law_freshness_error']}")
    elif _freshness:
        _names = ", ".join(c["name"] for c in _freshness[:5])
        _more = f" 외 {len(_freshness) - 5}건" if len(_freshness) > 5 else ""
        st.warning(
            f"저장된 법령 스냅샷과 현행본이 다릅니다: {_names}{_more}. "
            "터미널에서 `uv run python scripts/check_law_freshness.py --update-manifest` 후 "
            "`uv run python scripts/build_law_citation_graph.py --all`, "
            "`uv run python scripts/build_parallel_matrix.py` 실행을 권장합니다."
        )
    elif st.session_state.get("law_freshness_done"):
        st.success("저장된 법령 스냅샷이 현행본과 일치합니다.")

# ── 탭 ────────────────────────────────────────────────────────────────────────
# 탭 아이콘은 Material Symbols(:material/…:)를 쓴다. 이모지는 OS·글꼴마다
# 모양과 폭이 달라 정렬이 흔들리고 디자인 토큰으로 색을 맞출 수 없다.
_tab3_label = ":material/description: HWPX 출력" + ("" if ENABLE_HWPX_OUTPUT else " (준비 중)")
tab1, tab2, tab3, tab4, tab5 = st.tabs([
    ":material/edit_note: 초안 작성",
    ":material/link: 인용·준용 확인",
    _tab3_label,
    ":material/add_circle: 신설 조문 검토",
    ":material/forum: 입법예고 의견 분석",
])

with tab1:
    stage1_draft.render(law_api_key, openai_api_key)

with tab2:
    stage2_crossref.render(law_api_key, openai_api_key)

with tab3:
    if ENABLE_HWPX_OUTPUT:
        stage3_output.render(law_api_key, openai_api_key)
    else:
        st.markdown('<div class="mofe-section-header">3단계: HWPX 출력</div>', unsafe_allow_html=True)
        st.info(
            "🛠️ HWPX 출력 기능은 베타 테스트 기간 동안 비활성화되어 있습니다. "
            "1·2단계와 신설 조문 검토 기능을 이용해 주세요. 정식 제공 시 안내드리겠습니다."
        )

with tab4:
    new_article_ui.render(law_api_key, openai_api_key)

with tab5:
    opinion_ui.render(law_api_key, openai_api_key)
