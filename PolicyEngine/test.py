import json
import pytest
from main import app  # Replace 'your_api_file' with the name of your Flask app file

@pytest.fixture
def client():
    with app.test_client() as client:
        yield client

def test_permission_allowed(client):
    """Test that a read action is allowed under the permission constraints."""
    data = {
        "target": "http://example.com/asset:123",
        "action": "read",
        "context": {"dateTime": "2023-06-01T12:00:00Z"}
    }
    response = client.post('/evaluate', json=data)
    assert response.status_code == 200
    assert response.json == {"allowed": True}

def test_prohibition_applies(client):
    """Test that a write action is prohibited after the specified date."""
    data = {
        "target": "http://example.com/asset:123",
        "action": "write",
        "context": {"dateTime": "2024-01-02T12:00:00Z"}
    }
    response = client.post('/evaluate', json=data)
    assert response.status_code == 200
    assert response.json == {"allowed": False, "reason": "Prohibition applies"}

def test_duty_not_met(client):
    """Test that a read action is not allowed if the duty (attribute) is not met."""
    data = {
        "target": "http://example.com/asset:123",
        "action": "read",
        "context": {"dateTime": "2024-02-01T12:00:00Z"}  # After the duty's constraint date
    }
    response = client.post('/evaluate', json=data)
    assert response.status_code == 200
    assert response.json == {"allowed": False, "reason": "Duty not met"}

def test_permission_with_unmet_constraint(client):
    """Test that a read action is not allowed if the permission's constraint is not met."""
    data = {
        "target": "http://example.com/asset:123",
        "action": "read",
        "context": {"dateTime": "2024-03-02T12:00:00Z"}  # After the permission's constraint date
    }
    response = client.post('/evaluate', json=data)
    assert response.status_code == 200
    assert response.json == {"allowed": False, "reason": "Constraint not satisfied for permission"}

def test_no_applicable_permission_found(client):
    """Test the response when no applicable permission or prohibition is found."""
    data = {
        "target": "http://example.com/asset:999",  # Non-existing target
        "action": "read",
        "context": {"dateTime": "2023-06-01T12:00:00Z"}
    }
    response = client.post('/evaluate', json=data)
    assert response.status_code == 200
    assert response.json == {"allowed": False, "reason": "No applicable permission found"}
