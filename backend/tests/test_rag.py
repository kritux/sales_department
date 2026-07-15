"""
Tests for backend/tools/rag_loader.py.
All tests run in DRY_RUN mode — no ChromaDB writes.
"""

import os
import sys
from pathlib import Path

import pytest

# Ensure backend/ is on the path when running from backend/
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from tools.rag_loader import (
    _chunk_text,
    _collect_files,
    _parse_file,
    load_docs,
    CHUNK_SIZE,
    CHUNK_OVERLAP,
    SUPPORTED_EXTENSIONS,
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture()
def tmp_docs(tmp_path):
    """Create a small set of test docs in a temp directory."""
    (tmp_path / "intro.md").write_text("# Hello\n\nThis is a markdown file.", encoding="utf-8")
    (tmp_path / "notes.txt").write_text("Plain text content.\nSecond line.", encoding="utf-8")
    (tmp_path / "ignore.csv").write_text("a,b,c", encoding="utf-8")
    return tmp_path


@pytest.fixture()
def long_doc(tmp_path):
    """A file whose text exceeds CHUNK_SIZE so chunking is exercised."""
    text = "A" * (CHUNK_SIZE * 3)
    p = tmp_path / "long.txt"
    p.write_text(text, encoding="utf-8")
    return tmp_path


# ---------------------------------------------------------------------------
# _collect_files
# ---------------------------------------------------------------------------

class TestCollectFiles:
    def test_ignores_unsupported_extensions(self, tmp_docs):
        files = _collect_files(tmp_docs)
        names = {f.name for f in files}
        assert "ignore.csv" not in names

    def test_finds_md_and_txt(self, tmp_docs):
        files = _collect_files(tmp_docs)
        names = {f.name for f in files}
        assert "intro.md" in names
        assert "notes.txt" in names

    def test_single_file_input(self, tmp_docs):
        single = tmp_docs / "intro.md"
        files = _collect_files(single)
        assert len(files) == 1
        assert files[0].name == "intro.md"

    def test_unsupported_single_file_returns_empty(self, tmp_docs):
        csv_file = tmp_docs / "ignore.csv"
        assert _collect_files(csv_file) == []


# ---------------------------------------------------------------------------
# _parse_file
# ---------------------------------------------------------------------------

class TestParseFile:
    def test_parse_md(self, tmp_docs):
        text = _parse_file(tmp_docs / "intro.md")
        assert "Hello" in text
        assert "markdown" in text

    def test_parse_txt(self, tmp_docs):
        text = _parse_file(tmp_docs / "notes.txt")
        assert "Plain text" in text

    def test_unsupported_extension_raises(self, tmp_docs):
        with pytest.raises(ValueError, match="Unsupported"):
            _parse_file(tmp_docs / "ignore.csv")


# ---------------------------------------------------------------------------
# _chunk_text
# ---------------------------------------------------------------------------

class TestChunkText:
    def test_short_text_is_single_chunk(self):
        text = "Short text."
        chunks = _chunk_text(text)
        assert len(chunks) == 1
        assert chunks[0] == "Short text."

    def test_long_text_produces_multiple_chunks(self):
        text = "X" * (CHUNK_SIZE * 2 + 100)
        chunks = _chunk_text(text)
        assert len(chunks) > 1

    def test_chunks_respect_size_bound(self):
        text = "B" * (CHUNK_SIZE * 4)
        for chunk in _chunk_text(text):
            assert len(chunk) <= CHUNK_SIZE

    def test_empty_text_returns_empty_list(self):
        assert _chunk_text("") == []
        assert _chunk_text("   ") == []

    def test_overlap_means_consecutive_chunks_share_content(self):
        text = "A" * CHUNK_SIZE + "B" * CHUNK_SIZE
        chunks = _chunk_text(text)
        assert len(chunks) >= 2
        # The tail of chunk 0 and the head of chunk 1 should overlap
        tail = chunks[0][-CHUNK_OVERLAP:]
        head = chunks[1][:CHUNK_OVERLAP]
        assert tail == head


# ---------------------------------------------------------------------------
# load_docs — dry-run (no ChromaDB writes)
# ---------------------------------------------------------------------------

class TestLoadDocsDryRun:
    def test_returns_summary_dict(self, tmp_docs):
        result = load_docs("tenant_001", str(tmp_docs), dry_run=True)
        assert "files_processed" in result
        assert "chunks_loaded" in result
        assert "skipped" in result
        assert "dry_run_chunks" in result

    def test_no_real_chunks_loaded_in_dry_run(self, tmp_docs):
        result = load_docs("tenant_001", str(tmp_docs), dry_run=True)
        assert result["chunks_loaded"] == 0

    def test_dry_run_chunks_gt_zero_for_nonempty_docs(self, long_doc):
        result = load_docs("tenant_002", str(long_doc), dry_run=True)
        assert result["dry_run_chunks"] > 1

    def test_nonexistent_path_raises(self, tmp_path):
        with pytest.raises(FileNotFoundError):
            load_docs("tenant_001", str(tmp_path / "does_not_exist"), dry_run=True)

    def test_empty_directory_returns_zero_files(self, tmp_path):
        result = load_docs("tenant_001", str(tmp_path), dry_run=True)
        assert result["files_processed"] == 0

    def test_tenant_ids_are_independent(self, tmp_docs):
        r1 = load_docs("tenant_001", str(tmp_docs), dry_run=True)
        r2 = load_docs("tenant_002", str(tmp_docs), dry_run=True)
        assert r1["files_processed"] == r2["files_processed"]
