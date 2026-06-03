# 병행법령 탐지 — 로직, 한계, 확장 방법

## 현재 구현 위치

`core/cross_ref_checker.py`, `config.py` (`PARALLEL_LAWS`)

---

## 탐지 흐름

```
check_all_parallel_laws(law_name, article_text)
    ↓
config.PARALLEL_LAWS[law_name] → 후보 법령 목록
    ↓ (법령별 반복)
search_laws(후보법령명) → MST 조회
    ↓
get_law_text(MST) → 조문목록 조회
    ↓
_extract_keywords(article_text) → 개정 조문 제목에서 키워드 추출
    ↓
_known_parallel_hints → 확정 매핑 + 조특법 citation JSON
    ↓ (힌트 없을 때)
_filter_articles(조문목록, keywords, max_n=20) → 관련 조문 필터링
    ↓
GPT-5.4-nano 호출
    ↓
둘 다 match=true + 조문 번호 실제 존재 확인 → 채택
```

---

## 현재 매핑 (`config.py`)

`config.py`의 `PARALLEL_LAWS`를 참고한다. 예시:

```python
PARALLEL_LAWS = {
    "소득세법": ["법인세법", "조세특례제한법"],
    "법인세법": ["소득세법", "조세특례제한법", "부가가치세법"],
    "조세특례제한법": ["소득세법", "법인세법", "부가가치세법"],
    # 시행령·시행규칙·부가가치세법 등 — config.py 전체 목록
}
```

이 목록에 없는 법령은 기본 병행 검사 대상에서 제외된다(전체 법령 검사 scope는 별도).

---

## 탐지 실패 원인 3가지

### 원인 A: PARALLEL_LAWS에 해당 법령 없음

가장 흔한 원인.

**확인 방법**: 검색하는 법령명이 `PARALLEL_LAWS`의 키에 있는지 확인.

**해결**: `config.py`에 매핑 추가.

```python
# 예: 부가가치세법 추가
PARALLEL_LAWS = {
    ...
    "부가가치세법":        ["부가가치세법 시행령"],
    "부가가치세법 시행령":  ["부가가치세법"],
    "개별소비세법":        ["교통·에너지·환경세법"],
}
```

**주의**: 법령명은 법제처 API가 반환하는 정확한 명칭이어야 한다.
`search_laws("부가가치세법")`으로 조회해서 `법령명` 필드 값을 그대로 사용할 것.

---

### 원인 B: 키워드 필터가 관련 조문 제외

`_filter_articles()` 로직:
1. `_extract_keywords(article_text)` — 개정 조문 제목의 3자 이상 한국어 단어 추출.
2. 후보 법령 조문 중 키워드 포함 조문 최대 20개 선택.
3. 키워드 매칭 조문이 없으면 법령 앞 40개 조문으로 폴백.

**실패 케이스**: 정답 조문이 41번째 이후이거나, 키워드가 조문 제목에 없고 내용에만 있는 경우.

**해결 옵션**:

```python
# max_n 상향 (GPT 입력 토큰 증가 주의)
relevant = _filter_articles(articles, keywords, max_n=40)

# 또는 폴백 범위 확장
return matched[:max_n] if matched else articles[:80]  # 40 → 80
```

---

### 원인 C: 컨센서스 기준 너무 엄격

2회 호출 중 1회만 `match: true` → 버림.

**트레이드오프**:
- 완화하면 false positive 증가 (개정 불필요한 조문도 포함).
- 유지하면 false negative 발생 (실제 병행 개정 필요 조문 누락).

**완화 방법**:

```python
# 현재: 2/2 컨센서스
if result1.match == true AND result2.match == true: 채택

# 완화: 2/2 → 1/2
if result1.match == true OR result2.match == true: 채택
```

완화 시 결과 UI에 "GPT 1회만 match — 검토 필요" 레이블 추가 권장.

---

## 새 법령 추가 절차

1. `search_laws("추가할법령명")`으로 정확한 법령명 확인.
2. `config.py`의 `PARALLEL_LAWS`에 양방향 매핑 추가.

```python
# 예: 상속세및증여세법 추가
PARALLEL_LAWS["상속세및증여세법"] = ["소득세법", "법인세법"]
PARALLEL_LAWS["소득세법"].append("상속세및증여세법")
PARALLEL_LAWS["법인세법"].append("상속세및증여세법")
```

3. 앱 재기동 후 해당 법령으로 병행 검사 테스트.

---

## Hallucination 필터 동작

GPT가 존재하지 않는 조문 번호를 반환하는 경우를 차단한다.

```python
# cross_ref_checker.py:129
article_content = _extract_article_content(parallel_data, result.get("article", ""))
if not article_content:
    # 조문 번호가 실제 존재하지 않음 → no-match로 처리
    result = {"match": "false", "article": "", "reason": ""}
```

이 필터로 잘못된 병행법령 제안을 걸러낸다.
단, GPT가 올바른 조문 번호를 반환해도 다른 항을 언급하는 경우는 현재 거르지 않는다.

---

## 성능 개선 (선택적)

현재 `check_all_parallel_laws()`는 후보 법령을 순차 처리한다.
법령이 3개 이상이면 `ThreadPoolExecutor`로 병렬화 시 처리 시간 1/2~1/3 단축 가능.

```python
from concurrent.futures import ThreadPoolExecutor, as_completed

def check_all_parallel_laws(...):
    candidates = sorted(PARALLEL_LAWS.get(law_name, []))
    
    def check_one(pname):
        results = search_laws(pname, law_api_key)
        if not results:
            return None
        mst = results[0]["MST"]
        return find_parallel_articles(law_name, article_text, pname, mst, openai_api_key)
    
    suggestions = []
    with ThreadPoolExecutor(max_workers=3) as executor:
        futures = {executor.submit(check_one, p): p for p in candidates}
        for future in as_completed(futures):
            result = future.result()
            if result and str(result.get("match", "false")).lower() == "true":
                suggestions.append(...)
    return suggestions
```

OpenAI API rate limit 주의: `max_workers=3` 이상으로 올리면 429 오류 가능.
