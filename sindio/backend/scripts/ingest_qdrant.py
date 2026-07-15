"""
Ingest real sensor data from PostgreSQL into Qdrant.

- Reads the `DB_HOST`, `DB_USER`, `DB_PASSWORD`, `DB_NAME` env vars
- Connects to PostgreSQL via SQLAlchemy
- Serialises rows to numpy vectors (you can adapt the vectorisation logic)
- Sends vectors to Qdrant using the `qdrant-client` library.
"""

import os
import logging
from sqlalchemy import create_engine, text
import numpy as np
from qdrant_client import QdrantClient
from qdrant_client.http.models import PointStruct

logging.basicConfig(level=logging.INFO)
log = logging.getLogger(__name__)

def _postgres_engine():
    url = (
        f"postgresql://"
        f"{os.getenv('DB_USER', 'sindio_user')}:"
        f"{os.getenv('DB_PASSWORD')}"
        f"@{os.getenv('DB_HOST', 'postgres')}:5432/"
        f"{os.getenv('DB_NAME', 'sindio')}"
    )
    return create_engine(url, echo=False)

def _qdrant_client():
    return QdrantClient(
        host=os.getenv("QDRANT_HOST", "qdrant"),
        port=6333,
        api_key=os.getenv("QDRANT_API_KEY"),
        prefer_grpc=False,
    )

def _vectorise(row: dict) -> np.ndarray:
    """Convert a DB row into a numeric vector.
    This placeholder simply flattens numeric fields; replace with your own
    feature‑extraction logic if needed.
    """
    numeric_vals = [float(v) for v in row.values() if isinstance(v, (int, float))]
    return np.array(numeric_vals, dtype=np.float32)

def main():
    engine = _postgres_engine()
    qdrant = _qdrant_client()
    collection_name = "sensors"

    # Ensure collection exists
    if collection_name not in qdrant.get_collections().collections:
        qdrant.create_collection(
            collection_name=collection_name,
            vectors_config={"size": 8, "distance": "Cosine"}
        )
        log.info("Created Qdrant collection %s", collection_name)

    # Pull data from Postgres – adjust the query to the table you need
    query = text("SELECT id, * FROM sensor_data WHERE processed = false")
    with engine.connect() as conn:
        rows = conn.execute(query).fetchall()

    if not rows:
        log.info("No new rows to ingest.")
        return

    points = []
    for row in rows:
        row_dict = dict(row)
        vec = _vectorise(row_dict)
        points.append(
            PointStruct(
                id=row_dict["id"],
                vector=vec.tolist(),
                payload=row_dict,
            )
        )
        conn.execute(text("UPDATE sensor_data SET processed = true WHERE id = :id"), {"id": row_dict["id"]})

    qdrant.upsert(collection_name=collection_name, points=points)
    log.info("Ingested %d points into Qdrant.", len(points))

if __name__ == "__main__":
    main()
