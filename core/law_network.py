"""법령 간 인용·역인용 및 하위법령 연쇄 검토 유틸리티."""
from __future__ import annotations

import functools
from concurrent.futures import ThreadPoolExecutor, as_completed

from config import LAW_API_KEY, PARALLEL_LAWS
from core.citation_parser import (
    Citation,
    _article_range_covers,
    effective_law_name,
    parse_citations,
)
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


def _parallel_law_names(law_name: str) -> list[str]:
    """PARALLEL_LAWS에서 병행 법령군을 정규화 매칭으로 찾는다.

    설정 키와 입력 법령명의 공백·ㆍ 표기 차이로 병행 스코프가 통째 비는 것을 막는다.
    """
    target = normalize_law_name(law_name)
    for key, parallels in PARALLEL_LAWS.items():
        if normalize_law_name(key) == target:
            return parallels
    return []


def related_law_names(law_name: str) -> list[str]:
    """기준 법령, 병행 법령, 각 하위법령을 포함한 후보 법령군."""
    names: list[str] = [law_name]
    names.extend(subordinate_law_names(law_name))
    for parallel in _parallel_law_names(law_name):
        names.append(parallel)
        names.extend(subordinate_law_names(parallel))
    return list(dict.fromkeys(n for n in names if n))


def _choose_entry(results: list[dict], name: str) -> tuple[dict | None, bool]:
    """검색 결과에서 법령명 정확매칭을 고른다.

    정확매칭이 없으면 첫 결과를 쓰되 fuzzy=True로 표시 — 호출부가 '엉뚱한 법령을
    말없이 스캔'하지 않도록 경고할 수 있게 한다. 반환: (선택 결과 or None, fuzzy 여부).
    """
    exact = next((r for r in results if r.get("법령명") == name), None)
    if exact:
        return exact, False
    if results:
        return results[0], True
    return None, False


def resolve_law_entries(law_names: list[str], law_api_key: str = "") -> list[dict[str, str]]:
    """법령명을 실제 MST가 포함된 검색 결과로 해석한다.

    정확매칭 실패로 유사 법령으로 대체한 항목은 entry['_fuzzy_from']에 요청 법령명을
    남긴다(호출부가 사용자에게 매칭 주의를 표시할 수 있도록).
    """
    entries: list[dict[str, str]] = []
    seen: set[str] = set()
    for name in law_names:
        try:
            results = search_laws(name, law_api_key)
        except Exception:
            continue
        chosen, fuzzy = _choose_entry(results, name)
        if not chosen:
            continue
        key = chosen.get("MST") or chosen.get("법령명", "")
        if not key or key in seen:
            continue
        seen.add(key)
        if fuzzy:
            chosen = {**chosen, "_fuzzy_from": name}
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

    if citation.is_range and citation.range_end_jo:
        # 조문 범위는 가지번호 포함까지 펼쳐 판정 (find_back_citations와 동일 규칙).
        # 통조 범위(제2조~제8조)는 그 사이 가지번호 조문(제5조의2)도 포함한다.
        if not _article_range_covers(citation, target_jo, target_jo_sub):
            return False
    else:
        if citation.jo != target_jo:
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
    errors: list[dict] | None = None,
) -> list[dict]:
    """여러 법령에서 target 조문을 인용하는 조항을 찾는다.

    조회에 실패한 법령은 조용히 빠뜨리지 않고 errors(전달 시)에 기록한다 —
    누락 방지 도구에서 'API 실패'가 '인용 없음'으로 오인되는 것을 막는다.
    """
    if not law_entries:
        return []

    results: list[dict] = []

    def _scan_one(entry: dict[str, str]) -> list[dict]:
        law_name = entry.get("법령명", "")
        if entry.get("_fuzzy_from") and errors is not None:
            errors.append({
                "유형": "법령매칭주의", "법령명": law_name, "요청": entry["_fuzzy_from"],
            })
        try:
            data = _cached_law_text(entry["MST"], law_api_key or LAW_API_KEY)
        except Exception as exc:
            if errors is not None:
                errors.append({"유형": "조회실패", "법령명": law_name, "MST": entry.get("MST", ""), "error": str(exc)})
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
                    "via_range": bool(c.is_range and c.range_end_jo),
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
