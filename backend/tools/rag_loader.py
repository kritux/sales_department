"""
Load .md / .pdf / .txt docs into ChromaDB under the per-tenant namespace
f"rag_{tenant_id}".  Each stored chunk carries metadata:
    tenant_id, filename, chunk_index, loaded_at

CLI (run from backend/):
    python tools/rag_loader.py --tenant tenant_001 --docs ../knowledge_base/growth_bizon/
    python tools/rag_loader.py --tenant tenant_001 --docs ../knowledge_base/ --dry-run

DRY_RUN behaviour:
  - Reads and parses every file.
  - Logs how many chunks would be written.
  - Skips all ChromaDB writes.
  Controlled by --dry-run flag OR DRY_RUN=true in .env (settings.dry_run).
  Either source being true activates dry-run mode.
"""

import argparse
import logging
import sys
import uuid
from datetime import date, datetime
from pathlib import Path
from typing import List, Optional

from config.settings import settings

# chromadb is imported lazily inside load_docs() so that dry-run mode and
# tests work without the full dependency stack installed.

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

CHUNK_SIZE = 1_000       # target characters per chunk
CHUNK_OVERLAP = 150      # overlap between consecutive chunks (context continuity)
SUPPORTED_EXTENSIONS = {".md", ".txt", ".pdf"}

_REPO_ROOT = Path(__file__).resolve().parents[2]   # growth-bizon-sales-ai/
_CHROMA_PATH = str(_REPO_ROOT / "chroma_db")
_LOGS_ROOT = _REPO_ROOT / "logs"


# ---------------------------------------------------------------------------
# Logging
# ---------------------------------------------------------------------------

def _get_logger(tenant_id: str) -> logging.Logger:
    log_dir = _LOGS_ROOT / tenant_id
    log_dir.mkdir(parents=True, exist_ok=True)
    log_file = log_dir / f"{date.today().isoformat()}.log"

    logger = logging.getLogger(f"rag_loader.{tenant_id}")
    if logger.handlers:
        return logger

    logger.setLevel(logging.DEBUG)
    fmt = logging.Formatter("%(asctime)s [%(levelname)s] %(name)s — %(message)s")

    fh = logging.FileHandler(log_file, encoding="utf-8")
    fh.setFormatter(fmt)
    fh.setLevel(logging.DEBUG)

    ch = logging.StreamHandler(sys.stdout)
    ch.setFormatter(fmt)
    ch.setLevel(logging.INFO)

    logger.addHandler(fh)
    logger.addHandler(ch)
    return logger


# ---------------------------------------------------------------------------
# File parsing
# ---------------------------------------------------------------------------

def _parse_md_or_txt(path: Path) -> str:
    return path.read_text(encoding="utf-8", errors="replace")


def _parse_pdf(path: Path) -> str:
    """Try pypdf first; fall back to LlamaIndex SimpleDirectoryReader."""
    try:
        import pypdf
        reader = pypdf.PdfReader(str(path))
        pages = [page.extract_text() or "" for page in reader.pages]
        return "\n\n".join(pages)
    except ImportError:
        pass

    try:
        from llama_index.core import SimpleDirectoryReader
        docs = SimpleDirectoryReader(input_files=[str(path)]).load_data()
        return "\n\n".join(d.text for d in docs if d.text)
    except ImportError:
        pass

    raise RuntimeError(
        f"Cannot parse PDF '{path.name}': "
        "install pypdf (`pip install pypdf`) or llama-index-readers-file."
    )


def _parse_file(path: Path) -> str:
    suffix = path.suffix.lower()
    if suffix in {".md", ".txt"}:
        return _parse_md_or_txt(path)
    if suffix == ".pdf":
        return _parse_pdf(path)
    raise ValueError(f"Unsupported extension: {suffix}")


# ---------------------------------------------------------------------------
# Chunking
# ---------------------------------------------------------------------------

def _chunk_text(text: str) -> List[str]:
    """Sliding-window character chunker. Returns non-empty stripped chunks."""
    chunks: List[str] = []
    start = 0
    step = max(CHUNK_SIZE - CHUNK_OVERLAP, 1)
    while start < len(text):
        chunk = text[start : start + CHUNK_SIZE].strip()
        if chunk:
            chunks.append(chunk)
        start += step
    return chunks


# ---------------------------------------------------------------------------
# File discovery
# ---------------------------------------------------------------------------

def _collect_files(docs_path: Path) -> List[Path]:
    if docs_path.is_file():
        if docs_path.suffix.lower() in SUPPORTED_EXTENSIONS:
            return [docs_path]
        return []
    return sorted(
        p
        for p in docs_path.rglob("*")
        if p.is_file() and p.suffix.lower() in SUPPORTED_EXTENSIONS
    )


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def load_docs(
    tenant_id: str,
    docs_path: str,
    dry_run: Optional[bool] = None,
) -> dict:
    """
    Load all supported docs from docs_path into ChromaDB collection
    f"rag_{tenant_id}".

    Args:
        tenant_id:  Tenant identifier, e.g. "tenant_001".
        docs_path:  Directory or single file to load.
        dry_run:    If True, parse + log but skip ChromaDB writes.
                    If None, falls back to settings.dry_run.

    Returns:
        dict with keys: files_processed, chunks_loaded, skipped.
        In dry-run mode also includes dry_run_chunks (would-be chunk count).
    """
    is_dry_run = dry_run if dry_run is not None else settings.dry_run  # type: bool
    collection_name = f"rag_{tenant_id}"
    path = Path(docs_path).expanduser().resolve()
    logger = _get_logger(tenant_id)

    logger.info(
        "RAG loader starting | tenant=%s | path=%s | dry_run=%s",
        tenant_id, path, is_dry_run,
    )

    if not path.exists():
        raise FileNotFoundError(f"docs path not found: {path}")

    files = _collect_files(path)
    if not files:
        logger.warning("No supported files (.md .txt .pdf) found in: %s", path)
        return {"files_processed": 0, "chunks_loaded": 0, "skipped": 0}

    logger.info(
        "Files discovered (%d): %s",
        len(files), [f.name for f in files],
    )

    # ------------------------------------------------------------------
    # DRY-RUN: parse only, no ChromaDB writes
    # ------------------------------------------------------------------
    if is_dry_run:
        logger.info("[DRY_RUN] Parsing docs — ChromaDB writes are skipped")
        dry_run_chunks = 0
        parse_errors = 0
        for file_path in files:
            try:
                text = _parse_file(file_path)
                chunks = _chunk_text(text)
                logger.info(
                    "[DRY_RUN] %s → %d chunk(s) would be written to %s",
                    file_path.name, len(chunks), collection_name,
                )
                dry_run_chunks += len(chunks)
            except Exception as exc:
                logger.error("[DRY_RUN] Parse failed for %s: %s", file_path.name, exc)
                parse_errors += 1
        logger.info(
            "[DRY_RUN] Done | files=%d | would-load chunks=%d | parse_errors=%d",
            len(files), dry_run_chunks, parse_errors,
        )
        return {
            "files_processed": len(files),
            "chunks_loaded": 0,
            "skipped": parse_errors,
            "dry_run_chunks": dry_run_chunks,
        }

    # ------------------------------------------------------------------
    # PRODUCTION: write to ChromaDB
    # ------------------------------------------------------------------
    import chromadb
    from chromadb.utils import embedding_functions

    client = chromadb.PersistentClient(path=_CHROMA_PATH)
    ef = embedding_functions.DefaultEmbeddingFunction()
    collection = client.get_or_create_collection(
        name=collection_name,
        embedding_function=ef,
        metadata={"tenant_id": tenant_id},
    )

    loaded_at = datetime.utcnow().isoformat()
    total_chunks = 0
    skipped = 0

    for file_path in files:
        try:
            text = _parse_file(file_path)
            chunks = _chunk_text(text)
            if not chunks:
                logger.warning("Empty content after parsing %s — skipping", file_path.name)
                skipped += 1
                continue

            ids = [str(uuid.uuid4()) for _ in chunks]
            metadatas = [
                {
                    "tenant_id": tenant_id,
                    "filename": file_path.name,
                    "chunk_index": i,
                    "loaded_at": loaded_at,
                }
                for i in range(len(chunks))
            ]

            collection.add(documents=chunks, ids=ids, metadatas=metadatas)
            logger.info(
                "Loaded %s → %d chunk(s) → collection '%s'",
                file_path.name, len(chunks), collection_name,
            )
            total_chunks += len(chunks)

        except Exception as exc:
            logger.error("Failed to load %s: %s", file_path.name, exc)
            skipped += 1

    logger.info(
        "RAG load complete | tenant=%s | files=%d | chunks=%d | skipped=%d",
        tenant_id, len(files), total_chunks, skipped,
    )
    return {
        "files_processed": len(files),
        "chunks_loaded": total_chunks,
        "skipped": skipped,
    }


# ---------------------------------------------------------------------------
# CLI entry point
# ---------------------------------------------------------------------------

def main() -> None:
    parser = argparse.ArgumentParser(
        description="Load docs into ChromaDB RAG namespace for a tenant."
    )
    parser.add_argument(
        "--tenant", required=True,
        help="Tenant ID, e.g. tenant_001",
    )
    parser.add_argument(
        "--docs", required=True,
        help="Path to a directory or single .md / .txt / .pdf file",
    )
    parser.add_argument(
        "--dry-run", action="store_true", default=False,
        help="Parse and log without writing to ChromaDB (overrides DRY_RUN env var)",
    )
    args = parser.parse_args()

    # CLI --dry-run OR settings.dry_run = True → dry-run mode
    effective_dry_run = args.dry_run or settings.dry_run

    result = load_docs(
        tenant_id=args.tenant,
        docs_path=args.docs,
        dry_run=effective_dry_run,
    )
    print(result)


if __name__ == "__main__":
    main()
