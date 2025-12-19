"""
100% BLUEPRINT-COMPLIANT S3 Uploader
Enforces: segments → playlist (append), blueprint headers, sequential uploads
"""

import os
import time
import threading
import hashlib
import logging
from pathlib import Path
from typing import Dict, List, Set, Optional, Tuple
from collections import defaultdict, deque
import boto3

logger = logging.getLogger('gpu-worker')

class BlueprintS3Uploader:
    """100% BLUEPRINT-COMPLIANT: Uploads segments FIRST, then playlist"""
    
    def __init__(self, stories_bucket: str, region: str = "us-east-1"):
        self.s3 = boto3.client('s3', region_name=region)
        self.bucket = stories_bucket
        self.region = region
        
        # Track upload state per story
        self.story_state = {}  # story_id -> {'segments_uploaded': set(), 'playlist_uploaded': bool}
        self.state_lock = threading.Lock()
        
        # Upload queue with strict ordering
        self.upload_queue = defaultdict(deque)
        self.queue_lock = threading.Lock()
        
        # Upload workers (ONE per story for sequential uploads)
        self.upload_workers = {}
        self.worker_lock = threading.Lock()
        
        # Blueprint headers
        self.segment_headers = {
            'ContentType': 'video/mp4',
            'CacheControl': 'public, max-age=31536000, immutable'  # 1 year, immutable
        }
        
        self.playlist_headers = {
            'ContentType': 'application/vnd.apple.mpegurl',
            'CacheControl': 'public, max-age=3, stale-while-revalidate=30'  # 3s + 30s stale
        }
        
        logger.info(f"✅ BLUEPRINT S3 Uploader initialized: {stories_bucket}")
    
    # ============ BLUEPRINT: SEGMENTS FIRST ============
    
    def upload_segment(self, story_id: str, segment_path: Path, segment_num: int) -> bool:
        """
        BLUEPRINT: Upload segment FIRST with correct headers
        Returns: True if successful
        """
        try:
            if not segment_path.exists():
                logger.error(f"❌ Segment not found: {segment_path}")
                return False
            
            s3_key = f"stories/{story_id}/audio_{segment_num:03d}.m4s"
            
            # Check if already uploaded (idempotency)
            if self._segment_exists(story_id, segment_num):
                logger.debug(f"⏭️ Segment already uploaded: {s3_key}")
                with self.state_lock:
                    if story_id not in self.story_state:
                        self.story_state[story_id] = {'segments_uploaded': set(), 'playlist_uploaded': False}
                    self.story_state[story_id]['segments_uploaded'].add(segment_num)
                return True
            
            # Upload with blueprint headers
            self.s3.upload_file(
                str(segment_path),
                self.bucket,
                s3_key,
                ExtraArgs=self.segment_headers
            )
            
            # Update state
            with self.state_lock:
                if story_id not in self.story_state:
                    self.story_state[story_id] = {'segments_uploaded': set(), 'playlist_uploaded': False}
                self.story_state[story_id]['segments_uploaded'].add(segment_num)
            
            logger.info(f"📤 Uploaded segment: {s3_key}")
            return True
            
        except Exception as e:
            logger.error(f"❌ Failed to upload segment {segment_num} for {story_id}: {e}")
            return False
    
    # ============ BLUEPRINT: THEN PLAYLIST ============
    
    def update_playlist(self, story_id: str, playlist_path: Path) -> bool:
        """
        BLUEPRINT: Upload playlist AFTER segments are uploaded
        Returns: True if successful
        """
        try:
            if not playlist_path.exists():
                logger.error(f"❌ Playlist not found: {playlist_path}")
                return False
            
            s3_key = f"stories/{story_id}/playlist.m3u8"
            
            # Verify at least one segment is uploaded before playlist
            with self.state_lock:
                story_state = self.story_state.get(story_id, {})
                segments_uploaded = story_state.get('segments_uploaded', set())
                
                if not segments_uploaded:
                    logger.error(f"❌ No segments uploaded for {story_id}, cannot upload playlist")
                    return False
            
            # Upload with blueprint headers
            self.s3.upload_file(
                str(playlist_path),
                self.bucket,
                s3_key,
                ExtraArgs=self.playlist_headers
            )
            
            # Update state
            with self.state_lock:
                if story_id not in self.story_state:
                    self.story_state[story_id] = {'segments_uploaded': set(), 'playlist_uploaded': False}
                self.story_state[story_id]['playlist_uploaded'] = True
            
            logger.info(f"📋 Updated playlist: {s3_key}")
            return True
            
        except Exception as e:
            logger.error(f"❌ Failed to update playlist for {story_id}: {e}")
            return False
    
    # ============ BLUEPRINT: HLS CONTRACT VERIFICATION ============
    
    def verify_hls_contract(self, story_id: str) -> bool:
        """Verify HLS contract is valid (segments exist before playlist)"""
        try:
            # Check if playlist exists
            playlist_key = f"stories/{story_id}/playlist.m3u8"
            
            try:
                self.s3.head_object(Bucket=self.bucket, Key=playlist_key)
                playlist_exists = True
            except self.s3.exceptions.ClientError:
                playlist_exists = False
            
            # Check if any segments exist
            segments_exist = False
            response = self.s3.list_objects_v2(
                Bucket=self.bucket,
                Prefix=f"stories/{story_id}/audio_",
                MaxKeys=1
            )
            
            if 'Contents' in response and len(response['Contents']) > 0:
                segments_exist = True
            
            # BLUEPRINT RULE: Playlist should only exist if segments exist
            if playlist_exists and not segments_exist:
                logger.error(f"❌ HLS CONTRACT VIOLATION: Playlist exists but no segments for {story_id}")
                return False
            
            # BLUEPRINT RULE: Segments should exist before playlist
            if segments_exist and not playlist_exists:
                logger.warning(f"⚠️ HLS CONTRACT WARNING: Segments exist but no playlist for {story_id}")
                return True  # This is OK, playlist will be added
            
            if playlist_exists and segments_exist:
                logger.info(f"✅ HLS contract valid for {story_id}")
                return True
            
            logger.warning(f"⚠️ No HLS content found for {story_id}")
            return False
            
        except Exception as e:
            logger.error(f"❌ HLS contract verification failed for {story_id}: {e}")
            return False
    
    # ============ BLUEPRINT: SEQUENTIAL UPLOAD QUEUE ============
    
    def queue_sequential_upload(self, story_id: str, upload_tasks: List[Tuple[str, Path, int]]):
        """
        Queue upload tasks for sequential execution
        tasks: List of ('segment'/'playlist', path, segment_num)
        """
        with self.queue_lock:
            for task_type, path, segment_num in upload_tasks:
                self.upload_queue[story_id].append((task_type, path, segment_num))
            
            logger.info(f"📥 Queued {len(upload_tasks)} uploads for {story_id}")
            
            # Start upload worker if not already running
            self._start_upload_worker(story_id)
    
    def _start_upload_worker(self, story_id: str):
        """Start sequential upload worker for a story"""
        with self.worker_lock:
            if story_id in self.upload_workers:
                return
            
            def worker():
                logger.info(f"🔄 Starting sequential upload worker for {story_id}")
                
                while True:
                    # Get next task
                    with self.queue_lock:
                        if not self.upload_queue[story_id]:
                            # No more tasks, stop worker
                            with self.worker_lock:
                                if story_id in self.upload_workers:
                                    del self.upload_workers[story_id]
                            logger.info(f"✅ Upload worker finished for {story_id}")
                            break
                        
                        task_type, path, segment_num = self.upload_queue[story_id][0]
                    
                    # Execute task
                    success = False
                    if task_type == 'segment':
                        success = self.upload_segment(story_id, path, segment_num)
                    elif task_type == 'playlist':
                        success = self.update_playlist(story_id, path)
                    
                    # Remove task if successful
                    if success:
                        with self.queue_lock:
                            if self.upload_queue[story_id] and self.upload_queue[story_id][0] == (task_type, path, segment_num):
                                self.upload_queue[story_id].popleft()
                    else:
                        # Retry after delay
                        logger.warning(f"⚠️ Upload failed, retrying in 2s: {story_id}")
                        time.sleep(2)
                
            # Start worker thread
            worker_thread = threading.Thread(target=worker, daemon=True, name=f"upload-{story_id}")
            worker_thread.start()
            self.upload_workers[story_id] = worker_thread
    
    # ============ BLUEPRINT: INIT SEGMENT ============
    
    def upload_init_segment(self, story_id: str, init_path: Path) -> bool:
        """Upload init.mp4 segment"""
        try:
            if not init_path.exists():
                logger.error(f"❌ Init segment not found: {init_path}")
                return False
            
            s3_key = f"stories/{story_id}/init.mp4"
            
            self.s3.upload_file(
                str(init_path),
                self.bucket,
                s3_key,
                ExtraArgs=self.segment_headers  # Same headers as segments
            )
            
            logger.info(f"📤 Uploaded init segment: {s3_key}")
            return True
            
        except Exception as e:
            logger.error(f"❌ Failed to upload init segment for {story_id}: {e}")
            return False
    
    # ============ BLUEPRINT: BATCH UPLOADS ============
    
    def upload_story_hls(self, story_id: str, story_dir: Path, current_sequence: int = 0) -> Dict:
        """
        BLUEPRINT: Upload all HLS components in correct order
        1. init.mp4
        2. segments (in order)
        3. playlist.m3u8 (LAST)
        """
        try:
            if not story_dir.exists():
                return {'success': False, 'error': 'Story directory not found'}
            
            upload_results = {
                'success': True,
                'init_uploaded': False,
                'segments_uploaded': 0,
                'playlist_uploaded': False,
                'hls_contract_valid': False
            }
            
            # 1. Upload init.mp4 if exists
            init_path = story_dir / 'init.mp4'
            if init_path.exists():
                upload_results['init_uploaded'] = self.upload_init_segment(story_id, init_path)
            
            # 2. Find and sort segments
            segment_files = []
            for segment_file in story_dir.glob('audio_*.m4s'):
                try:
                    segment_num = int(segment_file.stem.split('_')[1])
                    if segment_num > current_sequence:  # Skip already processed
                        segment_files.append((segment_num, segment_file))
                except (ValueError, IndexError):
                    continue
            
            # Sort by segment number
            segment_files.sort(key=lambda x: x[0])
            
            # 3. Queue segments for upload
            upload_tasks = []
            for segment_num, segment_path in segment_files:
                upload_tasks.append(('segment', segment_path, segment_num))
            
            # 4. Queue playlist LAST
            playlist_path = story_dir / 'playlist.m3u8'
            if playlist_path.exists():
                upload_tasks.append(('playlist', playlist_path, 0))
            
            # 5. Start sequential upload
            if upload_tasks:
                self.queue_sequential_upload(story_id, upload_tasks)
                upload_results['segments_uploaded'] = len([t for t in upload_tasks if t[0] == 'segment'])
                upload_results['playlist_uploaded'] = any(t[0] == 'playlist' for t in upload_tasks)
            
            # 6. Verify HLS contract
            upload_results['hls_contract_valid'] = self.verify_hls_contract(story_id)
            
            logger.info(f"📤 HLS upload queued for {story_id}: {upload_results}")
            return upload_results
            
        except Exception as e:
            logger.error(f"❌ Failed to upload HLS for {story_id}: {e}")
            return {'success': False, 'error': str(e)}
    
    # ============ BLUEPRINT: IDEMPOTENCY ============
    
    def _segment_exists(self, story_id: str, segment_num: int) -> bool:
        """Check if segment already exists in S3"""
        try:
            s3_key = f"stories/{story_id}/audio_{segment_num:03d}.m4s"
            self.s3.head_object(Bucket=self.bucket, Key=s3_key)
            return True
        except self.s3.exceptions.ClientError as e:
            if e.response['Error']['Code'] == '404':
                return False
            raise
    
    def load_existing_segments(self, story_id: str) -> Set[int]:
        """Load already uploaded segments for resume capability"""
        existing_segments = set()
        
        try:
            response = self.s3.list_objects_v2(
                Bucket=self.bucket,
                Prefix=f"stories/{story_id}/audio_"
            )
            
            if 'Contents' in response:
                for obj in response['Contents']:
                    filename = Path(obj['Key']).name
                    if filename.startswith('audio_') and filename.endswith('.m4s'):
                        try:
                            segment_num = int(filename.split('_')[1].split('.')[0])
                            existing_segments.add(segment_num)
                        except (ValueError, IndexError):
                            continue
            
            logger.info(f"📥 Loaded {len(existing_segments)} existing segments for {story_id}")
            return existing_segments
            
        except Exception as e:
            logger.warning(f"⚠️ Failed to load existing segments: {e}")
            return set()
    
    # ============ BLUEPRINT: FINAL AUDIO ============
    
    def upload_final_audio(self, story_id: str, final_path: Path, format: str = "m4a") -> bool:
        """Upload final audio file (optional per blueprint)"""
        try:
            if not final_path.exists():
                logger.error(f"❌ Final audio not found: {final_path}")
                return False
            
            s3_key = f"stories/{story_id}/final/story.{format}"
            
            # Create final directory
            dir_key = f"stories/{story_id}/final/"
            try:
                self.s3.put_object(Bucket=self.bucket, Key=dir_key, Body=b'')
            except:
                pass  # Directory might already exist
            
            # Upload with appropriate headers
            headers = {
                'ContentType': f'audio/{format}' if format != 'm4a' else 'audio/mp4',
                'CacheControl': 'public, max-age=86400'  # 1 day for final files
            }
            
            self.s3.upload_file(str(final_path), self.bucket, s3_key, ExtraArgs=headers)
            
            logger.info(f"✅ Uploaded final audio: {s3_key}")
            return True
            
        except Exception as e:
            logger.error(f"❌ Failed to upload final audio for {story_id}: {e}")
            return False
    
    # ============ BLUEPRINT: MONITORING ============
    
    def get_upload_status(self, story_id: str) -> Dict:
        """Get current upload status for a story"""
        with self.state_lock:
            state = self.story_state.get(story_id, {'segments_uploaded': set(), 'playlist_uploaded': False})
            
            with self.queue_lock:
                queue_size = len(self.upload_queue.get(story_id, []))
            
            return {
                'story_id': story_id,
                'segments_uploaded': len(state['segments_uploaded']),
                'playlist_uploaded': state['playlist_uploaded'],
                'upload_queue_size': queue_size,
                'upload_worker_active': story_id in self.upload_workers,
                'hls_contract_valid': self.verify_hls_contract(story_id)
            }
    
    def wait_for_uploads(self, story_id: str, timeout: int = 30) -> bool:
        """Wait for all queued uploads to complete"""
        start_time = time.time()
        
        while time.time() - start_time < timeout:
            with self.queue_lock:
                if not self.upload_queue.get(story_id):
                    return True
            
            time.sleep(0.5)
        
        logger.warning(f"⚠️ Upload timeout for {story_id}")
        return False
    
    def get_stats(self) -> Dict:
        """Get overall upload statistics"""
        with self.state_lock:
            with self.queue_lock:
                with self.worker_lock:
                    return {
                        'total_stories': len(self.story_state),
                        'stories_with_uploads': len(self.upload_queue),
                        'active_upload_workers': len(self.upload_workers),
                        'total_queued_uploads': sum(len(q) for q in self.upload_queue.values()),
                        'bucket': self.bucket,
                        'region': self.region
                    }
    
    def shutdown(self):
        """Graceful shutdown"""
        logger.info("🔴 Shutting down BlueprintS3Uploader...")
        
        # Wait for active uploads
        for story_id in list(self.upload_workers.keys()):
            self.wait_for_uploads(story_id, timeout=10)
        
        logger.info("✅ BlueprintS3Uploader shutdown complete")