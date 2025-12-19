"""
Spot Interruption Handler with EBS Staging
Blueprint: Resume after Spot interruption using stories.last_seq_written
Blueprint: Staging writes on local EBS; watcher uploads in order
"""

import os
import time
import threading
import queue
import shutil
import logging
from pathlib import Path
from datetime import datetime

logger = logging.getLogger('voiceclone-worker')

# ============ EBS STAGING WATCHER ============

class EBSStagingWatcher:
    """BLUEPRINT: Staging writes on local EBS; watcher uploads in order"""
    
    def __init__(self, story_id: str, s3_uploader, spot_handler):
        self.story_id = story_id
        self.s3_uploader = s3_uploader
        self.spot_handler = spot_handler
        self.worker_id = spot_handler.get_instance_id()
        
        # BLUEPRINT: Staging writes on local EBS
        self.ebs_mount_point = os.environ.get('EBS_MOUNT_POINT', '/mnt/ebs')
        self.staging_dir = Path(self.ebs_mount_point) / "staging" / story_id
        self.completed_dir = Path(self.ebs_mount_point) / "completed" / story_id
        
        # Create directories
        self.staging_dir.mkdir(parents=True, exist_ok=True)
        self.completed_dir.mkdir(parents=True, exist_ok=True)
        
        # Upload queue for sequential processing
        self.upload_queue = queue.Queue()
        self.running = False
        self.upload_thread = None
        
        # Track uploaded segments
        self.uploaded_segments = set()
        self.lock = threading.Lock()
        
        logger.info(f"📁 EBS Staging initialized for {story_id}")
    
    def start(self):
        """Start the watcher thread"""
        self.running = True
        self.upload_thread = threading.Thread(
            target=self._upload_processor,
            daemon=True,
            name=f"ebs-watcher-{self.story_id}"
        )
        self.upload_thread.start()
        logger.info(f"👀 EBS watcher started for {self.story_id}")
    
    def _upload_processor(self):
        """BLUEPRINT: watcher uploads in order"""
        while self.running:
            try:
                # Get next upload task (blocks until available)
                task = self.upload_queue.get(timeout=1.0)
                file_path, segment_num, is_playlist = task
                
                # Wait for file to be completely written
                if self._wait_for_file_complete(file_path):
                    
                    if not is_playlist:
                        # Upload segment to S3
                        success = self.s3_uploader.upload_segment(
                            self.story_id, file_path, segment_num
                        )
                        
                        if success:
                            # Move to completed directory
                            completed_path = self.completed_dir / file_path.name
                            shutil.move(str(file_path), str(completed_path))
                            
                            with self.lock:
                                self.uploaded_segments.add(segment_num)
                            
                            # BLUEPRINT: Update last_seq_written in DynamoDB
                            self.spot_handler.update_story_progress(
                                self.story_id, 
                                segment_num, 
                                worker_id=self.worker_id
                            )
                            
                            logger.debug(f"✅ Uploaded segment {segment_num} for {self.story_id}")
                        else:
                            # Retry failed upload
                            logger.warning(f"⚠️ Upload failed, retrying segment {segment_num}")
                            self.upload_queue.put(task)
                            time.sleep(2)
                    
                    else:
                        # Upload playlist
                        success = self.s3_uploader.update_playlist(
                            self.story_id, file_path
                        )
                        
                        if success:
                            completed_path = self.completed_dir / file_path.name
                            shutil.move(str(file_path), str(completed_path))
                            logger.debug(f"✅ Uploaded playlist for {self.story_id}")
                        else:
                            logger.warning(f"⚠️ Playlist upload failed, retrying")
                            self.upload_queue.put(task)
                            time.sleep(2)
                
                self.upload_queue.task_done()
                
            except queue.Empty:
                continue
            except Exception as e:
                logger.error(f"❌ Upload processor error for {self.story_id}: {e}")
                time.sleep(1)
    
    def _wait_for_file_complete(self, file_path: Path, timeout=5.0):
        """Wait for file to be completely written to EBS"""
        start_time = time.time()
        last_size = -1
        stable_count = 0
        
        while time.time() - start_time < timeout:
            try:
                if not file_path.exists():
                    time.sleep(0.1)
                    continue
                
                current_size = file_path.stat().st_size
                if current_size == last_size:
                    stable_count += 1
                    if stable_count >= 2:  # Stable for 2 checks
                        return True
                else:
                    stable_count = 0
                    last_size = current_size
            except:
                pass
            time.sleep(0.1)
        
        logger.warning(f"⚠️ File write timeout: {file_path}")
        return file_path.exists()  # Return True if file exists, even if timeout
    
    def stage_segment(self, segment_data: bytes, segment_num: int) -> bool:
        """BLUEPRINT: Stage segment to local EBS"""
        try:
            # Write segment to EBS staging
            staging_path = self.staging_dir / f"audio_{segment_num:03d}.m4s"
            
            with open(staging_path, 'wb') as f:
                f.write(segment_data)
            
            # Queue for upload
            self.upload_queue.put((staging_path, segment_num, False))
            
            logger.debug(f"💾 Staged segment {segment_num} to EBS: {staging_path}")
            return True
            
        except Exception as e:
            logger.error(f"❌ Failed to stage segment {segment_num}: {e}")
            return False
    
    def stage_playlist(self, playlist_content: str) -> bool:
        """Stage playlist to EBS"""
        try:
            staging_path = self.staging_dir / "playlist.m3u8"
            
            with open(staging_path, 'w') as f:
                f.write(playlist_content)
            
            # Queue for upload
            self.upload_queue.put((staging_path, 0, True))
            
            return True
            
        except Exception as e:
            logger.error(f"❌ Failed to stage playlist: {e}")
            return False
    
    def get_uploaded_segments(self):
        """Get set of uploaded segments"""
        with self.lock:
            return self.uploaded_segments.copy()
    
    def check_staging_segments(self):
        """Check for segments in staging directory"""
        staging_segments = set()
        if self.staging_dir.exists():
            for seg_file in self.staging_dir.glob('audio_*.m4s'):
                try:
                    segment_num = int(seg_file.stem.split('_')[1])
                    staging_segments.add(segment_num)
                except:
                    continue
        return staging_segments
    
    def shutdown(self):
        """Graceful shutdown"""
        logger.debug(f"🔴 Shutting down EBS watcher for {self.story_id}")
        self.running = False
        
        if self.upload_thread:
            self.upload_thread.join(timeout=5.0)

# ============ SPOT INTERRUPTION HANDLER ============

class SpotInterruptionHandler:
    """BLUEPRINT: Resume after Spot interruption using stories.last_seq_written"""
    
    def __init__(self, ddb_client, s3_client, s3_uploader):
        """
        Args:
            ddb_client: DynamoDB client from ddb_client.py
            s3_client: S3 client
            s3_uploader: S3Uploader from s3_uploader.py
        """
        self.ddb = ddb_client
        self.s3 = s3_client
        self.s3_uploader = s3_uploader
        self.stories_bucket = os.environ['STORIES_BUCKET']
        
        # Worker coordination
        self.worker_lock = threading.Lock()
        self.active_workers = {}  # story_id -> worker_id
        
        # EBS watchers
        self.ebs_watchers = {}  # story_id -> EBSStagingWatcher
        self.watcher_lock = threading.Lock()
        
        # Instance info
        self.instance_id = self._get_instance_id()
        
        logger.info(f"🛡️ Spot Interruption Handler initialized")
    
    def _get_instance_id(self):
        """Get EC2 instance ID"""
        try:
            import requests
            response = requests.get(
                'http://169.254.169.254/latest/meta-data/instance-id',
                timeout=2
            )
            return response.text
        except:
            return f"worker-{os.getpid()}"
    
    def get_instance_id(self):
        """Public getter for instance ID"""
        return self.instance_id
    
    def check_spot_interruption(self):
        """Check if Spot interruption is imminent"""
        try:
            import requests
            response = requests.get(
                'http://169.254.169.254/latest/meta-data/spot/termination-time',
                timeout=2
            )
            if response.status_code == 200:
                termination_time = response.text
                logger.warning(f"🚨 SPOT INTERRUPTION DETECTED at {termination_time}")
                
                # Save checkpoints for all active stories
                self._save_checkpoints_before_termination()
                
                return True
        except:
            pass
        
        return False
    
    def _save_checkpoints_before_termination(self):
        """Save checkpoints for all active stories before termination"""
        logger.info("💾 Saving checkpoints before Spot termination...")
        
        with self.worker_lock:
            for story_id in list(self.active_workers.keys()):
                try:
                    # Get current progress from EBS watcher
                    watcher = self.ebs_watchers.get(story_id)
                    if watcher:
                        uploaded_segments = watcher.get_uploaded_segments()
                        last_seq = max(uploaded_segments) if uploaded_segments else 0
                        
                        # Update last_seq_written in DynamoDB
                        self.update_story_progress(
                            story_id, 
                            last_seq, 
                            worker_id=self.instance_id,
                            force_checkpoint=True
                        )
                        
                        logger.info(f"✅ Checkpoint saved for {story_id}: seq {last_seq}")
                except Exception as e:
                    logger.error(f"❌ Failed to save checkpoint for {story_id}: {e}")
    
    def get_or_create_watcher(self, story_id: str):
        """Get or create EBS staging watcher for a story"""
        with self.watcher_lock:
            if story_id not in self.ebs_watchers:
                if not self.s3_uploader:
                    logger.error("❌ Cannot create EBS watcher: s3_uploader not provided")
                    return None
                
                watcher = EBSStagingWatcher(
                    story_id=story_id,
                    s3_uploader=self.s3_uploader,
                    spot_handler=self
                )
                watcher.start()
                self.ebs_watchers[story_id] = watcher
                
                # Load existing segments from S3 for resume
                existing_segments = self._load_existing_s3_segments(story_id)
                with watcher.lock:
                    watcher.uploaded_segments.update(existing_segments)
                
                logger.info(f"📁 Created EBS watcher for {story_id}")
            
            return self.ebs_watchers[story_id]
    
    def stage_and_upload(self, story_id: str, segment_data: bytes, segment_num: int) -> bool:
        """BLUEPRINT COMPLETE: Stage to EBS, watcher uploads in order"""
        try:
            # Get EBS watcher for this story
            watcher = self.get_or_create_watcher(story_id)
            if not watcher:
                return False
            
            # Stage to EBS (watcher will automatically upload)
            return watcher.stage_segment(segment_data, segment_num)
            
        except Exception as e:
            logger.error(f"❌ Failed to stage segment {segment_num} for {story_id}: {e}")
            return False
    
    def stage_playlist(self, story_id: str, playlist_content: str) -> bool:
        """Stage playlist to EBS"""
        try:
            watcher = self.get_or_create_watcher(story_id)
            if not watcher:
                return False
            
            return watcher.stage_playlist(playlist_content)
            
        except Exception as e:
            logger.error(f"❌ Failed to stage playlist for {story_id}: {e}")
            return False
    
    def _load_existing_s3_segments(self, story_id):
        """Load already uploaded segments from S3"""
        existing_segments = set()
        
        try:
            prefix = f"stories/{story_id}/audio_"
            response = self.s3.list_objects_v2(
                Bucket=self.stories_bucket,
                Prefix=prefix,
                MaxKeys=1000
            )
            
            if 'Contents' in response:
                for obj in response['Contents']:
                    filename = obj['Key'].split('/')[-1]
                    if filename.startswith('audio_') and filename.endswith('.m4s'):
                        try:
                            seq = int(filename.split('_')[1].split('.')[0])
                            existing_segments.add(seq)
                        except:
                            continue
            
            logger.info(f"📥 Loaded {len(existing_segments)} existing segments from S3 for {story_id}")
            return existing_segments
            
        except Exception as e:
            logger.warning(f"⚠️ Failed to load S3 segments for {story_id}: {e}")
            return existing_segments
    
    def get_resume_point(self, story_id, worker_id):
        """BLUEPRINT: Resume after Spot interruption using stories.last_seq_written"""
        try:
            # Acquire story ownership
            if not self.acquire_story_ownership(story_id, worker_id):
                logger.warning(f"⏭️ Story {story_id} already owned by another worker")
                return {'status': 'already_processing', 'resume_from': 0}
            
            # BLUEPRINT: Get last_seq_written from DynamoDB
            last_seq = self.ddb.get_last_seq_written(story_id)
            
            if last_seq == 0:
                logger.info(f"🆕 New story: {story_id}")
                return {'status': 'new', 'resume_from': 0}
            
            # Check EBS staging for partial uploads
            watcher = self.ebs_watchers.get(story_id)
            ebs_segments = watcher.check_staging_segments() if watcher else set()
            
            # Verify S3 segments
            s3_segments = self._load_existing_s3_segments(story_id)
            
            # Calculate resume point
            resume_from = self._calculate_resume_point(last_seq, s3_segments, ebs_segments)
            
            resume_info = {
                'status': 'resuming',
                'resume_from': resume_from,
                'last_seq_written': last_seq,
                's3_segments_count': len(s3_segments),
                'ebs_staging_segments': len(ebs_segments),
                'worker_id': worker_id,
                'resume_gap': last_seq - resume_from
            }
            
            logger.info(f"🔄 RESUME PLAN for {story_id}:")
            logger.info(f"   • DynamoDB last_seq_written: {last_seq}")
            logger.info(f"   • S3 segments: {len(s3_segments)}")
            logger.info(f"   • EBS staging segments: {len(ebs_segments)}")
            logger.info(f"   • Resume from sequence: {resume_from}")
            logger.info(f"   • Segments to regenerate: {resume_info['resume_gap']}")
            
            return resume_info
            
        except Exception as e:
            logger.error(f"❌ Failed to get resume point for {story_id}: {e}")
            return {'status': 'error', 'resume_from': 0, 'error': str(e)}
    
    def _calculate_resume_point(self, last_seq_written, s3_segments, ebs_segments):
        """Calculate where to resume from"""
        if last_seq_written == 0:
            return 0
        
        # Start from last_seq_written and work backwards
        for seq in range(last_seq_written, -1, -1):
            if seq in s3_segments:
                # Segment exists in S3, resume from next one
                return seq + 1
        
        # No segments found in S3, check EBS staging
        if ebs_segments:
            min_ebs = min(ebs_segments)
            return min_ebs  # Resume from earliest EBS segment
        
        return 0  # Start from beginning
    
    def acquire_story_ownership(self, story_id, worker_id):
        """Coordinate worker handoff"""
        with self.worker_lock:
            current_owner = self.active_workers.get(story_id)
            
            if current_owner and current_owner != worker_id:
                return False
            
            self.active_workers[story_id] = worker_id
            logger.info(f"🔒 Worker {worker_id} acquired story {story_id}")
            return True
    
    def release_story_ownership(self, story_id, worker_id):
        """Release story ownership"""
        with self.worker_lock:
            if self.active_workers.get(story_id) == worker_id:
                del self.active_workers[story_id]
                logger.info(f"🔓 Worker {worker_id} released story {story_id}")
    
    def update_story_progress(self, story_id, last_seq_written, status="streaming", 
                              worker_id=None, force_checkpoint=False):
        """Update story progress with last_seq_written"""
        try:
            # Use DDB client to update story
            return self.ddb.update_story_progress(
                story_id=story_id,
                last_seq_written=last_seq_written,
                status=status,
                worker_id=worker_id,
                force_checkpoint=force_checkpoint
            )
        except Exception as e:
            logger.error(f"❌ Failed to update progress for {story_id}: {e}")
            return False
    
    def mark_story_complete(self, story_id, worker_id=None):
        """Mark story as complete"""
        try:
            if worker_id:
                self.release_story_ownership(story_id, worker_id)
            
            # Cleanup EBS watcher
            watcher = self.ebs_watchers.pop(story_id, None)
            if watcher:
                watcher.shutdown()
            
            # Use DDB client to mark complete
            return self.ddb.mark_story_complete(story_id)
            
        except Exception as e:
            logger.error(f"❌ Failed to mark story {story_id} complete: {e}")
            return False
    
    def shutdown(self):
        """Graceful shutdown of all watchers"""
        logger.info("🔴 Shutting down Spot Interruption Handler...")
        
        # Shutdown all EBS watchers
        for story_id, watcher in list(self.ebs_watchers.items()):
            try:
                watcher.shutdown()
            except:
                pass
        
        self.ebs_watchers.clear()
        
        logger.info("✅ Spot Interruption Handler shutdown complete")


# ============ FACTORY FUNCTION ============

def create_spot_interruption_handler(ddb_client, s3_client, s3_uploader):
    """Factory function to create SpotInterruptionHandler"""
    return SpotInterruptionHandler(
        ddb_client=ddb_client,
        s3_client=s3_client,
        s3_uploader=s3_uploader
    )