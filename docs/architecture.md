# 시스템 아키텍처 및 구현 이력

## 모듈 구조

```
core/
├── law_api.py            법제처 Open API 클라이언트
├── amendment_agent.py    GPT-4o 개정 초안 생성 + 섹션 파서
├── citation_parser.py    인용·준용 규정 regex 파싱
├── cross_ref_checker.py  병행법령 GPT 의미 매칭
└── hwpx_writer.py        HWPX 문서 생성

ui/
├── stage1_draft.py       1단계: 법령 검색 → 초안 생성
├── stage2_crossref.py    2단계: 인용 규정 확인
└── stage3_output.py      3단계: HWPX 출력
```

---

## 모듈별 설계

### law_api.py

**역할**: 법제처 DRF Open API 호출, 응답 XML 파싱, 이미지 OCR.

**주요 함수**:
- `search_laws(keyword, api_key)` → `[{법령명, MST, 종류}]`
- `get_law_text(law_mst, api_key, openai_key)` → `{법령명, 조문목록}`

**이미지 처리**:
법제처 API는 세율표 등을 `<img src="...flDownload...">` GIF 이미지로 반환한다.
`_clean()` 함수가 `_IMG_SRC_RE`로 이미지 URL을 추출하고 `_ocr_image_url()`이 GPT-4o vision으로 텍스트 변환한다.

**`_img_cache`**:
- 모듈 레벨 `dict[str, str]`로 OCR 결과 캐시.
- 최대 300개 제한 (`_IMG_CACHE_MAX`). 초과 시 가장 오래된 항목(삽입 순서 기준) 삭제.
- 앱 재기동 시 초기화됨 (프로세스 수명 기준 캐시).

**UI 레이어 캐시**:
`ui/stage1_draft.py`의 `_cached_law_text()`가 `@st.cache_data(ttl=3600)` 적용.
동일 MST + API키 조합은 1시간 내 재조회 시 즉시 반환. 첫 로딩만 느림.

---

### amendment_agent.py

**역할**: GPT-4o에게 개정 초안 생성 요청, 응답 텍스트를 섹션별로 분리.

**시스템 프롬프트 설계**:
- `<del>구문구</del>` — 현행에서 삭제되는 문구 (UI에서 파란색으로 표시).
- `<u>신문구</u>` — 개정안에서 추가·수정되는 문구 (UI에서 빨간색+밑줄로 표시).
- 변경 없는 항은 `② (현행과같음)` 형식.
- 연관 항 자동 수정 금지: 직접 인용이 없는 비례 수치는 `===SECTION:연관항===`에 제안으로만 표기.
- 부칙 적용 기준(사업연도, 과세기간, 신고, 지급·수령, 양도·취득, 공급, 발생·거래 등)별 적용례 문구 혼용 금지.

**섹션 구분자 방식** (`parse_draft_sections`):
1차: `===SECTION:지시문===` / `===SECTION:현행===` / `===SECTION:개정안===` / `===SECTION:부칙===` / `===SECTION:연관항===` 토큰 탐지.
2차 폴백: GPT가 구분자를 무시한 경우 키워드 방식으로 재시도.

기존 키워드 방식의 문제: GPT가 "3. 부칙 초안", "## 부칙", "**부칙**" 등 다양한 형태로 출력하면 파싱 실패 → 부칙 누락. 구분자 방식으로 해결.

**부칙 유형**:
`_BUCHIK_TEMPLATES` dict에 유형별 적용례 문구 하드코딩.
`config.py`에 있던 `BUCHIK_TYPES` (영문 코드 매핑)는 실제로 사용되지 않아 삭제.

---

### citation_parser.py

**역할**: 조문 텍스트에서 인용·준용 규정을 regex로 추출.

**6종 파싱 패턴** (우선순위 순):
1. 타법 인용: `「법령명」 제X조제Y항...`
2. 같은 법/령 인용: `같은 법 제X조...`
3. 조문 범위: `제X조부터 제Y조까지`
4. 항·호·목 범위: `제X항부터 제Y항까지`
5. 직접 인용: `제X조제Y항제Z호...`
6. 조 내 단독 항·호: `제X항` (조번호 없는 형태)

겹치는 스팬은 `seen` set으로 중복 제거.

**지원 안되는 패턴 및 확장 방법** → [citation-parsing.md](citation-parsing.md) 참조.

---

### cross_ref_checker.py

**역할**: 개정 조문과 동일 취지의 병행 법령 조문을 GPT-4o-nano로 탐색.

**흐름**:
1. `config.py`의 `PARALLEL_LAWS`에서 후보 법령 목록 조회.
2. 후보 법령의 조문목록 조회 후 키워드 필터링 (`_filter_articles`, 최대 20개).
3. GPT-4o-nano에 A 법령 개정 조문 + B 법령 후보 조문 전달, match 여부 판단.
4. **컨센서스 방식**: 동일 프롬프트로 2회 호출, 둘 다 `match: true`일 때만 채택.
5. Hallucination 필터: GPT가 반환한 조문 번호가 실제 존재하지 않으면 no-match.

**한계 및 확장** → [parallel-law-detection.md](parallel-law-detection.md) 참조.

---

### hwpx_writer.py

**역할**: HWPX(한글과컴퓨터 ZIP 기반 XML 포맷) 문서 생성.

**신·구조문대비표 색상 처리**:

HWPX의 텍스트 스타일은 `charPr`(문자 속성)으로 정의되며 `header.xml`에 선언, `section0.xml`의 각 `run`에서 ID로 참조한다.

`python-hwpx` 라이브러리의 `ensure_char_property()` 메서드가 `HwpxOxmlDocument`에 존재하지 않아 기존 코드가 silent fail했다 (예외 catch 후 ID "0" 반환 → 기본 스타일만 적용).

**현재 구현**:
- `add_run(char_pr_id_ref="200")` — 파란색 (현행 삭제 문구)
- `add_run(char_pr_id_ref="201")` — 빨간색+밑줄 (개정안 신규 문구)
- `_patch_font_in_hwpx()`: HWPX ZIP을 열어 `header.xml`에 charPr ID 200/201 정의를 직접 주입 (라이브러리 API 우회).

charPr XML 구조:
```xml
<!-- ID 200: 파란 텍스트 -->
<hh:charPr id="200" textColor="#0000FF" ...>
  <hh:underline type="NONE" ... />
</hh:charPr>

<!-- ID 201: 빨간 텍스트 + 빨간 밑줄 -->
<hh:charPr id="201" textColor="#FF0000" ...>
  <hh:underline type="SOLID" color="#FF0000" ... />
</hh:charPr>
```

**폰트 처리**: `_patch_font_in_hwpx()`가 ZIP 후처리 시 모든 `face="..."` 속성을 `face="신명조"`로 교체.

---

## UI 설계

### 세션 상태 키 목록

| 키 | 저장 내용 | 생성 위치 |
|----|-----------|-----------|
| `s1_search_results` | 법령 검색 결과 | stage1, 검색 후 |
| `s1_selected_law` | 선택한 법령 정보 | stage1 |
| `s1_law_data` | 조문 목록 | stage1, 불러오기 후 |
| `s1_article` | 선택한 조문 | stage1 |
| `s1_draft` | GPT 원문 응답 | stage1 |
| `s1_sections` | 파싱된 섹션 dict | stage1 |
| `s1_hang_overrides` | 항별 적용 여부 | stage1 |
| `s1_accepted_suggests` | 수락한 연관항 제안 | stage1 |
| `s1_parallel_suggestions` | 병행법령 탐지 결과 | stage1 |
| `s2_extra_amendments` | 포함할 병행법령 목록 | stage1 |
| `s3_parallel_sections` | 병행법령 초안 목록 | stage1 |
| `s2_citations` | 인용 파싱 결과 | stage2 |
| `s2_back_citations` | 역방향 인용 결과 | stage2 |
| `final_law_name` | 법령명 (최종) | stage1 |
| `final_instruction` | 개정지시문 (최종) | stage1 |
| `final_current` | 현행 조문 (최종) | stage1 |
| `final_amended` | 개정안 (최종) | stage1 |
| `final_buchik` | 부칙 (최종) | stage1 |
| `s3_generated` | 생성된 HWPX 파일 목록 | stage3 |

### 연쇄 개정 검토 큐 (Phase 1)

`core/related_review_queue.py`가 힌트·역인용·병행·같은조·GPT 연관항을 `RelatedCandidate`로 통합하고 `tier`(required/reference)로 분류한다.

1단계 UI(`ui/related_review_ui.py`):
- **필수 검토** / **참고 검토** expander 분리
- 타법·타조문: 「검토 완료」 / 「이 조문도 개정」
- 같은 조 항: 체크박스로 개정안 반영

`s1_amendment_queue`에 연쇄 작업을 쌓고 1단계 재진입(법령·조문·요강 프리필). 병행 법령 검사 결과도 동일 큐로 진입한다.

3단계 HWPX 생성 전: 필수 미검토·pending 큐가 있으면 경고 + 확인 체크박스.

### 인용 그래프 (Phase 2)

`scripts/build_law_citation_graph.py` → `data/law-citation-graph.json` (소득세법·시행령 1차).

`core/citation_graph.py`가 역인용 인덱스를 로드한다. `related_article_scanner`·`related_review_queue`는 그래프 역인용을 API 스캔보다 우선한다.

### 간접 연쇄 유형 (Phase 3)

`core/related_relation_types.py`: `rate_application`, `definition_scope`, `calculation_rule`, `law_to_decree`, `parallel_tax_law`.

`related_article_hints.py` 골든 케이스(129조 등)에 `relation_type`을 부여하고, 일반 케이스는 그래프+유형 규칙이 담당한다.

---

## 주요 설계 결정 이력

| 결정 | 이유 |
|------|------|
| HWPX 색상을 ZIP 후처리로 주입 | `python-hwpx` 라이브러리 API가 charPr 생성을 지원하지 않음 |
| GPT 섹션 구분에 `===SECTION:XXX===` 토큰 사용 | 키워드 방식은 GPT 출력 형식 변동에 취약, 부칙 누락 발생 |
| 병행법령 컨센서스 2회 방식 | 1회 판단 시 false positive 너무 많음 |
| Hallucination 필터 (조문 번호 존재 확인) | GPT가 없는 조문 번호를 날조하는 케이스 발생 |
| `@st.cache_data(ttl=3600)` UI 레이어 캐시 | `get_law_text` 내부 OCR 순차 호출로 20~60초 소요, 재조회 시 즉시 반환 필요 |
| `_img_cache` 300개 상한 | 무제한 dict → 장시간 운영 시 메모리 증가 |
| `BUCHIK_TYPES` 삭제 | 영문 코드 매핑값이 어디서도 참조되지 않는 dead code |
