"""연쇄 개정 작업 큐 (1단계 재진입)."""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass
class AmendmentJob:
    job_id: str
    law_name: str
    article_ref: str
    outline: str
    reason: str
    status: str = "pending"  # pending | active | done
    parent_law: str = ""
    parent_article: str = ""
    mst: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "job_id": self.job_id,
            "law_name": self.law_name,
            "article_ref": self.article_ref,
            "outline": self.outline,
            "reason": self.reason,
            "status": self.status,
            "parent_law": self.parent_law,
            "parent_article": self.parent_article,
            "mst": self.mst,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> AmendmentJob:
        return cls(
            job_id=str(data.get("job_id", "")),
            law_name=str(data.get("law_name", "")),
            article_ref=str(data.get("article_ref", "")),
            outline=str(data.get("outline", "")),
            reason=str(data.get("reason", "")),
            status=str(data.get("status", "pending")),
            parent_law=str(data.get("parent_law", "")),
            parent_article=str(data.get("parent_article", "")),
            mst=str(data.get("mst", "")),
        )


def build_cascade_outline(base_outline: str, parent_law: str, parent_article: str, reason: str) -> str:
    tail = (
        f"\n\n※ 연쇄 개정: {parent_law} {parent_article} 개정에 따른 검토"
        f"\n※ 검토 사유: {reason}"
    )
    return (base_outline.strip() + tail).strip()


def snapshot_current_amendment(session: dict[str, Any]) -> dict[str, Any]:
    """현재 1단계 초안 상태 스냅샷."""
    keys = (
        "final_law_name",
        "final_instruction",
        "final_current",
        "final_amended",
        "final_buchik",
        "s1_sections",
        "s1_article",
        "s1_outline",
        "s1_outline_intent",
        "s1_review_queue",
        "s1_reviewed_ids",
    )
    return {k: session.get(k) for k in keys if k in session}
