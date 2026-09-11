# DEMIS Schema Semantic Search PoC

관계구조가 복잡한 의료 DB Schema를 자동 분석·임베딩하여, 자연어로 관련 Table / Column / Relationship을 검색할 수 있는지 검증하는 기술 PoC입니다.

## 1. 현재 Step

**Step 3 — CPU-only Embedding Pipeline + pgvector**

Raw Schema Catalog를 기반으로 deterministic Search Document를 만들고,
CPU-only BGE-M3(또는 Fake Provider)로 Embedding을 생성하여 `schema_catalog`의 pgvector 컬럼에 저장합니다.

이번 Step에서는 Semantic Search / Keyword Search / Hybrid Search / 자연어 검색 UI를 구현하지 않습니다.

## 2. Step 3 Architecture

```text
medical-db
   ↓ metadata only

Schema Analyzer
   ↓

Raw Schema Catalog
   ↓

SearchDocumentBuilder
   ↓

catalog_search_document
   ↓

BgeM3EmbeddingProvider (CPU-only) / FakeEmbeddingProvider
   ↓

catalog_embedding
VECTOR(1024)
```

원칙:

- Raw Catalog는 Source of Truth
- Search Document / Embedding은 언제든 재생성 가능한 Derived Data
- Generative LLM 사용 금지 (Embedding 모델만 허용)
- Schema Metadata만 Embedding (환자 Row / Seed 업무 데이터 제외)

## 3. Search Document

| Object Type | 포함 내용 |
|------------|-----------|
| TABLE | schema/table/comment, columns+comments, PK, UNIQUE, FK |
| COLUMN | parent table/comment, column/comment/type, PK/UNIQUE, FK target |

Natural Key 예:

- `table:{source_id}:{schema}:{table}`
- `column:{source_id}:{schema}:{table}:{column}`

동일 Catalog로 rebuild하면 동일 `searchable_text` / `document_fingerprint`가 나와야 합니다.

## 4. Embedding Model (CPU-only)

기본 설정:

```env
EMBEDDING_PROVIDER=bge_m3   # 또는 fake
EMBEDDING_MODEL_NAME=BAAI/bge-m3
EMBEDDING_DEVICE=cpu
EMBEDDING_DIMENSION=1024
EMBEDDING_BATCH_SIZE=8
EMBEDDING_MAX_SEQ_LENGTH=1024
EMBEDDING_NORMALIZE=true
```

Offline / 폐쇄망:

```env
EMBEDDING_MODEL_PATH=/models/local/bge-m3
HF_HUB_OFFLINE=true
```

모델 선택 우선순위:

1. `EMBEDDING_MODEL_PATH`가 유효하면 Local Path
2. 그렇지 않으면 `EMBEDDING_MODEL_NAME`

모델 파일은 Git에 커밋하지 않습니다 (`models/`, `model-cache/`는 `.gitignore`).

### 모델 다운로드

Backend 시작 시 자동 다운로드하지 않습니다 (lazy load).

```bash
docker compose exec backend python scripts/download_embedding_model.py --output /models/local/bge-m3
# 또는 host에서
cd backend && python scripts/download_embedding_model.py --output ../models/bge-m3
```

## 5. API

| Method | Path | 설명 |
|--------|------|------|
| POST | `/api/v1/schema/analyze` | Schema Analyze (Embedding 자동 실행 없음) |
| POST | `/api/v1/embeddings/documents/rebuild` | Search Document 생성/갱신 |
| POST | `/api/v1/embeddings/run` | active document Embedding |
| GET | `/api/v1/embeddings/runs` | Embedding Run 이력 |
| GET | `/api/v1/embeddings/runs/{run_id}` | Run 상세 |
| GET | `/api/v1/embeddings/stats` | document/embedding/stale 통계 |
| GET | `/api/v1/embeddings/documents` | Search Document 목록 |
| GET | `/api/v1/embeddings/documents/{id}` | Search Document 상세 |

검색 Query API (`/search`, `/semantic-search`, `/query`)는 Step 4 범위입니다.

### Incremental Embedding

동일 `model_key` + 동일 `document_fingerprint`이면 skip 합니다.

## 6. Docker Compose

```bash
cp .env.example .env
mkdir -p models
docker compose up --build
```

서비스:

- medical-db :5433
- catalog-db :5434 (pgvector)
- backend :8000
- frontend :8501

Compose 기본 `EMBEDDING_PROVIDER=fake` (빠른 기동/CI용).
실제 BGE-M3:

```bash
EMBEDDING_PROVIDER=bge_m3 docker compose up --build backend
```

## 7. 테스트

```bash
# Fake Provider 기반 (기본, 모델 다운로드 없음)
bash scripts/run_tests.sh

# 또는
docker compose exec -e EMBEDDING_PROVIDER=fake backend pytest -q
```

실제 BGE-M3 smoke (선택):

```bash
docker compose exec -e EMBEDDING_PROVIDER=bge_m3 -e RUN_BGE_M3_SMOKE=1 backend \
  pytest -q tests/test_bge_m3_smoke.py
```

## 8. pgvector

- Extension: `CREATE EXTENSION IF NOT EXISTS vector;`
- Fresh volume: init SQL
- Existing volume: backend bootstrap에서도 안전하게 활성화
- Dimension: VECTOR(1024)
- HNSW/IVFFlat index는 Step 4에서 검토

## 9. 현재 제한사항

- Semantic / Keyword / Hybrid Search 미구현
- FK Relation Expansion 검색 미구현
- Synonym Dictionary / Query Expansion 미구현
- 자연어 검색 UI 미구현
- Generative LLM / NL→SQL 미사용

## 10. Step 4 제안

1. Semantic Search (query embedding + cosine similarity)
2. Keyword Search
3. Synonym Query Expansion
4. Hybrid Ranking (RRF 등)
5. FK Relation Expansion

## Roadmap

| Step | 내용 | 상태 |
|------|------|------|
| 1 | Foundation + Mock Medical DB | 완료 |
| 2 | Schema Analyzer + Schema Catalog | 완료 |
| 3 | CPU-only Embedding + pgvector | **현재** |
| 4 | Hybrid Search + FK Expansion | 예정 |
| 5 | Streamlit Schema Explorer | 예정 |
| 6 | 정확도 평가 / Schema Change Detection | 예정 |

## License

PoC / internal evaluation use.
