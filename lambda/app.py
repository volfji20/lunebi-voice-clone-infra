"""
Lunebi Voice Cloning API - Milestone 2 with Backend Wiring
Production Ready with Performance Optimizations
Version: 2.1.0 - No Authentication (Cognito handles at API Gateway)
"""

import json
import uuid
import os
import time
import boto3
import base64
import re
import hashlib
import threading
from datetime import datetime
from functools import wraps


# =============================================================================
# ENVIRONMENT CONFIGURATION
# =============================================================================
class Config:
    """Centralized configuration management"""
    # Feature Flags
    ENABLE_BACKEND_WIRING = (
        os.getenv('ENABLE_BACKEND_WIRING', 'true').lower() == 'true'
    )
    # Limits
    MAX_AUDIO_SIZE = 20 * 1024 * 1024  # 20MB
    MAX_TEXT_LENGTH = 5000  # characters
    MAX_AUDIO_DURATION = 120  # seconds
    MIN_AUDIO_DURATION = 10   # seconds

    # Backend Services
    VOICES_TABLE = os.getenv(
        'VOICES_TABLE_NAME',
        'lunebi-prod-us-east-1-voices'
    )
    STORIES_TABLE = os.getenv(
        'STORIES_TABLE_NAME',
        'lunebi-prod-us-east-1-stories'
    )
    SQS_QUEUE_URL = os.getenv(
        'SQS_QUEUE_URL',
        'https://sqs.us-east-1.amazonaws.com/579897422848/'
        'lunebi-prod-us-east-1-story-tasks'
    )

    S3_BUCKET = os.getenv(
        'S3_BUCKET_NAME',
        'voiceclone-stories-prod-us-east-1'
    )
    # Timeouts
    AWS_CONNECT_TIMEOUT = 5
    AWS_READ_TIMEOUT = 10
    OPERATION_TIMEOUT = 8  # seconds per AWS operation


# =============================================================================
# AWS CLIENTS WITH CONFIGURATION
# =============================================================================
def get_aws_client(service_name, region=None):
    """Get configured AWS client with proper timeouts"""
    config = boto3.session.Config(
        connect_timeout=Config.AWS_CONNECT_TIMEOUT,
        read_timeout=Config.AWS_READ_TIMEOUT,
        retries={'max_attempts': 3, 'mode': 'standard'}
    )

    if service_name == 'dynamodb' and region:
        resource = boto3.resource(
            'dynamodb',
            region_name=region,
            config=config
        )
        return resource
    elif region:
        return boto3.client(service_name, region_name=region, config=config)
    else:
        return boto3.client(service_name, config=config)


# Initialize clients
AWS_REGION = os.getenv('AWS_REGION', 'us-east-1')
cloudwatch = get_aws_client('cloudwatch', AWS_REGION)
sqs = get_aws_client('sqs', AWS_REGION)
dynamodb = get_aws_client('dynamodb', AWS_REGION)
s3 = get_aws_client('s3', AWS_REGION)

# DynamoDB Tables
voices_table = dynamodb.Table(Config.VOICES_TABLE)
stories_table = dynamodb.Table(Config.STORIES_TABLE)


# =============================================================================
# PERFORMANCE OPTIMIZATIONS
# =============================================================================
def non_blocking_metrics(route, status_code, lat_ms):
    """Emit metrics without blocking the main thread"""
    def emit():
        try:
            cloudwatch.put_metric_data(
                Namespace='Lunebi/API',
                MetricData=[
                    {
                        'MetricName': 'Requests',
                        'Dimensions': [
                            {'Name': 'Route', 'Value': route},
                            {'Name': 'Status', 'Value': str(status_code)}
                        ],
                        'Value': 1,
                        'Unit': 'Count'
                    },
                    {
                        'MetricName': 'Latency',
                        'Dimensions': [{'Name': 'Route', 'Value': route}],
                        'Value': lat_ms,
                        'Unit': 'Milliseconds',
                        'StorageResolution': 1
                    }
                ]
            )
        except Exception:
            # Fail silently for metrics
            pass

    threading.Thread(target=emit, daemon=True).start()


class TimeoutError(Exception):
    """Custom timeout exception"""
    pass


def timeout(seconds):
    """Decorator for operation timeout"""
    def decorator(func):
        @wraps(func)
        def wrapper(*args, **kwargs):
            result = [None]
            exception = [None]

            def target():
                try:
                    result[0] = func(*args, **kwargs)
                except Exception as e:
                    exception[0] = e

            thread = threading.Thread(target=target, daemon=True)
            thread.start()
            thread.join(timeout=seconds)

            if thread.is_alive():
                msg = f"Operation timed out after {seconds} seconds"
                raise TimeoutError(msg)
            elif exception[0]:
                raise exception[0]
            else:
                return result[0]
        return wrapper
    return decorator


# =============================================================================
# STRUCTURED LOGGING
# =============================================================================
class StructuredLogger:
    """Production-grade structured logging"""
    def __init__(self):
        self.request_start = {}

    def _log(self, level, msg, **kwargs):
        """Base logging method"""
        log_entry = {
            'level': level,
            'msg': msg,
            'timestamp': datetime.utcnow().isoformat() + 'Z',
            'region': AWS_REGION,
            'backend_wiring': Config.ENABLE_BACKEND_WIRING,
            **kwargs
        }
        print(json.dumps(log_entry))

    def request_started(self, request_id, route, user_id=None):
        """Log request start"""
        self.request_start[request_id] = time.time()
        self._log('INFO', 'Request started',
                  request_id=request_id,
                  route=route,
                  user_id=user_id)

    def request_completed(self, request_id, route, status_code, user_id=None):
        """Log request completion"""
        start_time = self.request_start.pop(request_id, time.time())
        lat_ms = int((time.time() - start_time) * 1000)

        self._log('INFO', 'Request completed',
                  request_id=request_id,
                  route=route,
                  status_code=status_code,
                  lat_ms=lat_ms,
                  user_id=user_id)

        # Emit metrics non-blocking
        non_blocking_metrics(route, status_code, lat_ms)

    def error(self, request_id, route, error_msg,
              error_code=None, user_id=None):
        """Log error"""
        self._log('ERROR', error_msg,
                  request_id=request_id,
                  route=route,
                  error_code=error_code,
                  user_id=user_id)

    def audit(self, action, resource_id, user_id, details=None):
        """Audit logging for compliance"""
        audit_data = {
            'action': action,
            'resource_id': resource_id,
            'user_id': user_id,
            'timestamp': int(time.time()),
            'region': AWS_REGION
        }
        if details:
            audit_data.update(details)

        self._log('AUDIT', 'Audit trail', audit_data=audit_data)


logger = StructuredLogger()


# =============================================================================
# EXCEPTION HANDLING
# =============================================================================
class APIException(Exception):
    """Standardized API exception"""
    def __init__(self, status_code, error_code, message):
        self.status_code = status_code
        self.error_code = error_code
        self.message = message
        super().__init__(self.message)


# =============================================================================
# USER ID EXTRACTION FROM COGNITO
# =============================================================================
def get_user_id(event):
    """Extract user ID from Cognito via API Gateway"""
    try:
        auth_context = event['requestContext'].get('authorizer', {})

        # Try different possible locations for user ID
        if auth_context.get('claims'):
            # Cognito JWT claims
            return (
                auth_context['claims'].get('sub')
                or auth_context['claims'].get('username')
            )
        elif auth_context.get('principalId'):
            # API Gateway custom authorizer
            return auth_context['principalId']
        elif auth_context.get('jwt'):
            # JWT authorizer
            claims = auth_context['jwt'].get('claims', {})
            return claims.get('sub') or claims.get('username')

        # If no auth context, return a default (for testing)
        return 'unknown-user'

    except Exception:
        return 'unknown-user'


# =============================================================================
# VALIDATION FUNCTIONS
# =============================================================================
def validate_uuid(uuid_str):
    """Validate UUID format"""
    try:
        uuid.UUID(uuid_str)
        return True
    except ValueError:
        return False


def validate_text_length(text):
    """Validate text length"""
    if len(text) > Config.MAX_TEXT_LENGTH:
        raise APIException(
            413,
            "payload_too_large",
            f"Text exceeds {Config.MAX_TEXT_LENGTH} character limit"
        )


def validate_json_body(body, required_fields):
    """Validate JSON body and required fields"""
    if not isinstance(body, dict):
        raise APIException(
            400,
            "invalid_json",
            "Request body must be JSON object"
        )
    missing = [field for field in required_fields if field not in body]
    if missing:
        raise APIException(
            400,
            "missing_fields",
            f"Missing required fields: {', '.join(missing)}"
        )


# =============================================================================
# BACKEND OPERATIONS (ENABLED)
# =============================================================================
@timeout(Config.OPERATION_TIMEOUT)
def create_voice_enrollment(user_id, user_agent,
                            ip_address, audio_metadata=None):
    """Create voice enrollment record"""
    voice_id = str(uuid.uuid4())

    voices_table.put_item(
        Item={
            'voice_id': voice_id,
            'user_id': user_id,
            'status': 'pending',
            'consent_metadata': {
                'consent_given': True,
                'consent_timestamp': int(time.time()),
                'user_agent': user_agent,
                'ip_address': ip_address,
                'consent_version': '1.0'
            },
            'audio_metadata': audio_metadata or {},
            'created_at': int(time.time()),
            'updated_at': int(time.time()),
            'region': AWS_REGION
        },
        ConditionExpression='attribute_not_exists(voice_id)'
    )

    logger.audit('voice_enrolled', voice_id, user_id, {
        'user_agent': user_agent,
        'ip_address': ip_address
    })

    return voice_id


@timeout(Config.OPERATION_TIMEOUT)
def delete_voice(voice_id, user_id):
    """Hard delete voice (compliance requirement)"""
    # First verify ownership
    response = voices_table.get_item(
        Key={'voice_id': voice_id},
        ProjectionExpression='user_id, #s',
        ExpressionAttributeNames={'#s': 'status'}
    )

    if 'Item' not in response:
        raise APIException(404, "voice_not_found", "Voice not found")

    item = response['Item']
    if item.get('user_id') != user_id:
        raise APIException(
            403,
            "forbidden",
            "Cannot delete voice that doesn't belong to you"
        )
    # Hard delete
    voices_table.delete_item(Key={'voice_id': voice_id})

    logger.audit('voice_deleted', voice_id, user_id)

    return True


@timeout(Config.OPERATION_TIMEOUT)
def prepare_story(voice_id, language, format_type, user_id):
    """Prepare new story with backend wiring - M3 COMPLIANT"""
    story_id = str(uuid.uuid4())

    # 1. Create story record
    stories_table.put_item(
        Item={
            'story_id': story_id,
            'voice_id': voice_id,
            'user_id': user_id,
            'language': language,
            'format': format_type,
            'status': 'queued',  # Changed from 'preparing'
            'last_seq_written': 0,
            'progress_pct': 0,
            'created_at': int(time.time()),
            'updated_at': int(time.time()),
            'region': AWS_REGION
        }
    )

    # 2. Create playlist skeleton
    playlist_content = (
        "#EXTM3U\n"
        "#EXT-X-VERSION:6\n"
        "#EXT-X-TARGETDURATION:1\n"
        "#EXT-X-MEDIA-SEQUENCE:0\n"
        "#EXT-X-PLAYLIST-TYPE:EVENT\n"
    )

    s3.put_object(
        Bucket=Config.S3_BUCKET,
        Key=f"stories/{story_id}/playlist.m3u8",
        Body=playlist_content.encode('utf-8'),
        ContentType='application/vnd.apple.mpegurl',
        CacheControl='public, max-age=3, stale-while-revalidate=30',
        Metadata={
            'story_id': story_id,
            'voice_id': voice_id,
            'user_id': user_id
        }
    )

    # 3. Enqueue first sentence
    welcome_text = "Welcome to your personalized story experience."
    params = {'speed': 1.0, 'format': format_type}
    idempotency_key = hashlib.sha256(
        f"{story_id}|0|{welcome_text}|{voice_id}|"
        f"{json.dumps(params, sort_keys=True)}".encode()
    ).hexdigest()

    sqs.send_message(
        QueueUrl=Config.SQS_QUEUE_URL,
        MessageBody=json.dumps({
            'story_id': story_id,
            'seq': 0,
            'text': welcome_text,
            'voice_id': voice_id,
            'lang': language,
            'params': params,
            'idempotency_key': idempotency_key
        }, separators=(',', ':')),
        MessageAttributes={
            'Operation': {'StringValue': 'synthesize', 'DataType': 'String'},
            'Priority': {'StringValue': 'high', 'DataType': 'String'}
        }
    )

    # 4. Generate HLS URL
    hls_url = f"https://cdn.lunebi.com/stories/{story_id}/playlist.m3u8"

    logger.audit('story_prepared', story_id, user_id, {
        'voice_id': voice_id,
        'language': language,
        'format': format_type,
        'status': 'queued'
    })

    return story_id, hls_url


@timeout(Config.OPERATION_TIMEOUT)
def append_to_story(story_id, text, user_id, voice_id=None):
    """Append text to existing story - M3 COMPLIANT"""
    # Get story details
    response = stories_table.get_item(
        Key={'story_id': story_id},
        ProjectionExpression=(
            'voice_id, #lang, #fmt, last_seq_written, '
            'user_id, progress_pct, #stat'
        ),    ExpressionAttributeNames={
            '#lang': 'language',
            '#fmt': 'format',
            '#stat': 'status'
        }
    )

    if 'Item' not in response:
        raise APIException(404, "story_not_found", "Story not found")

    story = response['Item']

    # Verify ownership
    if story.get('user_id') != user_id:
        raise APIException(
            403,
            "forbidden",
            "Cannot append to story that doesn't belong to you"
        )
    # Calculate next sequence
    next_seq = int(story.get('last_seq_written', 0)) + 1

    # Prepare SQS message
    target_voice_id = voice_id or story['voice_id']
    params = {'speed': 1.0, 'format': story.get('format', 'aac')}
    idempotency_key = hashlib.sha256(
        f"{story_id}|{next_seq}|{text}|{target_voice_id}|"
        f"{json.dumps(params, sort_keys=True)}".encode()
    ).hexdigest()

    # Send to SQS
    sqs.send_message(
        QueueUrl=Config.SQS_QUEUE_URL,
        MessageBody=json.dumps({
            'story_id': story_id,
            'seq': next_seq,
            'text': text,
            'voice_id': target_voice_id,
            'lang': story.get('language', 'en-US'),
            'params': params,
            'idempotency_key': idempotency_key
        }, separators=(',', ':')),
        MessageAttributes={
            'Operation': {'StringValue': 'synthesize', 'DataType': 'String'},
            'Priority': {'StringValue': 'normal', 'DataType': 'String'}
        }
    )

    # Update story status to show it's queued for processing
    stories_table.update_item(
        Key={'story_id': story_id},
        UpdateExpression='SET #stat = :status, updated_at = :ts',
        ExpressionAttributeNames={'#stat': 'status'},
        ExpressionAttributeValues={
            ':status': 'queued',
            ':ts': int(time.time())
        }
    )

    logger.audit('story_appended', story_id, user_id, {
        'seq': next_seq,
        'text_length': len(text),
        'status': 'queued',  # Not 'processed'
        'message': 'Sent to SQS for CPU Mock processing'
    })

    return True


@timeout(Config.OPERATION_TIMEOUT)
def get_story_status(story_id, user_id):
    """Get story status - M3 COMPLIANT"""
    response = stories_table.get_item(
        Key={'story_id': story_id},
        ProjectionExpression='#stat, progress_pct, last_seq_written, user_id',
        ExpressionAttributeNames={'#stat': 'status'}
    )

    if 'Item' not in response:
        raise APIException(404, "story_not_found", "Story not found")

    story = response['Item']

    # Verify ownership
    if story.get('user_id') != user_id:
        raise APIException(
            403,
            "forbidden",
            "Cannot access story that doesn't belong to you"
        )
    status = story.get('status', 'unknown')

    # ✅ M3 Logic: CPU Mock should update these
    # For now, return current values (CPU Mock will update them)
    return {
        'progress_pct': int(story.get('progress_pct', 0)),
        'playing': status in ['streaming', 'complete'],
        'ready_for_download': status == 'complete',
        'status': status  # Added for debugging
    }


# =============================================================================
# MULTIPART FORM PARSER
# =============================================================================
def parse_multipart_form_data(event):
    """Parse multipart form data for voice enrollment"""
    try:
        # Get body
        if event.get('isBase64Encoded', False):
            body = base64.b64decode(event['body'])
        else:
            body = event.get('body', '').encode('utf-8')

        if not body:
            raise APIException(400, "empty_body", "Request body is empty")

        # Get boundary
        content_type = event['headers'].get('content-type', '')
        boundary_match = re.search(r'boundary=([^;]+)', content_type)

        if not boundary_match:
            raise APIException(400, "invalid_content_type", "Missing boundary")

        boundary = boundary_match.group(1).encode('utf-8')
        parts = body.split(b'--' + boundary)

        form_data = {}

        for part in parts:
            if not part.strip() or part == b'--\r\n':
                continue

            # Find headers
            header_end = part.find(b'\r\n\r\n')
            if header_end == -1:
                continue

            headers = part[:header_end].decode('utf-8', errors='ignore')
            content = part[header_end + 4:].rstrip(b'\r\n')

            # Parse field name
            name_match = re.search(r'name="([^"]+)"', headers)
            if not name_match:
                continue

            field_name = name_match.group(1)

            if field_name == 'audio':
                # Validate audio
                filename_match = re.search(r'filename="([^"]+)"', headers)
                content_type_match = re.search(
                    r'Content-Type:\s*([^\r\n]+)',
                    headers
                )
                if filename_match:
                    filename = filename_match.group(1).lower()
                    valid_ext = (filename.endswith('.wav') or
                                 filename.endswith('.mp3'))
                    if not valid_ext:
                        raise APIException(
                            400,
                            "invalid_audio_format",
                            "Only WAV and MP3 files supported"
                        )

                form_data['audio'] = {
                    'filename': (
                        filename_match.group(1)
                        if filename_match else 'audio'
                    ),
                    'content_type': (
                        content_type_match.group(1)
                        if content_type_match else 'audio/wav'
                    ),
                    'size': len(content),
                    'data': content
                }

            elif field_name == 'consent':
                consent_value = content.decode('utf-8').strip().lower()
                if consent_value != 'true':
                    raise APIException(
                        400,
                        "consent_required",
                        "Explicit consent (consent=true) required"
                    )
                form_data['consent'] = True

        # Validate required fields
        if 'audio' not in form_data:
            raise APIException(400, "missing_audio", "Audio file is required")

        if 'consent' not in form_data:
            raise APIException(400, "missing_consent", "Consent is required")

        # Validate audio size
        audio_info = form_data['audio']
        if audio_info['size'] > Config.MAX_AUDIO_SIZE:
            mb_limit = Config.MAX_AUDIO_SIZE // 1024 // 1024
            msg = f"Audio file exceeds {mb_limit}MB limit"
            raise APIException(413, "payload_too_large", msg)

        return form_data

    except APIException:
        raise
    except Exception as e:
        msg = f"Failed to parse form data: {str(e)}"
        raise APIException(400, "parse_error", msg)


# =============================================================================
# ROUTE HANDLERS
# =============================================================================
def handle_voice_enroll(event, request_id, user_id):
    """Handle voice enrollment"""
    # Parse multipart form data
    form_data = parse_multipart_form_data(event)

    # Extract user info
    user_agent = event['headers'].get('user-agent', '')
    source_ip = event['requestContext']['http']['sourceIp']

    # Prepare audio metadata
    audio_info = form_data['audio']
    audio_metadata = {
        'filename': audio_info['filename'],
        'content_type': audio_info['content_type'],
        'size': audio_info['size'],
        'uploaded_at': int(time.time())
    }

    # Create voice enrollment
    voice_id = create_voice_enrollment(
        user_id=user_id,
        user_agent=user_agent,
        ip_address=source_ip,
        audio_metadata=audio_metadata
    )

    return {
        'statusCode': 201,
        'headers': {
            'Content-Type': 'application/json',
            'Access-Control-Allow-Origin': '*'
        },
        'body': json.dumps({
            'voice_id': voice_id,
            'request_id': request_id
        })
    }


def handle_voice_delete(event, request_id, user_id):
    """Handle voice deletion"""
    body = json.loads(event.get('body', '{}'))
    validate_json_body(body, ['voice_id'])

    voice_id = body['voice_id']
    if not validate_uuid(voice_id):
        raise APIException(
            400,
            "invalid_voice_id",
            "voice_id must be valid UUID"
        )
    delete_voice(voice_id, user_id)

    return {
        'statusCode': 202,
        'headers': {
            'Content-Type': 'application/json',
            'Access-Control-Allow-Origin': '*'
        },
        'body': json.dumps({
            'ok': True,
            'request_id': request_id
        })
    }


def handle_story_prepare(event, request_id, user_id):
    """Handle story preparation"""
    body = json.loads(event.get('body', '{}'))
    validate_json_body(body, ['voice_id'])

    voice_id = body['voice_id']
    if not validate_uuid(voice_id):
        raise APIException(
            400,
            "invalid_voice_id",
            "voice_id must be valid UUID"
        )
    language = body.get('language', 'en-US')
    format_type = body.get('format', 'aac')

    if format_type not in ['aac', 'opus', 'mp3']:
        raise APIException(
            400,
            "invalid_format",
            "Format must be aac, opus, or mp3"
        )
    story_id, hls_url = prepare_story(voice_id, language, format_type, user_id)

    return {
        'statusCode': 201,
        'headers': {
            'Content-Type': 'application/json',
            'Access-Control-Allow-Origin': '*'
        },
        'body': json.dumps({
            'story_id': story_id,
            'hls_url': hls_url,
            'request_id': request_id
        })
    }


def handle_story_append(event, request_id, user_id):
    """Handle story append"""
    story_id = event['pathParameters']['id']
    if not validate_uuid(story_id):
        raise APIException(
            400,
            "invalid_story_id",
            "story_id must be valid UUID"
        )
    body = json.loads(event.get('body', '{}'))
    validate_json_body(body, ['text'])

    text = body['text']
    validate_text_length(text)

    append_to_story(
        story_id=story_id,
        text=text,
        user_id=user_id,
        voice_id=body.get('voice_id')
    )

    return {
        'statusCode': 202,
        'headers': {
            'Content-Type': 'application/json',
            'Access-Control-Allow-Origin': '*'
        },
        'body': json.dumps({
            'ok': True,
            'request_id': request_id
        })
    }


def handle_story_status(event, request_id, user_id):
    """Handle story status"""
    story_id = event['pathParameters']['id']
    if not validate_uuid(story_id):
        raise APIException(
            400,
            "invalid_story_id",
            "story_id must be valid UUID"
        )
    status = get_story_status(story_id, user_id)

    return {
        'statusCode': 200,
        'headers': {
            'Content-Type': 'application/json',
            'Access-Control-Allow-Origin': '*'
        },
        'body': json.dumps({
            **status,
            'request_id': request_id
        })
    }


# =============================================================================
# MAIN LAMBDA HANDLER
# =============================================================================
def lambda_handler(event, context):
    """Production Lambda Handler with Backend Wiring Enabled"""
    try:
        # Handle test events
        if 'requestContext' not in event:
            return {
                'statusCode': 200,
                'body': json.dumps({
                    'message': 'Lambda is operational',
                    'backend_wiring': Config.ENABLE_BACKEND_WIRING,
                    'region': AWS_REGION,
                    'timestamp': datetime.utcnow().isoformat() + 'Z'
                })
            }

        # Extract request info
        request_id = event['requestContext']['requestId']
        route_key = event['requestContext']['routeKey']
        method = event['requestContext']['http']['method']

        # Handle CORS preflight
        if method == 'OPTIONS':
            methods = 'GET, POST, PUT, DELETE, OPTIONS'
            return {
                'statusCode': 200,
                'headers': {
                    'Access-Control-Allow-Origin': '*',
                    'Access-Control-Allow-Methods': methods,
                    'Access-Control-Allow-Headers': (
                        'Content-Type, Authorization'
                    )
                }
            }

        # Get user ID from Cognito (via API Gateway)
        user_id = get_user_id(event)

        # Log request start
        logger.request_started(request_id, route_key, user_id)

        # Route handling
        if route_key == 'POST /voices/enroll':
            response = handle_voice_enroll(event, request_id, user_id)
        elif route_key == 'POST /voices/delete':
            response = handle_voice_delete(event, request_id, user_id)
        elif route_key == 'POST /stories/prepare':
            response = handle_story_prepare(event, request_id, user_id)
        elif route_key == 'POST /stories/{id}':
            response = handle_story_append(event, request_id, user_id)
        elif route_key == 'GET /stories/{id}/status':
            response = handle_story_status(event, request_id, user_id)
        else:
            msg = f"Route {route_key} not found"
            raise APIException(404, "route_not_found", msg)

        # Log completion
        logger.request_completed(
            request_id,
            route_key,
            response['statusCode'],
            user_id
        )

        return response

    except APIException as e:
        # Log API-level errors
        if 'request_id' in locals() and 'route_key' in locals():
            logger.error(request_id, route_key, e.message, e.error_code,
                         user_id if 'user_id' in locals() else None)

        return {
            'statusCode': e.status_code,
            'headers': {
                'Content-Type': 'application/json',
                'Access-Control-Allow-Origin': '*'
            },
            'body': json.dumps({
                'error': e.error_code,
                'message': e.message,
                'request_id': request_id
                if 'request_id' in locals() else 'unknown'
            })
        }
    except TimeoutError:
        # Handle timeout errors
        error_msg = "Operation timeout - please try again"

        # Store locals() calls to variables
        has_request_id = 'request_id' in locals()
        has_route_key = 'route_key' in locals()
        has_user_id = 'user_id' in locals()

        if has_request_id and has_route_key:
            logger.error(request_id, route_key, error_msg, 'timeout',
                         user_id if has_user_id else None)
        return {
            'statusCode': 504,
            'headers': {
                'Content-Type': 'application/json',
                'Access-Control-Allow-Origin': '*'
            },
            'body': json.dumps({
                'error': 'timeout',
                'message': error_msg,
                'request_id': request_id if has_request_id else 'unknown'
            })
        }

    except Exception as e:
        # Handle unexpected errors
        error_msg = "Internal server error"

        # Store locals() calls to variables for better readability
        has_request_id = 'request_id' in locals()
        has_route_key = 'route_key' in locals()
        has_user_id = 'user_id' in locals()

        if has_request_id and has_route_key:
            logger.error(request_id, route_key, f"{error_msg}: {str(e)}",
                         'internal_error', user_id if has_user_id else None)

        return {
            'statusCode': 500,
            'headers': {
                'Content-Type': 'application/json',
                'Access-Control-Allow-Origin': '*'
            },
            'body': json.dumps({
                'error': 'internal_error',
                'message': error_msg,
                'request_id': request_id if has_request_id else 'unknown'
            })
        }
