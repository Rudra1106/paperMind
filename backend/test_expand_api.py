import asyncio
from fastapi.testclient import TestClient
from app.main import app
from app.core.auth import get_current_user

# Mock auth dependency
def mock_get_current_user():
    return {"id": "test_user_id", "email": "test@test.com"}

app.dependency_overrides[get_current_user] = mock_get_current_user

client = TestClient(app)

response = client.post(
    "/api/v1/concepts/scaled_dot_product_attention/expand",
    json={"paper_id": "paper_123"}
)
print("STATUS:", response.status_code)
print("RESPONSE:", response.json())
