"""
MemoryStore — Persistent Memory Architecture
=============================================
Three-layer memory system for the Schubert Bot:

1. Vector Layer (pgvector): Text embeddings for semantic search.
   Uses Ollama nomic-embed-text (768-dim) for embedding generation.
   Stored in PostgreSQL via pgvector extension with HNSW index.
   Replaces the previous Redis-based Python cosine similarity scan.

2. Entity Graph (Postgres): Structured knowledge of entities and relationships.
   Tables: memory_entities, memory_relationships, memory_facts.

3. Temporal Index (Postgres): Timestamped memory events for temporal queries.
   Table: memory_events.

Entity extraction runs asynchronously — the store() call returns immediately
after storing the vector and temporal event. LLM-based entity extraction,
reconciliation, and relationship creation happen in a background thread.

The MemoryStore API provides:
    store(text, metadata)    — Store a memory with reconciliation
    search(query, k)         — Semantic vector search via pgvector
    recall(query, k)         — Dual-route retrieval (semantic + entity)
    get_entity(name)         — Look up an entity
    get_recent(project, k)   — Get recent memories for a project

Usage:
    store = MemoryStore()
    store.init_db()  # Create tables (call once at startup)
    store.store("We deployed the GitHub MCP server on port 8091",
                metadata={"project": "schubert-bot", "session_id": "channel_123"})
    results = store.recall("GitHub MCP deployment")
    # Returns relevant memories from both semantic and entity routes
"""

from __future__ import annotations

import json
import logging
import os
import re
import threading
import time
import uuid
from datetime import datetime, timezone
from typing import Any, Optional

import numpy as np
import psycopg2
import psycopg2.extras
import redis

logger = logging.getLogger("schubert-bot.memory")


# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

REDIS_HOST = os.environ.get("REDIS_HOST", "localhost")
REDIS_PORT = int(os.environ.get("REDIS_PORT", "6379"))
REDIS_DB = int(os.environ.get("REDIS_DB", "0"))

PG_HOST = os.environ.get("POSTGRES_HOST", "/var/run/postgresql")
PG_PORT = int(os.environ.get("POSTGRES_PORT", "5432"))
PG_DB = os.environ.get("POSTGRES_DB", "tango")
PG_USER = os.environ.get("POSTGRES_USER", "z121532")
PG_PASSWORD = os.environ.get("POSTGRES_PASSWORD", "")

OLLAMA_URL = os.environ.get("OLLAMA_URL", "http://localhost:11434")
EMBEDDING_MODEL = os.environ.get("EMBEDDING_MODEL", "nomic-embed-text")
EMBEDDING_DIM = 768

MAX_RECALL_RESULTS = 5  # Max memories to return from recall()
MAX_SEARCH_RESULTS = 10  # Max memories from raw vector search
COSINE_THRESHOLD = 0.3  # Minimum similarity to include in results (1 - cosine_distance)

# Stop words and overly-generic terms that should never become entities.
# Built as a frozenset for O(1) membership testing.
STOP_WORDS: frozenset[str] = frozenset({
    "the", "a", "an", "am", "is", "are", "was", "were", "be", "been", "being",
    "have", "has", "had", "having", "do", "does", "did", "doing",
    "will", "would", "could", "should", "may", "might", "must", "can", "shall",
    "one", "two", "every", "some", "any", "all", "each", "few", "more", "most",
    "other", "such", "no", "nor", "not", "only", "own", "same", "so", "than",
    "too", "very", "just", "but", "for", "and", "or", "if", "as", "by", "with",
    "from", "to", "in", "on", "at", "of", "about", "into", "through", "during",
    "before", "after", "above", "below", "up", "down", "out", "off", "over",
    "under", "again", "further", "then", "once", "here", "there", "when",
    "where", "why", "how", "what", "which", "who", "whom", "this", "that",
    "these", "those",
    "i", "me", "my", "myself", "we", "our", "ours", "ourselves",
    "you", "your", "yours", "yourself", "yourselves",
    "he", "him", "his", "himself", "she", "her", "hers", "herself",
    "it", "its", "itself", "they", "them", "their", "theirs", "themselves",
    "because", "until", "while", "against", "between", "both",
    "s", "t", "don", "now", "d", "ll", "m", "o", "re", "ve", "y",
    "ain", "aren", "couldn", "didn", "doesn", "hadn", "hasn", "haven",
    "isn", "ma", "mightn", "mustn", "needn", "shan", "shouldn", "wasn",
    "weren", "won", "wouldn",
    # Overly generic words that add no semantic value as entities
    "uses", "form", "change",
})

# Maximum length for a valid entity (reject full sentences)
MAX_ENTITY_LENGTH = 60
# Minimum length for a valid entity
MIN_ENTITY_LENGTH = 3


# ---------------------------------------------------------------------------
# Database Schema
# ---------------------------------------------------------------------------

SCHEMA_SQL = """
-- Entity graph: structured knowledge of people, projects, services, tools, concepts
CREATE TABLE IF NOT EXISTS memory_entities (
    id          SERIAL PRIMARY KEY,
    name        TEXT UNIQUE NOT NULL,
    type        TEXT NOT NULL DEFAULT 'concept',
    description TEXT DEFAULT '',
    properties  JSONB DEFAULT '{}',
    created_at  TIMESTAMPTZ DEFAULT NOW(),
    updated_at  TIMESTAMPTZ DEFAULT NOW()
);

-- Relationships between entities
CREATE TABLE IF NOT EXISTS memory_relationships (
    id          SERIAL PRIMARY KEY,
    source_id   INTEGER REFERENCES memory_entities(id) ON DELETE CASCADE,
    target_id   INTEGER REFERENCES memory_entities(id) ON DELETE CASCADE,
    type        TEXT NOT NULL DEFAULT 'related_to',
    strength    FLOAT DEFAULT 1.0,
    created_at  TIMESTAMPTZ DEFAULT NOW(),
    UNIQUE(source_id, target_id, type)
);

-- Facts associated with entities
CREATE TABLE IF NOT EXISTS memory_facts (
    id          SERIAL PRIMARY KEY,
    entity_id   INTEGER REFERENCES memory_entities(id) ON DELETE CASCADE,
    fact        TEXT NOT NULL,
    source      TEXT DEFAULT 'conversation',
    confidence  FLOAT DEFAULT 1.0,
    created_at  TIMESTAMPTZ DEFAULT NOW(),
    updated_at  TIMESTAMPTZ DEFAULT NOW()
);

-- Temporal index: timestamped memory events
CREATE TABLE IF NOT EXISTS memory_events (
    id          SERIAL PRIMARY KEY,
    memory_id   TEXT NOT NULL,
    event_type  TEXT NOT NULL DEFAULT 'conversation',
    project     TEXT DEFAULT '',
    session_id  TEXT DEFAULT '',
    summary     TEXT NOT NULL,
    entities    TEXT[] DEFAULT '{}',
    created_at  TIMESTAMPTZ DEFAULT NOW()
);

-- Vector layer: embeddings stored in pgvector for sub-linear ANN search
CREATE TABLE IF NOT EXISTS memory_vectors (
    id          SERIAL PRIMARY KEY,
    memory_id   TEXT UNIQUE NOT NULL,
    embedding   vector(768) NOT NULL,
    text        TEXT NOT NULL,
    project     TEXT DEFAULT '',
    session_id  TEXT DEFAULT '',
    timestamp   TIMESTAMPTZ DEFAULT NOW(),
    event_type  TEXT DEFAULT 'conversation'
);

CREATE INDEX IF NOT EXISTS idx_memory_events_time ON memory_events(created_at DESC);
CREATE INDEX IF NOT EXISTS idx_memory_events_project ON memory_events(project);
CREATE INDEX IF NOT EXISTS idx_memory_events_entities ON memory_events USING GIN(entities);
CREATE INDEX IF NOT EXISTS idx_memory_entities_name ON memory_entities(name);
CREATE INDEX IF NOT EXISTS idx_memory_facts_entity ON memory_facts(entity_id);
"""

# HNSW index for vector cosine similarity search (created separately
# because CREATE EXTENSION must run before the vector type is available)
VECTOR_INDEX_SQL = """
CREATE INDEX IF NOT EXISTS idx_memory_vectors_embedding
    ON memory_vectors USING hnsw (embedding vector_cosine_ops);
"""


# ---------------------------------------------------------------------------
# MemoryStore
# ---------------------------------------------------------------------------

class MemoryStore:
    """
    Three-layer persistent memory: vector store (pgvector), entity graph (Postgres),
    and temporal index (Postgres).

    The vector layer uses pgvector with an HNSW index for sub-linear approximate
    nearest neighbor search, replacing the previous Redis-based Python cosine
    similarity scan that degraded with scale.

    Entity extraction runs asynchronously in a background thread — the store()
    call returns immediately after storing the vector and creating the temporal
    event. LLM-based entity extraction, reconciliation, and relationship creation
    happen without blocking the caller.
    """

    def __init__(self):
        self._redis: redis.Redis | None = None
        self._pg_conn = None
        self._embedding_cache: dict[str, np.ndarray] = {}

    # -- Connection management ---------------------------------------------

    def _get_redis(self) -> redis.Redis:
        """Get or create Redis connection (retained for backward compatibility)."""
        if self._redis is None:
            self._redis = redis.Redis(
                host=REDIS_HOST, port=REDIS_PORT, db=REDIS_DB,
                decode_responses=True, socket_timeout=5, socket_connect_timeout=5,
            )
        return self._redis

    def _get_pg(self):
        """Get or create Postgres connection."""
        if self._pg_conn is None or self._pg_conn.closed:
            kwargs = {
                "host": PG_HOST, "port": PG_PORT, "dbname": PG_DB, "user": PG_USER,
            }
            if PG_PASSWORD:
                kwargs["password"] = PG_PASSWORD
            self._pg_conn = psycopg2.connect(**kwargs)
            self._pg_conn.autocommit = True
        return self._pg_conn

    def init_db(self) -> None:
        """Create database tables and indexes if they don't exist. Call once at startup."""
        conn = self._get_pg()
        with conn.cursor() as cur:
            # Ensure pgvector extension is available
            cur.execute("CREATE EXTENSION IF NOT EXISTS vector")
            cur.execute(SCHEMA_SQL)
            cur.execute(VECTOR_INDEX_SQL)
        logger.info("Memory database tables initialized (pgvector enabled)")

    def close(self) -> None:
        """Close all connections."""
        if self._redis:
            self._redis.close()
        if self._pg_conn and not self._pg_conn.closed:
            self._pg_conn.close()

    # -- Embedding generation ---------------------------------------------

    def _generate_embedding(self, text: str) -> np.ndarray:
        """
        Generate a 768-dim embedding for text using Ollama nomic-embed-text.

        Uses the Ollama HTTP API at localhost:11434/api/embeddings.
        Caches embeddings by text hash to avoid redundant API calls.
        """
        # Check cache
        cache_key = text[:200]  # Truncate for cache key
        if cache_key in self._embedding_cache:
            return self._embedding_cache[cache_key]

        try:
            import urllib.request
            import urllib.error

            payload = json.dumps({"model": EMBEDDING_MODEL, "prompt": text}).encode()
            req = urllib.request.Request(
                f"{OLLAMA_URL}/api/embeddings",
                data=payload,
                headers={"Content-Type": "application/json"},
            )
            with urllib.request.urlopen(req, timeout=10) as resp:
                data = json.loads(resp.read())
                embedding = np.array(data.get("embedding", []), dtype=np.float32)

            if len(embedding) != EMBEDDING_DIM:
                logger.warning(
                    f"Embedding dimension mismatch: got {len(embedding)}, expected {EMBEDDING_DIM}"
                )

            # Cache it
            self._embedding_cache[cache_key] = embedding
            return embedding

        except Exception as e:
            logger.error(f"Failed to generate embedding: {e}")
            return np.zeros(EMBEDDING_DIM, dtype=np.float32)

    # -- Store -------------------------------------------------------------

    def store(
        self,
        text: str,
        metadata: dict | None = None,
        event_type: str = "conversation",
    ) -> str:
        """
        Store a memory across all three layers.

        1. Generate embedding and store in pgvector (vector layer) — synchronous
        2. Create temporal event with heuristic entities (temporal index) — synchronous
        3. Extract entities via LLM, reconcile, create relationships — async background

        The LLM entity extraction (step 3) runs in a background thread so the
        caller is not blocked waiting for the LLM response. The vector store and
        temporal event are created synchronously because they are fast and
        required for immediate search availability.

        Args:
            text: The memory text to store
            metadata: Optional metadata (project, session_id, etc.)
            event_type: Type of memory event ('conversation', 'tool', 'deployment')

        Returns:
            The memory ID (used as primary key in memory_vectors)
        """
        metadata = metadata or {}
        memory_id = str(uuid.uuid4())
        project = metadata.get("project", "")
        session_id = metadata.get("session_id", "")
        timestamp = datetime.now(timezone.utc)

        # 1. Vector layer: store embedding in pgvector
        embedding = self._generate_embedding(text)
        self._store_vector(
            memory_id=memory_id,
            embedding=embedding,
            text=text,
            project=project,
            session_id=session_id,
            timestamp=timestamp,
            event_type=event_type,
        )

        # 2. Extract heuristic entities immediately (fast, no LLM call)
        heuristic_entities = self._extract_entities_heuristic(text)

        # 3. Temporal index: create event record with heuristic entities
        self._create_event(
            memory_id=memory_id,
            event_type=event_type,
            project=project,
            session_id=session_id,
            summary=text[:500],
            entities=heuristic_entities,
        )

        # 4. Async: LLM entity extraction + reconciliation + relationships
        #    Runs in a background thread so the caller is not blocked
        thread = threading.Thread(
            target=self._extract_and_reconcile_async,
            args=(text, memory_id, project, heuristic_entities),
            daemon=True,
        )
        thread.start()

        logger.info(
            f"Stored memory {memory_id}: {text[:80]}... "
            f"(project={project}, heuristic_entities={len(heuristic_entities)}, "
            f"async_extraction=started)"
        )
        return memory_id

    def _store_vector(
        self,
        memory_id: str,
        embedding: np.ndarray,
        text: str,
        project: str,
        session_id: str,
        timestamp: datetime,
        event_type: str,
    ) -> None:
        """Store an embedding in the pgvector memory_vectors table."""
        conn = self._get_pg()
        # pgvector accepts the embedding as a string literal '[0.1, 0.2, ...]'
        emb_str = "[" + ",".join(str(float(x)) for x in embedding) + "]"
        with conn.cursor() as cur:
            cur.execute(
                "INSERT INTO memory_vectors "
                "(memory_id, embedding, text, project, session_id, timestamp, event_type) "
                "VALUES (%s, %s::vector, %s, %s, %s, %s, %s) "
                "ON CONFLICT (memory_id) DO UPDATE SET "
                "embedding = EXCLUDED.embedding, text = EXCLUDED.text, "
                "project = EXCLUDED.project, session_id = EXCLUDED.session_id, "
                "timestamp = EXCLUDED.timestamp, event_type = EXCLUDED.event_type",
                (memory_id, emb_str, text, project, session_id, timestamp, event_type),
            )

    def _extract_and_reconcile_async(
        self,
        text: str,
        memory_id: str,
        project: str,
        heuristic_entities: list[str],
    ) -> None:
        """
        Background thread: LLM entity extraction, reconciliation, and relationships.

        This method runs in a daemon thread spawned by store(). It performs the
        slow LLM-based entity extraction that would otherwise block the caller.
        Heuristic entities are already stored in the temporal event; this method
        adds any additional LLM-extracted entities to the entity graph.

        Each operation has its own try/except so a failure in one step does not
        prevent the others from running. The thread uses its own Postgres
        connection to avoid contention with the main thread.
        """
        pg_conn = None
        try:
            # Use a separate connection for the background thread
            kwargs = {
                "host": PG_HOST, "port": PG_PORT, "dbname": PG_DB, "user": PG_USER,
            }
            if PG_PASSWORD:
                kwargs["password"] = PG_PASSWORD
            pg_conn = psycopg2.connect(**kwargs)
            pg_conn.autocommit = True

            # LLM entity extraction (may take up to 15s)
            llm_entities = self._extract_entities_llm(text)

            # Merge LLM entities with heuristic entities
            all_entities = list(set(llm_entities + heuristic_entities))

            if not all_entities:
                return

            # Reconcile all entities in the entity graph
            entity_ids = self._reconcile_entities_pg(pg_conn, all_entities, text, project)

            # Create relationships between co-mentioned entities
            self._create_relationships_pg(pg_conn, entity_ids)

            # Update the temporal event with the full entity list if LLM found new entities
            new_entities = set(llm_entities) - set(heuristic_entities)
            if new_entities:
                with pg_conn.cursor() as cur:
                    cur.execute(
                        "UPDATE memory_events SET entities = %s "
                        "WHERE memory_id = %s",
                        (all_entities, memory_id),
                    )

            logger.debug(
                f"Async entity extraction complete for {memory_id}: "
                f"{len(all_entities)} entities ({len(new_entities)} new from LLM)"
            )

        except Exception as e:
            logger.error(f"Async entity extraction failed for {memory_id}: {e}")
        finally:
            if pg_conn and not pg_conn.closed:
                pg_conn.close()

    # -- Entity extraction ------------------------------------------------

    @staticmethod
    def _is_valid_entity(entity: str) -> bool:
        """
        Validate a single candidate entity string.

        Rejects:
        - Entities containing newlines (multiline fragments)
        - Stop words and overly generic terms
        - Entities shorter than MIN_ENTITY_LENGTH or longer than MAX_ENTITY_LENGTH
        - Entities starting with "the " (article prefix that adds no meaning)
        - Empty / whitespace-only strings
        """
        if not entity:
            return False
        stripped = entity.strip()
        if len(stripped) < MIN_ENTITY_LENGTH:
            return False
        if len(stripped) > MAX_ENTITY_LENGTH:
            return False
        if "\n" in stripped:
            return False
        if stripped in STOP_WORDS:
            return False
        if stripped.startswith("the "):
            return False
        # Reject multi-word phrases where every word is a stop word
        words = stripped.split()
        if len(words) > 1 and all(w in STOP_WORDS for w in words):
            return False
        return True

    def _extract_entities(self, text: str) -> list[str]:
        """
        Extract entity names from text.

        This method is retained for the entity route in recall() — it performs
        synchronous LLM extraction since recall is not on the hot store() path.
        For store(), entity extraction is async via _extract_and_reconcile_async().
        """
        # Try LLM-based extraction first
        try:
            llm_entities = self._extract_entities_llm(text)
            if llm_entities:
                # Merge with heuristic results for completeness
                heuristic_entities = self._extract_entities_heuristic(text)
                return list(set(llm_entities + heuristic_entities))
        except Exception as e:
            logger.debug(f"LLM entity extraction failed, using heuristic: {e}")

        return self._extract_entities_heuristic(text)

    def _extract_entities_llm(self, text: str) -> list[str]:
        """
        Use the LiteLLM proxy to extract entities from text.

        Sends a focused prompt asking the LLM to identify named entities,
        then parses the response as a JSON list.
        """
        import httpx

        litellm_url = os.environ.get("LITELLM_URL", "http://127.0.0.1:4000/v1")
        litellm_key = os.environ.get("LITELLM_MASTER_KEY", "")
        model = os.environ.get("LLM_MODEL", "writer/claude-sonnet-4-5")

        # Truncate text to keep the prompt small
        text_excerpt = text[:1000]

        prompt = (
            "Extract all named entities from the following text. "
            "Return ONLY a JSON array of entity names (lowercase, single words or short phrases). "
            "Include: project names, service names, tool names, technologies, people, "
            "repositories, file paths, ports, and any other named entities. "
            "Do not include common words or stop words.\n\n"
            f"Text: {text_excerpt}\n\n"
            "Entities (JSON array):"
        )

        try:
            with httpx.Client(timeout=15) as client:
                resp = client.post(
                    f"{litellm_url}/chat/completions",
                    json={
                        "model": model,
                        "messages": [{"role": "user", "content": prompt}],
                        "temperature": 0.1,
                        "max_tokens": 300,
                    },
                    headers={
                        "Authorization": f"Bearer {litellm_key}",
                        "Content-Type": "application/json",
                    },
                )
                if resp.status_code != 200:
                    return []

                data = resp.json()
                content = data.get("choices", [{}])[0].get("message", {}).get("content", "")

                # Parse the JSON array from the response
                # The LLM may wrap it in markdown or add extra text
                import json as _json
                # Find the JSON array in the response
                match = re.search(r'\[.*?\]', content, re.DOTALL)
                if match:
                    entities = _json.loads(match.group(0))
                    # Clean and validate
                    cleaned = []
                    for e in entities:
                        e = str(e).strip().lower()
                        if self._is_valid_entity(e):
                            cleaned.append(e)
                    return cleaned
        except Exception:
            return []

        return []

    def _extract_entities_heuristic(self, text: str) -> list[str]:
        """
        Extract entity names from text using pattern matching.

        Detects:
        - Known project names (tango, vinifera, schubert, etc.)
        - Service names (ending in .service)
        - MCP server names (github, gmail, redis, postgres, etc.)
        - Capitalized phrases (potential proper nouns)
        - File paths and URLs

        This is the fallback when LLM-based extraction is unavailable.
        """
        entities: set[str] = set()

        # Known project/service names (case-insensitive)
        known_names = [
            "tango", "vinifera", "schubert", "polyglot", "watson",
            "copernicus", "meetscribe", "foxtrot", "outline",
            "github", "gmail", "redis", "postgres", "ollama",
            "caddy", "cloudflare", "discord", "tailscale",
            "docker", "systemd",
        ]
        text_lower = text.lower()
        for name in known_names:
            if name in text_lower:
                entities.add(name)

        # Service names (xxx.service)
        for match in re.finditer(r'\b([a-zA-Z0-9@._-]+\.service)\b', text):
            entities.add(match.group(1).lower())

        # MCP server references
        for match in re.finditer(r'\b(\w+)_mcp\b', text_lower):
            entities.add(match.group(1))

        # Port references (e.g., "port 8091")
        for match in re.finditer(r'\bport\s+(\d+)\b', text_lower):
            entities.add(f"port_{match.group(1)}")

        # Capitalized phrases (potential proper nouns, 2+ words or single word)
        for match in re.finditer(r'\b([A-Z][a-z]+(?:\s+[A-Z][a-z]+)*)\b', text):
            phrase = match.group(1).strip()
            if len(phrase) > 2 and phrase not in {"The", "A", "An", "This", "That", "It"}:
                candidate = phrase.lower()
                if self._is_valid_entity(candidate):
                    entities.add(candidate)

        return list(entities)

    def _reconcile_entities(
        self, entity_names: list[str], source_text: str, project: str = "",
    ) -> list[int]:
        """
        Reconcile extracted entities with the Postgres entity graph.

        For each entity:
        - If it exists, update updated_at and merge any new info
        - If it doesn't exist, create it

        Also extracts and stores facts from the source text.

        Returns:
            List of entity IDs for relationship creation.
        """
        if not entity_names:
            return []

        conn = self._get_pg()
        return self._reconcile_entities_pg(conn, entity_names, source_text, project)

    def _reconcile_entities_pg(
        self, conn, entity_names: list[str], source_text: str, project: str = "",
    ) -> list[int]:
        """
        Reconcile entities using a provided Postgres connection.

        This allows the async background thread to use its own connection.
        """
        if not entity_names:
            return []

        entity_ids: list[int] = []

        with conn.cursor() as cur:
            for name in entity_names:
                # Try to find existing entity
                cur.execute(
                    "SELECT id, type, description FROM memory_entities WHERE name = %s",
                    (name,),
                )
                row = cur.fetchone()

                if row:
                    # Entity exists — update timestamp
                    entity_id, etype, desc = row
                    cur.execute(
                        "UPDATE memory_entities SET updated_at = NOW() WHERE id = %s",
                        (entity_id,),
                    )
                else:
                    # Create new entity
                    etype = self._classify_entity(name)
                    cur.execute(
                        "INSERT INTO memory_entities (name, type, description) "
                        "VALUES (%s, %s, %s) RETURNING id",
                        (name, etype, ""),
                    )
                    entity_id = cur.fetchone()[0]
                    logger.info(f"Created entity: {name} (type={etype}, id={entity_id})")

                entity_ids.append(entity_id)

            # Extract and store facts
            facts = self._extract_facts(source_text, entity_names)
            for entity_name, fact in facts:
                cur.execute(
                    "SELECT id FROM memory_entities WHERE name = %s", (entity_name,)
                )
                ent_row = cur.fetchone()
                if ent_row:
                    ent_id = ent_row[0]
                    # Check if fact already exists (simple dedup)
                    cur.execute(
                        "SELECT id FROM memory_facts WHERE entity_id = %s AND fact = %s",
                        (ent_id, fact),
                    )
                    if not cur.fetchone():
                        cur.execute(
                            "INSERT INTO memory_facts (entity_id, fact, source) "
                            "VALUES (%s, %s, 'conversation')",
                            (ent_id, fact),
                        )

        return entity_ids

    def _classify_entity(self, name: str) -> str:
        """Classify an entity name into a type."""
        if name.endswith(".service"):
            return "service"
        if name in {"tango", "vinifera", "schubert", "polyglot", "watson",
                     "copernicus", "meetscribe", "foxtrot", "outline"}:
            return "project"
        if name in {"github", "gmail", "redis", "postgres", "ollama",
                     "caddy", "cloudflare", "discord", "docker"}:
            return "tool"
        if name.startswith("port_"):
            return "port"
        return "concept"

    def _extract_facts(self, text: str, entity_names: list[str]) -> list[tuple[str, str]]:
        """
        Extract factual statements about entities from text.

        Simple heuristic: split text into sentences, and for each sentence
        that mentions an entity, store it as a fact about that entity.
        """
        facts: list[tuple[str, str]] = []

        # Split into sentences (simple split on . ! ?)
        sentences = re.split(r'[.!?]+', text)

        for sentence in sentences:
            sentence = sentence.strip()
            if len(sentence) < 10:
                continue
            sentence_lower = sentence.lower()
            for entity in entity_names:
                if entity in sentence_lower:
                    facts.append((entity, sentence[:300]))
                    # Don't break — store the fact for every entity mentioned

        return facts

    def _create_relationships(self, entity_ids: list[int]) -> None:
        """Create 'related_to' relationships between co-mentioned entities."""
        if len(entity_ids) < 2:
            return

        conn = self._get_pg()
        self._create_relationships_pg(conn, entity_ids)

    def _create_relationships_pg(self, conn, entity_ids: list[int]) -> None:
        """Create relationships using a provided Postgres connection."""
        if len(entity_ids) < 2:
            return

        with conn.cursor() as cur:
            for i, source_id in enumerate(entity_ids):
                for target_id in entity_ids[i + 1:]:
                    try:
                        cur.execute(
                            "INSERT INTO memory_relationships (source_id, target_id, type, strength) "
                            "VALUES (%s, %s, 'related_to', 1.0) "
                            "ON CONFLICT (source_id, target_id, type) "
                            "DO UPDATE SET strength = memory_relationships.strength + 0.1",
                            (source_id, target_id),
                        )
                    except Exception:
                        pass  # Ignore constraint violations

    # -- Temporal index ---------------------------------------------------

    def _create_event(
        self,
        memory_id: str,
        event_type: str,
        project: str,
        session_id: str,
        summary: str,
        entities: list[str],
    ) -> None:
        """Create a temporal event record in Postgres."""
        conn = self._get_pg()
        with conn.cursor() as cur:
            cur.execute(
                "INSERT INTO memory_events "
                "(memory_id, event_type, project, session_id, summary, entities) "
                "VALUES (%s, %s, %s, %s, %s, %s)",
                (memory_id, event_type, project, session_id, summary, entities),
            )

    # -- Search (semantic route via pgvector) ------------------------------

    def search(self, query: str, k: int = MAX_SEARCH_RESULTS) -> list[dict]:
        """
        Semantic vector search via pgvector HNSW index.

        Generates an embedding for the query and uses the pgvector cosine
        distance operator (<=>) with the HNSW index for sub-linear approximate
        nearest neighbor search. This replaces the previous Redis-based Python
        cosine similarity scan that was O(n) over all stored embeddings.

        Args:
            query: The search query
            k: Maximum number of results to return

        Returns:
            List of memory dicts with text, similarity score, and metadata.
        """
        query_embedding = self._generate_embedding(query)

        # Check for zero embedding (generation failed)
        if np.all(query_embedding == 0):
            logger.warning("Query embedding is zero vector, skipping search")
            return []

        conn = self._get_pg()
        emb_str = "[" + ",".join(str(float(x)) for x in query_embedding) + "]"

        # pgvector cosine distance: 0 = identical, 2 = opposite
        # similarity = 1 - distance
        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            cur.execute(
                "SELECT memory_id, text, project, session_id, timestamp, event_type, "
                "1 - (embedding <=> %s::vector) AS similarity "
                "FROM memory_vectors "
                "WHERE 1 - (embedding <=> %s::vector) >= %s "
                "ORDER BY embedding <=> %s::vector "
                "LIMIT %s",
                (emb_str, emb_str, COSINE_THRESHOLD, emb_str, k),
            )
            rows = cur.fetchall()

        return [
            {
                "id": r["memory_id"],
                "text": r["text"],
                "similarity": float(r["similarity"]),
                "project": r["project"] or "",
                "session_id": r["session_id"] or "",
                "timestamp": r["timestamp"].isoformat() if r["timestamp"] else "",
                "event_type": r["event_type"] or "",
            }
            for r in rows
        ]

    # -- Entity retrieval (entity route) -----------------------------------

    def get_entity(self, name: str) -> dict | None:
        """
        Look up an entity by name, including its facts and relationships.

        Returns:
            Dict with entity info, facts, and related entities, or None.
        """
        conn = self._get_pg()
        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            cur.execute(
                "SELECT * FROM memory_entities WHERE name = %s", (name,)
            )
            entity = cur.fetchone()
            if not entity:
                return None

            # Get facts
            cur.execute(
                "SELECT fact, source, confidence, created_at FROM memory_facts "
                "WHERE entity_id = %s ORDER BY created_at DESC", (entity["id"],)
            )
            facts = cur.fetchall()

            # Get relationships (outgoing)
            cur.execute(
                "SELECT e.name, e.type, r.type as rel_type, r.strength "
                "FROM memory_relationships r "
                "JOIN memory_entities e ON r.target_id = e.id "
                "WHERE r.source_id = %s", (entity["id"],)
            )
            related = cur.fetchall()

            return {
                "name": entity["name"],
                "type": entity["type"],
                "description": entity["description"],
                "facts": [{"fact": f["fact"], "source": f["source"]} for f in facts],
                "related": [{"name": r["name"], "type": r["type"],
                             "relationship": r["rel_type"]} for r in related],
                "created_at": entity["created_at"].isoformat() if entity["created_at"] else "",
                "updated_at": entity["updated_at"].isoformat() if entity["updated_at"] else "",
            }

    def _entity_route(self, query: str, k: int = 5) -> list[dict]:
        """
        Entity route: extract entities from query, look up in Postgres,
        return connected facts and recent events.

        Returns memory-like dicts for merge with semantic results.
        """
        entities = self._extract_entities(query)
        if not entities:
            return []

        conn = self._get_pg()
        results: list[dict] = []

        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            for entity_name in entities:
                # Get entity facts
                cur.execute(
                    "SELECT f.fact, f.created_at, e.name as entity_name "
                    "FROM memory_facts f "
                    "JOIN memory_entities e ON f.entity_id = e.id "
                    "WHERE e.name = %s "
                    "ORDER BY f.created_at DESC LIMIT 3",
                    (entity_name,),
                )
                for row in cur.fetchall():
                    results.append({
                        "id": f"entity:{row['entity_name']}:{row['fact'][:20]}",
                        "text": row["fact"],
                        "similarity": 0.5,  # Baseline score for entity matches
                        "project": "",
                        "session_id": "",
                        "timestamp": row["created_at"].isoformat() if row["created_at"] else "",
                        "event_type": "entity_fact",
                        "entity": row["entity_name"],
                    })

                # Get recent events mentioning this entity
                cur.execute(
                    "SELECT summary, created_at, project, event_type "
                    "FROM memory_events "
                    "WHERE %s = ANY(entities) "
                    "ORDER BY created_at DESC LIMIT 2",
                    (entity_name,),
                )
                for row in cur.fetchall():
                    results.append({
                        "id": f"event:{entity_name}:{row['created_at'].isoformat() if row['created_at'] else ''}",
                        "text": row["summary"],
                        "similarity": 0.4,  # Lower score for temporal matches
                        "project": row["project"],
                        "session_id": "",
                        "timestamp": row["created_at"].isoformat() if row["created_at"] else "",
                        "event_type": row["event_type"],
                        "entity": entity_name,
                    })

        return results[:k]

    # -- Dual-route retrieval ----------------------------------------------

    def recall(self, query: str, k: int = MAX_RECALL_RESULTS) -> str:
        """
        Dual-route retrieval: combine semantic search and entity graph traversal.

        This is the primary API for injecting recalled memories into the LLM
        context. It returns a formatted string suitable for injection into
        the system prompt.

        Args:
            query: The query (typically the user's message)
            k: Maximum number of memories to return

        Returns:
            Formatted string with recalled memories, or empty string if none found.
        """
        # Semantic route
        semantic_results = self.search(query, k=k)

        # Entity route
        entity_results = self._entity_route(query, k=k)

        # Merge and deduplicate
        all_results = semantic_results + entity_results
        seen_ids: set[str] = set()
        unique: list[dict] = []
        for r in all_results:
            if r["id"] not in seen_ids:
                seen_ids.add(r["id"])
                unique.append(r)

        # Sort by similarity (semantic results have real scores, entity have baseline)
        unique.sort(key=lambda x: x["similarity"], reverse=True)
        unique = unique[:k]

        if not unique:
            return ""

        # Format for injection
        lines = ["## Recalled Memories"]
        for i, r in enumerate(unique, 1):
            timestamp = r.get("timestamp", "")[:19] if r.get("timestamp") else ""
            project = r.get("project", "")
            sim = r.get("similarity", 0)
            entity = r.get("entity", "")
            source_label = f"[{r.get('event_type', 'memory')}]"
            if project:
                source_label += f" [{project}]"
            if entity:
                source_label += f" [{entity}]"
            if timestamp:
                source_label += f" [{timestamp}]"

            lines.append(f"{i}. {source_label} {r['text'][:300]}")

        return "\n".join(lines)

    # -- Temporal queries --------------------------------------------------

    def get_recent(
        self, project: str = "", k: int = 5, event_type: str = "",
    ) -> list[dict]:
        """
        Get recent memory events, optionally filtered by project and event type.

        Args:
            project: Filter by project name (empty for all)
            k: Maximum number of events
            event_type: Filter by event type (empty for all)

        Returns:
            List of event dicts with summary, timestamp, project, entities.
        """
        conn = self._get_pg()
        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            query_parts = ["SELECT * FROM memory_events"]
            conditions = []
            params = []

            if project:
                conditions.append("project = %s")
                params.append(project)
            if event_type:
                conditions.append("event_type = %s")
                params.append(event_type)

            if conditions:
                query_parts.append("WHERE " + " AND ".join(conditions))

            query_parts.append("ORDER BY created_at DESC LIMIT %s")
            params.append(k)

            cur.execute(" ".join(query_parts), params)
            rows = cur.fetchall()

        return [
            {
                "id": str(r["id"]),
                "memory_id": r["memory_id"],
                "event_type": r["event_type"],
                "project": r["project"],
                "summary": r["summary"],
                "entities": r["entities"],
                "timestamp": r["created_at"].isoformat() if r["created_at"] else "",
            }
            for r in rows
        ]

    def get_recent_formatted(self, project: str = "", k: int = 5) -> str:
        """Get recent memories as a formatted string for context injection."""
        events = self.get_recent(project=project, k=k)
        if not events:
            return ""

        lines = ["## Recent Activity"]
        for e in events:
            timestamp = e["timestamp"][:19] if e["timestamp"] else ""
            entities = ", ".join(e.get("entities", []))
            lines.append(
                f"- [{timestamp}] [{e['event_type']}] {e['summary'][:200]}"
                + (f" (entities: {entities})" if entities else "")
            )
        return "\n".join(lines)

    # -- Stats -------------------------------------------------------------

    def get_stats(self) -> dict:
        """Get memory store statistics for monitoring/debugging."""
        conn = self._get_pg()
        stats: dict[str, Any] = {}
        with conn.cursor() as cur:
            cur.execute("SELECT COUNT(*) FROM memory_vectors")
            stats["vectors"] = cur.fetchone()[0]
            cur.execute("SELECT COUNT(*) FROM memory_entities")
            stats["entities"] = cur.fetchone()[0]
            cur.execute("SELECT COUNT(*) FROM memory_facts")
            stats["facts"] = cur.fetchone()[0]
            cur.execute("SELECT COUNT(*) FROM memory_events")
            stats["events"] = cur.fetchone()[0]
            cur.execute("SELECT COUNT(*) FROM memory_relationships")
            stats["relationships"] = cur.fetchone()[0]

        # Redis stats (backward compatibility — may show 0 if Redis was cleaned)
        try:
            r = self._get_redis()
            stats["redis_memories"] = r.scard("mem:index")
        except Exception:
            stats["redis_memories"] = 0

        return stats

    # -- Change Log --------------------------------------------------------

    def log_change(
        self,
        actor: str,
        action: str,
        target: str = "",
        description: str = "",
        intent: str = "",
        outcome: str = "pending",
        details: dict | None = None,
    ) -> int:
        """
        Log a change made to the system by any actor (Architect, WRITER Agent,
        AutoUpdater, manual SSH, etc.) to the change_log table.

        Returns the ID of the created log entry, or -1 on failure.
        """
        try:
            conn = self._get_pg()
            with conn.cursor() as cur:
                cur.execute(
                    """INSERT INTO change_log
                        (actor, action, target, description, intent, outcome, details)
                        VALUES (%s, %s, %s, %s, %s, %s, %s)
                        RETURNING id""",
                    (
                        actor,
                        action,
                        target,
                        description[:2000],
                        intent[:500],
                        outcome,
                        json.dumps(details) if details else "{}",
                    ),
                )
                row = cur.fetchone()
                log_id = row[0] if row else -1
            logger.info(f"Change logged: {actor}/{action} on {target} (id={log_id})")
            return log_id
        except Exception as e:
            logger.error(f"Failed to log change: {e}")
            return -1

    def update_change_outcome(self, log_id: int, outcome: str, details: dict | None = None) -> bool:
        """Update the outcome of a previously logged change."""
        try:
            conn = self._get_pg()
            with conn.cursor() as cur:
                if details:
                    cur.execute(
                        """UPDATE change_log SET outcome = %s, details = details || %s::jsonb
                           WHERE id = %s""",
                        (outcome, json.dumps(details), log_id),
                    )
                else:
                    cur.execute(
                        """UPDATE change_log SET outcome = %s WHERE id = %s""",
                        (outcome, log_id),
                    )
            return True
        except Exception as e:
            logger.error(f"Failed to update change outcome: {e}")
            return False

    def get_change_log(self, limit: int = 20, actor: str = "") -> list[dict]:
        """Get recent change log entries."""
        try:
            conn = self._get_pg()
            with conn.cursor() as cur:
                if actor:
                    cur.execute(
                        """SELECT id, actor, action, target, description, intent,
                                  outcome, details, created_at
                           FROM change_log WHERE actor = %s
                           ORDER BY created_at DESC LIMIT %s""",
                        (actor, limit),
                    )
                else:
                    cur.execute(
                        """SELECT id, actor, action, target, description, intent,
                                  outcome, details, created_at
                           FROM change_log ORDER BY created_at DESC LIMIT %s""",
                        (limit,),
                    )
                rows = cur.fetchall()
            return [
                {
                    "id": r[0],
                    "actor": r[1],
                    "action": r[2],
                    "target": r[3],
                    "description": r[4],
                    "intent": r[5],
                    "outcome": r[6],
                    "details": r[7] if r[7] else {},
                    "created_at": r[8].isoformat() if r[8] else "",
                }
                for r in rows
            ]
        except Exception as e:
            logger.error(f"Failed to get change log: {e}")
            return []
