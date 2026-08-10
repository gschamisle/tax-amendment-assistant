# 시스템 아키텍처 및 구현 이력

## 모듈 구조

```
core/
├── law_api.py            법제처 Open API 클라이언트
├── amendment_agent.py    GPT-4o 개정 초안 생성 + 섹션 파서
├── citation_parser.py    인용·준용 규정 regex 파싱
├── cross_ref_checker.py  병행법령 매트릭스 조회 + 라이브 의미 매칭 폴백
├── parallel_matrix.py    사전 빌드 병행 매트릭스 런타임 조회
├── parallel_golden.py    병행개정 매뉴얼 골든 매핑 (빌드 주입 + recall 검증)
├── pdf_bill_text.py      PDF 개정안 강제 개행 복원
├── renumber_scan.py      번호 밀림 인용 정비 누락 검토 (결정적)
├── parallel_omission.py  병행개정 대응 조문 미개정 후보 (판단 보조)
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

**역할**: 개정 조문과 동일 취지의 병행 법령 조문 탐색.

**흐름** (우선순위 순):
1. **사전 빌드 매트릭스 조회** (`_matrix_match_result`): `data/parallel-law-matrix.json`에서
   확정 매핑·LLM 전수 판별 결과를 조회. 적중 시 LLM 호출 없이 즉시 반환.
2. **전수 판별 쌍 차단**: 매트릭스가 전 조문쌍을 판별한 법령쌍(`semantic_pair_covered`)은
   매트릭스 미등재 = 동일 취지 아님 → 라이브 LLM 생략하고 no-match.
3. 매트릭스 범위 밖 법령만 폴백: 코드 매핑 힌트 → 키워드 필터(`_filter_articles`, 최대 20개)
   → LLM 의미 판단 (컨센서스 2회 + hallucination 필터).

**한계 및 확장** → [parallel-law-detection.md](parallel-law-detection.md) 참조.

---

### parallel_matrix.py + 사전 빌드 파이프라인

**역할**: 병행·연관 검토 대상을 사전 계산해 런타임 LLM 비용을 데이터 갱신 시점으로 이전.

**파이프라인** (법령 개정 시 재실행):

| 단계 | 스크립트 | LLM | 내용 |
|------|----------|-----|------|
| 0 | `build_parallel_matrix.py` | 없음 | 법령 스냅샷 (`data/law-snapshots/`, content_hash 재사용) |
| 1 | `build_parallel_matrix.py` | 없음 | 골든 매핑(`parallel_golden.py`) + 코드 힌트 + 인용 그래프 타법 엣지 양방향 |
| 2 | `build_parallel_candidates.py` | 없음 | 전 조문쌍 스코어링 (동의어 정규화·제목/본문 교차·앵커 인접성). 골든 recall 보정 내장 |
| 3 | `adjudicate_parallel_pairs.py` | Haiku + Batches | 후보쌍 쌍별 판별 (structured outputs). 조문이 입력으로 주어져 hallucination 불가 |

**빌드 검증**: 매뉴얼 골든 매핑 누락 시 빌드 실패(assert). 조문 존재 검증.
오프라인 테스트(`test_parallel_matrix.py`)가 커밋된 매트릭스의 골든 recall을 CI에서 재검증.

**소스 우선순위**: golden_manual → code_hint → related_hint → semantic_llm → citation → back_citation.
citation/back_citation은 인용 관계라 병행 제안에서 제외하고 2단계 UI가 담당.

---

### parallel_omission.py

**역할**: 한 법을 고쳤는데 **병행 대응 조문을 안 고쳤는지** 추린다.
`renumber_scan`과 짝이지만 산출물의 성격이 다르다 — 그쪽은 기계적으로 확정되는
누락이고, 이쪽은 **판단이 필요한 검토 후보**다.

```
개정안 묶음 ─► 개정 대상 조 + 지시문 (draft_bill_parser)
            ─► 병행 매트릭스 조회 (parallel_matrix.parallel_hits)
            ─► 대응 조문이 같은 묶음에서 개정됐는지 대조
```

**병행 관계만 본다**: `golden_manual`(매뉴얼 확정) · `semantic_llm`(쌍별 판별) ·
`code_hint` · `related_hint`. `citation`/`back_citation`은 단순 인용이라 제외한다 —
섞으면 인용 한 건마다 후보가 쏟아져 사람이 볼 수 있는 양을 넘고, 그 영역은
`renumber_scan`이 이미 담당한다.

**지시문을 함께 싣는 이유**: 관계가 실재해도 **이번 개정 내용과 무관한 경우가
상당수다.** 실측(2026년 세법개정안 11건, 후보 18건) 기준 약칭 정리
(`"조세조약"` 정의 이관)나 대응 개념이 없는 개정(소득세법의 부동산임대업 세분 →
법인세법에는 그 소득 구분 자체가 없음)이 절반 가까이 섞였다. 지시문 한 줄이면
사람이 몇 초 만에 가른다.

**판정 3단계**: `missing`(그 법 개정안은 묶음에 있는데 대응 조문 미개정 — 검토 후보) ·
`covered`(함께 개정됨) · `pending`(그 법 개정안이 묶음에 없어 보류).

**스코프 한계**: 병행 후보 생성(`build_parallel_candidates._LAW_PAIRS`)이
법인세↔소득세·법인세↔부가세(및 각 시행령) 4쌍으로 하드코딩돼 있다. 인용 그래프를
32법령으로 넓혀도 병행 관계는 늘지 않는다. 다만 이는 결함이라기보다 실체에 가깝다 —
병행개정은 '같은 위계·같은 취지' 관계인데, 종합부동산세법의 상대는 재산세(지방세법)라
추적 밖이고 국세기본법·국세징수법은 절차법, 관세법은 별도 영역이다.
`laws_with_parallel_relations()`가 '등재됨'이 아니라 '병행 상대가 있음'으로 판별해
이 구분을 CLI 경고에 반영한다.

---

### pdf_bill_text.py + renumber_scan.py

**역할**: 입법예고 개정법률안(PDF)에서 **번호 밀림 인용 정비 누락**을 찾는다.
"내용상 함께 고쳤어야 할 조문"이 아니라, 기계적으로 확정되는 누락만 본다.

**문제**: 개정문이 `제95조제3항 및 제4항을 각각 제10항 및 제11항으로 한다`처럼 항·호·목
번호를 밀면, 그 번호를 인용하던 모든 조문의 인용이 다른 규정을 가리키게 된다.
누락되면 조문이 조용히 오작동한다 — 사람 눈으로는 가장 놓치기 쉬운 유형.

**흐름** (전 구간 결정적, LLM 0회):

| 단계 | 모듈 | 내용 |
|------|------|------|
| 0 | `pdf_bill_text.unwrap` | PDF 강제 개행 복원 (아래 설명) |
| 1 | `draft_bill_parser.find_amendment_body` | 개정문 본문 절단 |
| 2 | `renumber_scan.renumber_events` | 지시문에서 조·항·호·목 이동 사건 추출 |
| 3 | `citation_graph.back_citation_edges` | 이동 대상 조를 인용하는 엣지 전부 조회 |
| 4 | `renumber_scan.citation_fixed` | 구·신 표기 대조로 실제 정비 여부 확인 |

**PDF 개행 문제**: HWPX는 '한 지시문 = 한 문단'이지만 PDF는 조판 폭에서 문장이 끊긴다.
그대로 넘기면 서술어("…로 한다")가 다음 줄로 밀려 지시문 인식이 통째로 실패한다
(소득세법안 기준 지시문 9건 → 복원 후 27건). `unwrap()`이 머리 토큰(조·항·호·목 기호)이
아닌 줄을 직전 줄에 이어 붙여 원형을 복원한다.

**판정 6단계**: `missing`(같은 법인데 미개정) · `missing_other`(같은 회차 타법안이 그 조문
미개정) · `touched`/`touched_other`(조는 건드렸으나 구·신 표기 대조 실패) ·
`other_law`(회차에 그 법 개정안 없음) · `decree`(위임법령 후속개정) · `covered`/`covered_other`(정비 확인).

'조를 개정했다'와 '그 인용을 고쳤다'를 나눈 이유: 다른 사유로 그 조를 손댔을 뿐
인용 정비는 빠진 경우가 실제로 발생하며, 조 단위 판정은 이를 통과시킨다.

**오탐 차단**: 문구 치환(`"제20조"를 "제20조, 제21조"로`)과 신설 조문 본문(`⑧ 제7항을
적용할 때…`)은 이동이 아니다. 조 전체 인용(`제33조부터 제39조까지`)은 항·호·목 이동과
무관하므로 제외하되, 대상 조를 특정하지 못한 인용은 확인 대상으로 남긴다(누락 방지).

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

**스코프 (32법령, 2026-08 확장)**: 소득·법인·부가·상증·조특 5개 법령군에 관세법·국세기본법·
국세징수법·국제조세조정에 관한 법률·농어촌특별세법·종합부동산세법 6개 군을 더했다
(각 법률 + 시행령 + 시행규칙, 농특세법 시행규칙은 부존재).

스코프 목록은 `core.law_freshness.monitored_law_names()`가 만들고 manifest를 거쳐
`--all` 빌드에 들어간다. 출처는 둘로 나뉜다:

- `config.PARALLEL_LAWS` — 유사 취지로 **함께 고쳐야 하는** 법령 매핑 (병행 탐지가 소비)
- `config.CITATION_GRAPH_EXTRA_LAWS` — 병행 대상은 아니지만 **인용 관계가 실재하는** 법령

국세기본법 같은 절차법을 `PARALLEL_LAWS`에 넣으면 병행 탐지가 오작동하므로 분리했다.

**manifest 갱신 시 판(版) 후퇴 방지**: 법제처 검색 API가 같은 법령명에 늘 최신 시행일 판을
돌려주지는 않는다(소득세법: 기록 20260421 → 검색 20260101). 그대로 받으면 조번호가 구판으로
어긋나므로 `refresh_manifest()`가 시행일이 더 늦은 쪽을 남긴다. 또 `_resolve_mst()`는
이름이 안 맞으면 빈 값을 돌려준다 — 검색 첫 결과로 폴백하면 없는 법령(농어촌특별세법
시행규칙)이 다른 법령 MST로 둔갑해 유령 법령이 생긴다.

**열거 체인 단절 → 유령 자기참조 엣지 (해결)**: 스코프 확장 직후 '범위 초과 타깃'이
38 → 121건으로 늘었다. 원인은 `_resolve_enumerated_law_names`의 열거 체인이 부스러기에서
끊겨, 뒤따르는 맨 조번호가 출처법으로 오귀속된 것이다. 농어촌특별세법 시행령 제4조가
전형인데 — 조특법·관세법·지방세특례제한법 감면조문을 수십 개씩 열거하는 조문이라 —
농특세령(12개 조)이 자기 제96조를 인용하는 유령 엣지가 91건 실렸다.

끊던 부스러기 4종을 모두 흡수하도록 고쳤다:

| 부스러기 | 예 | 조치 |
|---|---|---|
| 앞 인용에 딸린 항·호 범위 | `제93조제4호부터 제7호까지 및` | `부터·까지·내지`를 filler에 추가 |
| 괄호·대괄호 한정어구 | `제72조제1항(…제외한다),` | `_bracket_mask()`로 마스킹 후 앵커·간격 판정 |
| 호·목 가지번호 꼬리 | `제13조제2항제1호의2,` | 간격 선두의 `의N` 제거 |
| 위치어 | `각 호 외의 부분 및` | `외의 부분`을 filler에 추가 |

또 `_resolve_range_law_names`가 **조 범위만** 처리해 항·호 범위(`「지방세법」 제9조제3항부터
제5항까지`)에는 법령명이 안 붙었다. 그 인용 자체가 오귀속될 뿐 아니라 뒤 열거의 앵커까지
무력화해 연쇄로 번졌다 — `is_range` 전체로 넓혔다.

결과: 범위 초과 121 → **50건**, 농특세령 자기참조 91 → 13건(그중 실존하지 않는 조 대상 1건).
과탐 방지 가드(실질 어구가 끼면 전파 안 함)는 그대로다 —
회귀는 `test_citation_parser.test_enumeration_chain_survives_fillers`가 지킨다.

**잔존 한계**: `동법 부칙 제13조 내지 제19조`처럼 **폐지 법률을 '동법'으로 받는** 인용은
아직 출처법으로 떨어진다(농특세령 1건).

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
| 병행법령 컨센서스 2회 방식 | 1회 판단 시 false positive 너무 많음 (라이브 폴백 경로에만 잔존) |
| Hallucination 필터 (조문 번호 존재 확인) | GPT가 없는 조문 번호를 날조하는 케이스 발생 (라이브 폴백 경로에만 잔존) |
| 병행 매칭을 사전 배치 매트릭스로 전환 | 런타임 키워드 상한 20개의 구조적 누락 제거 + 사용자 수와 무관한 비용 구조 (검사 기능 무료 배포 가능) |
| 쌍별 판별(discriminative) 프롬프트 | 두 조문을 입력으로 주고 yes/no만 판단 — hallucination 원천 차단, 컨센서스 중복 호출 불필요 |
| 상증세법은 citation 레이어만 연결 | 법인세·소득세와 유사취지 병행이 아닌 인용·준용 관계 (시가평가·특수관계인 등) |
| `@st.cache_data(ttl=3600)` UI 레이어 캐시 | `get_law_text` 내부 OCR 순차 호출로 20~60초 소요, 재조회 시 즉시 반환 필요 |
| `_img_cache` 300개 상한 | 무제한 dict → 장시간 운영 시 메모리 증가 |
| `BUCHIK_TYPES` 삭제 | 영문 코드 매핑값이 어디서도 참조되지 않는 dead code |
