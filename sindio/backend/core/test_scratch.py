import os
os.environ["ENV"] = "test"
os.environ["DB_PASSWORD"] = "test123"
os.environ["DB_HOST"] = "localhost"
os.environ["DB_PORT"] = "5432"
os.environ["DB_NAME"] = "sindio_test"
os.environ["DB_USER"] = "sindio_user"

from fastapi.testclient import TestClient
from app.main import app

client = TestClient(app)

response = client.get("/api/infrastructure/nonexistent")
print("STATUS:", response.status_code)
print("BODY:", response.json())
