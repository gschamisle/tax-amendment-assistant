"""연관·연쇄 개정 검토 큐 (필수/참고 티어)."""
from __future__ import annotations

import re
from dataclasses import dataclass, field

from core.citation_graph import back_citation_hits, graph_available
from core.cross_ref_checker import _known_parallel_hints
from core.law_network import related_law_names, resolve_law_entries, scan_back_citations
from core.outline_intent import OutlineIntent, hang_to_sym
from core.related_article_hints import lookup_related_hints
from core.related_relation_types import classify_relation

_SUGGEST_RE = re.compile(
    r'\[제안\]\s*(.*?):\s*"([^"]+)"\s*[→-]\s*"([^"]+)"(?:\s*[—\-]\s*(.+))?',
    re.MULTILINE,
)
_REVIEW_RE = re.compile(
    r'\[검토\]\s*(.*?):\s*"([^"]+)"\s*[→-]\s*"([^"]+)"(?:\s*[—\-]\s*(.+))?',
    re.MULTILINE,
)
_LAW_ARTICLE_RE = re.compile(
    r"^(?:(소득세법|법인세법|부가가치세법|조세특례제한법)(?:\s*시행령|\s*시행규칙)?)\s+"
    r"(제\d+(?:의\d+)?조(?:제\d+항)?(?:제\d+호)?)"
)
_HANG_SYM_RE = re.compile(r"[①②③④⑤⑥⑦⑧⑨⑩⑪⑫⑬⑭⑮⑯⑰⑱⑲⑳]")
_DIRECT_CITE_MARKERS = ("직접 인용", "인용:", "역인용", "명시 인용", "확정 병행", "확정 연관")


@dataclass
class RelatedCandidate:
    candidate_id: str
    tier: str  # required | reference
    source: str  # back_citation | hint | parallel_hint | same_article | gpt
    law_name: str
    article_ref: str
    label: str
    reason: str
    old_text: str = ""
    new_text: str = ""
    cite_raw: str = ""
    sym_char: str = ""  # 같은 조 항 단위 제안 시
    relation_type: str = ""
    apply_to_amended: bool = False  # 같은 조 [제안] 반영용

    def is_cross_article(self) -> bool:
        return bool(self.law_name and self.article_ref and not self.sym_char)

    def to_dict(self) -> dict:
        return {
            "candidate_id": self.candidate_id,
            "tier": self.tier,
            "source": self.source,
            "law_name": self.law_name,
            "article_ref": self.article_ref,
            "label": self.label,
            "reason": self.reason,
            "old_text": self.old_text,
            "new_text": self.new_text,
            "cite_raw": self.cite_raw,
            "sym_char": self.sym_char,
            "relation_type": self.relation_type,
            "apply_to_amended": self.apply_to_amended,
        }

    @classmethod
    def from_dict(cls, data: dict) -> RelatedCandidate:
        return cls(
            candidate_id=str(data.get("candidate_id", "")),
            tier=str(data.get("tier", "reference")),
            source=str(data.get("source", "")),
            law_name=str(data.get("law_name", "")),
            article_ref=str(data.get("article_ref", "")),
            label=str(data.get("label", "")),
            reason=str(data.get("reason", "")),
            old_text=str(data.get("old_text", "")),
            new_text=str(data.get("new_text", "")),
            cite_raw=str(data.get("cite_raw", "")),
            sym_char=str(data.get("sym_char", "")),
            relation_type=str(data.get("relation_type", "")),
            apply_to_amended=bool(data.get("apply_to_amended", False)),
        )


def _candidate_id(law: str, ref: str, source: str, sym: str = "") -> str:
    return f"{law}|{ref}|{source}|{sym}"


def _parse_label_parts(label: str) -> tuple[str, str]:
    """'소득세법 제127조제1항제3호(이유)' → (법령, 조문)."""
    m = _LAW_ARTICLE_RE.match(label.strip())
    if m:
        return m.group(1), m.group(2)
    m2 = re.match(r"^(제\d+(?:의\d+)?조(?:제\d+항)?(?:제\d+호)?)", label.strip())
    if m2:
        return "", m2.group(1)
    return "", ""


def _tier_for(
    *,
    source: str,
    is_suggest: bool,
    reason: str,
    label: str,
    sym_char: str,
) -> str:
    if source == "parallel_hint":
        return "required"
    if source == "back_citation":
        return "required"
    if is_suggest and sym_char:
        return "required" if any(m in reason for m in _DIRECT_CITE_MARKERS) else "reference"
    if is_suggest:
        return "required" if any(m in reason for m in _DIRECT_CITE_MARKERS) else "reference"
    if source == "hint":
        return "reference"
    if any(m in reason for m in _DIRECT_CITE_MARKERS):
        return "required"
    return "reference"


def _from_gpt_lines(gpt_related: str, base_law: str) -> list[RelatedCandidate]:
    out: list[RelatedCandidate] = []
    for is_suggest, pattern in ((True, _SUGGEST_RE), (False, _REVIEW_RE)):
        for m in pattern.findall(gpt_related):
            label, old_t, new_t = m[0], m[1], m[2]
            reason = m[3].strip() if len(m) > 3 and m[3] else ""
            sym_m = _HANG_SYM_RE.search(label)
            sym_char = sym_m.group(0) if sym_m else ""
            law, ref = _parse_label_parts(label)
            if not law:
                law = base_law
            tier = _tier_for(
                source="gpt",
                is_suggest=is_suggest,
                reason=reason + label,
                label=label,
                sym_char=sym_char,
            )
            out.append(
                RelatedCandidate(
                    candidate_id=_candidate_id(law, ref or label, "gpt", sym_char),
                    tier=tier,
                    source="gpt",
                    law_name=law,
                    article_ref=ref,
                    label=label.strip(),
                    reason=reason or "GPT 연관항",
                    old_text=old_t,
                    new_text=new_t,
                    sym_char=sym_char,
                    apply_to_amended=bool(is_suggest and sym_char),
                )
            )
    return out


def _from_same_article_rows(rows: list[str], base_law: str) -> list[RelatedCandidate]:
    out: list[RelatedCandidate] = []
    for line in rows:
        is_suggest = line.startswith("[제안]")
        pattern = _SUGGEST_RE if is_suggest else _REVIEW_RE
        m = pattern.search(line)
        if not m:
            continue
        label, old_t, new_t = m.group(1), m.group(2), m.group(3)
        reason = m.group(4).strip() if m.lastindex and m.lastindex >= 4 and m.group(4) else ""
        sym_m = _HANG_SYM_RE.search(label)
        sym_char = sym_m.group(0) if sym_m else ""
        tier = _tier_for(
            source="same_article",
            is_suggest=is_suggest,
            reason=reason + label,
            label=label,
            sym_char=sym_char,
        )
        out.append(
            RelatedCandidate(
                candidate_id=_candidate_id(base_law, "", "same_article", sym_char),
                tier=tier,
                source="same_article",
                law_name=base_law,
                article_ref="",
                label=label.strip(),
                reason=reason or "같은 조 다른 항",
                old_text=old_t,
                new_text=new_t,
                sym_char=sym_char,
                apply_to_amended=bool(is_suggest and sym_char),
            )
        )
    return out


def _from_hints(intent: OutlineIntent, law_name: str, jo: str) -> list[RelatedCandidate]:
    rep = intent.primary_replacement
    if not rep:
        return []
    out: list[RelatedCandidate] = []
    for hint in lookup_related_hints(law_name, jo, intent.primary_hang, intent.target_ho):
        law = hint.get("law_name", law_name)
        article = hint.get("article", "")
        reason = hint.get("reason", "연동 검토")
        rel_type = classify_relation(
            law,
            article,
            reason,
            explicit=hint.get("relation_type", ""),
        )
        out.append(
            RelatedCandidate(
                candidate_id=_candidate_id(law, article, "hint"),
                tier="reference",
                source="hint",
                law_name=law,
                article_ref=article,
                label=f"{law} {article}",
                reason=reason,
                old_text=rep.old_text,
                new_text=rep.new_text,
                relation_type=rel_type,
            )
        )
    return out


def _from_back_citations(
    intent: OutlineIntent,
    law_name: str,
    article: dict,
    law_api_key: str,
) -> list[RelatedCandidate]:
    rep = intent.primary_replacement
    jo = str(article.get("조번호", "")).strip()
    if not rep or not jo or not law_api_key:
        return []

    base_jo, jo_sub = jo, ""
    if "의" in jo:
        base_jo, jo_sub = jo.split("의", 1)

    hits: list[dict] = []
    if graph_available():
        scope = [law_name]
        if law_name.endswith("법") and not law_name.endswith("시행령"):
            scope.append(f"{law_name} 시행령")
        for scope_law in scope:
            hits.extend(
                back_citation_hits(
                    scope_law,
                    base_jo,
                    jo_sub,
                    intent.primary_hang,
                    intent.target_ho,
                )
            )
    elif law_api_key:
        scope = [law_name]
        if law_name.endswith("법") and not law_name.endswith("시행령"):
            scope.append(f"{law_name} 시행령")
        entries = resolve_law_entries(scope, law_api_key)
        hits = scan_back_citations(
            entries, law_name, base_jo, jo_sub, intent.primary_hang, law_api_key
        )
    out: list[RelatedCandidate] = []
    for hit in hits:
        if str(hit.get("조번호", "")) == jo:
            continue
        law = hit.get("법령명", law_name)
        hit_jo = str(hit.get("조번호", ""))
        ref = f"제{hit_jo}조"
        title = str(hit.get("제목", "")).strip()
        refs = hit.get("인용", [])
        cite_raw = ", ".join(r.get("raw", "") for r in refs[:2])
        reason = f"제{base_jo}조 인용: {cite_raw}" if cite_raw else "역인용"
        label = f"{law} {ref}" + (f"({title})" if title else "")
        out.append(
            RelatedCandidate(
                candidate_id=_candidate_id(law, ref, "back_citation"),
                tier="required",
                source="back_citation",
                law_name=law,
                article_ref=ref,
                label=label,
                reason=reason,
                old_text=rep.old_text,
                new_text=rep.new_text,
                cite_raw=cite_raw,
            )
        )
    return out


def _from_parallel_hints(
    intent: OutlineIntent,
    law_name: str,
    article: dict,
) -> list[RelatedCandidate]:
    rep = intent.primary_replacement
    if not rep:
        return []
    content = str(article.get("내용", ""))
    out: list[RelatedCandidate] = []
    for parallel_law in related_law_names(law_name):
        if parallel_law == law_name:
            continue
        for hint in _known_parallel_hints(law_name, content, parallel_law):
            art = hint.get("article", "")
            reason = hint.get("reason", "확정 병행 매핑")
            out.append(
                RelatedCandidate(
                    candidate_id=_candidate_id(parallel_law, art, "parallel_hint"),
                    tier="required",
                    source="parallel_hint",
                    law_name=parallel_law,
                    article_ref=art,
                    label=f"{parallel_law} {art}",
                    reason=reason,
                    old_text=rep.old_text,
                    new_text=rep.new_text,
                    relation_type="parallel_tax_law",
                )
            )
    return out


def build_review_queue(
    law_name: str,
    article: dict,
    intent: OutlineIntent,
    gpt_related: str,
    same_article_rows: list[str],
    law_api_key: str = "",
) -> list[RelatedCandidate]:
    """필수·참고 연관 후보 통합 목록."""
    merged: dict[str, RelatedCandidate] = {}

    def _add(candidates: list[RelatedCandidate]) -> None:
        for c in candidates:
            if c.candidate_id not in merged:
                merged[c.candidate_id] = c
            elif c.tier == "required" and merged[c.candidate_id].tier != "required":
                merged[c.candidate_id] = c

    _add(_from_hints(intent, law_name, str(article.get("조번호", ""))))
    _add(_from_back_citations(intent, law_name, article, law_api_key))
    _add(_from_parallel_hints(intent, law_name, article))
    _add(_from_same_article_rows(same_article_rows, law_name))
    _add(_from_gpt_lines(gpt_related, law_name))

    order = {"required": 0, "reference": 1}
    src_order = {
        "back_citation": 0,
        "parallel_hint": 1,
        "same_article": 2,
        "hint": 3,
        "gpt": 4,
    }
    return sorted(
        merged.values(),
        key=lambda c: (order.get(c.tier, 9), src_order.get(c.source, 9), c.label),
    )


def queue_summary(queue: list[RelatedCandidate]) -> dict[str, int]:
    req = sum(1 for c in queue if c.tier == "required")
    ref = sum(1 for c in queue if c.tier == "reference")
    return {"required": req, "reference": ref, "total": len(queue)}


def pending_required_reviews(
    queue: list[RelatedCandidate],
    reviewed_ids: set[str],
) -> list[RelatedCandidate]:
    return [
        c for c in queue
        if c.tier == "required" and c.candidate_id not in reviewed_ids
    ]
