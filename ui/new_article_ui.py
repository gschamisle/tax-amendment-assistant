"""신설 조문 검토 탭 — 조문안 직접 입력 또는 개정안 파일 업로드 → 연동 개정 후보 출력.

업로드 파일은 git에서 제외되는 data/uploads/ 에만 저장된다(내부자료 보호).
"""
import re
from pathlib import Path

import streamlit as st

from core.draft_bill_parser import compare_review, find_amendment_body
from core.new_article_scanner import parse_jo_tokens, review_new_articles

_JO_URL_RE = re.compile(r"제(\d+)조(?:의(\d+))?")
_UPLOAD_DIR = Path(__file__).resolve().parents[1] / "data" / "uploads"


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


def _ingest_upload(uploaded) -> dict | None:
    """업로드 파일 저장(data/uploads, git 제외) 후 개정문 본문 파싱."""
    from core.hwp_reader import extract_text

    _UPLOAD_DIR.mkdir(parents=True, exist_ok=True)
    dest = _UPLOAD_DIR / uploaded.name
    dest.write_bytes(uploaded.getbuffer())
    if dest.suffix.lower() == ".txt":
        text = dest.read_text(encoding="utf-8", errors="replace")
    else:
        text = extract_text(dest)
    if len(text) < 100:
        return None
    law_name, body = find_amendment_body(text)
    if not body:
        return None
    return {"law_name": law_name, "body": body, "file": uploaded.name}


def _stale_expanders(rows: list[dict]) -> None:
    for row in rows:
        jo_label = _format_jo_label(row["조번호"])
        url = _law_url(row["법령명"], row["조번호"])
        with st.expander(f"{row['법령명']} {jo_label} {row['제목']} — 대상: {', '.join(row['대상'])}"):
            st.markdown(f"[📄 법령 원문 바로가기]({url})")
            for raw in row["인용"]:
                st.markdown(f"**인용 구문**: `{raw}`")


def _proxy_table(rows: list[dict]) -> None:
    st.dataframe(
        [
            {
                "법령": r["법령명"],
                "조문": _format_jo_label(r["조번호"]),
                "제목": r["제목"],
                "인용": ", ".join(r["인용"][:2]),
                "원문 링크": _law_url(r["법령명"], r["조번호"]),
            }
            for r in rows
        ],
        column_config={
            "원문 링크": st.column_config.LinkColumn("원문 링크", display_text="바로가기"),
        },
        use_container_width=True,
    )


def _forward_section(external: list[dict], internal: list[dict]) -> None:
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
        st.caption(
            "외부 인용은 정의·요건을 차용하는 의존 관계입니다. "
            "주의: \"A법 제X조 및 제Y조\" 연결 열거의 두 번째 항목은 법령명이 자기 법령으로 표시될 수 있으니 원문을 확인하세요."
        )
    if internal:
        with st.expander(f"신설 범위 내 상호 인용 {len(internal)}건 (번호 정합성 확인용)"):
            st.dataframe(
                [{"조문": r["조문"], "인용 원문": r["인용 원문"]} for r in internal],
                use_container_width=True,
            )


_CATEGORY_STYLE = {
    "누락": ("❌", "누락 — 개정 반영 필요"),
    "판단필요": ("⚠️", "판단 필요"),
    "조치불요": ("✅", "조치 불요 (검토 완료)"),
}


def _render_llm_layer(cmp: dict) -> None:
    """AI 검토 — ①종합의견 ②삼분류 ③HWPX 의견서."""
    llm = st.session_state.get("na_llm")

    if not llm:
        with st.container(border=True):
            st.markdown('<div class="mofe-subheader">🤖 Claude 검토의견</div>', unsafe_allow_html=True)
            st.caption(
                "미반영 후보를 누락/판단필요/조치불요로 삼분류하고 종합 검토의견을 생성합니다. "
                "Claude API 과금(검토 1회당 수백 원 수준), 30초~2분 소요."
            )
            if st.button("Claude 검토의견 생성", key="na_llm_run"):
                from core.llm_review import run_llm_review

                try:
                    with st.spinner("Claude가 개정안 구조를 해석하고 항목을 판별하는 중..."):
                        st.session_state["na_llm"] = run_llm_review(
                            cmp, st.session_state.get("na_body", "")
                        )
                    st.rerun()
                except Exception as exc:
                    st.error(f"LLM 검토 실패: {exc}")
        return

    structure = llm.get("구조", {})
    review = llm.get("검토", {})

    # ── 1단: 종합 검토의견 ───────────────────────────────────────────────────
    with st.container(border=True):
        st.markdown('<div class="mofe-subheader">🤖 종합 검토의견</div>', unsafe_allow_html=True)
        if structure.get("제도명"):
            st.markdown(f"**신설 제도**: {structure['제도명']}")
        st.markdown(str(review.get("종합의견", "")))
        with st.expander("개정안 구조 해석 (AI)"):
            st.markdown(f"**제도 요약**: {structure.get('제도_요약', '')}")
            st.markdown(
                "**신설 조번호**: "
                + ", ".join(_format_jo_label(j) for j in structure.get("신설_조번호", []))
            )
            if structure.get("비고"):
                st.caption(structure["비고"])
            detected = {f"{jo}의{sub}" if sub else jo for jo, sub in cmp["jo_list"]}
            inferred = set(structure.get("신설_조번호", []))
            if inferred and inferred != detected:
                st.warning(
                    f"입력한 범위({', '.join(sorted(detected))})와 AI 추론 범위"
                    f"({', '.join(sorted(inferred))})가 다릅니다. 범위를 확인하세요."
                )

    # ── 2단: 삼분류 ──────────────────────────────────────────────────────────
    order = {"누락": 0, "판단필요": 1, "조치불요": 2}
    items = sorted(
        review.get("항목", []),
        key=lambda x: (order.get(x["구분"], 9), x["확신도"] != "높음"),
    )
    with st.container(border=True):
        st.markdown('<div class="mofe-subheader">항목별 판정</div>', unsafe_allow_html=True)
        for category in ("누락", "판단필요", "조치불요"):
            group = [it for it in items if it["구분"] == category]
            if not group:
                continue
            icon, label = _CATEGORY_STYLE[category]
            if category == "누락":
                st.error(f"{icon} {label} — {len(group)}건")
            elif category == "판단필요":
                st.warning(f"{icon} {label} — {len(group)}건")
            else:
                st.success(f"{icon} {label} — {len(group)}건")
            for it in group:
                expanded = category == "누락"
                title = f"{it['법령명']} {_format_jo_label(it['조번호'])} [확신도 {it['확신도']}]"
                with st.expander(title, expanded=expanded):
                    st.markdown(f"**쟁점**: {it['쟁점']}")
                    st.markdown(f"**권고 조치**: {it['권고조치']}")
                    url = _law_url(it["법령명"], it["조번호"])
                    st.markdown(f"[📄 법령 원문 바로가기]({url})")

    # ── 3단: 검토의견서 다운로드 ─────────────────────────────────────────────
    with st.container(border=True):
        st.markdown('<div class="mofe-subheader">검토의견서 출력</div>', unsafe_allow_html=True)
        if st.button("검토의견서 HWPX 생성", key="na_report"):
            from core.review_report import build_review_report_hwpx

            out = _UPLOAD_DIR / "검토의견서.hwpx"
            _UPLOAD_DIR.mkdir(parents=True, exist_ok=True)
            build_review_report_hwpx(
                cmp["law_name"], cmp, llm, str(out), source_file=cmp.get("file", "")
            )
            st.session_state["na_report_bytes"] = out.read_bytes()
        if st.session_state.get("na_report_bytes"):
            st.download_button(
                "📥 검토의견서 다운로드",
                data=st.session_state["na_report_bytes"],
                file_name=f"검토의견서_{cmp['law_name']}_신설조문.hwpx",
                mime="application/octet-stream",
                key="na_report_dl",
            )


def _render_comparison(cmp: dict) -> None:
    """업로드 개정안 vs 스캐너 대조 결과 렌더링."""
    jo_labels = ", ".join(
        f"제{jo}조의{sub}" if sub else f"제{jo}조" for jo, sub in cmp["jo_list"]
    )
    st.markdown(f"**검토 대상**: {cmp['law_name']} {jo_labels} (파일: {cmp.get('file', '')})")
    manual = cmp["manual_targets"]
    with st.expander(f"수기 병행개정 대상 {len(manual)}건 (지시문 기준)"):
        st.write(", ".join(_format_jo_label(j) for j in manual))

    _render_llm_layer(cmp)

    with st.container(border=True):
        st.markdown('<div class="mofe-subheader">① 신설 본문이 인용하는 조문</div>', unsafe_allow_html=True)
        _forward_section(cmp["forward"]["external"], cmp["forward"]["internal"])

    with st.container(border=True):
        st.markdown('<div class="mofe-subheader">② 재사용 조번호 잔존 인용 — 수기 개정과 대조</div>', unsafe_allow_html=True)
        s = cmp["stale"]
        if s["missing"]:
            st.warning(f"⚠️ 수기 개정안에 없는 잔존 인용 {len(s['missing'])}건 — 정비 또는 부칙 경과조치 검토")
            _stale_expanders(s["missing"])
        else:
            st.success("수기 개정안이 잔존 인용을 모두 다루고 있습니다")
        if s["covered"]:
            with st.expander(f"✅ 수기 개정에 이미 반영된 잔존 인용 {len(s['covered'])}건"):
                for row in s["covered"]:
                    st.write(f"{_format_jo_label(row['조번호'])} {row['제목']} — 대상: {', '.join(row['대상'])}")
        if s["decree"]:
            with st.expander(f"📋 시행령 잔존 인용 {len(s['decree'])}건 (법률 공포 후 시행령 개정에 반영)"):
                for row in s["decree"]:
                    st.write(f"{row['법령명']} {_format_jo_label(row['조번호'])} {row['제목']} — 대상: {', '.join(row['대상'])}")

    with st.container(border=True):
        st.markdown('<div class="mofe-subheader">③ 유사 제도 체크리스트 — 수기 개정과 대조</div>', unsafe_allow_html=True)
        px = cmp["proxy"]
        if not (px["missing"] or px["covered"]):
            st.info("유사 기존 제도 조문을 입력하면 체크리스트를 대조합니다.")
        else:
            if px["missing"]:
                st.warning(f"⚠️ 수기 개정안에 없는 체크리스트 조문 {len(px['missing'])}건 — 신설 조번호 추가 여부 검토")
                _proxy_table(px["missing"])
            if px["covered"]:
                with st.expander(f"✅ 수기 개정에 이미 반영 {len(px['covered'])}건"):
                    _proxy_table(px["covered"])


def render(law_api_key: str, openai_api_key: str) -> None:
    st.markdown('<div class="mofe-section-header">신설 조문 검토</div>', unsafe_allow_html=True)
    st.caption(
        "신설 조문안을 직접 입력하거나 개정안 파일(법률 개정 템플릿)을 통째로 업로드하면 "
        "① 조문안이 인용하는 조문(순방향) ② 재사용 조번호 잔존 인용 충돌 "
        "③ 유사 제도 기준 연동 개정 체크리스트를 찾습니다. "
        "파일 업로드 시 수기로 작성된 병행개정 조문과 자동 대조합니다."
    )

    with st.container(border=True):
        col1, col2, col3 = st.columns([2, 1, 1])
        with col1:
            law_name_input = st.text_input("신설 대상 법령", value="", key="na_law")
        with col2:
            jo_range_text = st.text_input(
                "신설 조번호 범위", value="", key="na_range",
                help="쉼표로 나열하거나 범위로 입력합니다. 가지번호는 '의'로 표기합니다.",
            )
        with col3:
            proxy_text = st.text_input(
                "유사 기존 제도 조문(선택)", value="", key="na_proxy",
                help="성격이 비슷한 기존 제도의 조번호. 그 제도를 인용하는 열거형 조문이 검토 대상이 됩니다.",
            )

        uploaded = st.file_uploader(
            "개정안 파일 업로드 (.hwpx / .hwp / .txt) — 수기 병행개정이 포함된 전체 조문안",
            type=["hwpx", "hwp", "txt"],
            key="na_file",
        )
        st.caption("🔒 업로드 파일은 로컬 data/uploads/ 에만 저장되며 git 저장소에는 포함되지 않습니다.")

        draft_text = st.text_area(
            "신설 조문안 직접 입력 (파일 업로드 시 무시됨)",
            height=240,
            key="na_draft",
        )

        if st.button("신설 검토 실행", key="na_run", type="primary"):
            if not jo_range_text.strip():
                st.error("신설 조번호 범위를 입력하세요.")
            elif uploaded is not None:
                with st.spinner("파일 추출·파싱 중..."):
                    payload = _ingest_upload(uploaded)
                if not payload:
                    st.error("개정문 본문을 찾지 못했습니다. 파일이 '…일부를 다음과 같이 개정한다' 템플릿인지 확인하세요.")
                else:
                    cmp = compare_review(
                        payload["law_name"], jo_range_text, payload["body"], proxy_text,
                    )
                    cmp["file"] = payload["file"]
                    st.session_state["na_cmp"] = cmp
                    st.session_state["na_body"] = payload["body"]
                    st.session_state.pop("na_result", None)
                    st.session_state.pop("na_llm", None)
                    st.session_state.pop("na_report_bytes", None)
            else:
                st.session_state["na_result"] = review_new_articles(
                    law_name_input.strip(), jo_range_text, draft_text, proxy_text,
                )
                st.session_state.pop("na_cmp", None)

    # ── 업로드 대조 모드 ──────────────────────────────────────────────────────
    cmp = st.session_state.get("na_cmp")
    if cmp:
        _render_comparison(cmp)
        return

    # ── 직접 입력 모드 (기존 동작) ────────────────────────────────────────────
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
            _forward_section(external, internal)

    with st.container(border=True):
        st.markdown('<div class="mofe-subheader">② 재사용 조번호 잔존 인용 충돌</div>', unsafe_allow_html=True)
        st.caption(
            "구 조문이 삭제됐어도 이월공제·경과규정 때문에 인용이 남아 있으면, "
            "같은 번호에 새 제도가 들어가는 순간 그 인용이 신설 조문을 가리키게 됩니다."
        )
        stale = result["stale"]
        if not result["graph_ok"]:
            st.info("그래프 빌드 후 사용 가능합니다.")
        elif not stale:
            st.success("재사용 번호를 인용 중인 현행 조문 없음")
        else:
            st.warning(f"⚠️ 잔존 인용 {len(stale)}건 — 정비·경과조치 검토 필요")
            _stale_expanders(stale)

    with st.container(border=True):
        st.markdown('<div class="mofe-subheader">③ 유사 제도 기준 연동 개정 체크리스트</div>', unsafe_allow_html=True)
        proxies = parse_jo_tokens(st.session_state.get("na_proxy", ""))
        proxy_rows = result["proxy"]
        if not proxies:
            st.info("유사 기존 제도 조문을 입력하면 체크리스트를 생성합니다.")
        elif not result["graph_ok"]:
            st.info("그래프 빌드 후 사용 가능합니다.")
        elif not proxy_rows:
            st.success("프록시 조문을 인용하는 조문 없음")
        else:
            st.write(f"검토 대상 {len(proxy_rows)}건")
            _proxy_table(proxy_rows)
