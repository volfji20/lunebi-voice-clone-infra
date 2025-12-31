#!/usr/bin/env python3
"""
🚀 MAIN.PY - Blueprint GPU Worker (100% Blueprint Compliant)
Production worker for Lunebi Voice Cloning
"""

import os
import sys
import time
import signal
import logging
import threading
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional

# Blueprint: Set TTS environment variables (from Packer)
os.environ['TTS_HOME'] = '/opt/voiceclone/.tts_cache'
os.environ['COQUI_TOS_AGREED'] = '1'

# Setup logging FIRST (before any imports)
def setup_logging():
    """Safe logging setup that won't crash"""
    try:
        # Use directory from Packer config: /var/log/voiceclone
        log_dir = Path('/var/log/voiceclone')
        log_dir.mkdir(parents=True, exist_ok=True)
        
        # Basic configuration
        logging.basicConfig(
            level=logging.INFO,
            format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
            handlers=[
                logging.StreamHandler(),  # Console
                logging.FileHandler(log_dir / 'worker.log')  # File
            ]
        )
        return True
    except Exception as e:
        # Fallback to console only
        logging.basicConfig(
            level=logging.INFO,
            format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
        )
        logging.error(f"Failed to setup file logging: {e}")
        return False

setup_logging()
logger = logging.getLogger('voiceclone-worker')

# Now import modules
try:
    # Add src directory to path (from Packer: files are in /opt/voiceclone/src/)
    sys.path.insert(0, '/opt/voiceclone')
    sys.path.insert(0, '/opt/voiceclone/src')
    
    # Import blueprint modules
    from src.tts_engine import ProductionTTSEngine
    from src.sqs_poller import ProductionSQSWorker, create_production_sqs_worker
    from src.audio_pipeline import create_audio_pipeline
    from src.s3_uploader import create_blueprint_s3_uploader
    from src.ddb_client import create_ddb_client
    from src.utils.idempotency import create_idempotency_manager
    from src.utils.resume import create_spot_resume_handler
    
    IMPORTS_READY = True
    logger.info("✅ All modules imported successfully")
    
except ImportError as e:
    logger.error(f"❌ Failed to import modules: {e}")
    logger.error("Make sure files are in /opt/voiceclone/src/")
    IMPORTS_READY = False
    # Exit if critical modules missing
    sys.exit(1)

class BlueprintGPUWorker:
    """100% Blueprint: Production GPU worker"""
    
    def __init__(self):
        self.running = True
        
        # Load configuration from environment (set by systemd)
        self.config = self._load_config()
        
        # Components
        self.tts_engine = None
        self.sqs_worker = None
        self.s3_uploader = None
        self.ddb_client = None
        self.idempotency = None
        self.spot_resume = None
        
        # State
        self.active_pipelines = {}
        self.pipeline_lock = threading.RLock()
        self.metrics = {
            'stories_started': 0,
            'sentences_synthesized': 0,
            'ttfa_values': []  # Blueprint: TTFA tracking
        }
        self.story_state = {}
        
        logger.info("Blueprint GPU Worker initialized")
    
    def _update_story_state(self, story_id, seq, is_final_from_message=False):
        if story_id not in self.story_state:
            self.story_state[story_id] = {
                'max_seq': seq,
                'received_final': is_final_from_message
            }
        else:
            self.story_state[story_id]['max_seq'] = max(
                self.story_state[story_id]['max_seq'], seq
            )
            if is_final_from_message:
                self.story_state[story_id]['received_final'] = True
        
        # Determine if this should be final for pipeline
        # Only mark as final if we've received the final flag AND this is the max seq
        should_be_final = (
            self.story_state[story_id].get('received_final', False) and
            seq == self.story_state[story_id]['max_seq']
        )
        
        return should_be_final
    
    def _load_config(self) -> Dict:
        """Load configuration from environment"""
        config = {
            # Required AWS resources (from systemd EnvironmentFile)
            'AWS_REGION': os.getenv('AWS_REGION', 'us-east-1'),
            'AWS_ACCOUNT_ID': os.getenv('AWS_ACCOUNT_ID', '579897422848'),
            
            # Resource Names (from Terraform)
            'VOICES_TABLE_NAME': os.getenv(
                'VOICES_TABLE_NAME',
                'lunebi-prod-us-east-1-voices'
            ),
            'STORIES_TABLE_NAME': os.getenv(
                'STORIES_TABLE_NAME',
                'lunebi-prod-us-east-1-stories'
            ),
            'STORIES_BUCKET': os.getenv(
                'S3_BUCKET_NAME',
                'voiceclone-stories-prod-us-east-1'
            ),
            'SQS_QUEUE_URL': os.getenv(
                'SQS_QUEUE_URL',
                'https://sqs.us-east-1.amazonaws.com/579897422848/lunebi-prod-us-east-1-story-tasks'
            ),
            
            # TTS configuration (from Packer)
            'MODEL_PATH': os.getenv('TTS_MODEL_PATH', '/opt/voiceclone/.tts_cache'),
            'EBS_MOUNT_POINT': os.getenv('EBS_MOUNT_POINT', '/mnt/ebs'),
            'SAMPLE_RATE': 24000,
            'SEGMENT_DURATION': 1.0,
            
            # Concurrency (detect GPU type)
            'MAX_CONCURRENT_STORIES': int(os.getenv('MAX_CONCURRENT_STORIES', '2')),
        }
        
        # Validate required config
        required = ['SQS_QUEUE_URL', 'STORIES_BUCKET', 'VOICES_TABLE_NAME', 'STORIES_TABLE_NAME']
        for key in required:
            if not config[key]:
                logger.error(f"❌ Missing required config: {key}")
                logger.error("Set in /etc/voiceclone/config.env or instance user-data")
                raise ValueError(f"Missing required config: {key}")
        
        logger.info(f"✅ Config loaded: {config['AWS_REGION']}, queue: {config['SQS_QUEUE_URL'].split('/')[-1]}")
        return config
    
    def _get_gpu_concurrency(self) -> int:
        """Detect GPU type for concurrency limits"""
        try:
            import torch
            if torch.cuda.is_available():
                gpu_name = torch.cuda.get_device_name(0).lower()
                if 'l4' in gpu_name:
                    return 4  # L4: 2-4 stories
                elif 't4' in gpu_name:
                    return 2  # T4: 1-2 stories
                elif 'a10g' in gpu_name:
                    return 3  # A10G: 2-3 stories
        except:
            pass
        return 2  # Default
    
    def initialize(self):
        """Initialize blueprint components"""
        logger.info("🚀 Initializing Blueprint GPU worker...")
        
        try:
            # 1. Initialize DDB client
            logger.info("📊 Initializing DDB client...")
            self.ddb_client = create_ddb_client(
                voices_table=self.config['VOICES_TABLE_NAME'],
                stories_table=self.config['STORIES_TABLE_NAME'],
                region=self.config['AWS_REGION']
            )
            
            # 2. Initialize TTS engine (model pre-downloaded by Packer)
            logger.info("🤖 Initializing TTS engine...")
            self.tts_engine = ProductionTTSEngine(
                cache_size=int(os.getenv('TTS_CACHE_SIZE', '200')),
                gpu_device='cuda:0'  # Use GPU if available
            )
            
            if not self.tts_engine.initialize(
                model_path=self.config['MODEL_PATH'],
                dynamodb_client=self.ddb_client.dynamodb,
                voices_table_name=self.config['VOICES_TABLE_NAME']
            ):
                raise RuntimeError("TTS engine initialization failed")
            
            # 3. Initialize SQS worker
            logger.info("📨 Initializing SQS worker...")
            self.sqs_worker = create_production_sqs_worker(
                self.config['SQS_QUEUE_URL']
            )
            
            # 4. Initialize S3 uploader
            logger.info("☁️ Initializing S3 uploader...")
            self.s3_uploader = create_blueprint_s3_uploader(
                self.config['STORIES_BUCKET']
            )
            
            # 5. Initialize idempotency manager
            logger.info("🔑 Initializing idempotency manager...")
            self.idempotency = create_idempotency_manager(
                self.config['STORIES_BUCKET']
            )
            
            # 6. Initialize spot resume handler
            logger.info("⚡ Initializing spot resume handler...")
            self.spot_resume = create_spot_resume_handler(self.ddb_client)
            
            # Log system info
            self._log_system_info()
            
            logger.info("✅ Blueprint worker initialized successfully")
            
        except Exception as e:
            logger.error(f"❌ Initialization failed: {e}")
            import traceback
            logger.error(traceback.format_exc())
            raise
    
    def _log_system_info(self):
        """Log system and GPU information"""
        try:
            import torch
            if torch.cuda.is_available():
                gpu_name = torch.cuda.get_device_name(0)
                gpu_memory = torch.cuda.get_device_properties(0).total_memory / (1024**3)
                logger.info(f"🎮 GPU: {gpu_name} ({gpu_memory:.1f}GB)")
                
                # Set concurrency based on GPU
                concurrency = self._get_gpu_concurrency()
                self.config['MAX_CONCURRENT_STORIES'] = concurrency
                logger.info(f"📈 Concurrency: {concurrency} stories/GPU")
            else:
                logger.warning("⚠️ No GPU available, running on CPU")
                self.config['MAX_CONCURRENT_STORIES'] = 1
        except:
            logger.warning("⚠️ Could not detect GPU")
    
    def process_story_sentence(self, message: Dict) -> bool:
        """Process single story sentence with blueprint requirements"""
        try:
            story_id = message['story_id']
            seq = message['seq']
            text = message['text']
            voice_id = message['voice_id']
            lang = message.get('lang', 'en')
            params = message.get('params', {})
            
            # BLUEPRINT: Check resume point
            if seq == 1:
                resume_point = self.spot_resume.get_resume_point(story_id)
                if resume_point > 1 and seq < resume_point:
                    logger.debug(f"⏭️ Skip {story_id}:{seq} (resume from {resume_point})")
                    return True
            
            # BLUEPRINT: Generate idempotency key
            idempotency_key = self.idempotency.generate_key(
                story_id, seq, text, voice_id,
                params.get('speed', 1.0),
                params.get('format', 'aac')
            )
            
            # BLUEPRINT: Idempotency check
            if not self.idempotency.should_process(story_id, seq, idempotency_key):
                logger.debug(f"⏭️ Idempotent skip {story_id}:{seq}")
                return True
            
            # BLUEPRINT: Track TTFA for first sentence
            start_time = time.time()
            if seq == 1:
                self.metrics['stories_started'] += 1
                logger.info(f"🚀 Starting story {story_id} (TTFA target <1s)")
            
            # BLUEPRINT: Synthesize audio
            audio_array = self.tts_engine.synthesize(
                text=text,
                voice_id=voice_id,
                language=lang,
                speed=params.get('speed', 1.0)
            )
            
            # 🎯 MILESTONE 4 FIX: Determine correct is_final using story tracking
            is_final_from_message = params.get('is_final', False)
            
            # Use story tracking to determine actual is_final
            should_be_final = self._update_story_state(
                story_id, seq, is_final_from_message
            )
            
            # Log if we're adjusting the is_final flag
            if is_final_from_message != should_be_final:
                logger.info(
                    f"🔧 Story tracking: message.is_final={is_final_from_message}, "
                    f"pipeline.is_final={should_be_final}"
                )
            
            # Use the tracked is_final value
            is_final = should_be_final
            
            # BLUEPRINT: Convert to PCM (24kHz mono s16le)
            import numpy as np
            audio_array = (audio_array * 32767).astype(np.int16)
            pcm_data = audio_array.tobytes()

            # ✅ DEBUG: Verify conversion
            logger.debug(f"🎵 Audio conversion: float32[{len(audio_array)}] → bytes[{len(pcm_data)}]")
                        
            # BLUEPRINT: Get or create pipeline (one per story)
            with self.pipeline_lock:
                if story_id not in self.active_pipelines:
                    pipeline = create_audio_pipeline(
                        story_id,
                        self.config['EBS_MOUNT_POINT']
                    )
                    self.active_pipelines[story_id] = pipeline
            
            # BLUEPRINT: Feed to continuous ffmpeg process
            pipeline = self.active_pipelines[story_id]
            pipeline.feed_audio(pcm_data, seq, is_final)
            
            # BLUEPRINT: Upload segments → playlist in order
            self._upload_segments(story_id, pipeline)
            
            # BLUEPRINT: Update progress
            processing_time = time.time() - start_time
            self.ddb_client.update_story_progress(
                story_id, seq, 'streaming', self.config['AWS_REGION']
            )
            
            self.idempotency.mark_hash_processed(idempotency_key)
            
            # BLUEPRINT: Track TTFA
            if seq == 1:
                ttfa_ms = processing_time * 1000
                self.metrics['ttfa_values'].append(ttfa_ms)
                logger.info(f"🎯 TTFA: {ttfa_ms:.0f}ms for {story_id}")
            
            self.metrics['sentences_synthesized'] += 1
            
            # BLUEPRINT: Handle story completion
            if is_final:
                self._complete_story(story_id, pipeline)
            
            return True
            
        except Exception as e:
            logger.error(f"❌ Processing failed: {e}")
            import traceback
            logger.error(traceback.format_exc())
            return False
    
    def _upload_segments(self, story_id: str, pipeline):
        """BLUEPRINT: Upload segments → playlist in correct order"""
        try:
            # Upload init segment
            init_path = pipeline.get_init_path()
            if init_path:
                self.s3_uploader.upload_init_segment(story_id, init_path)
            
            # Upload latest segment
            segment_path = pipeline.get_latest_segment()
            if segment_path:
                self.s3_uploader.upload_segment(story_id, segment_path)
            
            # Update playlist (after segments)
            playlist_path = pipeline.get_playlist_path()
            if playlist_path:
                self.s3_uploader.update_playlist(story_id, playlist_path)
                
        except Exception as e:
            logger.error(f"❌ Upload error: {e}")
    
    def _complete_story(self, story_id: str, pipeline):
        """BLUEPRINT: Complete story processing"""
        try:
            logger.info(f"🏁 Completing story {story_id}")
            
            
            # Update DDB
            self.ddb_client.mark_story_complete(story_id)
            
            # Cleanup
            with self.pipeline_lock:
                if story_id in self.active_pipelines:
                    del self.active_pipelines[story_id]
            
            logger.info(f"✅ Story completed: {story_id}")
            
        except Exception as e:
            logger.error(f"❌ Completion error: {e}")
    
    def _cleanup_pipelines(self):
        """Cleanup unhealthy pipelines"""
        with self.pipeline_lock:
            to_remove = []
            for story_id, pipeline in self.active_pipelines.items():
                if not pipeline.is_healthy():
                    logger.warning(f"Removing unhealthy pipeline {story_id}")
                    pipeline.shutdown()
                    to_remove.append(story_id)
            
            for story_id in to_remove:
                del self.active_pipelines[story_id]
    
    def run(self):
        """BLUEPRINT: Main processing loop with two-phase scheduler"""
        self.initialize()
        
        logger.info("🔄 Starting processing loop...")
        
        while self.running:
            try:
                # BLUEPRINT: Receive messages (long polling 20s)
                messages = self.sqs_worker.receive_messages(max_messages=10)
                
                for message in messages:
                    parsed = self.sqs_worker.parse_message(message)
                    if not parsed:
                        continue
                    
                    story_id = parsed['story_id']
                    self.sqs_worker.add_message_to_scheduler(story_id, parsed)
                
                # BLUEPRINT: Get next story (two-phase scheduler)
                next_story = self.sqs_worker.get_next_story_to_process()
                if not next_story:
                    time.sleep(0.1)
                    continue
                
                story_id, message_data = next_story
                
                # Process the sentence
                success = self.process_story_sentence(message_data)
                
                if success:
                    # Update scheduler and delete message
                    self.sqs_worker.complete_render(
                        story_id, 
                        message_data, 
                        synthesis_time=0.5,
                        ttfa_ms=200 if message_data['seq'] == 1 else None
                    )
                    self.sqs_worker.delete_message(message_data)
                else:
                    # Release for retry
                    self.sqs_worker.release_message(message_data, delay_seconds=10)
                
                # Periodic cleanup
                if self.metrics['sentences_synthesized'] % 20 == 0:
                    self._cleanup_pipelines()
                
                # Check for spot termination
                if self.spot_resume.check_spot_termination():
                    logger.warning("🚨 Spot termination detected")
                    break
                
            except KeyboardInterrupt:
                logger.info("Keyboard interrupt received")
                break
            except Exception as e:
                logger.error(f"Loop error: {e}")
                import traceback
                logger.error(traceback.format_exc())
                time.sleep(1)
        
        logger.info("Processing loop stopped")
    
    def shutdown(self):
        """BLUEPRINT: Graceful shutdown"""
        logger.info("🔴 Shutting down...")
        self.running = False
        
        # Shutdown components
        if self.tts_engine:
            self.tts_engine.shutdown()
        
        if self.sqs_worker:
            self.sqs_worker.shutdown()
        
        # Cleanup pipelines
        with self.pipeline_lock:
            for pipeline in self.active_pipelines.values():
                try:
                    pipeline.shutdown()
                except:
                    pass
            self.active_pipelines.clear()
        
        # Report metrics
        self._report_metrics()
        
        logger.info("✅ Shutdown complete")
    
    def _report_metrics(self):
        """Report final SLO metrics"""
        if self.metrics['ttfa_values']:
            ttfa_values = self.metrics['ttfa_values']
            avg_ttfa = sum(ttfa_values) / len(ttfa_values)
            p95_ttfa = sorted(ttfa_values)[int(len(ttfa_values) * 0.95)]
            
            logger.info("📊 BLUEPRINT FINAL METRICS:")
            logger.info(f"   Stories: {self.metrics['stories_started']}")
            logger.info(f"   Sentences: {self.metrics['sentences_synthesized']}")
            logger.info(f"   Avg TTFA: {avg_ttfa:.0f}ms")
            logger.info(f"   P95 TTFA: {p95_ttfa:.0f}ms")

def main():
    """Main entry point"""
    logger.info("""
    ╔══════════════════════════════════════════╗
    ║   🚀 VOICECLONE GPU WORKER v1.3          ║
    ║   100% Blueprint Compliant               ║
    ╚══════════════════════════════════════════╝
    """)
    
    # Log instance info
    try:
        import requests
        instance_id = requests.get(
            'http://169.254.169.254/latest/meta-data/instance-id',
            timeout=2
        ).text
        logger.info(f"Instance: {instance_id}")
    except:
        pass
    
    worker = None
    try:
        worker = BlueprintGPUWorker()
        
        # Signal handling
        def signal_handler(signum, frame):
            logger.info(f"Signal {signum} received")
            if worker:
                worker.shutdown()
            sys.exit(0)
        
        signal.signal(signal.SIGTERM, signal_handler)
        signal.signal(signal.SIGINT, signal_handler)
        
        # Run worker
        worker.run()
        
    except Exception as e:
        logger.error(f"💥 Worker failed: {e}")
        import traceback
        logger.error(traceback.format_exc())
        
        if worker:
            try:
                worker.shutdown()
            except:
                pass
        
        sys.exit(1)
    
    return 0

if __name__ == "__main__":
    sys.exit(main())