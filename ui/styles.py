"""디자인 시스템 — 레이아웃·밀도·표 서식 담당.

**색의 원천은 `.streamlit/config.toml`이다.** 탭 선택 표시나 위젯 강조색처럼
Streamlit이 내부 테마 클래스(`.st-bd` 등)로 직접 칠하는 부분은 CSS 주입으로 못 덮는다
(특이도를 올리고 !important를 붙여도 안 되는 지점이 있음 — 실측 확인).
그래서 팔레트는 네이티브 테마가 정하고, 여기서는 테마로 표현할 수 없는 것만 다룬다.
두 파일의 색값은 같은 팔레트다 — 한쪽만 바꾸면 어긋난다.

설계 방침:
  * **의미 토큰 우선** — 컴포넌트에 원시 hex를 박지 않고 `--c-*` 토큰만 참조한다
    (규칙 `color-semantic`).
  * **공공기관 톤** — 정부 업무용 도구다. 그라데이션·보라색 강조 같은 SaaS 마케팅
    어휘 대신 단색 남색을 쓴다. 상태색은 승인/주의/경고 3색으로 고정.
  * **높은 정보 밀도** — 조문·의견 목록을 다루는 실무 도구라 여백을 좁힌다
    (밀도 8/10, 간격 척도 4~32px).
  * **한글 우선 서체** — Pretendard. 라틴 전용 서체(EB Garamond 등)는 한글 글리프가
    없어 대체 폰트로 떨어지고 자간·굵기가 무너진다.
  * **접근성** — 포커스 링 상시 노출, 본문 대비 4.5:1 이상, prefers-reduced-motion 존중.
"""
import streamlit as st


def inject_global_css() -> None:
    st.markdown("""
<style>
@import url('https://cdn.jsdelivr.net/npm/pretendard@latest/dist/web/static/pretendard.css');

/* ─── 의미 토큰 ──────────────────────────────────────────────────────────── */
:root {
    --c-primary:        #1e40af;   /* 남색 — 정부 문서 톤 */
    --c-primary-hover:  #1b3a9e;
    --c-primary-weak:   #eef2ff;
    --c-on-primary:     #ffffff;
    --c-accent:         #15803d;   /* 완료·승인 */
    --c-warn:           #b45309;   /* 검토 필요 */
    --c-danger:         #b91c1c;   /* 누락·오류 */

    --c-bg:             #f6f8fb;
    --c-surface:        #ffffff;
    --c-surface-2:      #f8fafc;
    --c-border:         #d9e0ea;
    --c-border-strong:  #c3ccda;

    --c-text:           #0f172a;   /* 본문 — 흰 배경 대비 16:1 */
    --c-text-muted:     #52627a;   /* 보조 — 대비 7:1 (4.5:1 기준 충족) */
    --c-text-invert:    #ffffff;

    --c-ring:           rgba(30,64,175,0.32);

    /* 간격 척도 (밀도 8/10) */
    --s-1: 4px;  --s-2: 8px;  --s-3: 12px; --s-4: 16px;
    --s-5: 20px; --s-6: 24px; --s-8: 32px;

    --r-sm: 6px; --r-md: 8px; --r-lg: 12px;
    --shadow-1: 0 1px 2px rgba(15,23,42,0.06);
    --shadow-2: 0 2px 8px rgba(15,23,42,0.08);
    --dur: 160ms;
}

/* 다크 대응은 시스템 설정(prefers-color-scheme)이 아니라 Streamlit 테마를 따라야 한다.
   사용자가 메뉴에서 Light/Dark를 고르면 시스템 설정과 어긋나, 미디어쿼리로 토큰만
   뒤집으면 Streamlit 위젯은 밝고 배경만 어두운 잡종 화면이 된다(실측).
   지금은 config.toml에서 base="light"로 고정한다 — 문서 산출물과 톤을 맞추기 위함. */

/* ─── 기본 ───────────────────────────────────────────────────────────────── */
html, body, [class*="css"] {
    font-family: 'Pretendard', -apple-system, BlinkMacSystemFont, 'Segoe UI',
                 'Malgun Gothic', sans-serif !important;
}

[data-testid="stAppViewContainer"], [data-testid="stMain"] {
    background: var(--c-bg) !important;
}

.main .block-container {
    padding: var(--s-4) var(--s-8) var(--s-8) var(--s-8);
    max-width: 1400px;
}

/* 숫자 정렬 — 건수·비율 열이 자릿수마다 흔들리지 않게 (규칙 number-tabular) */
[data-testid="stTable"], [data-testid="stDataFrame"], [data-testid="stMetricValue"],
[data-testid="stMarkdownContainer"] table {
    font-variant-numeric: tabular-nums;
    font-feature-settings: "tnum";
}

/* ─── Streamlit 기본 크롬 정리 ───────────────────────────────────────────── */
[data-testid="stHeader"] {
    background: transparent !important;
    border: none !important;
    height: 0 !important;
    min-height: 0 !important;
}
#MainMenu, footer { visibility: hidden; }
[data-testid="stToolbar"], [data-testid="stDecoration"] { display: none !important; }

/* ─── 앱 헤더 ────────────────────────────────────────────────────────────── */
.mofe-header-card {
    background: var(--c-surface);
    border: 1px solid var(--c-border);
    border-left: 4px solid var(--c-primary);
    border-radius: var(--r-md);
    padding: var(--s-4) var(--s-6);
    margin-bottom: var(--s-5);
    box-shadow: var(--shadow-1);
    display: flex;
    align-items: center;
    gap: var(--s-5);
}

.mofe-header-logo { width: 132px; height: auto; object-fit: contain; flex-shrink: 0; }

.mofe-app-title h1 {
    font-size: 1.35rem;
    font-weight: 700;
    color: var(--c-text);
    margin: 0;
    letter-spacing: -0.02em;
    line-height: 1.25;
}
.mofe-app-title p {
    font-size: 0.85rem;
    color: var(--c-text-muted);
    margin: 2px 0 0 0;
}

/* ─── 섹션 제목 ──────────────────────────────────────────────────────────── */
.mofe-section-header {
    font-size: 1.12rem;
    font-weight: 700;
    color: var(--c-text);
    padding-bottom: var(--s-2);
    border-bottom: 1px solid var(--c-border);
    margin-bottom: var(--s-4);
    letter-spacing: -0.01em;
}
.mofe-subheader {
    font-size: 0.94rem;
    font-weight: 600;
    color: var(--c-primary);
    margin: var(--s-3) 0 var(--s-2) 0;
}

/* ─── 카드 ───────────────────────────────────────────────────────────────── */
[data-testid="stVerticalBlockBorderWrapper"] {
    background: var(--c-surface) !important;
    border: 1px solid var(--c-border) !important;
    border-radius: var(--r-md) !important;
    box-shadow: var(--shadow-1) !important;
    margin-bottom: var(--s-3) !important;
}
[data-testid="stVerticalBlockBorderWrapper"] > div { padding: var(--s-4) var(--s-5) !important; }

/* ─── 탭 ─────────────────────────────────────────────────────────────────── */
/* 셀렉터는 Streamlit의 data-testid(stTabs·stTab)를 쓴다. BaseWeb 내부 속성
   (data-baseweb="tab")은 버전마다 바뀌고 특이도가 낮아 기본 스타일에 진다. */
[data-testid="stTabs"] [data-baseweb="tab-list"] {
    background: transparent !important;
    border-bottom: 1px solid var(--c-border) !important;
    gap: var(--s-1) !important;
    padding: 0 !important;
    margin-bottom: var(--s-5) !important;
    overflow-x: auto !important;
    scrollbar-width: thin;
}
/* 탭이 5개면 flex:1 균등분할은 라벨을 뭉갠다 — 내용 폭 + 가로 스크롤로 둔다 */
[data-testid="stTabs"] button[data-testid="stTab"] {
    background: transparent !important;
    border: 0 !important;
    border-bottom: 2px solid transparent !important;
    border-radius: 0 !important;
    padding: var(--s-3) var(--s-4) !important;
    font-weight: 600 !important;
    font-size: 0.9rem !important;
    color: var(--c-text-muted) !important;
    white-space: nowrap !important;
    flex: 0 0 auto !important;
    transition: color var(--dur) ease, border-color var(--dur) ease !important;
}
[data-testid="stTabs"] button[data-testid="stTab"]:hover {
    color: var(--c-primary) !important;
    background: var(--c-primary-weak) !important;
}
[data-testid="stTabs"] button[data-testid="stTab"][aria-selected="true"] {
    color: var(--c-primary) !important;
    border-bottom-color: var(--c-primary) !important;
    background: transparent !important;
}
[data-testid="stTabs"] [data-baseweb="tab-highlight"],
[data-testid="stTabs"] [data-baseweb="tab-border"] { display: none !important; }

/* ─── 입력 ───────────────────────────────────────────────────────────────── */
.stTextInput input, .stTextArea textarea, .stNumberInput input {
    border: 1px solid var(--c-border-strong) !important;
    border-radius: var(--r-sm) !important;
    padding: 8px 12px !important;
    font-size: 0.9rem !important;
    color: var(--c-text) !important;
    background: var(--c-surface) !important;
    transition: border-color var(--dur) ease, box-shadow var(--dur) ease !important;
}
.stTextInput input:focus, .stTextArea textarea:focus, .stNumberInput input:focus {
    border-color: var(--c-primary) !important;
    box-shadow: 0 0 0 3px var(--c-ring) !important;
    outline: none !important;
}
.stTextInput input::placeholder, .stTextArea textarea::placeholder { color: var(--c-text-muted) !important; }

.stSelectbox [data-baseweb="select"] > div:first-child {
    border: 1px solid var(--c-border-strong) !important;
    border-radius: var(--r-sm) !important;
    background: var(--c-surface) !important;
    min-height: 40px !important;
}
.stSelectbox [data-baseweb="select"] > div:first-child:focus-within {
    border-color: var(--c-primary) !important;
    box-shadow: 0 0 0 3px var(--c-ring) !important;
}

/* ─── 버튼 ───────────────────────────────────────────────────────────────── */
/* 툴팁이 붙은 버튼은 .stButton > button 이 아니라 span 두 겹 안에 들어간다.
   자식 선택자 대신 testid로 버튼 자체를 잡는다. */
button[data-testid="stBaseButton-secondary"],
button[data-testid="stBaseButton-primary"],
button[data-testid="stBaseButton-secondaryFormSubmit"],
[data-testid="stDownloadButton"] button {
    border-radius: var(--r-sm) !important;
    padding: 9px 18px !important;
    min-height: 40px !important;
    font-weight: 600 !important;
    font-size: 0.9rem !important;
    transition: background var(--dur) ease, border-color var(--dur) ease !important;
    box-shadow: none !important;
}
/* 보조 동작 — 외곽선 버튼. hover에서 위치를 옮기지 않는다(레이아웃 흔들림 방지) */
button[data-testid="stBaseButton-secondary"],
button[data-testid="stBaseButton-secondaryFormSubmit"] {
    background: var(--c-surface) !important;
    color: var(--c-primary) !important;
    border: 1px solid var(--c-border-strong) !important;
}
button[data-testid="stBaseButton-secondary"]:hover,
button[data-testid="stBaseButton-secondaryFormSubmit"]:hover {
    background: var(--c-primary-weak) !important;
    border-color: var(--c-primary) !important;
}
/* 주 동작(type="primary")만 채운 버튼 — 화면당 주 CTA 하나 (규칙 primary-action) */
button[data-testid="stBaseButton-primary"] {
    background: var(--c-primary) !important;
    color: var(--c-on-primary) !important;
    border: 1px solid var(--c-primary) !important;
}
button[data-testid="stBaseButton-primary"]:hover {
    background: var(--c-primary-hover) !important;
    border-color: var(--c-primary-hover) !important;
}
[data-testid="stDownloadButton"] button {
    background: var(--c-surface) !important;
    color: var(--c-primary) !important;
    border: 1px solid var(--c-primary) !important;
}
[data-testid="stDownloadButton"] button:hover { background: var(--c-primary-weak) !important; }

/* 키보드 포커스 링 — 접근성 필수. 마우스 클릭에는 안 뜨게 :focus-visible */
button[data-testid^="stBaseButton"]:focus-visible,
[data-testid="stDownloadButton"] button:focus-visible,
[data-testid="stTabs"] button[data-testid="stTab"]:focus-visible,
details[data-testid="stExpander"] summary:focus-visible {
    outline: 2px solid var(--c-primary) !important;
    outline-offset: 2px !important;
}

/* 버튼 안 텍스트가 마크다운 색 규칙에 덮이지 않게 */
button[data-testid^="stBaseButton"] p, button[data-testid^="stBaseButton"] span,
button[data-testid^="stBaseButton"] div,
[data-testid="stDownloadButton"] button p, [data-testid="stDownloadButton"] button span,
[data-testid="stDownloadButton"] button div {
    color: inherit !important;
}

/* ─── 확장 패널 ──────────────────────────────────────────────────────────── */
details[data-testid="stExpander"], .streamlit-expander {
    border: 1px solid var(--c-border) !important;
    border-radius: var(--r-sm) !important;
    background: var(--c-surface) !important;
    margin-bottom: var(--s-2) !important;
}
details[data-testid="stExpander"] summary {
    font-weight: 600 !important;
    color: var(--c-text) !important;
    font-size: 0.9rem !important;
    padding: 10px var(--s-4) !important;
}

/* ─── 알림 — 색만으로 뜻을 전하지 않도록 좌측 색띠 추가 ──────────────────── */
[data-testid="stAlert"] > div {
    border-radius: var(--r-sm) !important;
    border-left: 3px solid currentColor !important;
}

/* ─── 표 ─────────────────────────────────────────────────────────────────── */
[data-testid="stDataFrame"], [data-testid="stTable"] {
    border-radius: var(--r-sm) !important;
    overflow: hidden !important;
    border: 1px solid var(--c-border) !important;
}
[data-testid="stMarkdownContainer"] table {
    border-collapse: collapse !important;
    width: 100% !important;
    font-size: 0.88rem !important;
}
[data-testid="stMarkdownContainer"] th {
    background: var(--c-surface-2) !important;
    color: var(--c-text) !important;
    font-weight: 600 !important;
    text-align: left !important;
    border-bottom: 1px solid var(--c-border-strong) !important;
    padding: 8px 10px !important;
}
[data-testid="stMarkdownContainer"] td {
    border-bottom: 1px solid var(--c-border) !important;
    padding: 7px 10px !important;
    vertical-align: top !important;
}

/* ─── 코드·캡션 ──────────────────────────────────────────────────────────── */
[data-testid="stCodeBlock"], .stCodeBlock, pre { border-radius: var(--r-sm) !important; }
[data-testid="stCaptionContainer"], .stCaption {
    font-size: 0.82rem !important;
    color: var(--c-text-muted) !important;
}

/* ─── 본문 색 ────────────────────────────────────────────────────────────── */
[data-testid="stWidgetLabel"] p, [data-testid="stWidgetLabel"] label,
.stRadio label, .stCheckbox label, [role="radiogroup"] label,
[data-testid="stMarkdownContainer"] > p, [data-testid="stMarkdownContainer"] li,
[data-testid="stMarkdownContainer"] strong, [data-testid="stMarkdownContainer"] td,
[data-testid="stMarkdownContainer"] h1, [data-testid="stMarkdownContainer"] h2,
[data-testid="stMarkdownContainer"] h3, [data-testid="stMarkdownContainer"] h4 {
    color: var(--c-text) !important;
}
[data-testid="stMarkdownContainer"] blockquote {
    border-left: 3px solid var(--c-border-strong) !important;
    color: var(--c-text-muted) !important;
    padding-left: var(--s-3) !important;
    margin-left: 0 !important;
}

/* ─── 스크롤바 ───────────────────────────────────────────────────────────── */
::-webkit-scrollbar { width: 10px; height: 10px; }
::-webkit-scrollbar-track { background: transparent; }
::-webkit-scrollbar-thumb { background: var(--c-border-strong); border-radius: 5px; }

/* ─── 모션 축소 존중 ─────────────────────────────────────────────────────── */
@media (prefers-reduced-motion: reduce) {
    *, *::before, *::after {
        animation-duration: 0.01ms !important;
        animation-iteration-count: 1 !important;
        transition-duration: 0.01ms !important;
    }
}
</style>
""", unsafe_allow_html=True)
