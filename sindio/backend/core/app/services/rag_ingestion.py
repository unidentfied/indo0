"""
RAG Document Ingestion Pipeline
================================

Watches ``/data/documents/`` for PDF, DOCX, TXT, HTML files and:
  1. Parses them with ``unstructured``
  2. Chunks into paragraph-level segments (500 tokens, 50-overlap)
  3. Extracts metadata: source_file, page_num, wards (spaCy NER),
     infrastructure_type (keyword match), document year
  4. Embeds chunks with ``BAAI/bge-large-en-v1.5`` (1024-dim)
  5. Upserts to Qdrant collection ``nairobi_planning_docs``
  6. Stores full text in PostgreSQL for keyword fallback

Usage::

    python -m app.services.rag_ingestion [--watch] [--once] [--dir /data/documents/]
"""

from __future__ import annotations

import hashlib
import logging
import os
import re
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Set, Tuple

import numpy as np
from dotenv import load_dotenv

load_dotenv()

logger = logging.getLogger("sindio.rag_ingestion")

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

EMBEDDING_MODEL = "BAAI/bge-large-en-v1.5"
EMBEDDING_DIM = 1024
QDRANT_COLLECTION = "nairobi_planning_docs"
CHUNK_TOKENS = 500
CHUNK_OVERLAP = 50

# Nairobi wards — spaCy NER fallback + substring match list
NAIROBI_WARDS: Set[str] = {
    "Kilimani", "Upper Hill", "Westlands", "CBD", "Central District",
    "Karen", "Eastleigh", "Langata", "Parklands", "Ngong Road",
    "Industrial Area", "Kibera", "Mathare", "Dandora", "Ruaraka",
    "Embakasi", "Kasarani", "Dagoretti", "Makadara", "Kamukunji",
    "Starehe", "Roysambu",
}

# Infrastructure type keyword matcher
INFRA_KEYWORDS: Dict[str, List[str]] = {
    "power": [
        "electricity", "power grid", "substation", "transformer", "kWh",
        "kilovolt", "generation capacity", "distribution network",
        "transmission line", "load shedding", "renewable energy",
        "solar farm", "grid stability",
    ],
    "water": [
        "water supply", "water main", "reservoir", "pump station",
        "borehole", "sewer", "sanitation", "wastewater", "pipe network",
        "water pressure", "treatment plant", "water quality",
    ],
    "roads": [
        "highway", "road network", "pavement", "bridge", "interchange",
        "bus rapid transit", "BRT", "expressway", "bypass", "roundabout",
        "traffic", "congestion", "pedestrian", "cycling lane",
    ],
    "sidewalks": [
        "pedestrian", "footpath", "sidewalk", "walkway", "non-motorised",
        "NMT", "crossing", "footbridge", "pedestrian bridge",
    ],
    "lrt": [
        "light rail", "LRT", "commuter rail", "tram", "light metro",
        "rail transit", "train station", "railway", "track gauge",
    ],
    "sgr": [
        "standard gauge", "SGR", "freight rail", "Madaraka Express",
        "rail corridor", "locomotive", "rolling stock", "rail freight",
    ],
    "airports": [
        "airport", "runway", "terminal", "JKIA", "Jomo Kenyatta",
        "Wilson Airport", "airstrip", "aviation", "air traffic",
        "KCAA", "Kenya Airports Authority",
    ],
    "solid_waste": [
        "solid waste", "landfill", "recycling", "waste collection",
        "dumpsite", "composting", "waste management", "garbage",
    ],
}

# ---------------------------------------------------------------------------
# Embedding model (lazy-loaded singleton)
# ---------------------------------------------------------------------------

_embedding_model: Any = None


def _get_embedder() -> Any:
    global _embedding_model
    if _embedding_model is None:
        logger.info("Loading embedding model: %s", EMBEDDING_MODEL)
        from sentence_transformers import SentenceTransformer

        _embedding_model = SentenceTransformer(EMBEDDING_MODEL, device="cpu")
        logger.info("Embedding model loaded (dim=%d)", _embedding_model.get_sentence_embedding_dimension())
    return _embedding_model


# ---------------------------------------------------------------------------
# spaCy NER (lazy-loaded singleton)
# ---------------------------------------------------------------------------

_nlp: Any = None


def _get_nlp() -> Any:
    global _nlp
    if _nlp is None:
        try:
            import spacy
            _nlp = spacy.load("en_core_web_sm")
        except OSError:
            logger.warning("spaCy model 'en_core_web_sm' not found — downloading...")
            import spacy
            spacy.cli.download("en_core_web_sm")
            _nlp = spacy.load("en_core_web_sm")
        logger.info("spaCy NER pipeline ready")
    return _nlp


# ---------------------------------------------------------------------------
# PostgreSQL connection (lazy)
# ---------------------------------------------------------------------------

_pg_pool: Any = None


def _get_pg_pool() -> Any:
    global _pg_pool
    if _pg_pool is None:
        from psycopg2 import pool as pgpool
        db_url = os.getenv(
            "DATABASE_URL",
            f"postgresql://{os.getenv('DB_USER','sindio_user')}:{os.getenv('DB_PASSWORD','sindio_pass')}"
            f"@{os.getenv('DB_HOST','localhost')}:{os.getenv('DB_PORT','5432')}/{os.getenv('DB_NAME','sindio')}",
        )
        _pg_pool = pgpool.ThreadedConnectionPool(
            minconn=2,
            maxconn=5,
            dsn=db_url,
        )
        _init_pg_table()
        logger.info("PostgreSQL pool ready")
    return _pg_pool


def _init_pg_table() -> None:
    """Ensure the document_chunks table exists (idempotent)."""
    pool = _get_pg_pool()
    conn = pool.getconn()
    try:
        with conn.cursor() as cur:
            cur.execute("""
                CREATE TABLE IF NOT EXISTS document_chunks (
                    id                UUID PRIMARY KEY DEFAULT gen_random_uuid(),
                    source_file       TEXT NOT NULL,
                    page_num          INTEGER,
                    chunk_index       INTEGER NOT NULL,
                    chunk_text        TEXT NOT NULL,
                    chunk_tokens      INTEGER,
                    wards_mentioned   TEXT[],
                    infrastructure_type TEXT,
                    document_year     INTEGER,
                    qdrant_point_id   TEXT,
                    embedding_model   TEXT,
                    metadata          JSONB DEFAULT '{}',
                    created_at        TIMESTAMPTZ DEFAULT NOW()
                );
            """)
            cur.execute("""
                CREATE INDEX IF NOT EXISTS idx_doc_chunks_fts
                    ON document_chunks USING GIN (to_tsvector('english', chunk_text));
            """)
            cur.execute("""
                CREATE INDEX IF NOT EXISTS idx_doc_chunks_source
                    ON document_chunks (source_file, chunk_index);
            """)
            cur.execute("""
                CREATE INDEX IF NOT EXISTS idx_doc_chunks_qdrant
                    ON document_chunks (qdrant_point_id)
                    WHERE qdrant_point_id IS NOT NULL;
            """)
            conn.commit()
    finally:
        pool.putconn(conn)


# ---------------------------------------------------------------------------
# Qdrant client (lazy)
# ---------------------------------------------------------------------------

_qdrant: Any = None


def _get_qdrant() -> Any:
    global _qdrant
    if _qdrant is None:
        from qdrant_client import QdrantClient
        from qdrant_client.http.models import Distance, VectorParams

        host = os.getenv("QDRANT_HOST", "http://localhost:6333")
        api_key = os.getenv("QDRANT_API_KEY", "") or None
        _qdrant = QdrantClient(url=host, api_key=api_key, timeout=60)

        # Ensure collection exists
        collections = {c.name for c in _qdrant.get_collections().collections}
        if QDRANT_COLLECTION not in collections:
            _qdrant.create_collection(
                collection_name=QDRANT_COLLECTION,
                vectors_config=VectorParams(
                    size=EMBEDDING_DIM,
                    distance=Distance.COSINE,
                ),
            )
            logger.info("Created Qdrant collection '%s' (dim=%d)", QDRANT_COLLECTION, EMBEDDING_DIM)
        else:
            logger.debug("Qdrant collection '%s' already exists", QDRANT_COLLECTION)
    return _qdrant


# ---------------------------------------------------------------------------
# Document parsing with unstructured
# ---------------------------------------------------------------------------

def parse_document(filepath: Path) -> List[Dict[str, Any]]:
    """Parse a document file into a list of element dicts with text + metadata."""
    from unstructured.partition.auto import partition

    logger.info("Parsing: %s", filepath.name)
    elements = partition(filename=str(filepath), strategy="auto")

    parsed: List[Dict[str, Any]] = []
    for el in elements:
        text = str(el).strip() if hasattr(el, "text") else str(el).strip()
        if not text or len(text) < 20:
            continue
        meta = el.metadata.to_dict() if hasattr(el, "metadata") else {}
        parsed.append({
            "text": text,
            "page_number": meta.get("page_number"),
            "filename": meta.get("filename", filepath.name),
            "element_type": type(el).__name__,
        })
    logger.info("  → %d text elements extracted", len(parsed))
    return parsed


# ---------------------------------------------------------------------------
# Token-based chunking
# ---------------------------------------------------------------------------

def _count_tokens(text: str, tokenizer: Any) -> int:
    return len(tokenizer.encode(text, add_special_tokens=False))


def chunk_documents(
    elements: List[Dict[str, Any]],
    max_tokens: int = CHUNK_TOKENS,
    overlap: int = CHUNK_OVERLAP,
) -> List[Dict[str, Any]]:
    """Merge elements into overlapping token-length chunks (paragraph-level)."""
    from transformers import AutoTokenizer

    tokenizer = AutoTokenizer.from_pretrained(EMBEDDING_MODEL)

    # Concatenate all element texts with separators
    paragraphs: List[Tuple[str, Optional[int], str]] = []  # (text, page, filename)
    for el in elements:
        paragraphs.append((el["text"], el.get("page_number"), el.get("filename", "")))

    chunks: List[Dict[str, Any]] = []
    current_text = ""
    current_pages: Set[int] = set()
    current_files: Set[str] = set()

    buffer: List[Tuple[str, Optional[int], str]] = []
    buffer_tokens = 0

    for text, page, fname in paragraphs:
        para_tokens = _count_tokens(text, tokenizer)

        if buffer_tokens + para_tokens > max_tokens and buffer:
            # Flush current chunk
            chunk_text = " ".join(t[0] for t in buffer)
            chunks.append({
                "text": chunk_text,
                "pages": sorted(current_pages),
                "files": sorted(current_files),
            })

            # Keep overlap: last `overlap` tokens from buffer
            overlap_tokens = 0
            overlap_buffer: List[Tuple[str, Optional[int], str]] = []
            for t in reversed(buffer):
                t_count = _count_tokens(t[0], tokenizer)
                if overlap_tokens + t_count > overlap:
                    break
                overlap_buffer.insert(0, t)
                overlap_tokens += t_count

            buffer = overlap_buffer
            current_pages = {t[1] for t in buffer if t[1] is not None}
            current_files = {t[2] for t in buffer if t[2]}
            buffer_tokens = overlap_tokens

        buffer.append((text, page, fname))
        buffer_tokens += para_tokens
        if page is not None:
            current_pages.add(page)
        if fname:
            current_files.add(fname)

    # Flush remaining
    if buffer:
        chunks.append({
            "text": " ".join(t[0] for t in buffer),
            "pages": sorted(current_pages),
            "files": sorted(current_files),
        })

    logger.info("  → %d chunks created (target %d tokens, %d overlap)", len(chunks), max_tokens, overlap)
    return chunks


# ---------------------------------------------------------------------------
# Metadata extraction
# ---------------------------------------------------------------------------

def extract_wards(text: str) -> List[str]:
    """Extract Nairobi ward mentions via spaCy NER + substring match."""
    nlp = _get_nlp()
    doc = nlp(text[:10000])  # Truncate for performance

    found: Set[str] = set()

    # spaCy NER for GPE/LOC
    for ent in doc.ents:
        if ent.label_ in ("GPE", "LOC", "FAC"):
            for ward in NAIROBI_WARDS:
                if ward.lower() in ent.text.lower():
                    found.add(ward)

    # Substring fallback
    lower_text = text.lower()
    for ward in NAIROBI_WARDS:
        if ward.lower() in lower_text:
            found.add(ward)

    return sorted(found)


def extract_infrastructure_type(text: str) -> Optional[str]:
    """Classify chunk by infrastructure type via keyword density."""
    lower = text.lower()
    scores: Dict[str, int] = {}
    for infra_type, keywords in INFRA_KEYWORDS.items():
        score = sum(1 for kw in keywords if kw.lower() in lower)
        if score > 0:
            scores[infra_type] = score
    if not scores:
        return None
    return max(scores, key=lambda k: scores[k])


def extract_year(text: str) -> Optional[int]:
    """Extract the most likely document year via regex."""
    years = re.findall(r"\b(19[89]\d|20[0-2]\d)\b", text)
    if not years:
        return None
    # Prefer years >= 2000 as context window
    candidate = max(int(y) for y in years)
    return candidate if 2000 <= candidate <= 2030 else int(years[0])


def enrich_metadata(chunk: Dict[str, Any]) -> Dict[str, Any]:
    """Add wards, infrastructure_type, and year to chunk metadata."""
    text = chunk["text"]
    chunk["wards"] = extract_wards(text)
    chunk["infrastructure_type"] = extract_infrastructure_type(text)
    chunk["year"] = extract_year(text)
    return chunk


# ---------------------------------------------------------------------------
# Embedding + Qdrant + PostgreSQL storage
# ---------------------------------------------------------------------------

def embed_chunks(chunks: List[Dict[str, Any]]) -> List[np.ndarray]:
    """Batch-embed all chunks with BAAI/bge-large-en-v1.5."""
    model = _get_embedder()
    texts = [c["text"] for c in chunks]
    logger.info("Embedding %d chunks...", len(texts))
    # bge models benefit from instruction prefix
    embeddings = model.encode(
        texts,
        batch_size=32,
        show_progress_bar=True,
        normalize_embeddings=True,
    )
    return embeddings


def upsert_to_qdrant(
    chunks: List[Dict[str, Any]],
    embeddings: np.ndarray,
) -> List[str]:
    """Batch-upsert chunks + embeddings into Qdrant."""
    from qdrant_client.http.models import PointStruct

    client = _get_qdrant()
    point_ids: List[str] = []
    points: List[PointStruct] = []

    for i, (chunk, emb) in enumerate(zip(chunks, embeddings)):
        pid = str(uuid.uuid4())
        point_ids.append(pid)
        chunk["qdrant_point_id"] = pid

        # Build payload — keep under Qdrant's payload size limits
        payload: Dict[str, Any] = {
            "source_file": chunk.get("files", ["unknown"])[0] if chunk.get("files") else "unknown",
            "page_num": chunk.get("pages", [None])[0],
            "chunk_index": i,
            "wards": chunk.get("wards", []),
            "infrastructure_type": chunk.get("infrastructure_type", ""),
            "year": chunk.get("year"),
            "chunk_text": chunk["text"][:8000],  # Truncate payload text
        }
        payload = {k: v for k, v in payload.items() if v is not None and v != ""}

        points.append(PointStruct(
            id=pid,
            vector=emb.tolist(),
            payload=payload,
        ))

    # Upsert in batches of 100
    for batch_start in range(0, len(points), 100):
        batch = points[batch_start:batch_start + 100]
        client.upsert(collection_name=QDRANT_COLLECTION, points=batch)
        logger.debug("  Qdrant upserted %d points", len(batch))

    logger.info("Qdrant: %d points upserted to '%s'", len(points), QDRANT_COLLECTION)
    return point_ids


def store_in_postgres(chunks: List[Dict[str, Any]]) -> None:
    """Store full text in PostgreSQL for keyword / FTS fallback."""
    pool = _get_pg_pool()
    conn = pool.getconn()
    try:
        with conn.cursor() as cur:
            for i, chunk in enumerate(chunks):
                cur.execute(
                    """
                    INSERT INTO document_chunks
                        (source_file, page_num, chunk_index, chunk_text, chunk_tokens,
                         wards_mentioned, infrastructure_type, document_year,
                         qdrant_point_id, embedding_model, metadata)
                    VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                    ON CONFLICT DO NOTHING
                    """,
                    (
                        chunk.get("files", ["unknown"])[0] if chunk.get("files") else "unknown",
                        chunk.get("pages", [None])[0],
                        i,
                        chunk["text"],
                        len(chunk["text"].split()),
                        chunk.get("wards", []),
                        chunk.get("infrastructure_type"),
                        chunk.get("year"),
                        chunk.get("qdrant_point_id"),
                        EMBEDDING_MODEL,
                        {"element_count": len(chunk.get("text", "").split("\n"))},
                    ),
                )
            conn.commit()
    finally:
        pool.putconn(conn)
    logger.info("PostgreSQL: %d chunks stored in document_chunks", len(chunks))


# ---------------------------------------------------------------------------
# Processing state — track already-ingested files via content hash
# ---------------------------------------------------------------------------

def _file_hash(filepath: Path) -> str:
    """SHA-256 of file content (first 1 MB for speed)."""
    sha = hashlib.sha256()
    with open(filepath, "rb") as f:
        sha.update(f.read(1_048_576))
    return sha.hexdigest()


def _load_processed_hashes() -> Set[str]:
    """Load hashes of already-processed files from PostgreSQL."""
    seen: Set[str] = set()
    try:
        pool = _get_pg_pool()
        conn = pool.getconn()
        try:
            with conn.cursor() as cur:
                cur.execute("SELECT DISTINCT source_file FROM document_chunks")
                seen = {row[0] for row in cur.fetchall()}
        finally:
            pool.putconn(conn)
    except Exception:
        logger.warning("Could not load processed hashes from PG — processing all files")
    return seen


# ---------------------------------------------------------------------------
# Main ingestion loop
# ---------------------------------------------------------------------------

SUPPORTED_SUFFIXES = {".pdf", ".docx", ".txt", ".html", ".htm", ".md", ".rst"}


def ingest_directory(
    data_dir: Path,
    reprocess: bool = False,
) -> int:
    """Process all supported files in a directory. Returns count of files ingested."""
    if not data_dir.exists():
        logger.error("Directory not found: %s", data_dir)
        return 0

    files = sorted(
        f for f in data_dir.rglob("*")
        if f.is_file() and f.suffix.lower() in SUPPORTED_SUFFIXES and not f.name.startswith(".")
    )

    if not files:
        logger.info("No supported files found in %s", data_dir)
        return 0

    processed_files = _load_processed_hashes() if not reprocess else set()
    new_files = [f for f in files if f.name not in processed_files or reprocess]

    if not new_files:
        logger.info("All %d files already processed. Use --reprocess to re-ingest.", len(files))
        return 0

    logger.info("Found %d new files to ingest (total: %d)", len(new_files), len(files))
    ingested = 0

    for filepath in new_files:
        try:
            elements = parse_document(filepath)
            if not elements:
                logger.warning("  No text elements in %s — skipping", filepath.name)
                continue

            chunks = chunk_documents(elements)
            for ch in chunks:
                enrich_metadata(ch)

            embeddings = embed_chunks(chunks)
            upsert_to_qdrant(chunks, embeddings)
            store_in_postgres(chunks)

            ingested += 1
            logger.info("  ✓ Ingested %s (%d chunks)", filepath.name, len(chunks))
        except Exception as exc:
            logger.error("  ✗ Failed to ingest %s: %s", filepath.name, exc)

    return ingested


def watch_directory(data_dir: Path, poll_interval: int = 30) -> None:
    """Continuously watch a directory for new files."""
    logger.info("Watching %s (poll interval: %ds)", data_dir, poll_interval)
    logger.info("Supported formats: %s", ", ".join(SUPPORTED_SUFFIXES))

    try:
        while True:
            ingested = ingest_directory(data_dir)
            if ingested == 0:
                logger.debug("No new files — sleeping %ds", poll_interval)
            time.sleep(poll_interval)
    except KeyboardInterrupt:
        logger.info("Ingestion watcher stopped.")


# ---------------------------------------------------------------------------
# CLI entry-point
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="Sindio RAG Document Ingestion")
    parser.add_argument(
        "--dir",
        default=os.getenv("DOCUMENTS_DIR", "data/documents"),
        help="Directory to watch/scan (default: data/documents)",
    )
    parser.add_argument(
        "--watch",
        action="store_true",
        help="Continuously watch for new files (default: process once)",
    )
    parser.add_argument(
        "--reprocess",
        action="store_true",
        help="Re-ingest all files even if already processed",
    )
    parser.add_argument(
        "--interval",
        type=int,
        default=30,
        help="Polling interval in seconds for --watch mode (default: 30)",
    )
    args = parser.parse_args()

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(name)s] %(levelname)s: %(message)s",
    )

    data_dir = Path(args.dir).resolve()

    if args.watch:
        watch_directory(data_dir, poll_interval=args.interval)
    else:
        ingested = ingest_directory(data_dir, reprocess=args.reprocess)
        logger.info("Done. %d files ingested.", ingested)
