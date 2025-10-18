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

def get_mock_timing():
    """Get mock timing from SSM Parameter Store"""
    try:
        min_ms = int(ssm.get_parameter(Name=os.environ['MOCK_MIN_MS_PARAM'])['Parameter']['Value'])
        max_ms = int(ssm.get_parameter(Name=os.environ['MOCK_MAX_MS_PARAM'])['Parameter']['Value'])
        return min_ms, max_ms
    except Exception as e:
        print(f"Error reading SSM parameters, using defaults: {e}")
        return 300, 800  # Default 300-800ms

def lambda_handler(event, context):
    queue_url = os.environ['SQS_QUEUE_URL']
    stories_table = dynamodb.Table(os.environ['STORIES_TABLE_NAME'])
    
    processed_count = 0
    batch_size = random.randint(1, 5)  # Random batch size 1-5
    
    try:
        # Receive messages from SQS
        response = sqs.receive_message(
            QueueUrl=queue_url,
            MaxNumberOfMessages=batch_size,
            WaitTimeSeconds=5,  # Short poll for Lambda
            MessageAttributeNames=['All']
        )
        
        messages = response.get('Messages', [])
        print(f"Received {len(messages)} messages for processing")
        
        for message in messages:
            try:
                body = json.loads(message['Body'])
                story_id = body['story_id']
                seq = body['seq']
                text = body.get('text', '')[:50]  # Log first 50 chars
                
                print(f"Processing story_id: {story_id}, seq: {seq}, text: '{text}...'")
                
                # Simulate processing time
                min_ms, max_ms = get_mock_timing()
                processing_time = random.randint(min_ms, max_ms) / 1000.0
                time.sleep(processing_time)
                
                # Calculate progress percentage
                progress_pct = min(100, seq * 10)  # Simple progress calculation
                
                # Update DynamoDB story progress - FIXED VERSION
                try:
                    stories_table.update_item(
                        Key={'story_id': story_id},
                        UpdateExpression='SET last_seq_written = :seq, progress_pct = :pct, updated_at = :now, #s = :status',
                        ExpressionAttributeNames={
                            '#s': 'status'
                        },
                        ExpressionAttributeValues={
                            ':seq': seq,
                            ':pct': progress_pct,
                            ':now': int(time.time()),
                            ':status': 'streaming' if progress_pct < 100 else 'complete'
                        },
                        ReturnValues='UPDATED_NEW'
                    )
                    print(f"✅ Updated story {story_id}: seq={seq}, progress={progress_pct}%")
                    
                except ClientError as e:
                    print(f"❌ Failed to update DynamoDB for story {story_id}: {e.response['Error']['Code']}")
                    # Don't delete message so it can be retried
                    continue
                
                # Delete message from queue only if DynamoDB update succeeded
                sqs.delete_message(
                    QueueUrl=queue_url,
                    ReceiptHandle=message['ReceiptHandle']
                )
                
                processed_count += 1
                
            except Exception as e:
                print(f"Failed to process message {message.get('MessageId', 'unknown')}: {str(e)}")
                # Message will become visible again after visibility timeout
                continue
        
        print(f"Successfully processed {processed_count} messages")
        
        return {
            'statusCode': 200,
            'body': json.dumps({
                'processed': processed_count,
                'total_received': len(messages),
                'batch_size': batch_size
            })
        }
        
    except Exception as e:
        print(f"Error in Lambda handler: {str(e)}")
        return {
            'statusCode': 500,
            'body': json.dumps({'error': str(e)})
        }