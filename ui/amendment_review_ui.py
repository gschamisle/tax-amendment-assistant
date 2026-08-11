"""개정안 검토 탭 — 발표된 개정법률안에서 추가 개정이 필요한 조문을 잡는다.

두 검토를 한 화면에 둔다. 성격이 다르므로 결과도 다르게 읽어야 한다.

  ① 번호 밀림  — 기계적으로 확정되는 누락. '고쳐야 한다'
  ② 병행개정   — 판단이 필요한 후보.   '봐야 한다'

둘 다 LLM을 쓰지 않는다(사전 빌드된 인용 그래프·병행 매트릭스 조회).
"""
from __future__ import annotations

from pathlib import Path

import streamlit as st

from core import law_abbrev

ROOT = Path(__file__).resolve().parents[1]
_UPLOAD_DIR = ROOT / "data" / "uploads"
_SUPPORTED = ("pdf", "hwpx", "hwp", "md", "txt")


def _read_upload(uploaded) -> tuple[str, str]:
    """업로드 파일을 data/uploads(gitignore)에 저장하고 텍스트를 뽑는다."""
    from core.document_text import extract

    _UPLOAD_DIR.mkdir(parents=True, exist_ok=True)
    dest = _UPLOAD_DIR / uploaded.name
    dest.write_bytes(uploaded.getbuffer())
    return extract(dest), str(dest)


def _renumber_block(texts: list[tuple[str, str]]) -> None:
    from core.draft_bill_parser import find_amendment_body
    from core.pdf_bill_text import unwrap
    from core.renumber_scan import apply_batch_coverage, scan_renumber_omissions

    results = []
    for text, name in texts:
        law_name, body = find_amendment_body(unwrap(text))
        if not body:
            st.warning(f"{name} — 개정문 본문을 찾지 못했습니다.")
            continue
        r = scan_renumber_omissions(law_name, body)
        r["law_name"], r["path"] = law_name, name
        results.append(r)
    if not results:
        return
    apply_batch_coverage(results)

    miss = ("missing", "missing_other", "touched", "touched_other")
    total_missing = sum(1 for r in results for h in r["hits"] if h["상태"] in miss)
    total_events = sum(len(r["events"]) for r in results)
    st.metric("번호 이동", f"{total_events}건", delta=f"정비 누락 후보 {total_missing}건",
              delta_color="inverse" if total_missing else "off")

    for r in results:
        with st.container(border=True):
            st.markdown(f"**{r['law_name']}**")
            if not r["graph_covered"]:
                st.caption("인용 그래프 미수록 법령 — 역인용 대조 불가")
            if not r["events"]:
                st.caption("번호 이동 없음")
                continue
            for ev in r["events"]:
                st.markdown(f"- {ev.label()}")
            flagged = [h for h in r["hits"] if h["상태"] in miss]
            if not flagged:
                st.caption("이동 번호를 인용하는 조문 중 정비가 필요한 건 없습니다.")
            for h in flagged:
                st.error(
                    f"**{law_abbrev.law(h['법령명'])} "
                    f"{law_abbrev.jo_key(str(h['조번호']))}** {h['제목']}\n\n"
                    f"대상: {h['대상']} · 인용된 번호: {', '.join(h['영향번호'])}"
                )
                for raw in h["인용"][:3]:
                    st.code(raw, language=None)


def _parallel_block(texts: list[tuple[str, str]]) -> None:
    from core.parallel_omission import (
        group_by_source_article, laws_with_parallel_relations, load_bill, scan,
    )

    bills = [b for b in (load_bill(t, n) for t, n in texts) if b]
    if not bills:
        return
    result = scan(bills)
    if not result["matrix_ok"]:
        st.warning("병행 매트릭스가 없습니다 — `build_parallel_matrix.py` 실행 후 재시도.")
        return

    rows = result["rows"]
    cand = [r for r in rows if r["상태"] == "missing"]
    st.metric("병행 대응 관계", f"{len(rows)}건", delta=f"검토 후보 {len(cand)}건",
              delta_color="inverse" if cand else "off")

    outside = sorted({b.law_name for b in bills if b.law_name not in laws_with_parallel_relations()})
    if outside:
        st.caption(
            "병행 상대가 등록되지 않은 법령: " + ", ".join(law_abbrev.law(x) for x in outside)
            + " — 병행개정은 '같은 위계·같은 취지' 관계라 대응 상대가 없을 수 있습니다."
        )
    if not cand:
        st.success("대응 조문이 모두 함께 개정되었거나, 대조할 상대가 없습니다.")
        return

    st.caption(
        "관계는 매트릭스가 확정한 것이지만 **이번 개정 내용에도 대응이 필요한지는 판단**이 "
        "필요합니다. 지시문을 보면 대개 몇 초 만에 갈립니다."
    )
    for g in group_by_source_article(cand):
        with st.expander(
            f"{law_abbrev.law(g['법령명'])} {law_abbrev.jo_key(g['조번호'])} "
            f"— 대응 {len(g['대응'])}건", expanded=False,
        ):
            if g["개정지시문"]:
                st.markdown("**개정 지시문**")
                st.code(g["개정지시문"][:600], language=None)
            for m in g["대응"]:
                st.markdown(
                    f"- **{law_abbrev.law(m['대상법령'])} "
                    f"{law_abbrev.article(m['대상조문'])}** "
                    f"`{m['근거']}` — {m['사유'][:70]}"
                )


def render(law_api_key: str = "", openai_api_key: str = "") -> None:
    st.markdown('<div class="mofe-section-header">개정안 검토</div>', unsafe_allow_html=True)
    st.caption(
        "발표된 개정법률안을 넣으면 **추가 개정이 필요한 조문**을 찾습니다. "
        "여러 법안을 함께 올리면 법안 사이의 정비 여부까지 대조합니다. "
        "LLM을 쓰지 않아 결과가 매번 같습니다."
    )

    uploads = st.file_uploader(
        "개정법률안 파일 (여러 개 가능)", type=list(_SUPPORTED),
        accept_multiple_files=True, key="ar_files",
        help="입법예고된 '(법령안) ○○법 일부개정법률(안)' 파일. PDF·HWPX 모두 됩니다.",
    )
    if not uploads:
        st.info("검토할 개정법률안 파일을 올려 주세요.")
        return

    if st.button("검토 실행", type="primary", key="ar_run"):
        # PDF는 kordoc 변환을 거치므로 파일당 수 초 걸린다. 어디까지 됐는지 보여준다.
        from core.document_text import ExtractError

        texts: list[tuple[str, str]] = []
        progress = st.progress(0.0, text="파일 추출 중...")
        for i, u in enumerate(uploads, 1):
            progress.progress(i / len(uploads), text=f"추출 중 — {u.name}")
            try:
                texts.append(_read_upload(u))
            except ExtractError as exc:
                st.error(f"**{u.name}** — {exc}")
            except Exception as exc:                     # noqa: BLE001
                st.error(f"**{u.name}** — 읽는 중 오류: {exc}")
        progress.empty()
        if not texts:
            st.warning("읽어 들인 파일이 없습니다.")
            return
        st.session_state["ar_texts"] = texts

    texts = st.session_state.get("ar_texts")
    if not texts:
        return

    st.caption(f"업로드 파일은 `data/uploads/`(git 제외)에만 저장됩니다 · {len(texts)}건")
    t1, t2 = st.tabs([
        ":material/swap_vert: 번호 밀림 — 인용 정비 누락",
        ":material/compare_arrows: 병행개정 — 대응 조문 검토",
    ])
    with t1:
        st.caption("개정문이 항·호·목 번호를 밀면 그 번호를 인용하던 조문이 다른 규정을 가리킵니다. **기계적으로 확정되는 누락**입니다.")
        _renumber_block(texts)
    with t2:
        st.caption("한 법을 고쳤는데 대응 조문을 안 고친 경우입니다. **판단이 필요한 후보**입니다.")
        _parallel_block(texts)
