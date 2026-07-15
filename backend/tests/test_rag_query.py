"""
Tests for backend/tools/rag_query.py.

chromadb is injected as a MagicMock into sys.modules before import so no
real DB is ever touched. All paths — found, not-found, empty, error — are covered.
"""

import sys
from pathlib import Path
from unittest.mock import MagicMock

import pytest

# ---------------------------------------------------------------------------
# Inject mock chromadb BEFORE importing rag_query (lazy-import pattern)
# ---------------------------------------------------------------------------

_mock_chroma_module = MagicMock()
_mock_ef_module = MagicMock()

sys.modules.setdefault("chromadb", _mock_chroma_module)
sys.modules.setdefault("chromadb.utils", _mock_ef_module)
sys.modules.setdefault("chromadb.utils.embedding_functions", _mock_ef_module)

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from tools.rag_query import (  # noqa: E402
    RAGChunk,
    RAGResponse,
    _build_context,
    _distance_to_score,
    _not_found,
    query_rag,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_collection(
    count: int = 3,
    documents=None,
    metadatas=None,
    distances=None,
    get_raises=None,
):
    """Return a mock chromadb collection with controllable query output."""
    mock_client = MagicMock()
    mock_collection = MagicMock()

    if get_raises is not None:
        mock_client.get_collection.side_effect = get_raises
    else:
        mock_collection.count.return_value = count
        mock_collection.query.return_value = {
            "documents": [documents or ["chunk text 1", "chunk text 2"]],
            "metadatas": [metadatas or [{"filename": "doc.md"}, {"filename": "doc.md"}]],
            "distances": [distances or [0.1, 0.3]],
        }
        mock_client.get_collection.return_value = mock_collection

    _mock_chroma_module.PersistentClient.return_value = mock_client
    return mock_client, mock_collection


@pytest.fixture(autouse=True)
def reset_chroma_mock():
    """Ensure chromadb mock is clean before each test."""
    _mock_chroma_module.reset_mock()
    yield


# ---------------------------------------------------------------------------
# _distance_to_score — pure function
# ---------------------------------------------------------------------------

class TestDistanceToScore:
    def test_zero_distance_gives_max_score(self):
        assert _distance_to_score(0.0) == 1.0

    def test_score_decreases_as_distance_grows(self):
        assert _distance_to_score(0.1) > _distance_to_score(0.5)
        assert _distance_to_score(0.5) > _distance_to_score(2.0)

    def test_score_always_in_zero_one_range(self):
        for d in [0.0, 0.01, 0.5, 1.0, 2.0, 10.0, 100.0]:
            score = _distance_to_score(d)
            assert 0.0 < score <= 1.0, f"score={score} out of range for distance={d}"

    def test_negative_distance_clamped(self):
        # negative distance is nonsensical but must not raise or go above 1
        assert 0.0 < _distance_to_score(-5.0) <= 1.0

    def test_returns_float_rounded_to_4dp(self):
        score = _distance_to_score(0.3)
        assert isinstance(score, float)
        assert len(str(score).split(".")[-1]) <= 4


# ---------------------------------------------------------------------------
# _build_context — pure function
# ---------------------------------------------------------------------------

class TestBuildContext:
    def test_single_chunk(self):
        chunks = [RAGChunk(text="hello world", source_file="a.md", relevance_score=0.9)]
        assert _build_context(chunks) == "hello world"

    def test_multiple_chunks_joined_with_separator(self):
        chunks = [
            RAGChunk(text="first", source_file="a.md", relevance_score=0.9),
            RAGChunk(text="second", source_file="b.md", relevance_score=0.7),
        ]
        ctx = _build_context(chunks)
        assert "first" in ctx
        assert "second" in ctx
        assert "---" in ctx

    def test_empty_chunks_returns_empty_string(self):
        assert _build_context([]) == ""

    def test_context_order_matches_chunk_order(self):
        chunks = [
            RAGChunk(text="A", source_file="x.md", relevance_score=0.9),
            RAGChunk(text="B", source_file="y.md", relevance_score=0.5),
        ]
        ctx = _build_context(chunks)
        assert ctx.index("A") < ctx.index("B")


# ---------------------------------------------------------------------------
# _not_found — pure function
# ---------------------------------------------------------------------------

class TestNotFound:
    def test_returns_rag_response(self):
        r = _not_found("tenant_001", "query")
        assert isinstance(r, RAGResponse)

    def test_found_is_false(self):
        assert _not_found("tenant_001", "q").found is False

    def test_chunks_is_empty_list(self):
        assert _not_found("tenant_001", "q").chunks == []

    def test_context_is_empty_string(self):
        assert _not_found("tenant_001", "q").context == ""

    def test_tenant_id_and_query_preserved(self):
        r = _not_found("tenant_042", "my query")
        assert r.tenant_id == "tenant_042"
        assert r.query == "my query"


# ---------------------------------------------------------------------------
# RAGChunk + RAGResponse model validation
# ---------------------------------------------------------------------------

class TestModels:
    def test_rag_chunk_fields(self):
        c = RAGChunk(text="t", source_file="f.md", relevance_score=0.8)
        assert c.text == "t"
        assert c.source_file == "f.md"
        assert c.relevance_score == 0.8

    def test_rag_response_found_true(self):
        chunks = [RAGChunk(text="t", source_file="f.md", relevance_score=0.9)]
        r = RAGResponse(
            tenant_id="tenant_001",
            query="q",
            chunks=chunks,
            context="t",
            found=True,
        )
        assert r.found is True
        assert len(r.chunks) == 1

    def test_rag_response_model_dump_contains_required_keys(self):
        r = _not_found("tenant_001", "q")
        d = r.model_dump()
        for key in ("tenant_id", "query", "chunks", "context", "found"):
            assert key in d


# ---------------------------------------------------------------------------
# query_rag — collection missing
# ---------------------------------------------------------------------------

class TestQueryRagCollectionMissing:
    def test_returns_not_found_when_collection_missing(self):
        _make_collection(get_raises=ValueError("Collection not found"))
        result = query_rag("tenant_001", "services and pricing")
        assert result.found is False

    def test_chunks_empty_when_collection_missing(self):
        _make_collection(get_raises=ValueError("no such collection"))
        result = query_rag("tenant_001", "query")
        assert result.chunks == []

    def test_context_empty_when_collection_missing(self):
        _make_collection(get_raises=ValueError("no such collection"))
        result = query_rag("tenant_001", "query")
        assert result.context == ""

    def test_uses_correct_collection_name(self):
        mock_client, _ = _make_collection(get_raises=ValueError("x"))
        query_rag("tenant_007", "q")
        mock_client.get_collection.assert_called_once()
        call_kwargs = mock_client.get_collection.call_args
        called_name = call_kwargs[1].get("name") or call_kwargs[0][0]
        assert called_name == "rag_tenant_007"


# ---------------------------------------------------------------------------
# query_rag — empty collection
# ---------------------------------------------------------------------------

class TestQueryRagEmptyCollection:
    def test_returns_not_found_for_empty_collection(self):
        _make_collection(count=0)
        result = query_rag("tenant_001", "services")
        assert result.found is False

    def test_does_not_call_query_on_empty_collection(self):
        _, mock_col = _make_collection(count=0)
        query_rag("tenant_001", "services")
        mock_col.query.assert_not_called()


# ---------------------------------------------------------------------------
# query_rag — blank / empty query
# ---------------------------------------------------------------------------

class TestQueryRagBlankQuery:
    def test_empty_string_returns_not_found(self):
        result = query_rag("tenant_001", "")
        assert result.found is False

    def test_whitespace_only_returns_not_found(self):
        result = query_rag("tenant_001", "   ")
        assert result.found is False

    def test_blank_query_does_not_hit_chromadb(self):
        query_rag("tenant_001", "")
        _mock_chroma_module.PersistentClient.assert_not_called()


# ---------------------------------------------------------------------------
# query_rag — successful results
# ---------------------------------------------------------------------------

class TestQueryRagSuccess:
    def test_found_is_true_when_results_exist(self):
        _make_collection(
            count=2,
            documents=["chunk A", "chunk B"],
            metadatas=[{"filename": "a.md"}, {"filename": "b.md"}],
            distances=[0.1, 0.4],
        )
        result = query_rag("tenant_001", "pricing for contractors")
        assert result.found is True

    def test_chunks_count_matches_results(self):
        _make_collection(
            count=2,
            documents=["c1", "c2"],
            metadatas=[{"filename": "f.md"}, {"filename": "f.md"}],
            distances=[0.0, 0.2],
        )
        result = query_rag("tenant_001", "q")
        assert len(result.chunks) == 2

    def test_chunk_text_matches_document(self):
        _make_collection(
            count=1,
            documents=["important knowledge"],
            metadatas=[{"filename": "info.md"}],
            distances=[0.05],
        )
        result = query_rag("tenant_001", "q")
        assert result.chunks[0].text == "important knowledge"

    def test_chunk_source_file_from_metadata(self):
        _make_collection(
            count=1,
            documents=["text"],
            metadatas=[{"filename": "pricing.md"}],
            distances=[0.1],
        )
        result = query_rag("tenant_001", "q")
        assert result.chunks[0].source_file == "pricing.md"

    def test_chunk_relevance_score_is_positive(self):
        _make_collection(
            count=1,
            documents=["text"],
            metadatas=[{"filename": "f.md"}],
            distances=[0.2],
        )
        result = query_rag("tenant_001", "q")
        assert result.chunks[0].relevance_score > 0.0

    def test_context_contains_all_chunk_texts(self):
        _make_collection(
            count=2,
            documents=["alpha content", "beta content"],
            metadatas=[{"filename": "a.md"}, {"filename": "b.md"}],
            distances=[0.1, 0.3],
        )
        result = query_rag("tenant_001", "q")
        assert "alpha content" in result.context
        assert "beta content" in result.context

    def test_tenant_id_preserved_in_response(self):
        _make_collection()
        result = query_rag("tenant_042", "q")
        assert result.tenant_id == "tenant_042"

    def test_query_preserved_in_response(self):
        _make_collection()
        result = query_rag("tenant_001", "specific query text")
        assert result.query == "specific query text"

    def test_top_k_limits_results(self):
        _make_collection(
            count=5,
            documents=["a", "b"],
            metadatas=[{"filename": "x.md"}, {"filename": "x.md"}],
            distances=[0.1, 0.2],
        )
        _, mock_col = _make_collection(
            count=5,
            documents=["a", "b"],
            metadatas=[{"filename": "x.md"}, {"filename": "x.md"}],
            distances=[0.1, 0.2],
        )
        query_rag("tenant_001", "q", top_k=2)
        mock_col.query.assert_called_once()
        call_kwargs = mock_col.query.call_args[1]
        assert call_kwargs["n_results"] <= 5

    def test_collection_name_always_tenant_namespaced(self):
        mock_client, _ = _make_collection()
        query_rag("tenant_099", "q")
        call_kwargs = mock_client.get_collection.call_args
        called_name = call_kwargs[1].get("name") or call_kwargs[0][0]
        assert called_name == "rag_tenant_099"
        assert "tenant_099" in called_name


# ---------------------------------------------------------------------------
# query_rag — tenant isolation
# ---------------------------------------------------------------------------

class TestTenantIsolation:
    def test_different_tenants_use_different_collections(self):
        results = []
        for tenant in ("tenant_001", "tenant_002", "tenant_003"):
            _make_collection(get_raises=ValueError("missing"))
            r = query_rag(tenant, "q")
            results.append((tenant, r.tenant_id))

        for tenant, response_tenant in results:
            assert response_tenant == tenant

    def test_collection_name_never_hardcoded(self):
        # Verify the collection name is always derived from tenant_id
        for tenant_id in ("tenant_001", "tenant_XYZ", "tenant_999"):
            mock_client, _ = _make_collection(get_raises=ValueError("x"))
            query_rag(tenant_id, "q")
            call_kwargs = mock_client.get_collection.call_args
            called_name = call_kwargs[1].get("name") or call_kwargs[0][0]
            assert called_name == f"rag_{tenant_id}"


# ---------------------------------------------------------------------------
# query_rag — unexpected chromadb error
# ---------------------------------------------------------------------------

class TestQueryRagError:
    def test_unexpected_exception_returns_not_found(self):
        _mock_chroma_module.PersistentClient.side_effect = RuntimeError("DB crash")
        result = query_rag("tenant_001", "q")
        assert result.found is False

    def test_unexpected_exception_does_not_raise(self):
        _mock_chroma_module.PersistentClient.side_effect = Exception("boom")
        # Should NOT raise — always returns RAGResponse
        result = query_rag("tenant_001", "q")
        assert isinstance(result, RAGResponse)
