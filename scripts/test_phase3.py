#!/usr/bin/env python3
"""
test_phase3.py — Test suite for the MemoryStore module
=======================================================

Tests the three-layer memory architecture:
  1. Vector Layer (Redis): Embedding storage and semantic search
  2. Entity Graph (Postgres): Entity extraction, reconciliation, relationships
  3. Temporal Index (Postgres): Event storage and temporal queries
  4. Dual-route retrieval (recall): Merging semantic + entity routes

Requirements:
  - Redis running at localhost:6379 (or REDIS_HOST/REDIS_PORT env vars)
  - PostgreSQL running at localhost:5432 (or PG_HOST/PG_PORT env vars)
  - Ollama running at localhost:11434 with nomic-embed-text model
  - Python packages: redis, psycopg2-binary, numpy

Usage:
  python3 test_phase3.py

On Schubert:
  /opt/Project-Tango/backend/venv/bin/python3 test_phase3.py
"""

import os
import sys
import time
import json
import tempfile
import shutil

# Add the scripts directory to the path
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, SCRIPT_DIR)

from memory_store import MemoryStore, REDIS_HOST, REDIS_PORT, PG_HOST, PG_DB, PG_USER


# ---------------------------------------------------------------------------
# Test framework
# ---------------------------------------------------------------------------

passed = 0
failed = 0
errors: list[str] = []


def test(name: str, condition: bool, detail: str = ""):
    """Run a single test assertion."""
    global passed, failed
    if condition:
        passed += 1
        print(f"  ✓ {name}")
    else:
        failed += 1
        msg = f"  ✗ {name}" + (f" — {detail}" if detail else "")
        errors.append(msg)
        print(msg)


def section(title: str):
    print(f"\n{'='*60}")
    print(f"  {title}")
    print(f"{'='*60}")


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

def test_connection():
    """Test Redis and Postgres connectivity."""
    section("Connection Tests")
    store = MemoryStore()

    # Redis
    try:
        r = store._get_redis()
        r.ping()
        test("Redis connection", True)
    except Exception as e:
        test("Redis connection", False, str(e))
        return None

    # Postgres
    try:
        conn = store._get_pg()
        with conn.cursor() as cur:
            cur.execute("SELECT 1")
            cur.fetchone()
        test("Postgres connection", True)
    except Exception as e:
        test("Postgres connection", False, str(e))
        return None

    # Ollama
    try:
        import urllib.request
        req = urllib.request.Request(
            "http://localhost:11434/api/tags",
            headers={"Content-Type": "application/json"},
        )
        with urllib.request.urlopen(req, timeout=5) as resp:
            data = json.loads(resp.read())
            models = [m.get("name", "") for m in data.get("models", [])]
            has_embed = any("nomic-embed-text" in m for m in models)
            test("Ollama connection", True)
            test("nomic-embed-text model available", has_embed,
                f"Available: {models}")
    except Exception as e:
        test("Ollama connection", False, str(e))

    return store


def test_init_db(store: MemoryStore):
    """Test database table creation."""
    section("Database Initialization Tests")

    try:
        store.init_db()
        test("init_db() creates tables without error", True)
    except Exception as e:
        test("init_db() creates tables without error", False, str(e))
        return

    # Verify tables exist
    conn = store._get_pg()
    with conn.cursor() as cur:
        for table in ["memory_entities", "memory_relationships",
                       "memory_facts", "memory_events"]:
            cur.execute(
                "SELECT EXISTS(SELECT 1 FROM information_schema.tables "
                "WHERE table_name = %s)", (table,)
            )
            exists = cur.fetchone()[0]
            test(f"Table '{table}' exists", exists)


def test_embedding(store: MemoryStore):
    """Test embedding generation via Ollama."""
    section("Embedding Generation Tests")

    # Generate embedding
    try:
        emb = store._generate_embedding("GitHub MCP server deployment")
        test("Embedding generation returns array", isinstance(emb.tolist() if hasattr(emb, 'tolist') else emb, list))
        test("Embedding has correct dimension", len(emb) == 768,
              f"Got {len(emb)} dims")
        test("Embedding has non-zero values", float(emb.sum()) != 0.0)
    except Exception as e:
        test("Embedding generation", False, str(e))

    # Test caching
    try:
        emb1 = store._generate_embedding("test caching sentence")
        start = time.time()
        emb2 = store._generate_embedding("test caching sentence")
        elapsed = time.time() - start
        test("Embedding cache hit is fast", elapsed < 0.01,
              f"Took {elapsed:.4f}s")
        test("Cached embeddings match",
              (emb1 == emb2).all() if hasattr(emb1, 'all') else emb1 == emb2)
    except Exception as e:
        test("Embedding caching", False, str(e))


def test_entity_extraction(store: MemoryStore):
    """Test entity extraction from text."""
    section("Entity Extraction Tests")

    # Known project names
    entities = store._extract_entities(
        "We deployed the GitHub MCP server on Schubert for the tango project"
    )
    test("Extracts 'github' from text", "github" in entities)
    test("Extracts 'schubert' from text", "schubert" in entities)
    test("Extracts 'tango' from text", "tango" in entities)

    # Service names
    entities = store._extract_entities(
        "The gmail-mcp-freelance.service is running on port 8071"
    )
    test("Extracts service names", any(".service" in e for e in entities))
    test("Extracts port references", any("port_8071" == e for e in entities))

    # MCP references
    entities = store._extract_entities(
        "The POSTGRES_MCP connector and REDIS_MCP are read-only"
    )
    test("Extracts MCP server names", "postgres" in entities or "redis" in entities)

    # No false positives on common words
    entities = store._extract_entities("The quick brown fox jumps over the lazy dog")
    test("No false positives on common text", len(entities) == 0 or
         all(e not in {"the", "quick", "brown", "fox", "jumps", "over", "lazy", "dog"}
             for e in entities))


def test_entity_classification(store: MemoryStore):
    """Test entity type classification."""
    section("Entity Classification Tests")

    test("Service classification",
          store._classify_entity("gmail-mcp-freelance.service") == "service")
    test("Project classification",
          store._classify_entity("tango") == "project")
    test("Tool classification",
          store._classify_entity("github") == "tool")
    test("Port classification",
          store._classify_entity("port_8091") == "port")
    test("Default concept classification",
          store._classify_entity("some_unknown_thing") == "concept")


def test_store(store: MemoryStore):
    """Test storing memories across all three layers."""
    section("Store Tests")

    # Store a memory
    try:
        mem_id = store.store(
            "We deployed the GitHub MCP server on port 8091 using the official "
            "Docker image ghcr.io/github/github-mcp-server v1.9.0 with all "
            "toolsets enabled for the Schubert bot project.",
            metadata={"project": "schubert-bot", "session_id": "test_session_1"},
            event_type="deployment"
        )
        test("store() returns memory ID", mem_id is not None and len(mem_id) > 0)
    except Exception as e:
        test("store() returns memory ID", False, str(e))
        return

    # Verify it's in Redis
    r = store._get_redis()
    exists = r.exists(f"mem:{mem_id}")
    test("Memory stored in Redis", exists > 0)

    in_index = r.sismember("mem:index", mem_id)
    test("Memory ID added to Redis index", in_index)

    # Verify it's in Postgres events
    conn = store._get_pg()
    with conn.cursor() as cur:
        cur.execute(
            "SELECT COUNT(*) FROM memory_events WHERE memory_id = %s", (mem_id,)
        )
        event_count = cur.fetchone()[0]
    test("Temporal event created in Postgres", event_count > 0)

    # Store a second memory with overlapping entities
    try:
        mem_id2 = store.store(
            "The GitHub MCP server has 85 tools available including repo "
            "management, issues, and pull requests. It connects to the tango "
            "project repository.",
            metadata={"project": "schubert-bot", "session_id": "test_session_1"},
        )
        test("store() second memory succeeds", mem_id2 is not None)
    except Exception as e:
        test("store() second memory succeeds", False, str(e))


def test_entity_reconciliation(store: MemoryStore):
    """Test entity reconciliation — duplicates merged, facts stored."""
    section("Entity Reconciliation Tests")

    # Store a memory mentioning 'github' and 'tango'
    store.store(
        "The GitHub MCP server integrates with the tango project for "
        "repository access and issue tracking.",
        metadata={"project": "schubert-bot"},
    )

    # Store another memory mentioning the same entities
    store.store(
        "GitHub MCP server was restarted after the tango project update "
        "to resolve a port conflict.",
        metadata={"project": "schubert-bot"},
    )

    # Check that 'github' entity exists and was not duplicated
    conn = store._get_pg()
    with conn.cursor() as cur:
        cur.execute("SELECT COUNT(*) FROM memory_entities WHERE name = 'github'")
        count = cur.fetchone()[0]
    test("Entity 'github' not duplicated", count == 1,
          f"Found {count} entities")

    # Check that facts were stored
    with conn.cursor() as cur:
        cur.execute(
            "SELECT COUNT(*) FROM memory_facts f "
            "JOIN memory_entities e ON f.entity_id = e.id "
            "WHERE e.name = 'github'"
        )
        fact_count = cur.fetchone()[0]
    test("Facts stored for 'github' entity", fact_count >= 1,
          f"Found {fact_count} facts")

    # Check relationship between github and tango
    with conn.cursor() as cur:
        cur.execute(
            "SELECT COUNT(*) FROM memory_relationships r "
            "JOIN memory_entities s ON r.source_id = s.id "
            "JOIN memory_entities t ON r.target_id = t.id "
            "WHERE s.name = 'github' AND t.name = 'tango'"
        )
        rel_count = cur.fetchone()[0]
    test("Relationship created between co-mentioned entities", rel_count > 0,
          f"Found {rel_count} relationships")


def test_search(store: MemoryStore):
    """Test semantic vector search."""
    section("Semantic Search Tests")

    # Store several distinct memories
    test_memories = [
        ("Gmail MCP server uses DWD service account authentication for "
         "headless access to the freelancing Google Workspace account.",
         {"project": "schubert-bot"}),
        ("The Outline Wiki container lost its port 3101 mapping and needed "
         "a restart to fix the 502 Bad Gateway error.",
         {"project": "schubert-bot"}),
        ("PostgreSQL database tango stores session data and entity graphs "
         "for the Schubert bot memory system.",
         {"project": "schubert-bot"}),
        ("Cloudflare tunnel cd4474e7 provides secure ingress to the "
         "Schubert server without exposing ports directly.",
         {"project": "schubert-bot"}),
    ]

    for text, meta in test_memories:
        store.store(text, metadata=meta)

    # Search for Gmail-related memories
    results = store.search("Gmail authentication and DWD", k=5)
    test("search() returns results", len(results) > 0)
    test("search() returns Gmail memory first",
          len(results) > 0 and "gmail" in results[0]["text"].lower())
    test("search() results have similarity scores",
          all("similarity" in r for r in results))

    # Search for database-related memories
    results = store.search("database storage", k=5)
    test("search() returns database memory",
          len(results) > 0 and any("postgres" in r["text"].lower()
                                    or "database" in r["text"].lower()
                                    for r in results))

    # Search for something unrelated (should return fewer or no results)
    results = store.search("quantum physics equations", k=5)
    test("search() returns fewer results for unrelated query",
          len(results) < 3 or all(r["similarity"] < 0.5 for r in results))


def test_recall(store: MemoryStore):
    """Test dual-route retrieval (recall)."""
    section("Recall (Dual-Route Retrieval) Tests")

    # Recall using a query that matches both semantically and by entity
    result = store.recall("Gmail MCP server deployment")
    test("recall() returns a string", isinstance(result, str))
    test("recall() returns non-empty for matching query", len(result) > 0)
    test("recall() includes header", "## Recalled Memories" in result or
         result == "")

    # Recall with entity-specific query
    result = store.recall("What do we know about the tango project?")
    test("recall() finds tango-related memories", len(result) > 0)

    # Recall with completely unrelated query
    result = store.recall("recipes for chocolate cake")
    test("recall() handles unrelated query gracefully",
          isinstance(result, str))


def test_get_entity(store: MemoryStore):
    """Test entity lookup with facts and relationships."""
    section("Entity Lookup Tests")

    # Look up an entity we know exists
    entity = store.get_entity("github")
    test("get_entity() returns entity dict", entity is not None)
    if entity:
        test("Entity has name", "name" in entity)
        test("Entity has type", "type" in entity)
        test("Entity has facts list", "facts" in entity and isinstance(entity["facts"], list))
        test("Entity has related list", "related" in entity and isinstance(entity["related"], list))

    # Look up non-existent entity
    entity = store.get_entity("nonexistent_entity_xyz123")
    test("get_entity() returns None for unknown entity", entity is None)


def test_get_recent(store: MemoryStore):
    """Test temporal queries."""
    section("Temporal Query Tests")

    # Get recent events
    events = store.get_recent(k=10)
    test("get_recent() returns events", len(events) > 0)
    test("get_recent() events have summaries",
          all("summary" in e for e in events))
    test("get_recent() events have timestamps",
          all("timestamp" in e for e in events))
    test("get_recent() events are ordered by time",
          len(events) <= 1 or events[0]["timestamp"] >= events[-1]["timestamp"])

    # Filter by project
    events = store.get_recent(project="schubert-bot", k=5)
    test("get_recent() with project filter works",
          all(e.get("project") == "schubert-bot" for e in events))

    # Get recent formatted
    formatted = store.get_recent_formatted(project="schubert-bot", k=3)
    test("get_recent_formatted() returns string", isinstance(formatted, str))


def test_stats(store: MemoryStore):
    """Test memory store statistics."""
    section("Stats Tests")

    stats = store.get_stats()
    test("get_stats() returns dict", isinstance(stats, dict))
    test("Stats includes redis_memories", "redis_memories" in stats)
    test("Stats includes entities", "entities" in stats)
    test("Stats includes facts", "facts" in stats)
    test("Stats includes events", "events" in stats)
    test("Stats includes relationships", "relationships" in stats)

    # After all our tests, we should have entities
    test("Stats shows entities > 0", stats.get("entities", 0) > 0)
    test("Stats shows events > 0", stats.get("events", 0) > 0)

    print(f"\n  Memory store stats: {json.dumps(stats, indent=2)}")


def test_write_time_reconciliation(store: MemoryStore):
    """Test that write-time reconciliation merges duplicates correctly."""
    section("Write-Time Reconciliation Tests")

    # Get initial entity count
    conn = store._get_pg()
    with conn.cursor() as cur:
        cur.execute("SELECT COUNT(*) FROM memory_entities WHERE name = 'redis'")
        initial_count = cur.fetchone()[0]

    # Store a memory mentioning redis
    store.store(
        "Redis is used for vector storage in the memory system, running as "
        "the polyglot-redis Docker container on port 6379.",
        metadata={"project": "schubert-bot"},
    )

    # Store another mentioning redis again
    store.store(
        "The Redis container polyglot-redis does not have the RediSearch "
        "module, so we use Python cosine similarity instead.",
        metadata={"project": "schubert-bot"},
    )

    # Check that redis entity count didn't increase (still 1 entity)
    with conn.cursor() as cur:
        cur.execute("SELECT COUNT(*) FROM memory_entities WHERE name = 'redis'")
        final_count = cur.fetchone()[0]
    test("Duplicate entity not created", final_count == 1,
          f"Found {final_count} entities (expected 1)")

    # Check that facts accumulated
    with conn.cursor() as cur:
        cur.execute(
            "SELECT COUNT(*) FROM memory_facts f "
            "JOIN memory_entities e ON f.entity_id = e.id "
            "WHERE e.name = 'redis'"
        )
        fact_count = cur.fetchone()[0]
    test("Multiple facts accumulated for same entity", fact_count >= 2,
          f"Found {fact_count} facts")


def test_cleanup(store: MemoryStore):
    """Clean up test data to keep the store tidy."""
    section("Cleanup")

    # Note: We intentionally leave test data in the store for inspection.
    # In production, you might want to clean up. For now, just close connections.
    try:
        store.close()
        test("close() shuts down cleanly", True)
    except Exception as e:
        test("close() shuts down cleanly", False, str(e))


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    print("\n" + "=" * 60)
    print("  Phase 3 — MemoryStore Test Suite")
    print("=" * 60)

    # Check prerequisites
    print(f"\n  Redis: {REDIS_HOST}:{REDIS_PORT}")
    print(f"  Postgres: {PG_HOST}:5432 / {PG_DB} (user: {PG_USER})")
    print(f"  Ollama: localhost:11434")

    # Run tests
    store = test_connection()
    if store is None:
        print("\n  Cannot connect to required infrastructure. Aborting.")
        sys.exit(1)

    test_init_db(store)
    test_embedding(store)
    test_entity_extraction(store)
    test_entity_classification(store)
    test_store(store)
    test_entity_reconciliation(store)
    test_search(store)
    test_recall(store)
    test_get_entity(store)
    test_get_recent(store)
    test_stats(store)
    test_write_time_reconciliation(store)
    test_cleanup(store)

    # Summary
    print("\n" + "=" * 60)
    total = passed + failed
    print(f"  Results: {passed}/{total} passed, {failed} failed")
    if errors:
        print(f"\n  Failures:")
        for e in errors:
            print(f"    {e}")
    print("=" * 60 + "\n")

    sys.exit(0 if failed == 0 else 1)


if __name__ == "__main__":
    main()
