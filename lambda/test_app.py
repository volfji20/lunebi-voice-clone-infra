"""
Test file for Lunebi Voice Cloning API
"""

import json
import time
import pytest
import base64
from unittest.mock import patch, MagicMock

# Mock everything first
with patch('boto3.client'), patch('boto3.resource'), \
     patch.dict('os.environ', {
         'VOICES_TABLE_NAME': 'lunebi-prod-us-east-1-voices',
         'STORIES_TABLE_NAME': 'lunebi-prod-us-east-1-stories',
         'S3_BUCKET_NAME': 'voiceclone-stories-prod-us-east-1',
         'SQS_QUEUE_URL':
             'https://sqs.us-east-1.amazonaws.com/579897422848/'
             'lunebi-prod-us-east-1-story-tasks',
         'AWS_REGION': 'us-east-1',
         'ENABLE_BACKEND_WIRING': 'true'
     }):

    # Set up mock tables
    mock_voices_table = MagicMock()
    mock_stories_table = MagicMock()

    # Mock the dynamodb.Table calls
    with patch('boto3.resource') as mock_resource:
        mock_dynamodb = MagicMock()
        mock_dynamodb.Table.side_effect = lambda x: {
            'lunebi-prod-us-east-1-voices': mock_voices_table,
            'lunebi-prod-us-east-1-stories': mock_stories_table
        }.get(x, MagicMock())
        mock_resource.return_value = mock_dynamodb

        # Import app now
        import app

        # Assign the mock tables to app module
        app.voices_table = mock_voices_table
        app.stories_table = mock_stories_table


class TestLambdaHandler:
    """Main Lambda handler tests"""

    def setup_method(self):
        """Setup before each test"""
        self.original_wiring = app.Config.ENABLE_BACKEND_WIRING
        app.Config.ENABLE_BACKEND_WIRING = True

    def teardown_method(self):
        """Cleanup after each test"""
        app.Config.ENABLE_BACKEND_WIRING = self.original_wiring

    def _make_event(
        self, route_key, method="POST", body=None,
        headers=None, path_params=None
    ):
        """Test helper to create API Gateway events"""
        headers = headers or {}
        # Add auth header for Cognito
        headers.setdefault("authorization", "Bearer test-token")

        if "content-type" not in headers and body is not None:
            headers["content-type"] = "application/json"

        event = {
            "version": "2.0",
            "routeKey": route_key,
            "rawPath": f"/{route_key.split()[-1]}",
            "requestContext": {
                "requestId": f"test-{int(time.time())}",
                "authorizer": {
                    "claims": {
                        "sub": "test-user-123",
                        "username": "testuser"
                    }
                },
                "http": {
                    "method": method,
                    "sourceIp": "127.0.0.1"
                },
                "routeKey": route_key
            },
            "headers": headers
        }

        if path_params:
            event["pathParameters"] = path_params

        if body is not None:
            event["body"] = (
                json.dumps(body) if isinstance(body, dict) else body
            )

        return event

    def test_cors_preflight(self):
        """Test CORS preflight requests"""
        event = self._make_event("OPTIONS /test", method="OPTIONS")
        event['requestContext']['http']['method'] = 'OPTIONS'

        response = app.lambda_handler(event, None)

        assert response["statusCode"] == 200
        assert "Access-Control-Allow-Origin" in response["headers"]

    def test_route_not_found(self):
        """Test unknown routes return 404"""
        event = self._make_event("GET /unknown")

        response = app.lambda_handler(event, None)

        assert response["statusCode"] == 404
        body = json.loads(response["body"])
        assert body["error"] == "route_not_found"

    def test_test_event_without_request_context(self):
        """Test Lambda test events"""
        event = {"test": "event"}
        response = app.lambda_handler(event, None)
        assert response["statusCode"] == 200
        body = json.loads(response["body"])
        assert "message" in body
        assert body["message"] == "Lambda is operational"


class TestVoiceEnrollment:
    """Voice enrollment endpoint tests"""

    def setup_method(self):
        self.original_wiring = app.Config.ENABLE_BACKEND_WIRING
        app.Config.ENABLE_BACKEND_WIRING = True

    def teardown_method(self):
        app.Config.ENABLE_BACKEND_WIRING = self.original_wiring

    def _make_multipart_event(self):
        """Create multipart form data event for voice enrollment"""
        multipart_body = (
            b'--boundary123\r\n'
            b'Content-Disposition: form-data; name="audio"; '
            b'filename="test.wav"\r\n'
            b'Content-Type: audio/wav\r\n'
            b'\r\n'
            b'mock-audio-data\r\n'
            b'--boundary123\r\n'
            b'Content-Disposition: form-data; name="consent"\r\n'
            b'\r\n'
            b'true\r\n'
            b'--boundary123--\r\n'
        )

        event = {
            "version": "2.0",
            "routeKey": "POST /voices/enroll",
            "rawPath": "/voices/enroll",
            "requestContext": {
                "requestId": f"test-{int(time.time())}",
                "authorizer": {
                    "claims": {
                        "sub": "test-user-123",
                        "username": "testuser"
                    }
                },
                "http": {
                    "method": "POST",
                    "sourceIp": "127.0.0.1"
                },
                "routeKey": "POST /voices/enroll"
            },
            "headers": {
                "authorization": "Bearer test-token",
                "content-type": "multipart/form-data; boundary=boundary123",
                "content-length": str(len(multipart_body)),
                "user-agent": "test-agent"
            },
            "isBase64Encoded": True,
            "body": base64.b64encode(multipart_body).decode('utf-8')
        }
        return event

    @patch('app.voices_table.put_item')
    def test_voice_enrollment_success(self, mock_put):
        """Test successful voice enrollment"""
        event = self._make_multipart_event()

        response = app.lambda_handler(event, None)

        assert response["statusCode"] == 201
        body = json.loads(response["body"])
        assert "voice_id" in body
        assert mock_put.called

    def test_voice_enrollment_missing_audio(self):
        """Test voice enrollment without audio file"""
        multipart_body = (
            b'--boundary123\r\n'
            b'Content-Disposition: form-data; name="consent"\r\n'
            b'\r\n'
            b'true\r\n'
            b'--boundary123--\r\n'
        )

        event = self._make_multipart_event()
        event['body'] = base64.b64encode(multipart_body).decode('utf-8')

        response = app.lambda_handler(event, None)

        assert response["statusCode"] == 400
        body = json.loads(response["body"])
        assert body["error"] == "missing_audio"

    def test_voice_enrollment_missing_consent(self):
        """Test voice enrollment without consent"""
        multipart_body = (
            b'--boundary123\r\n'
            b'Content-Disposition: form-data; name="audio"; '
            b'filename="test.wav"\r\n'
            b'Content-Type: audio/wav\r\n'
            b'\r\n'
            b'mock-audio-data\r\n'
            b'--boundary123--\r\n'
        )

        event = self._make_multipart_event()
        event['body'] = base64.b64encode(multipart_body).decode('utf-8')

        response = app.lambda_handler(event, None)

        assert response["statusCode"] == 400
        body = json.loads(response["body"])
        assert body["error"] == "missing_consent"

    def test_voice_enrollment_invalid_audio_format(self):
        """Test voice enrollment with invalid audio format"""
        multipart_body = (
            b'--boundary123\r\n'
            b'Content-Disposition: form-data; name="audio"; '
            b'filename="test.txt"\r\n'  # Invalid format
            b'Content-Type: text/plain\r\n'
            b'\r\n'
            b'mock-audio-data\r\n'
            b'--boundary123\r\n'
            b'Content-Disposition: form-data; name="consent"\r\n'
            b'\r\n'
            b'true\r\n'
            b'--boundary123--\r\n'
        )

        event = self._make_multipart_event()
        event['body'] = base64.b64encode(multipart_body).decode('utf-8')

        response = app.lambda_handler(event, None)

        assert response["statusCode"] == 400
        body = json.loads(response["body"])
        assert body["error"] == "invalid_audio_format"


class TestVoiceDeletion:
    """Voice deletion endpoint tests"""

    def setup_method(self):
        self.original_wiring = app.Config.ENABLE_BACKEND_WIRING
        app.Config.ENABLE_BACKEND_WIRING = True

    def teardown_method(self):
        app.Config.ENABLE_BACKEND_WIRING = self.original_wiring

    def _make_event(self, voice_id="123e4567-e89b-12d3-a456-426614174000"):
        return {
            "version": "2.0",
            "routeKey": "POST /voices/delete",
            "rawPath": "/voices/delete",
            "requestContext": {
                "requestId": f"test-{int(time.time())}",
                "authorizer": {
                    "claims": {
                        "sub": "test-user-123",
                        "username": "testuser"
                    }
                },
                "http": {
                    "method": "POST",
                    "sourceIp": "127.0.0.1"
                },
                "routeKey": "POST /voices/delete"
            },
            "headers": {
                "authorization": "Bearer test-token",
                "content-type": "application/json"
            },
            "body": json.dumps({"voice_id": voice_id})
        }

    @patch('app.voices_table.get_item')
    @patch('app.voices_table.delete_item')
    def test_voice_deletion_success(self, mock_delete, mock_get):
        """Test successful voice deletion"""
        mock_get.return_value = {
            'Item': {
                'voice_id': '123e4567-e89b-12d3-a456-426614174000',
                'user_id': 'test-user-123'
            }
        }

        event = self._make_event()
        response = app.lambda_handler(event, None)

        assert response["statusCode"] == 202
        body = json.loads(response["body"])
        assert body["ok"]
        assert mock_delete.called

    def test_voice_deletion_invalid_uuid(self):
        """Test voice deletion with invalid UUID"""
        event = self._make_event(voice_id="invalid-uuid")
        response = app.lambda_handler(event, None)

        assert response["statusCode"] == 400
        body = json.loads(response["body"])
        assert body["error"] == "invalid_voice_id"

    @patch('app.voices_table.get_item')
    def test_voice_deletion_not_found(self, mock_get):
        """Test voice deletion for non-existent voice"""
        mock_get.return_value = {}

        event = self._make_event()
        response = app.lambda_handler(event, None)

        assert response["statusCode"] == 404
        body = json.loads(response["body"])
        assert body["error"] == "voice_not_found"

    @patch('app.voices_table.get_item')
    def test_voice_deletion_unauthorized(self, mock_get):
        """Test voice deletion for voice belonging to another user"""
        mock_get.return_value = {
            'Item': {
                'voice_id': '123e4567-e89b-12d3-a456-426614174000',
                'user_id': 'other-user'
            }
        }

        event = self._make_event()
        response = app.lambda_handler(event, None)

        assert response["statusCode"] == 403
        body = json.loads(response["body"])
        assert body["error"] == "forbidden"


class TestStoryOperations:
    """Story preparation, append, and status tests"""

    def setup_method(self):
        self.original_wiring = app.Config.ENABLE_BACKEND_WIRING
        app.Config.ENABLE_BACKEND_WIRING = True

    def teardown_method(self):
        app.Config.ENABLE_BACKEND_WIRING = self.original_wiring

    @patch('app.stories_table.put_item')
    @patch('app.s3.put_object')
    @patch('app.sqs.send_message')
    def test_story_preparation_success(self, mock_sqs, mock_s3, mock_put):
        """Test successful story preparation"""
        event = {
            "version": "2.0",
            "routeKey": "POST /stories/prepare",
            "rawPath": "/stories/prepare",
            "requestContext": {
                "requestId": f"test-{int(time.time())}",
                "authorizer": {
                    "claims": {
                        "sub": "test-user-123",
                        "username": "testuser"
                    }
                },
                "http": {
                    "method": "POST",
                    "sourceIp": "127.0.0.1"
                },
                "routeKey": "POST /stories/prepare"
            },
            "headers": {
                "authorization": "Bearer test-token",
                "content-type": "application/json"
            },
            "body": json.dumps({
                "voice_id": "123e4567-e89b-12d3-a456-426614174000",
                "language": "en-US",
                "format": "aac"
            })
        }

        response = app.lambda_handler(event, None)

        assert response["statusCode"] == 201
        body = json.loads(response["body"])
        assert "story_id" in body
        assert "hls_url" in body
        assert mock_put.called
        assert mock_s3.called
        assert mock_sqs.called

    def test_story_preparation_invalid_format(self):
        """Test story preparation with invalid format"""
        event = {
            "version": "2.0",
            "routeKey": "POST /stories/prepare",
            "rawPath": "/stories/prepare",
            "requestContext": {
                "requestId": f"test-{int(time.time())}",
                "authorizer": {
                    "claims": {
                        "sub": "test-user-123",
                        "username": "testuser"
                    }
                },
                "http": {
                    "method": "POST",
                    "sourceIp": "127.0.0.1"
                },
                "routeKey": "POST /stories/prepare"
            },
            "headers": {
                "authorization": "Bearer test-token",
                "content-type": "application/json"
            },
            "body": json.dumps({
                "voice_id": "123e4567-e89b-12d3-a456-426614174000",
                "format": "invalid-format"
            })
        }

        response = app.lambda_handler(event, None)

        assert response["statusCode"] == 400
        body = json.loads(response["body"])
        assert body["error"] == "invalid_format"

    @patch('app.stories_table.get_item')
    @patch('app.sqs.send_message')
    def test_story_append_success(self, mock_sqs, mock_get):
        """Test successful story append"""
        mock_get.return_value = {
            'Item': {
                'story_id': '123e4567-e89b-12d3-a456-426614174000',
                'voice_id': '123e4567-e89b-12d3-a456-426614174001',
                'language': 'en-US',
                'format': 'aac',
                'user_id': 'test-user-123',
                'last_seq_written': 2,
                'progress_pct': 50,
                'status': 'queued'
            }
        }

        event = {
            "version": "2.0",
            "routeKey": "POST /stories/{id}",
            "rawPath": "/stories/123e4567-e89b-12d3-a456-426614174000",
            "requestContext": {
                "requestId": f"test-{int(time.time())}",
                "authorizer": {
                    "claims": {
                        "sub": "test-user-123",
                        "username": "testuser"
                    }
                },
                "http": {
                    "method": "POST",
                    "sourceIp": "127.0.0.1"
                },
                "routeKey": "POST /stories/{id}"
            },
            "headers": {
                "authorization": "Bearer test-token",
                "content-type": "application/json"
            },
            "pathParameters": {"id": "123e4567-e89b-12d3-a456-426614174000"},
            "body": json.dumps({"text": "Test story text"})
        }

        response = app.lambda_handler(event, None)

        assert response["statusCode"] == 202
        body = json.loads(response["body"])
        assert body["ok"]
        assert mock_sqs.called

    def test_story_append_text_too_long(self):
        """Test story append with text exceeding limit"""
        long_text = "a" * (app.Config.MAX_TEXT_LENGTH + 1)

        event = {
            "version": "2.0",
            "routeKey": "POST /stories/{id}",
            "rawPath": "/stories/123e4567-e89b-12d3-a456-426614174000",
            "requestContext": {
                "requestId": f"test-{int(time.time())}",
                "authorizer": {
                    "claims": {
                        "sub": "test-user-123",
                        "username": "testuser"
                    }
                },
                "http": {
                    "method": "POST",
                    "sourceIp": "127.0.0.1"
                },
                "routeKey": "POST /stories/{id}"
            },
            "headers": {
                "authorization": "Bearer test-token",
                "content-type": "application/json"
            },
            "pathParameters": {"id": "123e4567-e89b-12d3-a456-426614174000"},
            "body": json.dumps({"text": long_text})
        }

        response = app.lambda_handler(event, None)

        assert response["statusCode"] == 413
        body = json.loads(response["body"])
        assert body["error"] == "payload_too_large"

    @patch('app.stories_table.get_item')
    def test_story_status_success(self, mock_get):
        """Test successful story status retrieval"""
        mock_get.return_value = {
            'Item': {
                'story_id': '123e4567-e89b-12d3-a456-426614174000',
                'user_id': 'test-user-123',
                'status': 'streaming',
                'progress_pct': 75,
                'last_seq_written': 5
            }
        }

        event = {
            "version": "2.0",
            "routeKey": "GET /stories/{id}/status",
            "rawPath": "/stories/123e4567-e89b-12d3-a456-426614174000/status",
            "requestContext": {
                "requestId": f"test-{int(time.time())}",
                "authorizer": {
                    "claims": {
                        "sub": "test-user-123",
                        "username": "testuser"
                    }
                },
                "http": {
                    "method": "GET",
                    "sourceIp": "127.0.0.1"
                },
                "routeKey": "GET /stories/{id}/status"
            },
            "headers": {
                "authorization": "Bearer test-token"
            },
            "pathParameters": {"id": "123e4567-e89b-12d3-a456-426614174000"}
        }

        response = app.lambda_handler(event, None)

        assert response["statusCode"] == 200
        body = json.loads(response["body"])
        assert "progress_pct" in body
        assert "playing" in body
        assert "ready_for_download" in body


class TestValidationFunctions:
    """Validation function unit tests"""

    def test_validate_uuid_valid(self):
        """Test valid UUID validation"""
        valid_uuid = "123e4567-e89b-12d3-a456-426614174000"
        assert app.validate_uuid(valid_uuid) is True

    def test_validate_uuid_invalid(self):
        """Test invalid UUID validation"""
        invalid_uuid = "not-a-uuid"
        assert app.validate_uuid(invalid_uuid) is False

    def test_validate_text_length_valid(self):
        """Test valid text length"""
        valid_text = "a" * app.Config.MAX_TEXT_LENGTH
        # Should not raise exception
        app.validate_text_length(valid_text)

    def test_validate_text_length_invalid(self):
        """Test invalid text length"""
        invalid_text = "a" * (app.Config.MAX_TEXT_LENGTH + 1)
        with pytest.raises(app.APIException) as exc_info:
            app.validate_text_length(invalid_text)
        assert exc_info.value.status_code == 413

    def test_validate_json_body_valid(self):
        """Test valid JSON body"""
        valid_body = {"voice_id": "test", "text": "hello"}
        required_fields = ["voice_id", "text"]
        # Should not raise exception
        app.validate_json_body(valid_body, required_fields)

    def test_validate_json_body_missing_fields(self):
        """Test JSON body with missing fields"""
        invalid_body = {"voice_id": "test"}
        required_fields = ["voice_id", "text"]
        with pytest.raises(app.APIException) as exc_info:
            app.validate_json_body(invalid_body, required_fields)
        assert exc_info.value.status_code == 400

    def test_validate_json_body_not_dict(self):
        """Test JSON body that is not a dictionary"""
        invalid_body = "not a dict"
        required_fields = ["voice_id"]
        with pytest.raises(app.APIException) as exc_info:
            app.validate_json_body(invalid_body, required_fields)
        assert exc_info.value.status_code == 400


if __name__ == "__main__":
    pytest.main([__file__, "-v", "--tb=short"])
