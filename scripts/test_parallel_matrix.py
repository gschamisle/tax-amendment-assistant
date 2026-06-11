"""병행법령 매트릭스 골든 recall·스키마 테스트 (오프라인)."""
from __future__ import annotations

import sys

from core.parallel_golden import golden_entries
from core.parallel_matrix import matrix_available, matrix_meta, parallel_hits

_REQUIRED_FIELDS = ("target_law", "target_article", "relation_type", "confidence", "source")


def main() -> int:
    if not matrix_available():
        print("SKIP: parallel-law-matrix.json 없음 — build_parallel_matrix.py 실행 필요")
        return 0

    meta = matrix_meta()
    assert meta.get("entry_count", 0) > 0, meta
    assert meta.get("law_versions"), meta

    # 골든 recall 100%: 매뉴얼 매핑이 매트릭스에 전부 있어야 함
    missing: list[str] = []
    checked = 0
    for key, items in golden_entries().items():
        law, jo = key.split("|", 1)
        hits = parallel_hits(law, jo)
        have = {(h["target_law"], h["target_article"]) for h in hits}
        # 조번호 수준 비교 (표기 차이 허용)
        have_laws = {h["target_law"] for h in hits}
        for item in items:
            checked += 1
            if (item["target_law"], item["target_article"]) in have:
                continue
            if item["target_law"] in have_laws:
                # 같은 법령의 다른 표기 — 조번호로 재확인
                from scripts.build_parallel_matrix import _article_jo
                want_jo = _article_jo(item["target_article"])
                if any(
                    h["target_law"] == item["target_law"]
                    and _article_jo(h["target_article"]) == want_jo
                    for h in hits
                ):
                    continue
            missing.append(f"{key} → {item['target_law']} {item['target_article']}")
    assert not missing, "골든 매핑 누락:\n" + "\n".join(missing)

    # 스키마: 대표 키의 모든 엔트리에 필수 필드
    sample = parallel_hits("법인세법", "27의2")
    assert sample, "법인세법 27의2 엔트리 없음"
    for e in sample:
        for f in _REQUIRED_FIELDS:
            assert e.get(f), (f, e)
    assert any(
        e["target_law"] == "소득세법" and e["target_article"] == "제33조의2"
        for e in sample
    ), sample

    # 조번호 표기 정규화 조회 ("제27조의2"로도 동일 결과)
    assert parallel_hits("법인세법", "제27조의2") == sample

    # 3단계 이후: semantic_llm 레이어 + 전수 판별 쌍 메타
    n_semantic = 0
    if meta.get("stage", 0) >= 3:
        from core.parallel_matrix import semantic_pair_covered

        assert semantic_pair_covered("법인세법", "소득세법")
        assert semantic_pair_covered("소득세법", "법인세법")  # 방향 무관
        assert not semantic_pair_covered("법인세법", "상속세 및 증여세법")
        from core.parallel_matrix import _load
        entries, _ = _load()
        n_semantic = sum(
            1 for items in entries.values() for e in items
            if e.get("source") == "semantic_llm"
        )
        assert n_semantic > 0, "semantic_llm 엔트리 없음"

        # 런타임 매트릭스 조회 (LLM·API 없이 가짜 법령 데이터로 검증)
        from core.cross_ref_checker import _matrix_match_result

        fake_parallel_data = {
            "조문목록": [
                {"조번호": "33의2", "제목": "업무용승용차 관련 경비 등의 필요경비 불산입 특례",
                 "내용": "① 성실신고확인대상사업자가..."},
            ],
        }
        r = _matrix_match_result(
            "법인세법",
            "제27조의2(업무용승용차 관련비용의 손금불산입 특례) ① 내국법인이...",
            "소득세법",
            fake_parallel_data,
        )
        assert r and r["match"] == "true" and "제33조의2" in r["article"], r

    print(f"ALL OK (golden={checked}, entry_count={meta['entry_count']}, "
          f"semantic={n_semantic}, stage={meta.get('stage')})")
    return 0


if __name__ == "__main__":
    sys.exit(main())
