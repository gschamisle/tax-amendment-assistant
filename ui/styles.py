"""Premium UI design system — CSS injection only (no config.toml)."""
import streamlit as st


def inject_global_css() -> None:
    st.markdown("""
<style>
@import url('https://cdn.jsdelivr.net/npm/pretendard@latest/dist/web/static/pretendard.css');

/* ─── GLOBAL ─────────────────────────────────────────────────────────────── */
html, body, [class*="css"] {
    font-family: 'Pretendard', -apple-system, BlinkMacSystemFont, 'Segoe UI',
                 'Malgun Gothic', sans-serif !important;
}

/* ─── BACKGROUND ─────────────────────────────────────────────────────────── */
[data-testid="stAppViewContainer"],
[data-testid="stMain"] {
    background: linear-gradient(145deg, #f1f5f9 0%, #eaf0fb 55%, #f0f4ff 100%) !important;
}

.main .block-container {
    padding: 1.25rem 2.5rem 4rem 2.5rem;
    max-width: 1280px;
}

/* ─── HIDE STREAMLIT CHROME ──────────────────────────────────────────────── */
[data-testid="stHeader"] {
    background: transparent !important;
    border: none !important;
    height: 0 !important;
    min-height: 0 !important;
}
#MainMenu { visibility: hidden; }
footer { visibility: hidden; }
[data-testid="stToolbar"] { display: none !important; }
[data-testid="stDecoration"] { display: none !important; }

/* ─── APP HEADER CARD ────────────────────────────────────────────────────── */
.mofe-header-card {
    background: linear-gradient(135deg,
        rgba(255,255,255,0.97) 0%,
        rgba(248,252,255,0.92) 100%);
    backdrop-filter: blur(20px);
    -webkit-backdrop-filter: blur(20px);
    border: 1px solid rgba(226,232,240,0.85);
    border-radius: 24px;
    padding: 1.1rem 2rem;
    margin-bottom: 1.5rem;
    box-shadow: 0 4px 24px rgba(37,99,235,0.07), 0 1px 4px rgba(0,0,0,0.04);
    display: flex;
    align-items: center;
    gap: 1.25rem;
    animation: fadeInDown 0.45s ease;
}

.mofe-header-logo {
    width: 160px;
    height: auto;
    object-fit: contain;
    flex-shrink: 0;
    border-radius: 14px;
}

.mofe-app-title h1 {
    font-size: 1.55rem;
    font-weight: 700;
    color: #0f172a;
    margin: 0 0 3px 0;
    letter-spacing: -0.02em;
    line-height: 1.2;
}

.mofe-app-title p {
    font-size: 0.87rem;
    color: #64748b;
    margin: 0;
    font-weight: 400;
}

/* ─── SECTION HEADERS ────────────────────────────────────────────────────── */
.mofe-section-header {
    font-size: 1.3rem;
    font-weight: 700;
    color: #0f172a;
    padding: 0.25rem 0 0.75rem 0;
    border-bottom: 2px solid #e2e8f0;
    margin-bottom: 1.25rem;
    letter-spacing: -0.01em;
}

.mofe-subheader {
    font-size: 0.98rem;
    font-weight: 600;
    color: #1e40af;
    margin: 0.5rem 0 0.5rem 0;
}

/* ─── CARDS (st.container border=True) ───────────────────────────────────── */
[data-testid="stVerticalBlockBorderWrapper"] {
    background: #ffffff !important;
    border: 1px solid #e8edf5 !important;
    border-radius: 20px !important;
    box-shadow: 0 2px 12px rgba(0,0,0,0.048) !important;
    margin-bottom: 1rem !important;
    transition: box-shadow 0.25s ease !important;
    overflow: visible !important;
}

[data-testid="stVerticalBlockBorderWrapper"]:hover {
    box-shadow: 0 6px 28px rgba(37,99,235,0.09) !important;
}

[data-testid="stVerticalBlockBorderWrapper"] > div {
    padding: 1.4rem 1.75rem !important;
}

/* ─── TABS / STEPPER ─────────────────────────────────────────────────────── */
[data-testid="stTabs"] [data-baseweb="tab-list"] {
    background: #f1f5f9 !important;
    border-radius: 16px !important;
    padding: 5px !important;
    gap: 4px !important;
    border: 1px solid #e2e8f0 !important;
    margin-bottom: 1.5rem !important;
}

[data-testid="stTabs"] [data-baseweb="tab"] {
    background: transparent !important;
    border-radius: 12px !important;
    padding: 10px 22px !important;
    font-family: 'Pretendard', sans-serif !important;
    font-weight: 600 !important;
    font-size: 0.92rem !important;
    color: #64748b !important;
    border: none !important;
    transition: all 0.2s ease !important;
    flex: 1 !important;
    justify-content: center !important;
}

[data-testid="stTabs"] [data-baseweb="tab"]:hover {
    background: rgba(255,255,255,0.75) !important;
    color: #2563eb !important;
}

[data-testid="stTabs"] [aria-selected="true"] {
    background: linear-gradient(135deg, #2563eb 0%, #7c3aed 100%) !important;
    color: #ffffff !important;
    box-shadow: 0 4px 14px rgba(37,99,235,0.30) !important;
}

[data-testid="stTabs"] [data-baseweb="tab-highlight"],
[data-testid="stTabs"] [data-baseweb="tab-border"] {
    display: none !important;
}

/* ─── TEXT INPUTS ────────────────────────────────────────────────────────── */
.stTextInput input,
.stTextArea textarea,
.stNumberInput input {
    border: 1.5px solid #dde3ef !important;
    border-radius: 12px !important;
    padding: 10px 14px !important;
    font-family: 'Pretendard', sans-serif !important;
    font-size: 0.92rem !important;
    color: #0f172a !important;
    background: #f8fafc !important;
    transition: border-color 0.2s ease, box-shadow 0.2s ease, background 0.2s ease !important;
}

.stTextInput input:focus,
.stTextArea textarea:focus,
.stNumberInput input:focus {
    border-color: #2563eb !important;
    box-shadow: 0 0 0 3px rgba(37,99,235,0.11) !important;
    background: #ffffff !important;
    outline: none !important;
}

.stTextInput input::placeholder,
.stTextArea textarea::placeholder {
    color: #a0aec0 !important;
}

/* ─── SELECTBOX ──────────────────────────────────────────────────────────── */
.stSelectbox [data-baseweb="select"] > div:first-child {
    border: 1.5px solid #dde3ef !important;
    border-radius: 12px !important;
    background: #f8fafc !important;
    min-height: 42px !important;
    transition: border-color 0.2s ease, box-shadow 0.2s ease !important;
}

.stSelectbox [data-baseweb="select"] > div:first-child:focus-within {
    border-color: #2563eb !important;
    box-shadow: 0 0 0 3px rgba(37,99,235,0.11) !important;
}

/* ─── BUTTONS ────────────────────────────────────────────────────────────── */
.stButton > button {
    background: linear-gradient(135deg, #2563eb 0%, #1d4ed8 100%) !important;
    color: #ffffff !important;
    border: none !important;
    border-radius: 12px !important;
    padding: 10px 26px !important;
    font-family: 'Pretendard', sans-serif !important;
    font-weight: 600 !important;
    font-size: 0.92rem !important;
    transition: all 0.2s ease !important;
    box-shadow: 0 2px 8px rgba(37,99,235,0.22) !important;
    letter-spacing: 0.01em !important;
}

.stButton > button:hover {
    transform: translateY(-2px) !important;
    box-shadow: 0 6px 20px rgba(37,99,235,0.32) !important;
    background: linear-gradient(135deg, #1d4ed8 0%, #1e40af 100%) !important;
}

.stButton > button:active {
    transform: translateY(0) !important;
    box-shadow: 0 1px 5px rgba(37,99,235,0.18) !important;
}

.stFormSubmitButton > button {
    background: linear-gradient(135deg, #2563eb 0%, #1d4ed8 100%) !important;
    color: #ffffff !important;
    border: none !important;
    border-radius: 12px !important;
    padding: 10px 26px !important;
    font-family: 'Pretendard', sans-serif !important;
    font-weight: 600 !important;
    font-size: 0.92rem !important;
    transition: all 0.2s ease !important;
    box-shadow: 0 2px 8px rgba(37,99,235,0.22) !important;
    letter-spacing: 0.01em !important;
}

.stFormSubmitButton > button:hover {
    transform: translateY(-2px) !important;
    box-shadow: 0 6px 20px rgba(37,99,235,0.32) !important;
}

.stDownloadButton > button {
    background: #ffffff !important;
    color: #2563eb !important;
    border: 1.5px solid #2563eb !important;
    border-radius: 12px !important;
    padding: 10px 26px !important;
    font-family: 'Pretendard', sans-serif !important;
    font-weight: 600 !important;
    font-size: 0.92rem !important;
    transition: all 0.2s ease !important;
}

.stDownloadButton > button:hover {
    background: #eff6ff !important;
    transform: translateY(-2px) !important;
    box-shadow: 0 4px 14px rgba(37,99,235,0.18) !important;
}

/* ─── CHECKBOX ───────────────────────────────────────────────────────────── */
.stCheckbox label {
    font-family: 'Pretendard', sans-serif !important;
    font-size: 0.91rem !important;
    color: #334155 !important;
}

/* ─── EXPANDER ───────────────────────────────────────────────────────────── */
details[data-testid="stExpander"],
.streamlit-expander {
    border: 1px solid #e2e8f0 !important;
    border-radius: 14px !important;
    background: #fafbfe !important;
    margin-bottom: 8px !important;
    overflow: hidden !important;
}

details[data-testid="stExpander"] summary {
    font-family: 'Pretendard', sans-serif !important;
    font-weight: 600 !important;
    color: #334155 !important;
    font-size: 0.92rem !important;
    padding: 12px 16px !important;
}

/* ─── ALERTS ─────────────────────────────────────────────────────────────── */
[data-testid="stAlert"] > div {
    border-radius: 12px !important;
}

/* ─── DATAFRAME ──────────────────────────────────────────────────────────── */
[data-testid="stDataFrame"] {
    border-radius: 14px !important;
    overflow: hidden !important;
    border: 1px solid #e2e8f0 !important;
}

/* ─── CODE BLOCKS ────────────────────────────────────────────────────────── */
[data-testid="stCodeBlock"],
.stCodeBlock {
    border-radius: 12px !important;
    overflow: hidden !important;
}

pre {
    border-radius: 12px !important;
}

/* ─── CAPTION ────────────────────────────────────────────────────────────── */
[data-testid="stCaptionContainer"],
.stCaption {
    font-size: 0.83rem !important;
    color: #64748b !important;
}

/* ─── NUMBER INPUT ARROWS ────────────────────────────────────────────────── */
.stNumberInput [data-baseweb="input"] {
    border-radius: 12px !important;
}

/* ─── CUSTOM SCROLLBAR ───────────────────────────────────────────────────── */
::-webkit-scrollbar { width: 6px; height: 6px; }
::-webkit-scrollbar-track { background: #f1f5f9; border-radius: 6px; }
::-webkit-scrollbar-thumb { background: #cbd5e1; border-radius: 6px; }
::-webkit-scrollbar-thumb:hover { background: #94a3b8; }

/* ─── ANIMATIONS ─────────────────────────────────────────────────────────── */
@keyframes fadeInDown {
    from { opacity: 0; transform: translateY(-10px); }
    to   { opacity: 1; transform: translateY(0);     }
}

@keyframes fadeInUp {
    from { opacity: 0; transform: translateY(10px); }
    to   { opacity: 1; transform: translateY(0);    }
}

/* ─── TEXT CONTRAST (light mode base) ────────────────────────────────────── */
/* 위젯 라벨·라디오/체크박스·일반 마크다운 본문은 라이트 모드에서 어두운 글씨 */
[data-testid="stWidgetLabel"] p,
[data-testid="stWidgetLabel"] label,
.stRadio label, .stCheckbox label, [role="radiogroup"] label,
[data-testid="stMarkdownContainer"] > p,
[data-testid="stMarkdownContainer"] li {
    color: #1e293b !important;
}

/* ─── DARK MODE (시스템 다크모드 시 어두운 배경 + 밝은 글씨로 일관) ──────────── */
@media (prefers-color-scheme: dark) {
    [data-testid="stAppViewContainer"],
    [data-testid="stMain"] {
        background: linear-gradient(145deg, #0b1220 0%, #111a2e 55%, #0e1525 100%) !important;
    }
    .mofe-header-card {
        background: linear-gradient(135deg, rgba(30,41,59,0.97) 0%, rgba(15,23,42,0.94) 100%);
        border-color: rgba(51,65,85,0.85);
        box-shadow: 0 4px 24px rgba(0,0,0,0.45), 0 1px 4px rgba(0,0,0,0.3);
    }
    .mofe-app-title h1, .mofe-section-header { color: #f1f5f9 !important; }
    .mofe-app-title p { color: #94a3b8 !important; }
    .mofe-section-header { border-bottom-color: #334155 !important; }
    .mofe-subheader { color: #93c5fd !important; }

    [data-testid="stVerticalBlockBorderWrapper"] {
        background: #1e293b !important;
        border-color: #334155 !important;
        box-shadow: 0 2px 12px rgba(0,0,0,0.35) !important;
    }
    [data-testid="stVerticalBlockBorderWrapper"]:hover {
        box-shadow: 0 6px 28px rgba(0,0,0,0.45) !important;
    }

    [data-testid="stWidgetLabel"] p,
    [data-testid="stWidgetLabel"] label,
    .stRadio label, .stCheckbox label, [role="radiogroup"] label,
    [data-testid="stMarkdownContainer"] > p,
    [data-testid="stMarkdownContainer"] li,
    [data-testid="stMarkdownContainer"] strong {
        color: #e2e8f0 !important;
    }
    [data-testid="stCaptionContainer"], .stCaption { color: #94a3b8 !important; }

    .stTextInput input, .stTextArea textarea, .stNumberInput input {
        background: #0f172a !important;
        color: #f1f5f9 !important;
        border-color: #334155 !important;
    }
    .stTextInput input:focus, .stTextArea textarea:focus, .stNumberInput input:focus {
        background: #111a2e !important;
    }
    .stTextInput input::placeholder, .stTextArea textarea::placeholder { color: #64748b !important; }
    .stSelectbox [data-baseweb="select"] > div:first-child {
        background: #0f172a !important;
        border-color: #334155 !important;
    }

    [data-testid="stTabs"] [data-baseweb="tab-list"] {
        background: #1e293b !important;
        border-color: #334155 !important;
    }
    [data-testid="stTabs"] [data-baseweb="tab"] { color: #94a3b8 !important; }

    details[data-testid="stExpander"], .streamlit-expander {
        background: #1e293b !important;
        border-color: #334155 !important;
    }
    details[data-testid="stExpander"] summary { color: #e2e8f0 !important; }

    ::-webkit-scrollbar-track { background: #1e293b; }
    ::-webkit-scrollbar-thumb { background: #475569; }
    ::-webkit-scrollbar-thumb:hover { background: #64748b; }
}
</style>
""", unsafe_allow_html=True)
