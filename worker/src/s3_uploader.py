#!/usr/bin/env python3
"""
🚀 BLUEPRINT S3 UPLOADER - 100% COMPLIANT
Blueprint Requirements:
• Upload order: segments → playlist (append)
• Headers: segments=1y immutable, playlist=3s+SWR30
• EBS staging: writes locally then uploads
• Idempotency: skip existing segments
• Resume: check existing segments for Spot interruption
"""

import logging
from pathlib import Path
from typing import Set, Optional
import boto3
from botocore.exceptions import ClientError

logger = logging.getLogger('s3-uploader')

class BlueprintS3Uploader:
    """100% Blueprint: Synchronous S3 uploads with strict segments→playlist order"""
    
    def __init__(self, bucket_name: str, region: str = "us-east-1"):
        # BLUEPRINT: S3 client with region
        self.s3 = boto3.client('s3', region_name=region)
        self.bucket = bucket_name
        
        # BLUEPRINT: Cache-Control headers
        self.segment_headers = {
            'ContentType': 'video/mp4',
            'CacheControl': 'public, max-age=31536000, immutable'  # 1 year, immutable
        }
        
        self.playlist_headers = {
            'ContentType': 'application/vnd.apple.mpegurl',
            'CacheControl': 'public, max-age=3, stale-while-revalidate=30'  # 3s + 30s stale
        }
        
        logger.info(f"✅ S3 Uploader initialized: bucket={bucket_name}")
    
    def upload_segment(self, story_id: str, segment_path: Path) -> bool:
        """
        BLUEPRINT: Upload HLS segment (.m4s file)
        Returns: True if successful or already exists
        """
        try:
            if not segment_path.exists():
                logger.error(f"❌ Segment not found: {segment_path}")
                return False
            
            # Extract filename (audio_001.m4s)
            filename = segment_path.name
            s3_key = f"stories/{story_id}/{filename}"
            
            # BLUEPRINT: Idempotency check
            if self._object_exists(s3_key):
                logger.debug(f"⏭️ Segment already exists: {s3_key}")
                return True
            
            # BLUEPRINT: Upload with immutable headers
            self.s3.upload_file(
                Filename=str(segment_path),
                Bucket=self.bucket,
                Key=s3_key,
                ExtraArgs=self.segment_headers
            )
            
            logger.debug(f"📤 Uploaded segment: {s3_key}")
            return True
            
        except Exception as e:
            logger.error(f"❌ Failed to upload segment {segment_path.name}: {e}")
            return False
    
    def upload_init_segment(self, story_id: str, init_path: Path) -> bool:
        """
        BLUEPRINT: Upload init.mp4 segment
        Same headers as regular segments
        """
        try:
            if not init_path.exists():
                logger.error(f"❌ Init segment not found: {init_path}")
                return False
            
            s3_key = f"stories/{story_id}/init.mp4"
            
            # Idempotency check
            if self._object_exists(s3_key):
                return True
            
            self.s3.upload_file(
                Filename=str(init_path),
                Bucket=self.bucket,
                Key=s3_key,
                ExtraArgs=self.segment_headers
            )
            
            logger.debug(f"📤 Uploaded init segment: {s3_key}")
            return True
            
        except Exception as e:
            logger.error(f"❌ Failed to upload init segment: {e}")
            return False
    
    def update_playlist(self, story_id: str, playlist_path: Path) -> bool:
        """
        BLUEPRINT: Upload playlist AFTER segments
        Returns: True if successful
        """
        try:
            if not playlist_path.exists():
                logger.error(f"❌ Playlist not found: {playlist_path}")
                return False
            
            s3_key = f"stories/{story_id}/playlist.m3u8"
            
            # BLUEPRINT: Basic HLS contract check - verify at least one segment exists
            if not self._any_segments_exist(story_id):
                logger.warning(f"⚠️ No segments found for {story_id}, skipping playlist")
                return False
            
            # BLUEPRINT: Upload with short TTL headers
            self.s3.upload_file(
                Filename=str(playlist_path),
                Bucket=self.bucket,
                Key=s3_key,
                ExtraArgs=self.playlist_headers
            )
            
            logger.debug(f"📋 Updated playlist: {s3_key}")
            return True
            
        except Exception as e:
            logger.error(f"❌ Failed to update playlist: {e}")
            return False
    
    def upload_segment_then_playlist(self, story_id: str, segment_path: Path, playlist_path: Path) -> bool:
        """
        BLUEPRINT: Complete upload sequence for one segment
        1. Upload segment (.m4s)
        2. Update playlist (.m3u8)
        Returns: True if both successful
        """
        # Step 1: Upload segment
        segment_success = self.upload_segment(story_id, segment_path)
        if not segment_success:
            logger.error(f"❌ Segment upload failed, skipping playlist")
            return False
        
        # Step 2: Update playlist
        playlist_success = self.update_playlist(story_id, playlist_path)
        return playlist_success
    
    def ensure_story_directory(self, story_id: str) -> bool:
        """
        BLUEPRINT: Ensure story directory exists in S3
        Creates empty marker object
        """
        try:
            # Create directory marker (empty object)
            dir_key = f"stories/{story_id}/"
            self.s3.put_object(
                Bucket=self.bucket,
                Key=dir_key,
                Body=b'',
                ContentType='application/x-directory'
            )
            return True
        except Exception as e:
            logger.error(f"❌ Failed to create story directory: {e}")
            return False
    
    def upload_final_audio(self, story_id: str, final_path: Path, audio_format: str = "m4a") -> bool:
        """
        BLUEPRINT: Optional final audio upload
        For story downloads after streaming
        """
        try:
            if not final_path.exists():
                logger.error(f"❌ Final audio not found: {final_path}")
                return False
            
            # Create final directory
            dir_key = f"stories/{story_id}/final/"
            try:
                self.s3.put_object(Bucket=self.bucket, Key=dir_key, Body=b'')
            except:
                pass  # May already exist
            
            # Determine content type
            content_types = {
                'm4a': 'audio/mp4',
                'mp3': 'audio/mpeg',
                'opus': 'audio/ogg',
                'aac': 'audio/aac'
            }
            
            s3_key = f"stories/{story_id}/final/story.{audio_format}"
            
            # Upload with 1-day cache
            headers = {
                'ContentType': content_types.get(audio_format, 'audio/mpeg'),
                'CacheControl': 'public, max-age=86400'  # 1 day
            }
            
            self.s3.upload_file(
                Filename=str(final_path),
                Bucket=self.bucket,
                Key=s3_key,
                ExtraArgs=headers
            )
            
            logger.info(f"✅ Uploaded final audio: {s3_key}")
            return True
            
        except Exception as e:
            logger.error(f"❌ Failed to upload final audio: {e}")
            return False
    
    def get_existing_segments(self, story_id: str) -> Set[int]:
        """
        BLUEPRINT: Get uploaded segment numbers
        For resume after Spot interruption
        """
        existing = set()
        
        try:
            # List all segments for this story
            response = self.s3.list_objects_v2(
                Bucket=self.bucket,
                Prefix=f"stories/{story_id}/audio_"
            )
            
            if 'Contents' in response:
                for obj in response['Contents']:
                    filename = Path(obj['Key']).name
                    # Extract number from audio_001.m4s
                    try:
                        num_part = filename.split('_')[1].split('.')[0]
                        segment_num = int(num_part)
                        existing.add(segment_num)
                    except (ValueError, IndexError):
                        continue
            
            logger.debug(f"📥 Found {len(existing)} existing segments for {story_id}")
            return existing
            
        except Exception as e:
            logger.warning(f"⚠️ Failed to list segments: {e}")
            return set()
    
    def get_last_uploaded_segment(self, story_id: str) -> Optional[int]:
        """
        BLUEPRINT: Get highest segment number uploaded
        For resume logic
        """
        existing = self.get_existing_segments(story_id)
        return max(existing) if existing else None
    
    def verify_hls_contract(self, story_id: str) -> bool:
        """
        BLUEPRINT: Verify HLS contract is valid
        Playlist should only exist if segments exist
        """
        try:
            # Check if playlist exists
            playlist_key = f"stories/{story_id}/playlist.m3u8"
            playlist_exists = self._object_exists(playlist_key)
            
            # Check if any segments exist
            segments_exist = self._any_segments_exist(story_id)
            
            # BLUEPRINT RULE: Playlist without segments = violation
            if playlist_exists and not segments_exist:
                logger.error(f"❌ HLS VIOLATION: Playlist exists without segments for {story_id}")
                return False
            
            # BLUEPRINT RULE: Segments without playlist = OK (playlist coming)
            if segments_exist and not playlist_exists:
                logger.debug(f"✅ HLS OK: Segments waiting for playlist for {story_id}")
                return True
            
            if playlist_exists and segments_exist:
                logger.debug(f"✅ HLS OK: Complete for {story_id}")
                return True
            
            # No content yet
            logger.debug(f"ℹ️  No HLS content yet for {story_id}")
            return True
            
        except Exception as e:
            logger.error(f"❌ HLS verification failed: {e}")
            return False
    
    def cleanup_story(self, story_id: str) -> bool:
        """
        BLUEPRINT: Cleanup story from S3 (for testing or errors)
        Note: Production uses S3 lifecycle policies (7-30 days)
        """
        try:
            # List all objects for this story
            response = self.s3.list_objects_v2(
                Bucket=self.bucket,
                Prefix=f"stories/{story_id}/"
            )
            
            if 'Contents' not in response:
                logger.debug(f"No objects found for {story_id}")
                return True
            
            # Delete all objects
            objects = [{'Key': obj['Key']} for obj in response['Contents']]
            self.s3.delete_objects(
                Bucket=self.bucket,
                Delete={'Objects': objects}
            )
            
            logger.info(f"🧹 Cleaned up {len(objects)} objects for {story_id}")
            return True
            
        except Exception as e:
            logger.error(f"❌ Failed to cleanup {story_id}: {e}")
            return False
    
    def _object_exists(self, s3_key: str) -> bool:
        """Check if S3 object exists"""
        try:
            self.s3.head_object(Bucket=self.bucket, Key=s3_key)
            return True
        except ClientError as e:
            if e.response['Error']['Code'] == '404':
                return False
            raise
    
    def _any_segments_exist(self, story_id: str) -> bool:
        """Check if any segments exist for this story"""
        try:
            response = self.s3.list_objects_v2(
                Bucket=self.bucket,
                Prefix=f"stories/{story_id}/audio_",
                MaxKeys=1
            )
            return 'Contents' in response and len(response['Contents']) > 0
        except Exception:
            return False
    
    def health_check(self) -> bool:
        """Simple health check - verify bucket access"""
        try:
            self.s3.head_bucket(Bucket=self.bucket)
            return True
        except Exception as e:
            logger.error(f"❌ S3 health check failed: {e}")
            return False
    
    def get_bucket_info(self) -> dict:
        """Get bucket information for monitoring"""
        try:
            # Get bucket location
            location = self.s3.get_bucket_location(Bucket=self.bucket)
            
            # Get approximate object count for stories
            response = self.s3.list_objects_v2(
                Bucket=self.bucket,
                Prefix='stories/',
                MaxKeys=1,
                Delimiter='/'
            )
            
            return {
                'bucket': self.bucket,
                'region': location.get('LocationConstraint', 'us-east-1'),
                'stories_count': response.get('KeyCount', 0),
                'healthy': True
            }
        except Exception as e:
            logger.error(f"❌ Failed to get bucket info: {e}")
            return {
                'bucket': self.bucket,
                'error': str(e),
                'healthy': False
            }

# ============ FACTORY FUNCTION ============

def create_blueprint_s3_uploader(bucket_name: Optional[str] = None) -> BlueprintS3Uploader:
    """Factory function for creating S3 uploader"""
    import os
    
    if not bucket_name:
        bucket_name = os.environ['STORIES_BUCKET']
    
    region = os.environ.get('AWS_REGION', 'us-east-1')
    
    uploader = BlueprintS3Uploader(bucket_name, region)
    
    # Verify bucket access
    if not uploader.health_check():
        raise RuntimeError(f"Cannot access bucket: {bucket_name}")
    
    logger.info(f"✅ Created S3 uploader for {bucket_name} in {region}")
    return uploader

if __name__ == "__main__":
    # Test the uploader
    import logging
    logging.basicConfig(level=logging.INFO)
    
    # Set test environment
    import os
    os.environ['STORIES_BUCKET'] = 'test-bucket'
    
    try:
        uploader = create_blueprint_s3_uploader()
        print(f"✅ Uploader created: {uploader.get_bucket_info()}")
    except Exception as e:
        print(f"❌ Test failed: {e}")