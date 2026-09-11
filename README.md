# DEMIS Schema Semantic Search PoC

관계구조가 복잡한 의료 DB Schema를 자동 분석·임베딩하여, 자연어로 관련 Table / Column / Relationship을 검색하고,
Gold Set 기반 정량지표로 재현 가능한 평가를 수행하는 기술 PoC입니다.

## 1. 현재 Step

**Step 5 — Gold Set 기반 Schema Search 정량평가 자동화**

Step 1~4.1의 Search Pipeline을 **Evaluation Baseline으로 고정**한 뒤,
Gold Query Set으로 Semantic / Keyword / Hybrid를 자동 실행하고
Top-1 / Hit@K / Mean Recall@K / MRR / Latency를 산출합니다.

- 검색 알고리즘을 평가 결과에 맞춰 튜닝하지 않습니다.
- 자연어 → SQL / 생성형 LLM은 구현하지 않습니다.

## 2. Search Baseline (Freeze)

| Item | Value |
|------|-------|
| Embedding | BAAI/bge-m3, CPU, dim=1024 |
| Semantic | pgvector exact cosine |
| Keyword | PostgreSQL FTS/token |
| Hybrid | RRF K=60 |
| Terminology | `backend/app/resources/medical_terms.json` |
| Relation | FK BFS max hop 2 |
| LLM / NL→SQL | None |

## 3. Evaluation 목적

생성형 LLM 없이 Schema Metadata + BGE-M3 + Keyword + Terminology + FK 정보가
Schema Discovery에서 어느 정도 정확도를 보이는지 **재현 가능한 정량지표**로 검증합니다.

## 4. Gold Dataset

**Source of Truth:** `backend/evaluation/gold_schema_queries.json`

- 약 45 Query
- Categories: `clinical_natural_language`, `paraphrase`, `schema_semantic`, `physical_identifier`, `ambiguous`, `relation`
- Identity 형식: `public.tb_lab_rst`, `public.tb_lab_rst.rst_val`
- Gold는 Evaluation Runner만 읽습니다 (Search Logic / Dictionary에 주입 금지)

Gold 구조 예:

```json
{
  "id": "Q001",
  "category": "clinical_natural_language",
  "query": "최근 간수치 검사 결과",
  "gold": {
    "primary_tables": ["public.tb_lab_rst"],
    "acceptable_tables": ["public.tb_lab_mst", "public.tb_lab_ord"],
    "relevant_columns": ["public.tb_lab_rst.rst_val"],
    "relation_tables": ["public.tb_lab_rst", "public.tb_lab_ord"]
  }
}
```

## 5. Experiments

| Name | mode | expand_terms | expand_relations |
|------|------|--------------|------------------|
| keyword_no_expansion | keyword | false | false |
| semantic_no_expansion | semantic | false | false |
| semantic_expansion | semantic | true | false |
| hybrid_no_expansion | hybrid | false | false |
| hybrid_expansion | hybrid | true | false |
| hybrid_expansion_relation | hybrid | true | true (hop=2) |

## 6. Metric 정의

- **Top-1 Primary Accuracy**: 첫 Table Candidate ∈ primary_tables
- **Hit@K (`hit_rate_at_k`)**: Top-K에 Relevant(primary∪acceptable) 1개 이상
- **Mean Recall@K (`mean_recall_at_k`)**: |Top-K ∩ Relevant| / |Relevant|
- **MRR**: 첫 Relevant Table rank의 reciprocal mean
- **Column Hit@K / Column MRR**: relevant_columns가 있는 Query만
- **Relation Recall**: Direct∪Related 에서 gold relation_tables coverage
- COLUMN Document도 부모 Table로 환산 후 Table Candidate Dedup (첫 등장 rank)

## 7. Runner

```bash
# Official (BGE-M3 required)
docker compose exec \
  -e EMBEDDING_PROVIDER=bge_m3 \
  -e EMBEDDING_MODEL_PATH=/models/local/bge-m3 \
  -e HF_HUB_OFFLINE=1 \
  -e PYTHONPATH=/app \
  backend python -m app.evaluation.runner \
    --gold /app/evaluation/gold_schema_queries.json \
    --output /app/evaluation/results/run_manual
```

Fake Provider는 Official Evaluation에서 차단됩니다 (`--allow-fake`는 unit/dev only).

본 평가 전 Warm-up Query 1회를 수행하며, Warm-up latency는 통계에서 제외합니다.

## 8. Output 파일

`backend/evaluation/results/<timestamp>/`

- `summary.json` / `summary.csv` / `summary.txt`
- `query_results.jsonl` / `query_results.csv`
- `failures.csv`
- `category_summary.csv`
- `run_metadata.json` (model_key, gold hash, git SHA, timings settings 등)

## 9. Evaluation Viewer

Streamlit `Evaluation Results` 탭에서 저장된 Run을 조회합니다.

- Experiment Comparison / Hit@5·MRR·Latency chart
- Category metrics
- Failure list
- Query detail (Gold / Top / Expansion / Timing)

## 10. 평가 누수 방지 / Search Freeze

- Gold Table/Column을 Terminology·Search Document에 넣지 않음
- Query별 Hardcoding / Ranking Weight 튜닝 금지
- Evaluation은 `SchemaSearchService.search()`를 그대로 호출
- 결과 순서 변조 금지

## 11. 실행 / 테스트

```bash
cp .env.example .env
docker compose up --build

docker compose exec -e EMBEDDING_PROVIDER=fake -e ALLOW_FAKE_SEMANTIC_SEARCH=true \
  -e CATALOG_DB_HOST=catalog-db -e MEDICAL_DB_HOST=medical-db \
  -e CATALOG_DB_PORT=5432 -e MEDICAL_DB_PORT=5432 \
  backend pytest -q
```

## 12. 이번 Step에서 하지 않은 것

- Search Weight / Dictionary 튜닝
- HNSW / LLM / SQL 생성·실행 / Query Router / RAG
- 실제 DEMIS / 환자 데이터 검색
