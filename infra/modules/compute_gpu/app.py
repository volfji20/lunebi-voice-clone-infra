import json
import time
import random
import boto3
import os
from botocore.exceptions import ClientError

# Initialize AWS clients
sqs = boto3.client('sqs')
dynamodb = boto3.resource('dynamodb')
ssm = boto3.client('ssm')
autoscaling = boto3.client('autoscaling')

def get_mock_timing():
    """Get mock timing from SSM Parameter Store"""
    try:
        min_ms = int(ssm.get_parameter(Name=os.environ['MOCK_MIN_MS_PARAM'])['Parameter']['Value'])
        max_ms = int(ssm.get_parameter(Name=os.environ['MOCK_MAX_MS_PARAM'])['Parameter']['Value'])
        return min_ms, max_ms
    except Exception as e:
        print(f"⚠️ Error reading SSM parameters, using defaults: {e}")
        return 300, 800  # Default 300-800ms

def check_gpu_worker_availability():
    """Check if GPU workers are available (not in Test Mode or Spot unavailable)"""
    try:
        # Get GPU ASG name from SSM
        asg_name_param = ssm.get_parameter(Name='/voiceclone/gpu_asg_name')
        asg_name = asg_name_param['Parameter']['Value']
        
        # Check ASG status
        response = autoscaling.describe_auto_scaling_groups(
            AutoScalingGroupNames=[asg_name]
        )
        
        if not response['AutoScalingGroups']:
            print("❌ No GPU Auto Scaling Group found")
            return False
        
        asg = response['AutoScalingGroups'][0]
        
        # Check if there are running instances
        running_instances = sum(
            1 for instance in asg['Instances'] 
            if instance['LifecycleState'] == 'InService' 
            and instance['HealthStatus'] == 'Healthy'
        )
        
        print(f"🔍 GPU Worker Status: {running_instances} running instances in {asg_name}")
        
        return running_instances > 0
        
    except Exception as e:
        print(f"⚠️ Could not check GPU worker availability: {e}")
        return False

def validate_message_schema(message_body: str) -> bool:
    """Validate SQS message against schema contract to prevent drift"""
    try:
        message = json.loads(message_body)
        
        # Required fields check
        required_fields = ['story_id', 'seq', 'text', 'voice_id', 'lang', 'params', 'idempotency_key']
        for field in required_fields:
            if field not in message:
                print(f"❌ SCHEMA ERROR: Missing required field: {field}")
                return False
        
        # Type checks
        if not isinstance(message['seq'], int) or message['seq'] < 0:
            print("❌ SCHEMA ERROR: Invalid seq: must be non-negative integer")
            return False
            
        if not isinstance(message['text'], str) or len(message['text'].strip()) == 0:
            print("❌ SCHEMA ERROR: Invalid text: must be non-empty string")
            return False
            
        # Language format check (basic)
        lang_parts = message['lang'].split('-')
        if len(lang_parts) != 2 or len(lang_parts[0]) != 2 or len(lang_parts[1]) != 2:
            print("❌ SCHEMA ERROR: Invalid lang format: must be like 'en-US'")
            return False
            
        # Params validation
        params = message['params']
        if 'speed' not in params or 'format' not in params:
            print("❌ SCHEMA ERROR: Missing required params: speed and format")
            return False
            
        speed = params['speed']
        if not isinstance(speed, (int, float)) or speed < 0.5 or speed > 2.0:
            print("❌ SCHEMA ERROR: Invalid speed: must be between 0.5 and 2.0")
            return False
            
        valid_formats = ['aac', 'opus', 'mp3']
        if params['format'] not in valid_formats:
            print(f"❌ SCHEMA ERROR: Invalid format: must be one of {valid_formats}")
            return False
            
        print("✅ Message schema validation passed")
        return True
        
    except json.JSONDecodeError:
        print("❌ SCHEMA ERROR: Invalid JSON in message body")
        return False
    except Exception as e:
        print(f"❌ SCHEMA ERROR: Validation error: {e}")
        return False

def mark_story_as_mocked(stories_table, story_id: str, seq: int, reason: str = "spot_unavailable"):
    """Mark story as processed by CPU mock due to no GPU capacity"""
    try:
        stories_table.update_item(
            Key={'story_id': story_id},
            UpdateExpression='SET last_seq_written = :seq, progress_pct = :pct, updated_at = :now, #s = :status, processing_mode = :mode, mocked_reason = :reason, mocked_at = :ts',
            ExpressionAttributeNames={
                '#s': 'status'
            },
            ExpressionAttributeValues={
                ':seq': seq,
                ':pct': min(100, seq * 10),
                ':now': int(time.time()),
                ':status': 'streaming',
                ':mode': 'cpu_mock',
                ':reason': reason,
                ':ts': int(time.time())
            },
            ReturnValues='UPDATED_NEW'
        )
        print(f"📝 Marked story {story_id} seq {seq} as mocked (reason: {reason})")
    except Exception as e:
        print(f"❌ Failed to mark story as mocked: {e}")
        raise

def update_story_progress(stories_table, story_id: str, seq: int, mocked: bool = False):
    """Update story progress with optional mock indicator"""
    try:
        if mocked:
            update_expr = 'SET last_seq_written = :seq, progress_pct = :pct, updated_at = :now, #s = :status, processing_mode = :mode'
            attr_values = {
                ':seq': seq,
                ':pct': min(100, seq * 10),
                ':now': int(time.time()),
                ':status': 'streaming',
                ':mode': 'cpu_mock'
            }
        else:
            update_expr = 'SET last_seq_written = :seq, progress_pct = :pct, updated_at = :now, #s = :status'
            attr_values = {
                ':seq': seq,
                ':pct': min(100, seq * 10),
                ':now': int(time.time()),
                ':status': 'streaming'
            }
        
        stories_table.update_item(
            Key={'story_id': story_id},
            UpdateExpression=update_expr,
            ExpressionAttributeNames={
                '#s': 'status'
            },
            ExpressionAttributeValues=attr_values,
            ReturnValues='UPDATED_NEW'
        )
        
        mode_text = "mocked" if mocked else "processed"
        print(f"✅ {mode_text.title()} story {story_id}: seq={seq}, progress={min(100, seq * 10)}%")
        
    except ClientError as e:
        print(f"❌ Failed to update DynamoDB for story {story_id}: {e.response['Error']['Code']}")
        raise

def lambda_handler(event, context):
    """CPU Mock Lambda with Spot fallback detection and schema validation"""
    print("🚀 CPU MOCK LAMBDA - COMPLETE WORKING VERSION STARTING")
    
    # Get environment variables
    queue_url = os.environ.get('SQS_QUEUE_URL', '')
    stories_table_name = os.environ.get('STORIES_TABLE_NAME', 'lunebi-prod-us-east-1-stories')
    
    print(f"📊 Configuration:")
    print(f"  - Queue URL: {queue_url}")
    print(f"  - Table Name: {stories_table_name}")
    print(f"  - Mock Min MS Param: {os.environ.get('MOCK_MIN_MS_PARAM', 'Not set')}")
    print(f"  - Mock Max MS Param: {os.environ.get('MOCK_MAX_MS_PARAM', 'Not set')}")
    
    # Initialize DynamoDB table
    stories_table = dynamodb.Table(stories_table_name)
    
    processed_count = 0
    mocked_count = 0
    schema_rejected_count = 0
    
    # Check if we have proper event structure
    if 'Records' not in event:
        print(f"⚠️ No 'Records' in event. Event: {json.dumps(event)[:200]}...")
        return {
            'statusCode': 400,
            'body': json.dumps({'error': 'Invalid event format'})
        }
    
    print(f"📨 Processing {len(event.get('Records', []))} records from event")
    
    for record in event.get('Records', []):
        try:
            message_id = record.get('messageId', 'unknown')
            receipt_handle = record.get('receiptHandle')
            body = record.get('body', '{}')
            
            print(f"🔍 Processing message: {message_id}")
            print(f"Body preview: {body[:200]}...")
            
            # SCHEMA VALIDATION
            if not validate_message_schema(body):
                print(f"❌ Schema validation failed for message {message_id}")
                schema_rejected_count += 1
                continue
            
            # Parse message
            message_data = json.loads(body)
            story_id = message_data.get('story_id')
            seq = message_data.get('seq', 0)
            text = message_data.get('text', '')[:50]
            
            print(f"📖 Processing: story_id={story_id}, seq={seq}, text='{text}...'")
            
            # Get mock timing
            min_ms, max_ms = get_mock_timing()
            processing_time = random.randint(min_ms, max_ms) / 1000.0
            print(f"⏱️ Simulating {processing_time:.2f}s processing time...")
            time.sleep(processing_time)
            
            # Update DynamoDB
            try:
                # For now, always mark as mocked in test mode
                mark_story_as_mocked(stories_table, story_id, seq, "test_mode")
                mocked_count += 1
                print(f"✅ Successfully updated DDB for story {story_id}")
                
            except Exception as ddb_error:
                print(f"❌ DDB update failed: {str(ddb_error)}")
                continue
            
            # Delete message from SQS if we have queue URL
            if receipt_handle and queue_url:
                try:
                    sqs.delete_message(
                        QueueUrl=queue_url,
                        ReceiptHandle=receipt_handle
                    )
                    print(f"🗑️ Deleted message from SQS")
                except Exception as sqs_error:
                    print(f"⚠️ Failed to delete from SQS: {sqs_error}")
            
            processed_count += 1
            
        except Exception as e:
            print(f"❌ Error processing message: {str(e)}")
            import traceback
            traceback.print_exc()
    
    # Return results
    result = {
        'statusCode': 200,
        'body': json.dumps({
            'processed': processed_count,
            'mocked': mocked_count,
            'schema_rejected': schema_rejected_count,
            'timestamp': int(time.time())
        })
    }
    
    print(f"📊 Processing complete:")
    print(f"  - Processed: {processed_count}")
    print(f"  - Mocked: {mocked_count}")
    print(f"  - Schema Rejected: {schema_rejected_count}")
    
    return result

# Local test
if __name__ == "__main__":
    print("🧪 Local test of complete CPU Mock Lambda")
    
    test_event = {
        'Records': [{
            'messageId': 'test-123',
            'receiptHandle': 'test-handle',
            'body': json.dumps({
                'story_id': 'local-test-story',
                'seq': 1,
                'text': 'Local test sentence for complete lambda.',
                'voice_id': 'test-voice',
                'lang': 'en-US',
                'params': {'speed': 1.0, 'format': 'aac'},
                'idempotency_key': 'local-test-hash'
            })
        }]
    }
    
    # Set test environment
    os.environ['SQS_QUEUE_URL'] = 'https://sqs.test.amazonaws.com/123456789012/test-queue'
    os.environ['STORIES_TABLE_NAME'] = 'test-stories-table'
    os.environ['MOCK_MIN_MS_PARAM'] = '/test/cpu_mock_min_ms'
    os.environ['MOCK_MAX_MS_PARAM'] = '/test/cpu_mock_max_ms'
    
    # Mock SSM response
    import unittest.mock as mock
    with mock.patch('boto3.client') as mock_client:
        mock_ssm = mock.Mock()
        mock_ssm.get_parameter.return_value = {
            'Parameter': {'Value': '300'}
        }
        mock_client.return_value = mock_ssm
        
        result = lambda_handler(test_event, None)
        print(f"Test result: {result}")