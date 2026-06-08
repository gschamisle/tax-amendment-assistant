"""1단계 연관·연쇄 검토 큐 UI."""
from __future__ import annotations

import streamlit as st

from core.amendment_queue import AmendmentJob, build_cascade_outline
from core.law_api import search_laws
from core.related_review_queue import RelatedCandidate


def _law_url(law_name: str, article_ref: str) -> str:
    base = f"https://www.law.go.kr/법령/{law_name}"
    if article_ref:
        return f"{base}/{article_ref.replace(' ', '')}"
    return base


def _enqueue_amendment_job(
    candidate: RelatedCandidate,
    parent_law: str,
    parent_article: str,
    base_outline: str,
    law_api_key: str,
) -> None:
    jobs: list[dict] = st.session_state.setdefault("s1_amendment_queue", [])
    job_id = f"job_{len(jobs)}_{candidate.candidate_id}"
    mst = ""
    try:
        results = search_laws(candidate.law_name, law_api_key)
        exact = next((r for r in results if r.get("법령명") == candidate.law_name), None)
        if exact:
            mst = exact.get("MST", "")
    except Exception:
        pass
    jobs.append(
        AmendmentJob(
            job_id=job_id,
            law_name=candidate.law_name,
            article_ref=candidate.article_ref,
            outline=build_cascade_outline(base_outline, parent_law, parent_article, candidate.reason),
            reason=candidate.reason,
            status="pending",
            parent_law=parent_law,
            parent_article=parent_article,
            mst=mst,
        ).to_dict()
    )
    st.session_state["s1_amendment_queue"] = jobs
    st.session_state["s1_active_job_id"] = job_id


def _article_key_from_dict(article: dict) -> tuple[str, str]:
    jo = str(article.get("조번호", "")).strip()
    if "의" in jo:
        base, sub = jo.split("의", 1)
        return base, sub
    return jo, ""


def _activate_job(job: dict, law_api_key: str, openai_api_key: str, cached_law_text) -> None:
    """큐 항목으로 1단계 컨텍스트 전환."""
    if st.session_state.get("s1_sections"):
        completed = st.session_state.setdefault("s1_completed_amendments", [])
        completed.append({
            "job_id": st.session_state.get("s1_active_job_id", "main"),
            "law_name": st.session_state.get("final_law_name", ""),
            "snapshot": {
                k: st.session_state.get(k)
                for k in (
                    "final_instruction", "final_current", "final_amended",
                    "final_buchik", "s1_sections",
                )
            },
        })
        st.session_state["s1_completed_amendments"] = completed

    law_name = job["law_name"]
    results = search_laws(law_name, law_api_key)
    entry = next((r for r in results if r.get("법령명") == law_name), results[0] if results else None)
    if not entry:
        st.error(f"{law_name} 검색 실패")
        return

    mst = job.get("mst") or entry.get("MST", "")
    data = cached_law_text(mst, law_api_key, openai_api_key)
    st.session_state["s1_selected_law"] = entry
    st.session_state["s1_law_data"] = data

    ref = job.get("article_ref", "")
    parsed = None
    import re
    m = re.search(r"제(\d+)(?:의(\d+))?조", ref)
    if m:
        jo, sub = m.group(1), m.group(2) or ""
        parsed = (jo, sub)
    articles = data.get("조문목록", [])
    target = None
    if parsed:
        key = (parsed[0], parsed[1])
        for a in articles:
            if _article_key_from_dict(a) == key:
                target = a
                break
    if target:
        st.session_state["s1_article"] = target
        for i, a in enumerate(articles):
            if a is target:
                st.session_state["s1_article_idx"] = i
                break
    st.session_state["s1_outline"] = job.get("outline", "")
    st.session_state["s1_active_job_id"] = job.get("job_id", "")
    for k in ("s1_sections", "s1_draft", "s1_review_queue", "s1_reviewed_ids"):
        st.session_state.pop(k, None)
    jobs = st.session_state.get("s1_amendment_queue", [])
    for j in jobs:
        if j.get("job_id") == job.get("job_id"):
            j["status"] = "active"
    st.session_state["s1_amendment_queue"] = jobs
    st.rerun()


def render_review_queue(
    queue: list[RelatedCandidate],
    parent_law: str,
    parent_article: str,
    base_outline: str,
    law_api_key: str,
    openai_api_key: str,
    cached_law_text,
) -> list[tuple[str, str, str]]:
    """필수/참고 큐 렌더. 같은 조 [제안] 수락 목록 반환."""
    if not queue:
        return []

    reviewed: set[str] = set(st.session_state.get("s1_reviewed_ids", []))
    accepted: list[tuple[str, str, str]] = []

    required = [c for c in queue if c.tier == "required"]
    reference = [c for c in queue if c.tier == "reference"]

    if required or reference:
        st.warning("연관·연쇄 개정 검토가 필요합니다.")

    def _render_candidate(c: RelatedCandidate, prefix: str) -> None:
        nonlocal reviewed, accepted
        cid = c.candidate_id
        with st.container(border=True):
            cap = f"**{c.label}**"
            if c.reason:
                cap += f" — {c.reason}"
            if c.relation_type:
                cap += f" `[{c.relation_type}]`"
            st.markdown(cap)
            if c.old_text and c.new_text:
                st.caption(f'`{c.old_text}` → `{c.new_text}`')
            if c.cite_raw:
                st.caption(f"인용: {c.cite_raw}")
            if c.is_cross_article():
                url = _law_url(c.law_name, c.article_ref)
                st.markdown(f"[법제처 원문]({url})")
                col1, col2, col3 = st.columns(3)
                with col1:
                    if st.button("검토 완료 (개정 불필요)", key=f"{prefix}_done_{cid}"):
                        reviewed.add(cid)
                        st.session_state["s1_reviewed_ids"] = list(reviewed)
                        st.rerun()
                with col2:
                    if st.button("이 조문도 개정", key=f"{prefix}_amend_{cid}"):
                        _enqueue_amendment_job(c, parent_law, parent_article, base_outline, law_api_key)
                        jobs = st.session_state.get("s1_amendment_queue", [])
                        active = next((j for j in jobs if j.get("job_id") == st.session_state.get("s1_active_job_id")), None)
                        if active:
                            _activate_job(active, law_api_key, openai_api_key, cached_law_text)
                with col3:
                    st.caption("완료" if cid in reviewed else "미확인")
            elif c.apply_to_amended and c.sym_char:
                label = f"{c.sym_char}항: \"{c.old_text}\" → \"{c.new_text}\" 개정안 반영"
                if st.checkbox(label, key=f"{prefix}_apply_{cid}"):
                    accepted.append((c.sym_char, c.old_text, c.new_text))

    if required:
        with st.expander(f"필수 검토 ({len(required)}건)", expanded=True):
            for i, c in enumerate(required):
                _render_candidate(c, f"req{i}")

    if reference:
        with st.expander(f"참고 검토 ({len(reference)}건)", expanded=False):
            for i, c in enumerate(reference):
                _render_candidate(c, f"ref{i}")

    st.session_state["s1_reviewed_ids"] = list(reviewed)
    return accepted


def enqueue_parallel_entries(
    entries: list[dict],
    parent_law: str,
    parent_article: str,
    base_outline: str,
    law_api_key: str,
) -> int:
    """병행 법령 검사 결과를 연쇄 개정 큐에 추가."""
    jobs: list[dict] = st.session_state.setdefault("s1_amendment_queue", [])
    added = 0
    for entry in entries:
        law_name = entry.get("법령명", "")
        article_ref = entry.get("조문", "")
        mst = entry.get("MST", "")
        reason = f"{parent_law} {parent_article} 병행 개정 검토"
        job_id = f"job_{len(jobs)}_{law_name}_{article_ref}"
        jobs.append(
            AmendmentJob(
                job_id=job_id,
                law_name=law_name,
                article_ref=article_ref,
                outline=build_cascade_outline(base_outline, parent_law, parent_article, reason),
                reason=reason,
                status="pending",
                parent_law=parent_law,
                parent_article=parent_article,
                mst=mst,
            ).to_dict()
        )
        added += 1
    st.session_state["s1_amendment_queue"] = jobs
    return added


def render_amendment_queue_bar(
    law_api_key: str,
    openai_api_key: str,
    cached_law_text,
) -> None:
    jobs: list[dict] = st.session_state.get("s1_amendment_queue", [])
    if not jobs:
        return
    pending = [j for j in jobs if j.get("status") == "pending"]
    if not pending:
        return
    st.info(f"연쇄 개정 대기 {len(pending)}건")
    for job in pending:
        col1, col2 = st.columns([4, 1])
        with col1:
            st.caption(f"{job.get('law_name')} {job.get('article_ref')} — {job.get('reason', '')[:60]}")
        with col2:
            if st.button("시작", key=f"start_{job.get('job_id')}"):
                st.session_state["s1_active_job_id"] = job.get("job_id")
                _activate_job(job, law_api_key, openai_api_key, cached_law_text)
