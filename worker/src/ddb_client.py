import boto3
import time
import logging
import base64
from decimal import Decimal
from typing import Optional, Tuple, Dict, Any, List

logger = logging.getLogger('gpu-worker')

class ProductionDynamoDBClient:
    """PRODUCTION DynamoDB client with correct binary attribute handling"""
    
    def __init__(self, voices_table_name: str, stories_table_name: str, region: str = None):
        # PRODUCTION: Configure boto3 session with retries
        session = boto3.Session()
        config = boto3.session.Config(
            max_pool_connections=50,  # Higher for production
            retries={'max_attempts': 5, 'mode': 'standard'}
        )
        
        self.dynamodb = session.resource('dynamodb', region_name=region, config=config)
        self.voices_table = self.dynamodb.Table(voices_table_name)
        self.stories_table = self.dynamodb.Table(stories_table_name)
        
        # PRODUCTION: Metrics
        self.voice_cache_hits = 0
        self.voice_cache_misses = 0
        self.start_time = time.time()
        
        logger.info(f"🏭 PRODUCTION DynamoDB Client initialized: {voices_table_name}, {stories_table_name}")
    
    # ============ CRITICAL FIX: BINARY ATTRIBUTE HANDLING ============
    
    def _decode_ddb_binary(self, binary_data: Any) -> Optional[bytes]:
        """
        PRODUCTION: Correctly decode DynamoDB binary attribute
        DynamoDB returns binary in format: {'B': b'...'} or {'B': 'base64 string'}
        """
        if binary_data is None:
            return None
        
        try:
            if isinstance(binary_data, bytes):
                # Already bytes
                return binary_data
            elif isinstance(binary_data, dict) and 'B' in binary_data:
                # boto3.resource format
                b_value = binary_data['B']
                if isinstance(b_value, bytes):
                    return b_value
                elif isinstance(b_value, str):
                    # Base64 encoded string
                    return base64.b64decode(b_value)
                else:
                    logger.warning(f"⚠️ Unknown binary format value: {type(b_value)}")
                    return None
            elif isinstance(binary_data, str):
                # Try to decode as base64 string
                return base64.b64decode(binary_data)
            elif hasattr(binary_data, 'value'):
                # boto3.dynamodb.types.Binary
                return binary_data.value
            else:
                logger.warning(f"⚠️ Cannot decode binary data: {type(binary_data)}")
                return None
                
        except Exception as e:
            logger.error(f"❌ Binary decoding failed: {e}")
            return None
    
    def _encode_ddb_binary(self, data: bytes) -> Dict[str, Any]:
        """Encode bytes for DynamoDB binary attribute"""
        try:
            if not data:
                return {'B': b''}
            
            # boto3 expects {'B': b'...'} format
            return {'B': data}
        except Exception as e:
            logger.error(f"❌ Binary encoding failed: {e}")
            return {'B': b''}
    
    def get_voice_embedding(self, voice_id: str) -> Tuple[Optional[bytes], Optional[bytes]]:
        """Get voice embeddings with CORRECT binary handling"""
        try:
            start_time = time.time()
            
            response = self.voices_table.get_item(
                Key={'voice_id': voice_id},
                ProjectionExpression='embeddings, style, last_accessed',
                ConsistentRead=False  # Use eventually consistent for performance
            )
            
            latency = (time.time() - start_time) * 1000
            
            if 'Item' in response:
                item = response['Item']
                
                # ✅ CRITICAL FIX: Correctly decode binary attributes
                embeddings_raw = item.get('embeddings')
                style_raw = item.get('style')
                
                embeddings = self._decode_ddb_binary(embeddings_raw)
                style = self._decode_ddb_binary(style_raw)
                
                if embeddings is None or style is None:
                    logger.warning(f"⚠️ Voice {voice_id} has missing embeddings/style")
                    return None, None
                
                # Update last accessed time (for cache warming)
                self._update_voice_access_time(voice_id)
                
                # Track metrics
                if embeddings and style:
                    self.voice_cache_hits += 1
                else:
                    self.voice_cache_misses += 1
                
                logger.debug(f"✅ Voice {voice_id} retrieved in {latency:.1f}ms")
                return embeddings, style
            
            logger.warning(f"⚠️ Voice {voice_id} not found")
            self.voice_cache_misses += 1
            return None, None
            
        except Exception as e:
            logger.error(f"❌ Failed to get voice embeddings for {voice_id}: {e}")
            self.voice_cache_misses += 1
            return None, None
    
    def store_voice_embeddings(self, voice_id: str, embeddings: bytes, style: bytes, 
                              consent_metadata: Dict[str, Any] = None) -> bool:
        """PRODUCTION: Store voice embeddings with correct binary encoding"""
        try:
            # ✅ CRITICAL: Encode binary attributes for DynamoDB
            embeddings_attr = self._encode_ddb_binary(embeddings)
            style_attr = self._encode_ddb_binary(style)
            
            item = {
                'voice_id': voice_id,
                'embeddings': embeddings_attr,
                'style': style_attr,
                'created_at': Decimal(str(time.time())),
                'last_accessed': Decimal(str(time.time())),
                'storage_version': 'binary_v1'
            }
            
            if consent_metadata:
                item['consent_metadata'] = consent_metadata
            
            self.voices_table.put_item(Item=item)
            logger.info(f"💾 Stored voice embeddings for {voice_id}")
            return True
            
        except Exception as e:
            logger.error(f"❌ Failed to store voice embeddings: {e}")
            return False
    
    # ============ FIXED BATCH METHODS ============
    
    def batch_get_voices(self, voice_ids: List[str]) -> Dict[str, Dict[str, Any]]:
        """PRODUCTION: Batch get voice embeddings with CORRECT binary decoding"""
        try:
            if not voice_ids:
                return {}
            
            # DynamoDB batch_get_item limit: 100 items
            batch_size = 100
            all_voices = {}
            
            for i in range(0, len(voice_ids), batch_size):
                batch = voice_ids[i:i + batch_size]
                keys = [{'voice_id': voice_id} for voice_id in batch]
                
                response = self.dynamodb.batch_get_item(
                    RequestItems={
                        self.voices_table.name: {
                            'Keys': keys,
                            'ProjectionExpression': 'voice_id, embeddings, style, last_accessed',
                            'ConsistentRead': False
                        }
                    }
                )
                
                for item in response.get('Responses', {}).get(self.voices_table.name, []):
                    voice_id = item['voice_id']
                    
                    # ✅ CRITICAL: Decode binary attributes
                    embeddings_raw = item.get('embeddings')
                    style_raw = item.get('style')
                    
                    embeddings = self._decode_ddb_binary(embeddings_raw)
                    style = self._decode_ddb_binary(style_raw)
                    
                    all_voices[voice_id] = {
                        'embeddings': embeddings,
                        'style': style,
                        'last_accessed': item.get('last_accessed', 0)
                    }
                
                # Handle unprocessed keys
                unprocessed = response.get('UnprocessedKeys', {}).get(self.voices_table.name, {})
                if unprocessed.get('Keys'):
                    logger.warning(f"⚠️ Unprocessed keys in batch: {len(unprocessed['Keys'])}")
            
            logger.debug(f"📦 Batch retrieved {len(all_voices)} voices")
            return all_voices
            
        except Exception as e:
            logger.error(f"❌ Batch voice get failed: {e}")
            return {}
    
    def get_popular_voices(self, limit: int = 50) -> List[Dict[str, Any]]:
        """PRODUCTION: Get popular voices with CORRECT binary decoding"""
        try:
            # Using scan with filter - in production you should have a GSI on last_accessed
            response = self.voices_table.scan(
                FilterExpression='attribute_exists(last_accessed)',
                ProjectionExpression='voice_id, embeddings, style, last_accessed',
                Limit=limit
            )
            
            voices = response.get('Items', [])
            
            # Decode binary attributes
            for voice in voices:
                embeddings_raw = voice.get('embeddings')
                style_raw = voice.get('style')
                
                voice['embeddings'] = self._decode_ddb_binary(embeddings_raw)
                voice['style'] = self._decode_ddb_binary(style_raw)
            
            # Sort by last_accessed (most recent first)
            voices.sort(key=lambda x: x.get('last_accessed', 0), reverse=True)
            
            logger.info(f"🔥 Retrieved {len(voices)} popular voices for cache warm-up")
            return voices
            
        except Exception as e:
            logger.error(f"❌ Failed to get popular voices: {e}")
            return []
    
    # ============ OTHER METHODS (UNCHANGED) ============
    
    def _update_voice_access_time(self, voice_id: str):
        """Update last accessed time for voice (for cache warming)"""
        try:
            self.voices_table.update_item(
                Key={'voice_id': voice_id},
                UpdateExpression='SET last_accessed = :now',
                ExpressionAttributeValues={':now': Decimal(str(time.time()))},
                ReturnValues='NONE'
            )
        except Exception as e:
            logger.debug(f"⚠️ Failed to update voice access time for {voice_id}: {e}")
    
    def get_last_seq_written(self, story_id: str) -> int:
        """CRITICAL: Get last_seq_written for resume after Spot interruption"""
        try:
            response = self.stories_table.get_item(
                Key={'story_id': story_id},
                ProjectionExpression='last_seq_written, status'
            )
            
            if 'Item' in response:
                item = response['Item']
                last_seq = item.get('last_seq_written', 0)
                status = item.get('status', 'preparing')
                
                logger.info(f"📖 Resume info for {story_id}: seq={last_seq}, status={status}")
                return last_seq
            
            return 0
            
        except Exception as e:
            logger.error(f"❌ Failed to get last_seq_written for {story_id}: {e}")
            return 0
    
    def update_story_progress(self, story_id: str, last_seq_written: int, status: str = "streaming", 
                              region: str = None, processing_mode: str = None):
        """PRODUCTION: Update story progress with region and processing mode"""
        try:
            update_expr = 'SET last_seq_written = :seq, #s = :status, updated_at = :now'
            attr_values = {
                ':seq': last_seq_written,
                ':status': status,
                ':now': Decimal(str(time.time()))
            }
            
            # Add optional attributes
            if region:
                update_expr += ', region = :region'
                attr_values[':region'] = region
            
            if processing_mode:
                update_expr += ', processing_mode = :mode'
                attr_values[':mode'] = processing_mode
            
            # Calculate progress percentage (assuming 10 sentences per story)
            progress_pct = min(100, last_seq_written * 10)
            update_expr += ', progress_pct = :pct'
            attr_values[':pct'] = progress_pct
            
            self.stories_table.update_item(
                Key={'story_id': story_id},
                UpdateExpression=update_expr,
                ExpressionAttributeNames={'#s': 'status'},
                ExpressionAttributeValues=attr_values,
                ReturnValues='UPDATED_NEW'
            )
            
            logger.debug(f"📝 Updated story {story_id}: seq={last_seq_written}, status={status}, progress={progress_pct}%")
            
        except Exception as e:
            logger.error(f"❌ Failed to update story progress: {e}")
            raise
    
    def mark_story_complete(self, story_id: str, final_audio_url: str = None):
        """PRODUCTION: Mark story as completed with optional final audio URL"""
        try:
            update_expr = 'SET #s = :status, completed_at = :now, progress_pct = :pct'
            attr_values = {
                ':status': 'complete',
                ':now': Decimal(str(time.time())),
                ':pct': 100
            }
            
            if final_audio_url:
                update_expr += ', final_audio_url = :url'
                attr_values[':url'] = final_audio_url
            
            # Set TTL for story cleanup (Blueprint: 7-30 days)
            ttl_days = 30  # Configurable
            ttl_timestamp = int(time.time()) + (ttl_days * 24 * 3600)
            update_expr += ', ttl = :ttl'
            attr_values[':ttl'] = ttl_timestamp
            
            self.stories_table.update_item(
                Key={'story_id': story_id},
                UpdateExpression=update_expr,
                ExpressionAttributeNames={'#s': 'status'},
                ExpressionAttributeValues=attr_values,
                ReturnValues='UPDATED_NEW'
            )
            
            logger.info(f"🎉 Marked story as complete: {story_id}, TTL={ttl_days} days")
            
        except Exception as e:
            logger.error(f"❌ Failed to mark story complete: {e}")
            raise
    
    def delete_voice(self, voice_id: str) -> bool:
        """PRODUCTION: Hard delete voice (Blueprint: /voices/delete hard-deletes)"""
        try:
            self.voices_table.delete_item(
                Key={'voice_id': voice_id},
                ConditionExpression='attribute_exists(voice_id)',
                ReturnValues='ALL_OLD'
            )
            logger.info(f"🗑️ Hard-deleted voice: {voice_id}")
            return True
            
        except self.dynamodb.meta.client.exceptions.ConditionalCheckFailedException:
            logger.warning(f"⚠️ Voice {voice_id} not found for deletion")
            return False
        except Exception as e:
            logger.error(f"❌ Failed to delete voice {voice_id}: {e}")
            return False
    
    def pre_warm_connections(self):
        """PRODUCTION: Pre-warm DynamoDB connections for Warm Pool instances"""
        try:
            # Make a few light queries to establish connections
            self.voices_table.get_item(Key={'voice_id': 'warmup_test'})
            self.stories_table.get_item(Key={'story_id': 'warmup_test'})
            
            # Batch request to warm up batch connections
            self.dynamodb.batch_get_item(
                RequestItems={
                    self.voices_table.name: {
                        'Keys': [{'voice_id': 'test1'}, {'voice_id': 'test2'}]
                    }
                }
            )
            
            logger.info("🔥 Pre-warmed DynamoDB connections for Warm Pool")
            
        except Exception as e:
            # Expected to fail - we just want to establish connections
            logger.debug(f"🔥 Warm-up queries completed (errors expected): {e}")
    
    def get_client_stats(self) -> Dict[str, Any]:
        """Get client statistics for monitoring"""
        uptime = time.time() - self.start_time
        
        return {
            'uptime_seconds': uptime,
            'voice_cache_hits': self.voice_cache_hits,
            'voice_cache_misses': self.voice_cache_misses,
            'cache_hit_rate': (
                self.voice_cache_hits / max(self.voice_cache_hits + self.voice_cache_misses, 1)
            ),
            'tables': {
                'voices': self.voices_table.name,
                'stories': self.stories_table.name
            }
        }