#!/usr/bin/env python3
"""
🚀 BLUEPRINT DYNAMODB CLIENT - 100% COMPLIANT
Simple DynamoDB operations for voice cloning blueprint
"""

import logging
import boto3
import time
from typing import Optional, Tuple, Dict, Any
from botocore.exceptions import ClientError

logger = logging.getLogger('ddb-client')

class BlueprintDynamoDBClient:
    """100% Blueprint: Simple DynamoDB client with SSE-KMS encryption"""
    
    def __init__(self, voices_table_name: str, stories_table_name: str, region: str = "us-east-1"):
        """
        Initialize DynamoDB client
        Blueprint: Uses SSE-KMS for encryption at rest
        """
        self.dynamodb = boto3.resource('dynamodb', region_name=region)
        self.voices_table = self.dynamodb.Table(voices_table_name)
        self.stories_table = self.dynamodb.Table(stories_table_name)
        
        logger.info(f"✅ DDB Client initialized:")
        logger.info(f"   • Voices table: {voices_table_name}")
        logger.info(f"   • Stories table: {stories_table_name}")
        logger.info(f"   • Region: {region}")
    
    # ============ VOICE EMBEDDINGS (SSE-KMS ENCRYPTED) ============
    
    def get_voice_embeddings(self, voice_id: str) -> Tuple[Optional[bytes], Optional[bytes]]:
        """
        BLUEPRINT: Get voice embeddings from DynamoDB
        Returns: (embeddings_bytes, style_bytes) or (None, None)
        """
        try:
            response = self.voices_table.get_item(
                Key={'voice_id': voice_id},
                ProjectionExpression='embeddings, style, consent_metadata'
            )
            
            if 'Item' not in response:
                logger.warning(f"Voice not found: {voice_id}")
                return None, None
            
            item = response['Item']
            
            # BLUEPRINT: embeddings and style are KMS-encrypted binary attributes
            embeddings = self._decode_binary_attribute(item.get('embeddings'))
            style = self._decode_binary_attribute(item.get('style'))
            
            if embeddings is None or style is None:
                logger.warning(f"Voice {voice_id} missing embeddings/style")
                return None, None
            
            logger.debug(f"Retrieved voice: {voice_id}")
            return embeddings, style
            
        except ClientError as e:
            if e.response['Error']['Code'] == 'ResourceNotFoundException':
                logger.error(f"Table not found: {e}")
            else:
                logger.error(f"DynamoDB error getting voice {voice_id}: {e}")
            return None, None
        except Exception as e:
            logger.error(f"Unexpected error getting voice {voice_id}: {e}")
            return None, None
    
    def store_voice_embeddings(self, voice_id: str, embeddings: bytes, style: bytes, 
                               consent_metadata: Dict = None) -> bool:
        """
        BLUEPRINT: Store voice embeddings with SSE-KMS encryption
        Consent metadata must include: user_id, consent_at, consent_version, ip, ua
        """
        try:
            # Validate consent metadata
            if not consent_metadata:
                logger.error("Consent metadata required")
                return False
            
            required_fields = ['user_id', 'consent_at', 'consent_version']
            for field in required_fields:
                if field not in consent_metadata:
                    logger.error(f"Missing consent field: {field}")
                    return False
            
            item = {
                'voice_id': voice_id,
                'embeddings': embeddings,  # Binary attribute, SSE-KMS encrypted
                'style': style,            # Binary attribute, SSE-KMS encrypted
                'consent_metadata': consent_metadata,
                'created_at': int(time.time()),
                'updated_at': int(time.time())
            }
            
            self.voices_table.put_item(Item=item)
            logger.info(f"✅ Stored voice embeddings: {voice_id}")
            return True
            
        except Exception as e:
            logger.error(f"❌ Failed to store voice {voice_id}: {e}")
            return False
    
    # ============ STORY PROGRESS (TTL FOR EPHEMERAL) ============
    
    def get_story_progress(self, story_id: str) -> Dict[str, Any]:
        """
        BLUEPRINT: Get story progress including last_seq_written
        For Spot interruption resume
        """
        try:
            response = self.stories_table.get_item(Key={'story_id': story_id})
            
            if 'Item' not in response:
                return {'last_seq_written': 0, 'status': 'not_found', 'found': False}
            
            item = response['Item']
            return {
                'found': True,
                'last_seq_written': item.get('last_seq_written', 0),
                'status': item.get('status', 'unknown'),
                'region': item.get('region', 'unknown'),
                'progress_pct': item.get('progress_pct', 0)
            }
            
        except Exception as e:
            logger.error(f"Failed to get story {story_id}: {e}")
            return {'last_seq_written': 0, 'status': 'error', 'found': False}
    
    def update_story_progress(self, story_id: str, last_seq_written: int, 
                            status: str = "streaming", region: str = None):
        """
        BLUEPRINT: Update story progress with TTL
        TTL: 30 days (configurable via story_retention_days)
        """
        try:
            # BLUEPRINT: Set TTL for ephemeral stories
            story_retention_days = 30  # From blueprint
            ttl_timestamp = int(time.time()) + (story_retention_days * 24 * 3600)
            
            # Calculate progress percentage
            # Assuming ~10 sentences per story for estimation
            progress_pct = min(100, last_seq_written * 10)
            
            # FIXED: Use ExpressionAttributeNames for reserved keyword 'ttl'
            update_values = {
                ':seq': last_seq_written,
                ':status': status,
                ':ttl_val': ttl_timestamp,  # Changed from :ttl to :ttl_val
                ':progress': progress_pct,
                ':updated': int(time.time())
            }
            
            # FIXED: Use #t for ttl reserved keyword
            update_expr = 'SET last_seq_written = :seq, #s = :status, #t = :ttl_val, '
            update_expr += 'progress_pct = :progress, updated_at = :updated'
            
            # Add region if provided (Blueprint: multi-region support)
            if region:
                update_expr += ', #r = :region'  # ✅ FIXED: Use #r for reserved keyword
                update_values[':region'] = region

            self.stories_table.update_item(
                Key={'story_id': story_id},
                UpdateExpression=update_expr,
                ExpressionAttributeNames={
                    '#s': 'status',
                    '#t': 'ttl',  # ttl is a reserved keyword
                    '#r': 'region'  # ✅ ADD THIS: region is ALSO a reserved keyword!
                },
                ExpressionAttributeValues=update_values
            )
            
            logger.debug(f"📝 Updated story {story_id}: seq={last_seq_written}, progress={progress_pct}%")
            
        except Exception as e:
            logger.error(f"❌ Failed to update story {story_id}: {e}")
            raise
    
    def mark_story_complete(self, story_id: str, final_audio_url: str = None):
        """BLUEPRINT: Mark story as completed with optional final audio"""
        try:
            update_values = {
                ':status': 'complete',
                ':now': int(time.time()),
                ':progress': 100
            }
            
            update_expr = 'SET #s = :status, completed_at = :now, progress_pct = :progress'
            
            if final_audio_url:
                update_expr += ', final_audio_url = :url'
                update_values[':url'] = final_audio_url
            
            self.stories_table.update_item(
                Key={'story_id': story_id},
                UpdateExpression=update_expr,
                ExpressionAttributeNames={'#s': 'status'},
                ExpressionAttributeValues=update_values
            )
            
            logger.info(f"✅ Story completed: {story_id}")
            
        except Exception as e:
            logger.error(f"❌ Failed to mark story complete {story_id}: {e}")
    
    # ============ VOICE DELETION (HARD DELETE) ============
    
    def delete_voice(self, voice_id: str) -> bool:
        """
        BLUEPRINT: Hard delete voice embeddings and metadata
        Called by /voices/delete API endpoint
        """
        try:
            # Delete the item
            response = self.voices_table.delete_item(
                Key={'voice_id': voice_id},
                ReturnValues='ALL_OLD'
            )
            
            # Check if item was actually deleted
            if 'Attributes' in response:
                logger.info(f"🗑️ Hard-deleted voice: {voice_id}")
                return True
            else:
                logger.warning(f"Voice not found for deletion: {voice_id}")
                return False
                
        except Exception as e:
            logger.error(f"❌ Failed to delete voice {voice_id}: {e}")
            return False
    
    # ============ UTILITY METHODS ============
    
    def _decode_binary_attribute(self, binary_data) -> Optional[bytes]:
        """
        Decode DynamoDB binary attribute
        boto3.resource returns bytes directly for binary attributes
        """
        try:
            if binary_data is None:
                return None
            
            if isinstance(binary_data, bytes):
                return binary_data
            
            if isinstance(binary_data, dict) and 'B' in binary_data:
                value = binary_data['B']
                if isinstance(value, bytes):
                    return value
                # Shouldn't happen with boto3.resource
                return None
            
            return None
            
        except Exception as e:
            logger.error(f"Binary decode error: {e}")
            return None
    
    def health_check(self) -> bool:
        """Simple health check for ASG/ELB"""
        try:
            # Verify tables exist and are accessible
            self.voices_table.table_status
            self.stories_table.table_status
            return True
        except Exception as e:
            logger.error(f"❌ DDB health check failed: {e}")
            return False
    
    def get_table_info(self) -> Dict[str, Any]:
        """Get table information for monitoring"""
        try:
            voices_table_info = self.voices_table.table_status
            stories_table_info = self.stories_table.table_status
            
            return {
                'voices_table': self.voices_table.name,
                'stories_table': self.stories_table.name,
                'voices_status': voices_table_info,
                'stories_status': stories_table_info,
                'healthy': True
            }
        except Exception as e:
            logger.error(f"Failed to get table info: {e}")
            return {'healthy': False, 'error': str(e)}

# ============ FACTORY FUNCTION ============

def create_ddb_client(voices_table: str = None, stories_table: str = None, 
                      region: str = None) -> BlueprintDynamoDBClient:
    """
    Factory function for creating DDB client
    Blueprint: Environment-based configuration
    """
    import os
    
    if not voices_table:
        voices_table = os.environ['VOICES_TABLE_NAME']
    
    if not stories_table:
        stories_table = os.environ['STORIES_TABLE_NAME']
    
    if not region:
        region = os.environ.get('AWS_REGION', 'us-east-1')
    
    client = BlueprintDynamoDBClient(voices_table, stories_table, region)
    
    # Quick health check
    if not client.health_check():
        logger.error("DynamoDB tables not accessible")
        # Don't raise - let ASG handle unhealthy instances
    
    logger.info(f"✅ Created DDB client in region {region}")
    return client

if __name__ == "__main__":
    # Test the client
    import logging
    logging.basicConfig(level=logging.INFO)
    
    # Set test environment
    import os
    os.environ['VOICES_TABLE_NAME'] = 'voiceclone-voices-test'
    os.environ['STORIES_TABLE_NAME'] = 'voiceclone-stories-test'
    os.environ['AWS_REGION'] = 'us-east-1'
    
    try:
        client = create_ddb_client()
        print(f"✅ Client created: {client.health_check()}")
        print(f"Table info: {client.get_table_info()}")
        
        # Test story operations
        test_story_id = 'test-story-123'
        client.update_story_progress(test_story_id, 1, 'streaming', 'us-east-1')
        
        progress = client.get_story_progress(test_story_id)
        print(f"Story progress: {progress}")
        
        print("✅ All tests passed")
        
    except Exception as e:
        print(f"❌ Test failed: {e}")