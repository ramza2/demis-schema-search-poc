# DEMIS Schema Semantic Search PoC

관계구조가 복잡한 의료 DB Schema를 자동 분석·임베딩하여, 자연어로 관련 Table / Column / Relationship을 검색할 수 있는지 검증하는 기술 PoC입니다.

## 1. 현재 Step

**Step 4.1 — Search Evaluation Readiness** (Step 4 Hybrid Search 보완)

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

**Source of Truth:** `backend/app/resources/medical_terms.json` (YAML 미사용)

Concept 구조:

```json
{
  "id": "liver_function",
  "label": "간기능",
  "triggers": ["간수치", "AST", "ALT"],
  "expansion_terms": ["AST", "ALT", "임상검사", "검사결과"]
}
```

| 필드 | 역할 |
|------|------|
| `triggers` | Concept을 식별하는 비교적 고유한 용어 |
| `expansion_terms` | Trigger 이후 Recall을 높이는 용어 (범용어 허용) |

평가 왜곡 방지:

- 범용어(`검사결과`, `진단`, `임상문서`, `encounter`)는 `triggers`에 넣지 않음
- 정답 Table/Column 물리명(`tb_*`, `exm_cd`) 및 Query→Table Mapping 금지
- `AST` / `ALT` / `HbA1c` / `Creatinine` 같은 의료용어는 허용
- `expand_terms=true|false`로 ON/OFF 비교 가능

## 7. Hybrid Ranking (RRF)

```text
rrf = 1/(K + semantic_rank) + 1/(K + keyword_rank)
K default = 60
```

한쪽 검색에만 등장한 Document도 포함합니다.

## 8. FK Relation Expansion (Schema-qualified)

- `catalog_relation` 기반 Python BFS (Inbound/Outbound)
- Node identity: `(schema_name, table_name)` 또는 `catalog_table.id`
- Dedup key: `seed_schema.seed_table -> target_schema.target_table`
- Direct Result에 `schema_name` 포함
- `expand_relations` ON/OFF, `max_relation_hops` (기본 2, 최대 4)
- Cycle-safe visited set (table id)
- RELATED 결과는 DIRECT score와 분리 (`match_type=RELATED`)
- 현재 medical_demo는 `public` 단일 Schema로 동작

## 9. Search Timing

응답 `timings`:

| Key | Semantic | Keyword | Hybrid | Relation ON |
|-----|----------|---------|--------|-------------|
| `query_embedding_ms` | ✓ | | ✓ | |
| `semantic_search_ms` | ✓ | | ✓ | |
| `keyword_search_ms` | | ✓ | ✓ | |
| `relation_expansion_ms` | | | | ✓ |
| `total_ms` | ✓ | ✓ | ✓ | ✓ |

Query Embedding과 pgvector Search 시간을 분리 측정합니다.

## 10. Keyword Search

- Elasticsearch 미사용
- PostgreSQL `simple` FTS + ILIKE / identifier boost
- Physical name (`tb_lab_rst`, `exm_cd`) 강한 매칭

## 11. Streamlit UI

`http://localhost:8501`

- Query input, mode, expansion options, top_k, hops
- Direct results + Related FK paths + timings
- NL→SQL UI 없음

## 12. 실행

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

## 13. 테스트

```bash
docker compose exec -e EMBEDDING_PROVIDER=fake -e ALLOW_FAKE_SEMANTIC_SEARCH=true \
  -e CATALOG_DB_HOST=catalog-db -e MEDICAL_DB_HOST=medical-db \
  -e CATALOG_DB_PORT=5432 -e MEDICAL_DB_PORT=5432 \
  backend pytest -q
```

## 14. Baseline Queries (평가용 Gold는 Step 5/6)

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

## 15. 이번 Step에서 하지 않은 것

- Gold Dataset / Recall@K / MRR / NDCG / 평가 Dashboard
- 자연어 → SQL / Dynamic SQL / SQL 실행
- Query Router / Approved Template / HNSW
- RAG / 생성형 LLM
- 실제 DEMIS 연결 / 환자 데이터 조회

## 16. 다음 Step

- Step 5/6: Gold set 기반 정량평가 (Recall@K / MRR), mode ablation
- 검색 로직 기능 확장은 Step 4.1에서 종료
