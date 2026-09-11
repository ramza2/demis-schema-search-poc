"""Download BGE-M3 embedding model for local / offline use.

Does NOT run during backend startup. Use this helper in development
or to prepare an offline model directory for air-gapped environments.

Examples:
  python scripts/download_embedding_model.py
  python scripts/download_embedding_model.py --output /models/bge-m3
"""

from __future__ import annotations

import argparse
from pathlib import Path


def main() -> None:
    parser = argparse.ArgumentParser(description="Download BAAI/bge-m3 for offline embedding")
    parser.add_argument(
        "--model-name",
        default="BAAI/bge-m3",
        help="Hugging Face model id (default: BAAI/bge-m3)",
    )
    parser.add_argument(
        "--output",
        default="./models/bge-m3",
        help="Local directory to store the model (default: ./models/bge-m3)",
    )
    args = parser.parse_args()

    output = Path(args.output).resolve()
    output.mkdir(parents=True, exist_ok=True)

    from sentence_transformers import SentenceTransformer

    print(f"Downloading {args.model_name} -> {output}")
    model = SentenceTransformer(args.model_name, device="cpu")
    model.save(str(output))
    print("Done. Set EMBEDDING_MODEL_PATH to this directory for offline load:")
    print(f"  EMBEDDING_MODEL_PATH={output}")
    print("Optional: HF_HUB_OFFLINE=1")


if __name__ == "__main__":
    main()
