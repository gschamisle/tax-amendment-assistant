"""법령 간 인용·역인용 및 하위법령 연쇄 검토 유틸리티."""
from __future__ import annotations

import functools
from concurrent.futures import ThreadPoolExecutor, as_completed

from config import LAW_API_KEY, PARALLEL_LAWS
from core.citation_parser import Citation, effective_law_name, parse_citations
from core.law_api import get_law_text, list_all_laws, search_laws


def normalize_law_name(name: str) -> str:
    """법령명 비교용 정규화."""
    return str(name).replace(" ", "").replace("ㆍ", "").replace("·", "").strip()


def subordinate_law_names(law_name: str) -> list[str]:
    """법률/시행령 기준 하위법령 후보를 만든다."""
    name = law_name.strip()
    if not name:
        return []
    if name.endswith("시행규칙"):
        return []
    if name.endswith("시행령"):
        base = name.removesuffix(" 시행령").removesuffix("시행령").strip()
        return [f"{base} 시행규칙"] if base else []
    return [f"{name} 시행령", f"{name} 시행규칙"]


def related_law_names(law_name: str) -> list[str]:
    """기준 법령, 병행 법령, 각 하위법령을 포함한 후보 법령군."""
    names: list[str] = [law_name]
    names.extend(subordinate_law_names(law_name))
    for parallel in PARALLEL_LAWS.get(law_name, []):
        names.append(parallel)
        names.extend(subordinate_law_names(parallel))
    return list(dict.fromkeys(n for n in names if n))


def resolve_law_entries(law_names: list[str], law_api_key: str = "") -> list[dict[str, str]]:
    """법령명을 실제 MST가 포함된 검색 결과로 해석한다."""
    entries: list[dict[str, str]] = []
    seen: set[str] = set()
    for name in law_names:
        try:
            results = search_laws(name, law_api_key)
        except Exception:
            continue
        exact = next((r for r in results if r.get("법령명") == name), None)
        chosen = exact or (results[0] if results else None)
        if not chosen:
            continue
        key = chosen.get("MST") or chosen.get("법령명", "")
        if not key or key in seen:
            continue
        seen.add(key)
        entries.append(chosen)
    return entries


@functools.lru_cache(maxsize=256)
def _cached_law_text(mst: str, law_api_key: str) -> dict:
    return get_law_text(mst, law_api_key or LAW_API_KEY, "")


def _citation_matches(
    citation: Citation,
    source_law_name: str,
    target_law_name: str,
    target_jo: str,
    target_jo_sub: str = "",
    target_hang: str = "",
) -> bool:
    cite_law = effective_law_name(citation, source_law_name)
    if normalize_law_name(cite_law) != normalize_law_name(target_law_name):
        return False

    if citation.jo != target_jo:
        try:
            if not (
                citation.range_end_jo
                and int(citation.jo) <= int(target_jo) <= int(citation.range_end_jo)
            ):
                return False
        except ValueError:
            return False

    if target_jo_sub and citation.jo_sub != target_jo_sub:
        return False

    if target_hang and citation.hang:
        if citation.hang_end:
            try:
                return int(citation.hang) <= int(target_hang) <= int(citation.hang_end)
            except ValueError:
                return False
        return citation.hang == target_hang

    return True


def scan_back_citations(
    law_entries: list[dict[str, str]],
    target_law_name: str,
    target_jo: str,
    target_jo_sub: str = "",
    target_hang: str = "",
    law_api_key: str = "",
    max_workers: int = 6,
) -> list[dict]:
    """여러 법령에서 target 조문을 인용하는 조항을 찾는다."""
    if not law_entries:
        return []

    results: list[dict] = []

    def _scan_one(entry: dict[str, str]) -> list[dict]:
        law_name = entry.get("법령명", "")
        try:
            data = _cached_law_text(entry["MST"], law_api_key or LAW_API_KEY)
        except Exception:
            return []
        found: list[dict] = []
        for article in data.get("조문목록", []):
            citations = parse_citations(article.get("내용", ""))
            matching = [
                {
                    "raw": c.raw,
                    "law_name": c.law_name or law_name,
                    "jo": c.jo,
                    "jo_sub": c.jo_sub,
                    "hang": c.hang,
                    "hang_end": c.hang_end,
                }
                for c in citations
                if _citation_matches(c, law_name, target_law_name, target_jo, target_jo_sub, target_hang)
            ]
            if matching:
                found.append({
                    "법령명": law_name,
                    "MST": entry.get("MST", ""),
                    "조번호": article.get("조번호", ""),
                    "제목": article.get("제목", ""),
                    "내용": article.get("내용", ""),
                    "인용": matching,
                })
        return found

    with ThreadPoolExecutor(max_workers=max_workers) as pool:
        futures = {pool.submit(_scan_one, entry): entry for entry in law_entries}
        for future in as_completed(futures):
            results.extend(future.result())

    return sorted(results, key=lambda r: (r.get("법령명", ""), str(r.get("조번호", ""))))


def candidate_scope_entries(law_name: str, law_api_key: str = "") -> list[dict[str, str]]:
    """기준 법령의 병행·하위 후보 법령군을 MST 목록으로 반환한다."""
    return resolve_law_entries(related_law_names(law_name), law_api_key)


def all_law_scope_entries(law_api_key: str = "", max_pages: int = 30) -> list[dict[str, str]]:
    """전체 법령목록 검색용 MST 목록."""
    return list_all_laws(law_api_key, max_pages=max_pages)
