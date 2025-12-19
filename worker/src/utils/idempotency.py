import hashlib
import threading
import boto3
import json
import logging
from datetime import datetime, timedelta

logger = logging.getLogger('gpu-worker')

class IdempotencyManager:
    """Manages idempotent operations with S3 lock files matching blueprint"""
    
    def __init__(self, s3_client, stories_bucket, model_version="xtts-v2"):
        self.s3 = s3_client
        self.stories_bucket = stories_bucket
        self.model_version = model_version
        
        # In-memory cache for performance (supplements S3 lock files)
        self.processed_keys = set()
        self.idempotency_lock = threading.Lock()
        self.persistence_enabled = True
        
        logger.info(f"🎯 IdempotencyManager initialized with model: {model_version}")
    
    def generate_idempotency_key(self, story_id, seq, text, voice_id, speed=1.0, format="aac"):
        """
        Generate idempotency key matching blueprint specification:
        hash(model|voice|text|speed|format)
        
        Returns dict with:
          - memory_key: For in-memory cache
          - s3_key: For S3 lock file
          - hash: The computed hash
        """
        # Create hash string exactly as blueprint specifies
        hash_string = f"{self.model_version}|{voice_id}|{text}|{speed}|{format}"
        
        # Use SHA-256 for consistency (matches typical AWS patterns)
        key_hash = hashlib.sha256(hash_string.encode('utf-8')).hexdigest()[:32]  # First 32 chars
        
        # Create S3 key matching blueprint: stories/{story_id}/idempotency/{seq}_{hash}.lock
        s3_key = f"stories/{story_id}/idempotency/{seq:04d}_{key_hash}.lock"
        
        # Also create in-memory key for fast lookups
        memory_key = f"{story_id}_{seq}_{key_hash}"
        
        logger.debug(f"🔑 Generated idempotency key: {memory_key} -> S3: {s3_key}")
        return {
            'memory_key': memory_key,
            's3_key': s3_key,
            'hash': key_hash
        }
    
    def check_already_processed(self, idempotency_data):
        """Check if segment has been processed - uses S3 lock files as source of truth"""
        if not self.persistence_enabled:
            # Fallback to memory-only check
            memory_key = idempotency_data['memory_key']
            with self.idempotency_lock:
                return memory_key in self.processed_keys
        
        memory_key = idempotency_data['memory_key']
        s3_key = idempotency_data['s3_key']
        
        # 1. Check in-memory cache (fast path)
        with self.idempotency_lock:
            if memory_key in self.processed_keys:
                logger.debug(f"🎯 Idempotency HIT (memory cache): {memory_key}")
                return True
        
        # 2. Check S3 lock file (source of truth)
        try:
            # Try to get the lock file
            self.s3.head_object(Bucket=self.stories_bucket, Key=s3_key)
            
            # Lock file exists, add to memory cache
            with self.idempotency_lock:
                self.processed_keys.add(memory_key)
            
            logger.info(f"✅ Idempotency HIT (S3 lock file): {s3_key}")
            return True
            
        except self.s3.exceptions.ClientError as e:
            if e.response['Error']['Code'] == '404':
                # Lock file doesn't exist - not processed yet
                logger.debug(f"🔄 Idempotency MISS: No lock file for {s3_key}")
                return False
            else:
                # Other S3 error - log but assume not processed
                logger.warning(f"⚠️ S3 error checking lock file {s3_key}: {e}")
                return False
        except Exception as e:
            logger.warning(f"⚠️ Error checking idempotency: {e}")
            return False
    
    def mark_processed(self, idempotency_data, metadata=None):
        """Mark segment as processed by creating S3 lock file"""
        memory_key = idempotency_data['memory_key']
        s3_key = idempotency_data['s3_key']
        
        # First update memory cache
        with self.idempotency_lock:
            self.processed_keys.add(memory_key)
        
        # Then persist to S3 if enabled
        if self.persistence_enabled:
            try:
                # Create lock file in S3
                lock_content = {
                    'story_id': memory_key.split('_')[0],
                    'seq': int(memory_key.split('_')[1]),
                    'hash': idempotency_data['hash'],
                    'processed_at': datetime.utcnow().isoformat(),
                    'metadata': metadata or {},
                    'model_version': self.model_version
                }
                
                self.s3.put_object(
                    Bucket=self.stories_bucket,
                    Key=s3_key,
                    Body=json.dumps(lock_content, indent=2),
                    ContentType='application/json',
                    Metadata={
                        'idempotency-key': memory_key,
                        'processed-at': datetime.utcnow().isoformat()
                    }
                )
                
                logger.info(f"✅ Created idempotency lock file: {s3_key}")
                return True
                
            except Exception as e:
                logger.error(f"❌ Failed to create idempotency lock file: {e}")
                return False
        else:
            logger.debug(f"✅ Marked processed (memory only): {memory_key}")
            return True
    
    def check_s3_segment_exists(self, story_id, sequence):
        """Check if segment already exists in S3 - PERSISTENT STORAGE"""
        try:
            segment_key = f"stories/{story_id}/audio_{sequence:03d}.m4s"
            self.s3.head_object(Bucket=self.stories_bucket, Key=segment_key)
            logger.info(f"✅ Segment already exists in S3: {segment_key}")
            return True
        except self.s3.exceptions.ClientError as e:
            if e.response['Error']['Code'] == '404':
                return False
            else:
                logger.warning(f"⚠️ Error checking S3 segment: {e}")
                return False
        except Exception as e:
            logger.warning(f"⚠️ Unexpected error checking S3: {e}")
            return False
    
    def load_processed_keys_from_s3(self, story_id):
        """Load already processed segments from S3 for resume capability"""
        try:
            # List all lock files for this story
            response = self.s3.list_objects_v2(
                Bucket=self.stories_bucket,
                Prefix=f"stories/{story_id}/idempotency/"
            )
            
            if 'Contents' not in response:
                return set()
            
            processed_keys = set()
            for obj in response['Contents']:
                key = obj['Key']
                if key.endswith('.lock'):
                    # Extract memory key from S3 key
                    # Pattern: stories/{story_id}/idempotency/{seq}_{hash}.lock
                    parts = key.split('/')
                    if len(parts) >= 4:
                        filename = parts[-1]
                        # Remove .lock extension
                        if filename.endswith('.lock'):
                            base_name = filename[:-5]  # Remove .lock
                            # Format: {seq:04d}_{hash}
                            seq_hash = base_name
                            memory_key = f"{story_id}_{seq_hash}"
                            processed_keys.add(memory_key)
            
            # Add to memory cache
            with self.idempotency_lock:
                self.processed_keys.update(processed_keys)
            
            logger.info(f"📥 Loaded {len(processed_keys)} existing idempotency locks from S3 for {story_id}")
            return processed_keys
            
        except Exception as e:
            logger.warning(f"⚠️ Failed to load processed keys from S3: {e}")
            return set()
    
    def clear_processed_keys(self, story_id=None):
        """Clear processed keys (for testing or memory management)"""
        with self.idempotency_lock:
            if story_id:
                # Remove only keys for specific story
                self.processed_keys = {k for k in self.processed_keys if not k.startswith(f"{story_id}_")}
                logger.info(f"🧹 Cleared processed keys for story: {story_id}")
            else:
                # Clear all keys
                count = len(self.processed_keys)
                self.processed_keys.clear()
                logger.info(f"🧹 Cleared all {count} processed keys")
    
    def get_idempotency_stats(self):
        """Get idempotency statistics for monitoring"""
        with self.idempotency_lock:
            # Group by story_id for better insights
            story_stats = {}
            for key in self.processed_keys:
                story_id = key.split('_')[0]
                if story_id not in story_stats:
                    story_stats[story_id] = 0
                story_stats[story_id] += 1
            
            return {
                'total_processed_keys': len(self.processed_keys),
                'stories_tracked': len(story_stats),
                'keys_per_story': story_stats,
                'persistence_enabled': self.persistence_enabled,
                'model_version': self.model_version
            }
    
    def cleanup_old_entries(self):
        """Clean up old cache entries (basic memory management)"""
        with self.idempotency_lock:
            # Simple cleanup: if we have too many entries, clear oldest stories
            if len(self.processed_keys) > 1000:  # Arbitrary limit
                # For now, just clear all (in production, you'd track timestamps)
                old_count = len(self.processed_keys)
                self.processed_keys.clear()
                logger.info(f"🧹 Cleaned up {old_count} idempotency entries")
                self.last_cleanup = datetime.now()
    
    def cleanup_old_lock_files(self, story_id=None, older_than_hours=24):
        """Clean up old lock files (optional maintenance)"""
        if not self.persistence_enabled:
            return 0
        
        try:
            if story_id:
                prefix = f"stories/{story_id}/idempotency/"
            else:
                prefix = "stories/"
            
            cutoff_time = datetime.utcnow() - timedelta(hours=older_than_hours)
            deleted_count = 0
            
            response = self.s3.list_objects_v2(
                Bucket=self.stories_bucket,
                Prefix=prefix
            )
            
            if 'Contents' not in response:
                return 0
            
            for obj in response['Contents']:
                if obj['Key'].endswith('.lock'):
                    try:
                        # Get object metadata to check age
                        metadata = self.s3.head_object(
                            Bucket=self.stories_bucket,
                            Key=obj['Key']
                        )
                        
                        # Check if lock file is old
                        last_modified = metadata['LastModified'].replace(tzinfo=None)
                        if last_modified < cutoff_time:
                            self.s3.delete_object(
                                Bucket=self.stories_bucket,
                                Key=obj['Key']
                            )
                            deleted_count += 1
                            logger.debug(f"🧹 Deleted old lock file: {obj['Key']}")
                            
                    except Exception as e:
                        logger.warning(f"⚠️ Error processing lock file {obj['Key']}: {e}")
                        continue
            
            if deleted_count > 0:
                logger.info(f"🧹 Cleaned up {deleted_count} old lock files")
            
            return deleted_count
            
        except Exception as e:
            logger.error(f"❌ Failed to clean up lock files: {e}")
            return 0
    
    def verify_idempotency_integrity(self, story_id, expected_sequences):
        """
        Verify that idempotency state matches expected sequences.
        Useful for debugging and integrity checks.
        """
        try:
            # Load all lock files for this story
            response = self.s3.list_objects_v2(
                Bucket=self.stories_bucket,
                Prefix=f"stories/{story_id}/idempotency/"
            )
            
            found_sequences = set()
            if 'Contents' in response:
                for obj in response['Contents']:
                    if obj['Key'].endswith('.lock'):
                        try:
                            filename = obj['Key'].split('/')[-1]
                            seq_str = filename.split('_')[0]
                            sequence = int(seq_str)
                            found_sequences.add(sequence)
                        except (ValueError, IndexError):
                            continue
            
            # Check for missing sequences
            missing = [seq for seq in expected_sequences if seq not in found_sequences]
            extra = [seq for seq in found_sequences if seq not in expected_sequences]
            
            integrity_report = {
                'story_id': story_id,
                'expected_count': len(expected_sequences),
                'found_count': len(found_sequences),
                'missing_sequences': missing,
                'extra_sequences': extra,
                'integrity_ok': len(missing) == 0 and len(extra) == 0
            }
            
            if not integrity_report['integrity_ok']:
                logger.warning(f"⚠️ Idempotency integrity issues: {integrity_report}")
            else:
                logger.info(f"✅ Idempotency integrity verified: {story_id}")
            
            return integrity_report
            
        except Exception as e:
            logger.error(f"❌ Failed to verify idempotency integrity: {e}")
            return {
                'story_id': story_id,
                'error': str(e),
                'integrity_ok': False
            }