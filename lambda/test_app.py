import json
import time
from unittest.mock import patch, MagicMock


def make_event(route_key, method="POST", body=None, headers=None,
               path_params=None):
    """Helper to build API Gateway event for your Lambda function."""
    headers = headers or {}
    headers["authorization"] = "Bearer mock-token-123"

    if "content-type" not in headers and body is not None:
        headers["content-type"] = "application/json"

    event = {
        "version": "2.0",
        "routeKey": route_key,
        "rawPath": f"/{route_key.split()[-1]}",
        "requestContext": {
            "requestId": f"test-{int(time.time())}",
            "http": {
                "method": method
            },
            "routeKey": route_key
        },
        "headers": headers
    }

    if path_params:
        event["pathParameters"] = path_params

    if body is not None:
        event["body"] = json.dumps(body) if isinstance(body, dict) else body

    return event


# ---------------------------
# Happy Path Tests
# ---------------------------
@patch('boto3.client')
def test_stories_prepare(mock_boto3):
    """Test POST /stories/prepare"""
    mock_boto3.return_value = MagicMock()

    # Import app inside the test to use the mocked boto3
    import app

    event = make_event(
        "POST /stories/prepare",
        body={
            "voice_id": "123e4567-e89b-12d3-a456-426614174000",
            "language": "en-US",
            "format": "aac"
        }
    )
    resp = app.lambda_handler(event, None)

    assert resp["statusCode"] == 201
    body = json.loads(resp["body"])
    assert "story_id" in body
    assert "hls_url" in body
    assert "request_id" in body
    assert "cdn.lunebi.com" in body["hls_url"]
    print("✅ POST /stories/prepare - SUCCESS")


@patch('boto3.client')
def test_stories_status(mock_boto3):
    """Test GET /stories/{id}/status"""
    mock_boto3.return_value = MagicMock()
    import app

    event = make_event(
        "GET /stories/{id}/status",
        method="GET",
        path_params={"id": "123e4567-e89b-12d3-a456-426614174000"}
    )
    resp = app.lambda_handler(event, None)

    assert resp["statusCode"] == 200
    body = json.loads(resp["body"])
    assert "progress_pct" in body
    assert "playing" in body
    assert "ready_for_download" in body
    assert "request_id" in body
    print("✅ GET /stories/{id}/status - SUCCESS")


@patch('boto3.client')
def test_stories_append(mock_boto3):
    """Test POST /stories/{id}"""
    mock_boto3.return_value = MagicMock()
    import app

    event = make_event(
        "POST /stories/{id}",
        path_params={"id": "123e4567-e89b-12d3-a456-426614174000"},
        body={"text": "The quick brown fox jumps over the lazy dog."}
    )
    resp = app.lambda_handler(event, None)

    assert resp["statusCode"] == 202
    body = json.loads(resp["body"])
    assert body["ok"] is True
    assert "request_id" in body
    print("✅ POST /stories/{id} - SUCCESS")


@patch('boto3.client')
def test_voices_delete(mock_boto3):
    """Test POST /voices/delete"""
    mock_boto3.return_value = MagicMock()
    import app

    event = make_event(
        "POST /voices/delete",
        body={"voice_id": "123e4567-e89b-12d3-a456-426614174000"}
    )
    resp = app.lambda_handler(event, None)

    assert resp["statusCode"] == 202
    body = json.loads(resp["body"])
    assert body["ok"] is True
    assert "request_id" in body
    print("✅ POST /voices/delete - SUCCESS")


@patch('boto3.client')
def test_voices_enroll(mock_boto3):
    """Test POST /voices/enroll"""
    mock_boto3.return_value = MagicMock()
    import app

    event = make_event(
        "POST /voices/enroll",
        headers={
            "authorization": "Bearer mock-token-123",
            "content-type": "multipart/form-data",
            "content-length": "1024"
        },
        body="mock-audio-data"
    )
    resp = app.lambda_handler(event, None)

    assert resp["statusCode"] == 201
    body = json.loads(resp["body"])
    assert "voice_id" in body
    assert "request_id" in body
    print("✅ POST /voices/enroll - SUCCESS")


# ---------------------------
# Negative Path Tests
# ---------------------------
@patch('boto3.client')
def test_missing_auth_header(mock_boto3):
    """Test request without authorization header"""
    mock_boto3.return_value = MagicMock()
    import app

    event = make_event("POST /stories/prepare", headers={})
    # Remove auth header
    del event["headers"]["authorization"]

    resp = app.lambda_handler(event, None)

    assert resp["statusCode"] == 401
    body = json.loads(resp["body"])
    assert body["error"] == "missing_auth_header"
    print("✅ Missing auth header - SUCCESS")


@patch('boto3.client')
def test_invalid_json(mock_boto3):
    """Test request with invalid JSON"""
    mock_boto3.return_value = MagicMock()
    import app

    event = make_event("POST /stories/prepare")
    event["body"] = "invalid-json{"

    resp = app.lambda_handler(event, None)

    assert resp["statusCode"] == 400
    body = json.loads(resp["body"])
    assert body["error"] == "invalid_json"
    print("✅ Invalid JSON - SUCCESS")


@patch('boto3.client')
def test_oversized_text(mock_boto3):
    """Test text exceeding 5000 character limit"""
    mock_boto3.return_value = MagicMock()
    import app

    long_text = "x" * 6000
    event = make_event(
        "POST /stories/{id}",
        path_params={"id": "123e4567-e89b-12d3-a456-426614174000"},
        body={"text": long_text}
    )
    resp = app.lambda_handler(event, None)

    assert resp["statusCode"] == 413
    body = json.loads(resp["body"])
    assert body["error"] == "payload_too_large"
    print("✅ Oversized text - SUCCESS")


@patch('boto3.client')
def test_missing_required_field(mock_boto3):
    """Test request missing required field"""
    mock_boto3.return_value = MagicMock()
    import app

    event = make_event(
        "POST /stories/prepare",
        body={"language": "en-US"}  # Missing voice_id
    )
    resp = app.lambda_handler(event, None)

    assert resp["statusCode"] == 400
    body = json.loads(resp["body"])
    assert body["error"] == "missing_fields"
    print("✅ Missing required field - SUCCESS")


@patch('boto3.client')
def test_invalid_uuid(mock_boto3):
    """Test request with invalid UUID"""
    mock_boto3.return_value = MagicMock()
    import app

    event = make_event(
        "POST /stories/prepare",
        body={"voice_id": "invalid-uuid"}
    )
    resp = app.lambda_handler(event, None)

    assert resp["statusCode"] == 400
    body = json.loads(resp["body"])
    assert body["error"] == "invalid_voice_id"
    print("✅ Invalid UUID - SUCCESS")


# ---------------------------
# Test Runner
# ---------------------------
def run_all_tests():
    """Run all tests and report results"""
    tests = [
        test_stories_prepare,
        test_stories_status,
        test_stories_append,
        test_voices_delete,
        test_voices_enroll,
        test_missing_auth_header,
        test_invalid_json,
        test_oversized_text,
        test_missing_required_field,
        test_invalid_uuid,
    ]

    print("🚀 Starting M2 API Tests...\n")

    passed = 0
    failed = 0

    for test in tests:
        try:
            test()
            passed += 1
        except Exception as e:
            failed += 1
            print(f"❌ {test.__name__} - FAILED: {str(e)}")

    print(f"\n📊 Test Results: {passed} passed, {failed} failed")

    if failed == 0:
        print("🎉 ALL TESTS PASSED! M2 Implementation is working correctly!")
    else:
        print("💥 Some tests failed. Check the implementation.")


if __name__ == "__main__":
    run_all_tests()
