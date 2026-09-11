# DEMIS Schema Semantic Search PoC

관계구조가 복잡한 의료 DB Schema를 자동 분석·임베딩하여, 자연어로 관련 Table / Column / Relationship을 검색할 수 있는지 검증하는 기술 PoC입니다.

## 1. 현재 Step

**Step 4 — Semantic / Keyword Hybrid Search + Medical Terminology Expansion + FK Relation Expansion**

생성형 LLM 없이 자연어 의료 업무 요청을 입력하면,
Schema Metadata Embedding + Keyword + 의료용어 사전 + FK 관계 정보를 이용해
관련 Table / Column / 관계 경로 후보를 탐색합니다.

자연어 → SQL 생성은 **구현하지 않습니다**.

## 2. Search Architecture

```text
User NL Query
   ↓
Query Normalizer
   ↓
Medical Terminology Expander  (ON/OFF)
   ↓
┌────────────────┬────────────────┐
│ Semantic Search│ Keyword Search │
│ BGE-M3 + pgvector│ PG FTS/token  │
└────────┬───────┴────────┬───────┘
         └──────┬─────────┘
                ↓
           Hybrid Ranker (RRF)
                ↓
          Seed Schema Results
                ↓
         FK Relation Expansion (BFS)
                ↓
         Final Schema Candidates
```

## 3. Search Modes

| Mode | 설명 |
|------|------|
| `semantic` | Query Embedding ↔ Document Embedding cosine |
| `keyword` | Physical name / comment token matching (PG only) |
| `hybrid` | RRF fusion of semantic + keyword ranks (default) |

API:

```http
POST /api/v1/search/schema
```

```json
{
  "query": "최근 간수치 검사 결과",
  "mode": "hybrid",
  "top_k": 10,
  "object_type": "ALL",
  "expand_terms": true,
  "expand_relations": true,
  "max_relation_hops": 2,
  "debug": false
}
```

## 4. Model Identity (Path-independent)

Loading path와 logical identity를 분리합니다.

```env
EMBEDDING_MODEL_NAME=BAAI/bge-m3
EMBEDDING_MODEL_REVISION=default
EMBEDDING_MODEL_PATH=/models/local/bge-m3
```

`model_key` 예:

```text
BAAI/bge-m3|rev=default|dim=1024|norm=true|maxlen=1024
```

동일 모델이 서버마다 다른 Path에 있어도 `model_key`는 같습니다.
Document Embedding과 Query Embedding은 **동일 model_key**를 사용합니다.

## 5. Fake Provider Protection

기본 Compose는 `EMBEDDING_PROVIDER=fake` (CI/빠른 기동).

- Fake 상태에서 Semantic/Hybrid는 기본 차단 (`SEMANTIC_PROVIDER_NOT_AVAILABLE`)
- 테스트에서만 `ALLOW_FAKE_SEMANTIC_SEARCH=true`로 허용
- Keyword mode는 Fake에서도 동작
- Streamlit에 Fake 경고 표시

## 6. Medical Terminology Dictionary

파일: `backend/app/resources/medical_terms.json`

- Concept 단위 aliases (간기능/혈당/신장/고혈압/영상판독/퇴원요약/처방/입원 등)
- **정답 Table/Column명을 넣지 않음** (평가 누수 방지)
- `expand_terms=true|false`로 ON/OFF 비교 가능

## 7. Hybrid Ranking (RRF)

```text
rrf = 1/(K + semantic_rank) + 1/(K + keyword_rank)
K default = 60
```

한쪽 검색에만 등장한 Document도 포함합니다.

## 8. FK Relation Expansion

- `catalog_relation` 기반 Python BFS (Inbound/Outbound)
- `expand_relations` ON/OFF, `max_relation_hops` (기본 2, 최대 4)
- Cycle-safe visited set
- RELATED 결과는 DIRECT score와 분리 (`match_type=RELATED`)

## 9. Keyword Search

- Elasticsearch 미사용
- PostgreSQL `simple` FTS + ILIKE / identifier boost
- Physical name (`tb_lab_rst`, `exm_cd`) 강한 매칭

## 10. Streamlit UI

`http://localhost:8501`

- Query input, mode, expansion options, top_k, hops
- Direct results + Related FK paths + timings
- NL→SQL UI 없음

## 11. 실행

```bash
cp .env.example .env
mkdir -p models
docker compose up --build

# Fake(기본)
curl -s -X POST localhost:8000/api/v1/search/schema \
  -H 'Content-Type: application/json' \
  -d '{"query":"tb_lab_rst","mode":"keyword"}'

# Real BGE-M3
EMBEDDING_PROVIDER=bge_m3 \
EMBEDDING_MODEL_PATH=/models/local/bge-m3 \
HF_HUB_OFFLINE=1 \
  docker compose up backend
```

모델 다운로드:

```bash
cd backend && python scripts/download_embedding_model.py --output ../models/bge-m3
```

## 12. 테스트

```bash
docker compose exec -e EMBEDDING_PROVIDER=fake -e ALLOW_FAKE_SEMANTIC_SEARCH=true \
  -e CATALOG_DB_HOST=catalog-db -e MEDICAL_DB_HOST=medical-db \
  -e CATALOG_DB_PORT=5432 -e MEDICAL_DB_PORT=5432 \
  backend pytest -q
```

## 13. Baseline Queries (평가용 Gold는 Step 6)

1. 최근 간수치 검사 결과
2. 환자의 최근 혈당 검사
3. 신장기능 검사 결과
4. 최근 처방 약품
5. 고혈압 진단 이력
6. 최근 영상 판독 결과
7. 최근 입원 기록
8. 퇴원요약 문서
9. 검사결과값이 저장된 컬럼
10. exm_cd 컬럼

## 14. 이번 Step에서 하지 않은 것

- 자연어 → SQL / Dynamic SQL / SQL 실행
- Query Router / Approved Template
- RAG / 생성형 LLM
- 실제 DEMIS 연결 / 환자 데이터 조회

## 15. Step 5 / 6 제안

- Step 5: Search UX 고도화, evidence 설명, 결과 저장/비교
- Step 6: Gold set 기반 Recall@K / MRR 평가, mode ablation (semantic vs hybrid vs expansion)
