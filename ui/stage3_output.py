"""Stage 3: HWPX 출력 및 다운로드."""
import os
import re
import streamlit as st
from core.hwpx_writer import build_comparison_table, _patch_font_in_hwpx
from core.law_api import get_law_text
from core.article_comparison_format import format_compressed_hang_label
from hwpx.document import HwpxDocument

_HANG_RE = re.compile(r"^[①②③④⑤⑥⑦⑧⑨⑩⑪⑫⑬⑭⑮⑯⑰⑱⑲⑳]")
_HANG_SYMBOL_RE = re.compile(r"^([①②③④⑤⑥⑦⑧⑨⑩⑪⑫⑬⑭⑮⑯⑰⑱⑲⑳])")
_HANG_SYMS = "①②③④⑤⑥⑦⑧⑨⑩⑪⑫⑬⑭⑮⑯⑰⑱⑲⑳"
_JO_RE = re.compile(r"제(?:(\d+)의(\d+)조|(\d+)조(?:의(\d+))?)")
# 조 제목 뒤에 ① 이 붙어있는 패턴: "제N조(제목) ①..."
_INLINE_HANG_RE = re.compile(
    r"(제\d+조(?:의\d+)?[^①②③④⑤⑥⑦⑧⑨⑩⑪⑫⑬⑭⑮⑯⑰⑱⑲⑳]*)"
    r"([①②③④⑤⑥⑦⑧⑨⑩⑪⑫⑬⑭⑮⑯⑰⑱⑲⑳])"
)


def _clean_article_ref_for_law(law_name: str, jo_ref: str) -> str:
    ref = str(jo_ref).strip()
    if law_name and ref.startswith(law_name):
        ref = ref[len(law_name):].strip()
    return ref


def _split_by_hang(text: str) -> list[str]:
    """항(①②③...) 시작 기준으로 텍스트를 청크 분리.

    법령 API가 "제N조(제목) ①..." 형태로 한 줄 반환할 때
    ① 앞에서 줄바꿈을 삽입해 조 제목과 ①항을 분리한다.
    """
    # 전처리: 조 제목 뒤 인라인 ① 분리
    lines_pre: list[str] = []
    for line in text.splitlines():
        if not _HANG_RE.match(line.lstrip()):
            m = _INLINE_HANG_RE.search(line)
            if m:
                lines_pre.append(line[:m.start(2)].rstrip())
                lines_pre.append(line[m.start(2):])
                continue
        lines_pre.append(line)

    chunks: list[str] = []
    buf: list[str] = []
    for line in lines_pre:
        if _HANG_RE.match(line.lstrip()) and buf:
            chunks.append("\n".join(buf))
            buf = [line]
        else:
            buf.append(line)
    if buf:
        chunks.append("\n".join(buf))
    return [c for c in chunks if c.strip()]


def _is_unchanged(left: str, right: str) -> bool:
    """right에 <u> 없고 '(현행과같음)' 포함이면 미변경."""
    if "<u>" in right or "(현행과같음)" not in right:
        return False
    return "(생략)" in left and "<del>" not in left


def _extract_hang_sym(chunk: str) -> str | None:
    m = _HANG_SYMBOL_RE.match(chunk.lstrip())
    return m.group(1) if m else None


def _dedup_hang_chunks(chunks: list[str]) -> list[str]:
    """같은 항 기호 중복 시 <del>/<u> 있는 것 우선, 없으면 선행 유지."""
    result: list[str] = []
    sym_idx: dict[str, int] = {}
    for chunk in chunks:
        sym = _extract_hang_sym(chunk)
        if sym is None:
            result.append(chunk)
            continue
        if sym not in sym_idx:
            sym_idx[sym] = len(result)
            result.append(chunk)
        else:
            prev = result[sym_idx[sym]]
            if ("<del>" in chunk or "<u>" in chunk) and not ("<del>" in prev or "<u>" in prev):
                result[sym_idx[sym]] = chunk
    return result


def _compress_unchanged_chunks(
    pairs: list[tuple[str, str]],
) -> list[tuple[str, str]]:
    """연속된 미변경 항을 ①·②(생략)|①~④(현행과같음) 형식으로 압축."""
    result: list[tuple[str, str]] = []
    i = 0
    while i < len(pairs):
        left, right = pairs[i]
        if not _is_unchanged(left, right):
            result.append((left, right))
            i += 1
            continue
        j = i
        syms: list[str] = []
        while j < len(pairs) and _is_unchanged(pairs[j][0], pairs[j][1]):
            sym = _extract_hang_sym(pairs[j][0])
            if sym:
                syms.append(sym)
            j += 1
        if syms:
            result.append((
                format_compressed_hang_label(syms, "(생략)"),
                format_compressed_hang_label(syms, "(현행과같음)"),
            ))
        else:
            result.extend(pairs[i:j])
        i = j
    return result


def _build_comparison_rows(current: str, amended: str) -> list[tuple[str, str]]:
    """현행/개정안 텍스트 → (현행 셀, 개정안 셀) 행 목록."""
    rows: list[tuple[str, str]] = [("현  행", "개  정  안")]

    c_chunks = _dedup_hang_chunks(_split_by_hang(current))
    a_chunks = _dedup_hang_chunks(_split_by_hang(amended))

    if not c_chunks and not a_chunks:
        rows.append((current.strip(), amended.strip()))
        return rows

    # 헤더(조 제목) 청크 — 항 기호 없는 것
    c_hdrs = [c for c in c_chunks if _extract_hang_sym(c) is None]
    a_hdrs = [c for c in a_chunks if _extract_hang_sym(c) is None]
    c_sym_map = {_extract_hang_sym(c): c for c in c_chunks if _extract_hang_sym(c) is not None}
    a_sym_map = {_extract_hang_sym(c): c for c in a_chunks if _extract_hang_sym(c) is not None}

    data_pairs: list[tuple[str, str]] = []

    # 헤더: 인덱스 기반 (조 제목은 동일 구조)
    for i in range(max(len(c_hdrs), len(a_hdrs))):
        data_pairs.append((
            c_hdrs[i] if i < len(c_hdrs) else "",
            a_hdrs[i] if i < len(a_hdrs) else "",
        ))

    # 항 청크: 기호 기반 정렬
    all_syms = sorted(
        c_sym_map.keys() | a_sym_map.keys(),
        key=lambda s: _HANG_SYMS.index(s) if s in _HANG_SYMS else 99,
    )
    for sym in all_syms:
        left = c_sym_map.get(sym, "")
        right = a_sym_map.get(sym, f"{sym}(현행과같음)")
        data_pairs.append((left, right))

    compressed = _compress_unchanged_chunks(data_pairs)
    return rows + compressed


def _fetch_parallel_article(entry: dict, law_api_key: str, openai_api_key: str) -> str | None:
    """병행 법령 조문 텍스트 조회. 실패 시 None."""
    try:
        data = get_law_text(entry["MST"], law_api_key, openai_api_key)
        articles = data.get("조문목록", [])
        m = _JO_RE.search(entry.get("조문", ""))
        if not m:
            return None
        if m.group(1) is not None:
            jo_num = m.group(1)
            jo_suffix = m.group(2) or ""
        else:
            jo_num = m.group(3)
            jo_suffix = m.group(4) or ""
        target = f"{jo_num}의{jo_suffix}" if jo_suffix else jo_num
        # 조번호 정확 매칭 (제33조의2 ≠ 제33조)
        for a in articles:
            a_jo = str(a.get("조번호", ""))
            if a_jo == target or (not jo_suffix and a_jo == jo_num):
                return a.get("내용", "")
    except Exception:
        pass
    return None


def _amendment_title(law_name: str) -> str:
    """법률은 일부개정법률(안), 시행령ㆍ시행규칙은 일부개정령(안)으로 표시한다."""
    suffix = "일부개정령(안)" if ("시행령" in law_name or "시행규칙" in law_name) else "일부개정법률(안)"
    return f"{law_name} {suffix}"


def render(law_api_key: str, openai_api_key: str) -> None:
    st.markdown('<div class="mofe-section-header">3단계: HWPX 출력</div>', unsafe_allow_html=True)

    if "s1_sections" not in st.session_state:
        st.info("1단계에서 먼저 초안을 생성하세요.")
        return

    law_name = st.session_state.get("final_law_name", "법령")
    instruction = st.session_state.get("final_instruction", "")
    current_text = st.session_state.get("final_current", "")
    amended_text = st.session_state.get("final_amended", "")
    buchik = st.session_state.get("final_buchik", "")
    title = _amendment_title(law_name)

    # ── 메인 미리보기 ──────────────────────────────────────────────────────
    with st.container(border=True):
        st.markdown('<div class="mofe-subheader">개정지시문 미리보기</div>', unsafe_allow_html=True)
        st.code(instruction, language="")

    with st.container(border=True):
        st.markdown('<div class="mofe-subheader">신·구조문대비표 미리보기</div>', unsafe_allow_html=True)
        rows = _build_comparison_rows(current_text, amended_text)
        if len(rows) > 1:
            preview_data = [{"현 행": r[0], "개 정 안": r[1]} for r in rows[1:]]
            st.dataframe(preview_data, use_container_width=True)

    with st.container(border=True):
        st.markdown('<div class="mofe-subheader">부칙 미리보기</div>', unsafe_allow_html=True)
        st.code(buchik, language="")

    # ── 병행 법령 미리보기 (Stage 1에서 생성한 결과 표시) ──────────────────
    parallel_sections: list[dict] = st.session_state.get("s3_parallel_sections", [])

    if parallel_sections:
        with st.container(border=True):
            st.markdown('<div class="mofe-subheader">병행 법령 개정 초안 (Stage 1에서 생성)</div>', unsafe_allow_html=True)
            for ps in parallel_sections:
                ps_ref = _clean_article_ref_for_law(ps["법령명"], ps["조문"])
                with st.expander(f"{ps['법령명']} {ps_ref}"):
                    st.markdown("**개정지시문**")
                    st.code(ps["instruction"], language="")
                    st.markdown("**신·구조문대비표**")
                    if len(ps["rows"]) > 1:
                        st.dataframe(
                            [{"현 행": r[0], "개 정 안": r[1]} for r in ps["rows"][1:]],
                            use_container_width=True,
                        )
                    st.markdown("**부칙**")
                    st.code(ps["buchik"], language="")

    # ── HWPX 생성 ─────────────────────────────────────────────────────────
    with st.container(border=True):
        st.markdown('<div class="mofe-subheader">HWPX 파일 생성</div>', unsafe_allow_html=True)

        pending_jobs = [
            j for j in st.session_state.get("s1_amendment_queue", [])
            if j.get("status") in ("pending", "active")
        ]
        review_queue_raw = st.session_state.get("s1_review_queue", [])
        reviewed_ids = set(st.session_state.get("s1_reviewed_ids", []))
        pending_required = [
            d for d in review_queue_raw
            if d.get("tier") == "required"
            and d.get("candidate_id") not in reviewed_ids
            and d.get("law_name")
            and d.get("article_ref")
        ]
        hwpx_blockers = bool(pending_jobs or pending_required)
        hwpx_ack = False
        if hwpx_blockers:
            parts: list[str] = []
            if pending_required:
                parts.append(f"필수 연쇄 검토 미완료 {len(pending_required)}건")
            if pending_jobs:
                parts.append(f"연쇄 개정 큐 미처리 {len(pending_jobs)}건")
            st.warning("⚠️ " + " · ".join(parts) + " — HWPX 생성 전 확인이 필요합니다.")
            hwpx_ack = st.checkbox(
                "필수 연쇄 검토를 완료했습니다 (미검토 항목이 있어도 진행)",
                key="s3_hwpx_ack",
            )

        if st.button("HWPX 생성", type="primary", key="s3_generate", disabled=hwpx_blockers and not hwpx_ack):
            os.makedirs("output", exist_ok=True)
            generated: list[dict] = []  # {"label", "path", "file_name"}

            # 메인 법령 HWPX
            main_path = "output/amendment.hwpx"
            with st.spinner(f"{title} HWPX 생성 중..."):
                try:
                    _generate_single_hwpx(
                        title=title,
                        instruction=instruction,
                        comparison_rows=rows,
                        buchik=buchik,
                        output_path=main_path,
                    )
                    generated.append({"label": f"{title} 다운로드", "path": main_path, "file_name": f"{title}.hwpx"})
                except Exception as e:
                    st.error(f"메인 HWPX 생성 실패: {e}")

            # 병행 법령별 별도 HWPX
            for ps in st.session_state.get("s3_parallel_sections", []):
                ps_title = _amendment_title(ps["법령명"])
                safe_name = ps['법령명'].replace(" ", "_").replace("/", "_")
                ps_path = f"output/amendment_{safe_name}.hwpx"
                with st.spinner(f"{ps_title} HWPX 생성 중..."):
                    try:
                        _generate_single_hwpx(
                            title=ps_title,
                            instruction=ps["instruction"],
                            comparison_rows=ps["rows"],
                            buchik=ps["buchik"],
                            output_path=ps_path,
                        )
                        generated.append({"label": f"{ps_title} 다운로드", "path": ps_path, "file_name": f"{ps_title}.hwpx"})
                    except Exception as e:
                        st.error(f"{ps_title} HWPX 생성 실패: {e}")

            st.session_state["s3_generated"] = generated
            if generated:
                st.success(f"HWPX {len(generated)}개 생성 완료")

        for item in st.session_state.get("s3_generated", []):
            if os.path.exists(item["path"]):
                with open(item["path"], "rb") as f:
                    st.download_button(
                        label=item["label"],
                        data=f.read(),
                        file_name=item["file_name"],
                        mime="application/hwp+zip",
                        key=f"s3_dl_{item['path']}",
                    )


def _generate_single_hwpx(
    title: str,
    instruction: str,
    comparison_rows: list[tuple[str, str]],
    buchik: str,
    output_path: str,
) -> None:
    """단일 법령 HWPX 생성 (메인·병행 공용)."""
    doc = HwpxDocument.new()

    doc.add_paragraph(title, section_index=0)
    doc.add_paragraph("", section_index=0)

    doc.add_paragraph("개정지시문", section_index=0)
    for line in instruction.splitlines():
        doc.add_paragraph(line, section_index=0)
    doc.add_paragraph("", section_index=0)

    doc.add_paragraph("신·구조문대비표", section_index=0)
    build_comparison_table(doc, comparison_rows)
    doc.add_paragraph("", section_index=0)

    doc.add_paragraph("부  칙", section_index=0)
    for line in buchik.splitlines():
        doc.add_paragraph(line, section_index=0)

    doc.save_to_path(output_path)
    _patch_font_in_hwpx(output_path)
