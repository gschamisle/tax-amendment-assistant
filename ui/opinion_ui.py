"""입법예고 의견 분석 탭 — 수집 → 군집화 → 리포트 → HWPX.

파이프라인은 CLI(`scripts/fetch_opinions.py`·`analyze_opinions.py`)와 **같은 코드**를 쓴다.
UI는 입력을 받아 그 진입점을 부르고 산출물을 보여주는 얇은 층이다 — 로직을 옮겨 적으면
CLI와 화면이 따로 놀기 시작한다.

수집 원문은 data/opinions/(gitignore)에만 저장된다. 작성자 실명은 수집 시점에 마스킹되어
어떤 산출물에도 남지 않는다.
"""
from __future__ import annotations

import io
import re
import subprocess
import sys
from pathlib import Path

import streamlit as st

from core.opinion_source import cache_path, fetch_opinions, load_records, load_selectors

ROOT = Path(__file__).resolve().parents[1]
OUT_DIR = ROOT / "output"

# 입법예고 ID는 URL 경로에 있다: …/gcom/ogLmPp/<ID>/myOpn?…
_BILL_IN_URL_RE = re.compile(r"/ogLmPp/(\d+)")


def parse_bill_id(text: str) -> str:
    """입력에서 입법예고 ID를 뽑는다. URL 전체를 붙여넣어도 되고 ID만 써도 된다."""
    raw = str(text).strip()
    m = _BILL_IN_URL_RE.search(raw)
    if m:
        return m.group(1)
    digits = raw.strip("/ ").split("?")[0].split("/")[-1]
    return digits if digits.isdigit() else ""


def _outputs(bill: str) -> dict[str, Path]:
    return {
        "md": OUT_DIR / f"opinions-{bill}.md",
        "clusters": OUT_DIR / f"opinions-{bill}-clusters.csv",
        "members": OUT_DIR / f"opinions-{bill}-members.csv",
        "hwpx": OUT_DIR / f"opinions-{bill}.hwpx",
    }


def _collect(bill: str, incremental: bool, max_pages: int) -> None:
    from core.opinion_source import dedupe_records, save_records
    from datetime import datetime

    previous = load_records(bill) if (incremental and cache_path(bill).exists()) else []
    status = st.empty()
    if previous:
        status.info(f"기존 수집분 {len(previous):,}건 — 새 의견만 받아옵니다.")

    def on_page(page: int, fresh: int, total: int) -> None:
        status.info(f"{page}페이지 수집 중 — 새 의견 {total:,}건")

    report = fetch_opinions(
        bill,
        max_pages=max_pages,
        selectors=load_selectors(),
        on_page=on_page,
        known=previous,
    )
    records = dedupe_records(previous + report.records) if previous else report.records
    if not records:
        status.error("수집된 의견이 0건입니다. 입법예고 ID와 셀렉터를 확인하세요.")
        return

    save_records(
        bill, records,
        meta={
            "collected_at": datetime.now().isoformat(timespec="seconds"),
            "source": f"http:{report.pages_fetched}pages",
        },
    )
    status.empty()
    st.success(
        f"새 의견 {len(report.records):,}건 · 누적 {len(records):,}건 "
        f"({report.pages_fetched}페이지 조회)"
    )
    if report.stopped_reason:
        st.caption(f"중단 사유: {report.stopped_reason}")
    for warning in report.warnings:
        st.warning(warning)


def _analyze(bill: str, law: str, top: int, use_llm: bool) -> None:
    from scripts.analyze_opinions import main as analyze_main

    argv = ["--bill", bill, "--law", law, "--top", str(top), "--out", str(OUT_DIR)]
    if not use_llm:
        argv.append("--no-llm")

    buf = io.StringIO()
    stdout, sys.stdout = sys.stdout, buf
    try:
        code = analyze_main(argv)
    finally:
        sys.stdout = stdout
    if code != 0:
        st.error("분석에 실패했습니다.")
        st.code(buf.getvalue() or "(출력 없음)")
        return
    st.success("분석 완료")
    with st.expander("실행 로그"):
        st.code(buf.getvalue())


def _make_hwpx(bill: str, preset: str) -> None:
    from scripts.opinions_md_to_hwpx import transform

    paths = _outputs(bill)
    staged = paths["md"].with_name(f"{paths['md'].stem}-hwpx소스.md")
    staged.write_text(transform(paths["md"].read_text(encoding="utf-8")), encoding="utf-8")

    for cmd in (
        ["npx", "-y", "kordoc@^4", "generate", str(staged), "-o", str(paths["hwpx"]),
         "--preset", preset],
        ["npx", "-y", "kordoc@^4", "validate", str(paths["hwpx"])],
    ):
        done = subprocess.run(
            cmd, cwd=ROOT, capture_output=True, text=True,
            shell=(sys.platform == "win32"),
        )
        if done.returncode != 0:
            st.error("HWPX 생성·검증에 실패했습니다.")
            st.code((done.stdout or "") + (done.stderr or ""))
            return
    st.success("HWPX 생성 완료 (구조 검증 통과)")


def _downloads(bill: str) -> None:
    paths = _outputs(bill)
    cols = st.columns(4)
    labels = {
        "md": ("리포트 (Markdown)", "text/markdown"),
        "hwpx": ("리포트 (HWPX)", "application/octet-stream"),
        "clusters": ("군집 요약 (CSV)", "text/csv"),
        "members": ("전 건 소속 (CSV)", "text/csv"),
    }
    for col, key in zip(cols, ("md", "hwpx", "clusters", "members")):
        path = paths[key]
        label, mime = labels[key]
        with col:
            if path.is_file():
                st.download_button(
                    label, data=path.read_bytes(), file_name=path.name,
                    mime=mime, key=f"op_dl_{key}", width="stretch",
                )
            else:
                st.caption(f"{label} — 없음")


def render(law_api_key: str = "", openai_api_key: str = "") -> None:
    st.markdown('<div class="mofe-section-header">입법예고 의견 분석</div>', unsafe_allow_html=True)
    st.caption(
        "국민참여입법센터에 제출된 입법의견을 유사 내용끼리 묶어 상위 쟁점을 정리합니다. "
        "군집·건수는 규칙과 유사도로 결정되고, Claude는 상위 군집의 문장 정리에만 관여합니다."
    )

    raw_bill = st.text_input(
        "입법예고 주소 또는 ID", key="op_bill",
        placeholder="https://opinion.lawmaking.go.kr/gcom/ogLmPp/87936/myOpn?…  (또는 87936)",
        help="국민참여입법센터의 해당 입법예고 '입법의견' 화면 주소를 그대로 붙여넣으세요. "
             "세법에 한정되지 않고 어떤 입법예고든 됩니다.",
    )
    col2, col3 = st.columns([2.6, 1])
    law = col2.text_input(
        "법령명", key="op_law", placeholder="예: 소득세법",
        help="관련 조문·쟁점 태깅에 쓰입니다. 비워도 군집화·건수는 그대로 나옵니다.",
    )
    top = col3.number_input("상위 군집 수", 5, 50, 20, key="op_top")

    bill = parse_bill_id(raw_bill)
    if not bill:
        if str(raw_bill).strip():
            st.error("주소에서 입법예고 ID를 찾지 못했습니다 — `/ogLmPp/<숫자>/` 형태가 포함돼야 합니다.")
        else:
            st.info("분석할 입법예고의 '입법의견' 화면 주소를 붙여넣으세요.")
        return
    st.caption(f"입법예고 ID `{bill}`")

    cached = cache_path(bill)
    if cached.is_file():
        try:
            st.info(f"수집된 의견 {len(load_records(bill)):,}건 (`{cached.relative_to(ROOT)}`)")
        except Exception:
            st.warning("수집 파일을 읽지 못했습니다. 다시 수집하세요.")

    st.divider()

    # ── 1) 수집 ──────────────────────────────────────────────────────────────
    st.markdown("**① 의견 수집**")
    c1, c2, c3 = st.columns([1.2, 1, 1.4])
    incremental = c1.checkbox("증분 수집", value=True, key="op_inc",
                              help="이미 가진 의견은 건너뛰고 새로 올라온 것만 받습니다. "
                                   "접수기간 중 반복 실행에 씁니다.")
    max_pages = c2.number_input("최대 페이지", 1, 500, 200, key="op_pages")
    if c3.button("의견 수집", key="op_fetch", type="primary", width="stretch"):
        with st.spinner("국민참여입법센터에서 의견을 받아오는 중..."):
            try:
                _collect(bill, incremental, int(max_pages))
            except Exception as exc:
                st.error(f"수집 실패: {exc}")

    # ── 2) 분석 ──────────────────────────────────────────────────────────────
    st.markdown("**② 군집 분석**")
    c1, c2 = st.columns([1.2, 2.2])
    use_llm = c1.checkbox("Claude 요약", value=True, key="op_llm",
                          help="끄면 API 키 없이 결정적 라벨로만 리포트를 만듭니다. "
                               "건수·비율은 어느 쪽이든 같습니다.")
    if c2.button("분석 실행", key="op_analyze", type="primary", width="stretch"):
        if not cached.is_file():
            st.error("먼저 의견을 수집하세요.")
        else:
            with st.spinner("군집화 중... (Claude 요약을 켜면 몇 분 걸립니다)"):
                _analyze(bill, str(law).strip(), int(top), use_llm)

    # ── 3) 결과 ──────────────────────────────────────────────────────────────
    paths = _outputs(bill)
    if not paths["md"].is_file():
        st.caption("분석을 실행하면 결과가 여기 표시됩니다.")
        return

    st.divider()
    st.markdown("**③ 결과**")
    report_md = paths["md"].read_text(encoding="utf-8")
    with st.expander("리포트 미리보기", expanded=True):
        st.markdown(report_md)

    c1, c2 = st.columns([1.2, 2.2])
    preset = c1.selectbox("HWPX 서식", ["보고서", "기안문", "계획서", "개조식"], key="op_preset")
    if c2.button("HWPX 생성", key="op_hwpx", width="stretch"):
        with st.spinner("HWPX 생성·구조 검증 중..."):
            try:
                _make_hwpx(bill, preset)
            except Exception as exc:
                st.error(f"HWPX 생성 실패: {exc}")

    _downloads(bill)
