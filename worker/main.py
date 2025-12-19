#!/usr/bin/env python3
"""
🚀 MAIN.PY - Production Worker for Lunebi Voice Cloning + Instant Story Streaming
BLUEPRINT Version 1.3 (US now, EU ready) compliant

This is the main entry point for the GPU worker fleet that:
1. Pre-warms voice cache at boot (Blueprint: recent voice_id → embeddings/style in RAM)
2. Polls SQS for story generation tasks
3. Uses Two-phase round-robin scheduler
4. Implements idempotency and Spot interruption resilience
5. Streams HLS segments with <1s TTFA
6. Maintains 3s buffer per story

Supports both Test Mode (Spot-only, zero-idle) and Production Mode (SLO-driven)
"""
import os
import sys

# 🔴 CRITICAL: Set TTS environment variables BEFORE any imports
# This ensures TTS library uses our global path
os.environ['TTS_HOME'] = os.getenv('TTS_HOME', '/opt/voiceclone/.tts_cache')
os.environ['XDG_DATA_HOME'] = os.getenv('XDG_DATA_HOME', '/opt/voiceclone/.tts_cache')
os.environ['TTS_CACHE_DIR'] = os.getenv('TTS_CACHE_DIR', '/opt/voiceclone/.tts_cache')
os.environ['COQUI_TOS_AGREED'] = '1'
os.environ['HF_HUB_DISABLE_SYMLINKS_WARNING'] = '1'

import os
import sys
import time
import signal
import logging
import threading
import json
import boto3
from datetime import datetime
from pathlib import Path
from typing import Dict, Any, Optional, List
import traceback

# Add src directory to path
sys.path.append(os.path.join(os.path.dirname(__file__), 'src'))

from src.sqs_poller import ProductionSQSWorker, create_production_sqs_worker
from src.tts_engine import ProductionTTSEngine, create_production_tts_engine
from src.audio_pipeline import StoryFFmpegPipeline
from src.ddb_client import ProductionDynamoDBClient
from src.s3_uploader import BlueprintS3Uploader
from src.utils.health_check import get_health_status, simple_health_check
from src.utils.idempotency import IdempotencyManager
from src.utils.resume import create_spot_interruption_handler

# ============ CONFIGURATION ============

class ProductionConfig:
    """Production configuration matching Blueprint"""
    
    @staticmethod
    def from_environment():
        """Load configuration from environment variables"""
        config = {
            # AWS Configuration
            'AWS_REGION': os.getenv('AWS_REGION', 'us-east-1'),
            'AWS_ACCOUNT_ID': os.getenv('AWS_ACCOUNT_ID', '579897422848'),
            
            # Resource Names (from Terraform)
            'VOICES_TABLE': os.getenv(
                'VOICES_TABLE_NAME',
                'lunebi-prod-us-east-1-voices'
            ),
            'STORIES_TABLE': os.getenv(
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
            
            # GPU Configuration
            'GPU_TYPE': os.getenv('GPU_TYPE', 'auto'),
            'MAX_CONCURRENT_STORIES': int(os.getenv('MAX_CONCURRENT_STORIES', '3')),
            'MIN_CONCURRENT_STORIES': int(os.getenv('MIN_CONCURRENT_STORIES', '1')),
            
            # TTS Configuration
            'TTS_CACHE_SIZE': int(os.getenv('TTS_CACHE_SIZE', '200')),
            'TTS_PRELOAD_COUNT': int(os.getenv('TTS_PRELOAD_COUNT', '50')),
            'TTS_MODEL_PATH': os.getenv('TTS_MODEL_PATH', '/opt/voiceclone/.tts_cache'),
            
            # Audio Configuration (Blueprint: 24 kHz mono)
            'SAMPLE_RATE': 24000,
            'CHANNELS': 1,
            'SEGMENT_DURATION': 1.0,  # 1-second HLS segments
            
            # Operational Mode
            'OPERATION_MODE': os.getenv('OPERATION_MODE', 'production'),  # 'test' or 'production'
            'ENABLE_SPOT_INTERRUPTION_HANDLING': os.getenv('ENABLE_SPOT_INTERRUPTION_HANDLING', 'true').lower() == 'true',
            
            # Monitoring
            'HEALTH_CHECK_PORT': int(os.getenv('HEALTH_CHECK_PORT', '8080')),
            'METRICS_INTERVAL': int(os.getenv('METRICS_INTERVAL', '30')),
            
            # EBS Staging (Blueprint: staging writes on local EBS)
            'EBS_MOUNT_POINT': os.getenv('EBS_MOUNT_POINT', '/mnt/ebs'),
            'ENABLE_EBS_STAGING': os.getenv('ENABLE_EBS_STAGING', 'true').lower() == 'true',
            
            # Instance Metadata
            'INSTANCE_ID': os.getenv('INSTANCE_ID', 'unknown'),
            'ASG_NAME': os.getenv('ASG_NAME', 'unknown'),
            'DEPLOYMENT_ID': os.getenv('DEPLOYMENT_ID', 'unknown'),
            
            # Feature Flags
            'ENABLE_LL_HLS': os.getenv('ENABLE_LL_HLS', 'false').lower() == 'true',
            'ENABLE_CROSSFADES': os.getenv('ENABLE_CROSSFADES', 'true').lower() == 'true',
            'ENABLE_SILENCE_TRIMMING': os.getenv('ENABLE_SILENCE_TRIMMING', 'true').lower() == 'true',
        }
        
        # Set environment variables for child processes
        os.environ['ENABLE_LL_HLS'] = str(config['ENABLE_LL_HLS'])
        
        return config
    
    @staticmethod
    def validate(config: Dict[str, Any]):
        """Validate configuration"""
        required_vars = [
            'SQS_QUEUE_URL',
            'STORIES_BUCKET',
            'VOICES_TABLE',
            'STORIES_TABLE',
        ]
        
        missing = [var for var in required_vars if not config.get(var)]
        if missing:
            raise ValueError(f"Missing required environment variables: {missing}")
        
        # Validate directories exist
        if not Path(config['EBS_MOUNT_POINT']).exists():
            logging.warning(f"EBS mount point not found: {config['EBS_MOUNT_POINT']}")
        
        if not Path(config['TTS_MODEL_PATH']).exists():
            logging.warning(f"TTS model path not found: {config['TTS_MODEL_PATH']}")
        
        return True

# ============ LOGGING SETUP ============

def setup_logging():
    """Configure production logging"""
    log_level = os.getenv('LOG_LEVEL', 'INFO').upper()
    
    # Create logs directory
    logs_dir = Path('/var/log/voiceclone')
    logs_dir.mkdir(parents=True, exist_ok=True)
    
    # Configure logging
    logging.basicConfig(
        level=log_level,
        format='%(asctime)s - %(name)s - %(levelname)s - [%(threadName)s] - %(message)s',
        handlers=[
            logging.StreamHandler(),
            logging.FileHandler(logs_dir / f'worker_{datetime.now().strftime("%Y%m%d_%H%M%S")}.log'),
        ]
    )
    
    # Set specific loggers
    logging.getLogger('boto3').setLevel(logging.WARNING)
    logging.getLogger('botocore').setLevel(logging.WARNING)
    logging.getLogger('urllib3').setLevel(logging.WARNING)
    
    return logging.getLogger(__name__)

# ============ MAIN WORKER CLASS ============

class LunebiGPUWorker:
    """Main GPU worker that integrates all components"""
    
    def __init__(self, config: Dict[str, Any]):
        self.config = config
        self.logger = logging.getLogger('lunebi-worker')
        
        # State tracking
        self.running = True
        self.shutdown_requested = False
        self.initialized = False
        
        # Component references
        self.sqs_worker = None
        self.tts_engine = None
        self.ddb_client = None
        self.s3_uploader = None
        self.idempotency_manager = None
        self.spot_handler = None
        
        # Story pipelines (one per active story)
        self.active_pipelines: Dict[str, StoryFFmpegPipeline] = {}
        self.pipeline_lock = threading.RLock()
        
        # Performance metrics
        self.metrics = {
            'stories_processed': 0,
            'sentences_synthesized': 0,
            'total_ttfa_ms': [],
            'errors': 0,
            'start_time': time.time(),
        }
        
        # Background threads
        self.spot_check_thread = None
        self.metrics_thread = None
        self.health_server_thread = None
        
        self.logger.info("🚀 Lunebi GPU Worker Initializing...")
        self.logger.info(f"📋 Config: {json.dumps(config, indent=2, default=str)}")
    
    def initialize_components(self):
        """Initialize all components in correct order"""
        try:
            self.logger.info("🔧 Initializing components...")
            
            # 1. Initialize AWS clients
            region = self.config['AWS_REGION']
            s3_client = boto3.client('s3', region_name=region)
            
            # 2. Initialize DynamoDB client (CRITICAL: binary handling)
            self.ddb_client = ProductionDynamoDBClient(
                voices_table_name=self.config['VOICES_TABLE'],
                stories_table_name=self.config['STORIES_TABLE'],
                region=region
            )
            self.logger.info("✅ DynamoDB client initialized")
            
            # 3. Initialize S3 Uploader (Blueprint: segments → playlist)
            self.s3_uploader = BlueprintS3Uploader(
                stories_bucket=self.config['STORIES_BUCKET'],
                region=region
            )
            self.logger.info("✅ S3 Uploader initialized")
            
            # 4. Initialize Idempotency Manager (Blueprint: hash-based deduplication)
            self.idempotency_manager = IdempotencyManager(
                s3_client=s3_client,
                stories_bucket=self.config['STORIES_BUCKET'],
                model_version="xtts-v2"
            )
            self.logger.info("✅ Idempotency Manager initialized")
            
            # 5. Initialize Spot Interruption Handler (Blueprint: resume from last_seq_written)
            if self.config['ENABLE_SPOT_INTERRUPTION_HANDLING']:
                self.spot_handler = create_spot_interruption_handler(
                    ddb_client=self.ddb_client,
                    s3_client=s3_client,
                    s3_uploader=self.s3_uploader
                )
                self.logger.info("✅ Spot Interruption Handler initialized")
            
            # 6. Initialize TTS Engine (BLUEPRINT: Pre-warm cache at boot)
            self.tts_engine = create_production_tts_engine(
                voices_table_name=self.config['VOICES_TABLE'],
                cache_size=self.config['TTS_CACHE_SIZE'],
                preload_count=self.config['TTS_PRELOAD_COUNT'],
            )
            self.logger.info("✅ TTS Engine initialized with pre-warmed cache")
            
            # 7. Initialize SQS Worker (BLUEPRINT: Two-phase round-robin scheduler)
            self.sqs_worker = create_production_sqs_worker(
                sqs_queue_url=self.config['SQS_QUEUE_URL']
            )
            self.logger.info("✅ SQS Worker initialized")
            
            # 8. Create EBS staging directory
            if self.config['ENABLE_EBS_STAGING']:
                ebs_dir = Path(self.config['EBS_MOUNT_POINT']) / "staging"
                ebs_dir.mkdir(parents=True, exist_ok=True)
                self.logger.info(f"✅ EBS staging directory: {ebs_dir}")
            
            self.initialized = True
            self.logger.info("🎉 All components initialized successfully!")
            
            return True
            
        except Exception as e:
            self.logger.error(f"❌ Component initialization failed: {e}")
            self.logger.error(traceback.format_exc())
            return False
    
    def _create_audio_pipeline(self, story_id: str) -> Optional[StoryFFmpegPipeline]:
        """Create a new audio pipeline for a story"""
        try:
            # Create local directory for ffmpeg output
            local_dir = Path(self.config['EBS_MOUNT_POINT']) / "working" / story_id
            local_dir.mkdir(parents=True, exist_ok=True)
            
            # Create pipeline
            pipeline = StoryFFmpegPipeline(
                story_id=story_id,
                output_dir=local_dir,
                s3_uploader=self.s3_uploader
            )
            
            # Check health
            if not pipeline.is_healthy():
                self.logger.error(f"❌ Pipeline health check failed for {story_id}")
                pipeline.shutdown()
                return None
            
            return pipeline
            
        except Exception as e:
            self.logger.error(f"❌ Failed to create pipeline for {story_id}: {e}")
            return None
    
    def _synthesize_sentence(self, story_id: str, seq: int, text: str, voice_id: str, 
                           lang: str, params: Dict[str, Any]) -> Dict[str, Any]:
        """Synthesize a single sentence with TTS"""
        start_time = time.time()
        
        try:
            # 1. Generate idempotency key (Blueprint: hash(model|voice|text|speed|format))
            speed = params.get('speed', 1.0)
            audio_format = params.get('format', 'aac')
            
            idempotency_data = self.idempotency_manager.generate_idempotency_key(
                story_id=story_id,
                seq=seq,
                text=text,
                voice_id=voice_id,
                speed=speed,
                format=audio_format
            )
            
            # 2. Check if already processed
            if self.idempotency_manager.check_already_processed(idempotency_data):
                self.logger.info(f"⏭️ Sentence already processed: {story_id}:{seq}")
                return {
                    'success': True,
                    'skipped': True,
                    'reason': 'idempotent',
                    'processing_time': 0,
                }
            
            # 3. Check if segment already exists in S3
            if self.idempotency_manager.check_s3_segment_exists(story_id, seq):
                self.logger.info(f"⏭️ Segment already in S3: {story_id}:{seq}")
                return {
                    'success': True,
                    'skipped': True,
                    'reason': 'segment_exists',
                    'processing_time': 0,
                }
            
            # 4. Synthesize audio with TTS
            self.logger.info(f"🎵 Synthesizing: {story_id}:{seq} ({len(text)} chars)")
            
            audio_wav = self.tts_engine.synthesize(
                text=text,
                voice_id=voice_id,
                language=lang,
                speed=speed,
                **params
            )
            
            # 5. Convert to PCM (Blueprint: 24 kHz mono, s16le)
            import numpy as np
            import soundfile as sf
            
            # Ensure correct format
            if audio_wav.ndim > 1:
                audio_wav = np.mean(audio_wav, axis=1)  # Convert to mono
            
            # Resample if needed
            if hasattr(self.tts_engine.tts_model.config, 'sample_rate'):
                target_sr = self.tts_engine.tts_model.config.sample_rate
            else:
                target_sr = self.config['SAMPLE_RATE']
            
            if target_sr != self.config['SAMPLE_RATE']:
                import librosa
                audio_wav = librosa.resample(
                    audio_wav, 
                    orig_sr=target_sr, 
                    target_sr=self.config['SAMPLE_RATE']
                )
            
            # Convert to s16le PCM
            audio_pcm = (audio_wav * 32767).astype(np.int16).tobytes()
            sample_count = len(audio_wav)
            
            # 6. Get or create audio pipeline
            with self.pipeline_lock:
                if story_id not in self.active_pipelines:
                    pipeline = self._create_audio_pipeline(story_id)
                    if not pipeline:
                        return {'success': False, 'error': 'Pipeline creation failed'}
                    self.active_pipelines[story_id] = pipeline
                else:
                    pipeline = self.active_pipelines[story_id]
            
            # 7. Feed audio to pipeline (BLUEPRINT: one ffmpeg per story)
            is_final = params.get('is_final', False)
            success = pipeline.feed_audio(
                pcm_data=audio_pcm,
                sequence=seq,
                sample_count=sample_count,
                is_final=is_final
            )
            
            if not success:
                return {'success': False, 'error': 'Pipeline feed failed'}
            
            # 8. Mark as processed for idempotency
            self.idempotency_manager.mark_processed(
                idempotency_data,
                metadata={
                    'sentence_length': len(text),
                    'sample_count': sample_count,
                    'processing_time': time.time() - start_time
                }
            )
            
            # 9. Calculate processing time
            processing_time = time.time() - start_time
            
            # Record TTFA for first sentence
            ttfa_ms = None
            if seq == 1:
                ttfa_ms = processing_time * 1000
                self.metrics['total_ttfa_ms'].append(ttfa_ms)
                self.logger.info(f"🚀 TTFA: {ttfa_ms:.0f}ms for {story_id}")
            
            # Update metrics
            self.metrics['sentences_synthesized'] += 1
            
            return {
                'success': True,
                'processing_time': processing_time,
                'ttfa_ms': ttfa_ms,
                'sample_count': sample_count,
                'skipped': False,
            }
            
        except Exception as e:
            self.logger.error(f"❌ Synthesis failed for {story_id}:{seq}: {e}")
            self.logger.error(traceback.format_exc())
            self.metrics['errors'] += 1
            return {'success': False, 'error': str(e)}
    
    def _process_story_tasks(self):
        """Main processing loop - integrates SQS scheduler with TTS engine"""
        self.logger.info("🔄 Starting main processing loop...")
        
        while self.running and not self.shutdown_requested:
            try:
                # 1. Get next story to process from scheduler (Blueprint: two-phase round-robin)
                result = self.sqs_worker.get_next_story_to_process()
                if not result:
                    time.sleep(0.1)  # Small sleep to prevent tight loop
                    continue
                
                story_id, message_data = result
                seq = message_data.get('seq', 0)
                text = message_data.get('text', '')
                voice_id = message_data.get('voice_id', '')
                lang = message_data.get('lang', 'en')
                params = message_data.get('params', {})
                
                # 2. Mark as starting render
                self.sqs_worker.start_render(story_id)
                
                # 3. Check resume point for Spot interruption
                resume_info = None
                if self.spot_handler and seq == 1:
                    resume_info = self.spot_handler.get_resume_point(
                        story_id=story_id,
                        worker_id=self.config['INSTANCE_ID']
                    )
                    
                    if resume_info.get('status') == 'resuming':
                        resume_from = resume_info.get('resume_from', 0)
                        if seq < resume_from:
                            # Skip already processed segments
                            self.logger.info(f"⏭️ Skipping seq {seq}, resuming from {resume_from}")
                            self.sqs_worker.complete_render(
                                story_id, message_data, 
                                synthesis_time=0,
                                ttfa_ms=None
                            )
                            continue
                
                # 4. Synthesize sentence
                start_time = time.time()
                synthesis_result = self._synthesize_sentence(
                    story_id=story_id,
                    seq=seq,
                    text=text,
                    voice_id=voice_id,
                    lang=lang,
                    params=params
                )
                synthesis_time = time.time() - start_time
                
                # 5. Update scheduler with result
                self.sqs_worker.complete_render(
                    story_id=story_id,
                    message_data=message_data,
                    synthesis_time=synthesis_time,
                    ttfa_ms=synthesis_result.get('ttfa_ms')
                )
                
                # 6. Handle story completion
                if params.get('is_final', False):
                    self._complete_story(story_id)
                
                # 7. Update pipeline health
                self._cleanup_completed_pipelines()
                
            except Exception as e:
                self.logger.error(f"❌ Processing loop error: {e}")
                self.logger.error(traceback.format_exc())
                time.sleep(1)  # Backoff on error
    
    def _complete_story(self, story_id: str):
        """Complete a story and cleanup resources"""
        try:
            self.logger.info(f"🎬 Completing story: {story_id}")
            
            # 1. Shutdown pipeline
            with self.pipeline_lock:
                pipeline = self.active_pipelines.pop(story_id, None)
                if pipeline:
                    pipeline.shutdown()
            
            # 2. Mark story complete in scheduler
            self.sqs_worker.mark_story_complete(story_id)
            
            # 3. Mark story complete in DynamoDB
            if self.ddb_client:
                self.ddb_client.mark_story_complete(story_id)
            
            # 4. Release story ownership
            if self.spot_handler:
                self.spot_handler.mark_story_complete(
                    story_id=story_id,
                    worker_id=self.config['INSTANCE_ID']
                )
            
            # 5. Update metrics
            self.metrics['stories_processed'] += 1
            
            self.logger.info(f"✅ Story completed: {story_id}")
            
        except Exception as e:
            self.logger.error(f"❌ Failed to complete story {story_id}: {e}")
    
    def _cleanup_completed_pipelines(self):
        """Cleanup pipelines for completed stories"""
        with self.pipeline_lock:
            for story_id, pipeline in list(self.active_pipelines.items()):
                if not pipeline.is_healthy():
                    self.logger.warning(f"⚠️ Unhealthy pipeline detected: {story_id}")
                    pipeline.shutdown()
                    del self.active_pipelines[story_id]
    
    def _start_background_monitoring(self):
        """Start background monitoring threads"""
        # Spot interruption monitoring
        if self.config['ENABLE_SPOT_INTERRUPTION_HANDLING'] and self.spot_handler:
            def spot_monitor():
                while self.running:
                    try:
                        if self.spot_handler.check_spot_interruption():
                            # Spot interruption detected - initiate graceful shutdown
                            self.logger.warning("🚨 Spot interruption detected, initiating shutdown...")
                            self.shutdown_requested = True
                            break
                    except Exception as e:
                        self.logger.error(f"Spot monitor error: {e}")
                    time.sleep(30)  # Check every 30 seconds
            
            self.spot_check_thread = threading.Thread(
                target=spot_monitor,
                daemon=True,
                name="SpotMonitor"
            )
            self.spot_check_thread.start()
            self.logger.info("✅ Spot interruption monitor started")
        
        # Metrics reporting
        def metrics_reporter():
            while self.running:
                try:
                    self._report_metrics()
                except Exception as e:
                    self.logger.error(f"Metrics reporter error: {e}")
                time.sleep(self.config['METRICS_INTERVAL'])
        
        self.metrics_thread = threading.Thread(
            target=metrics_reporter,
            daemon=True,
            name="MetricsReporter"
        )
        self.metrics_thread.start()
        self.logger.info(f"✅ Metrics reporter started (interval: {self.config['METRICS_INTERVAL']}s)")
    
    def _report_metrics(self):
        """Report metrics to CloudWatch/logs"""
        try:
            uptime = time.time() - self.metrics['start_time']
            
            # Calculate TTFA stats
            ttfa_values = self.metrics['total_ttfa_ms']
            if ttfa_values:
                avg_ttfa = sum(ttfa_values) / len(ttfa_values)
                p95_ttfa = sorted(ttfa_values)[int(len(ttfa_values) * 0.95)] if len(ttfa_values) >= 20 else 0
            else:
                avg_ttfa = p95_ttfa = 0
            
            # Get component stats
            sqs_stats = self.sqs_worker.get_stats() if self.sqs_worker else {}
            tts_stats = self.tts_engine.get_cache_stats() if self.tts_engine else {}
            
            metrics = {
                'timestamp': datetime.utcnow().isoformat(),
                'instance_id': self.config['INSTANCE_ID'],
                'deployment_id': self.config['DEPLOYMENT_ID'],
                'operation_mode': self.config['OPERATION_MODE'],
                'uptime_seconds': uptime,
                'stories_processed': self.metrics['stories_processed'],
                'sentences_synthesized': self.metrics['sentences_synthesized'],
                'errors': self.metrics['errors'],
                'ttfa_avg_ms': avg_ttfa,
                'ttfa_p95_ms': p95_ttfa,
                'active_pipelines': len(self.active_pipelines),
                'sqs_stats': sqs_stats,
                'tts_cache_stats': {
                    'cache_size': tts_stats.get('cache_size', 0),
                    'hit_ratio': tts_stats.get('hit_ratio_percent', 0),
                },
                'health_check': get_health_status(),
            }
            
            # Log metrics (in production, also send to CloudWatch)
            self.logger.info(f"📊 METRICS: {json.dumps(metrics, indent=2, default=str)}")
            
        except Exception as e:
            self.logger.error(f"❌ Metrics reporting failed: {e}")
    
    def _start_health_server(self):
        """Start health check HTTP server"""
        try:
            from flask import Flask, jsonify
            import threading
            
            app = Flask(__name__)
            
            @app.route('/health')
            def health():
                """Health check endpoint for ELB/ASG"""
                try:
                    # Perform quick health check
                    is_healthy, details, critical = simple_health_check()
                    
                    # Add component health
                    components = {
                        'tts_engine': self.tts_engine.is_healthy() if self.tts_engine else False,
                        'sqs_worker': self.sqs_worker.is_healthy() if self.sqs_worker else False,
                        'active_pipelines': len(self.active_pipelines),
                    }
                    
                    response = {
                        'status': 'healthy' if is_healthy and all(components.values()) else 'unhealthy',
                        'timestamp': datetime.utcnow().isoformat(),
                        'instance_id': self.config['INSTANCE_ID'],
                        'component_health': components,
                        'health_details': details,
                        'critical_failures': critical,
                        'metrics': {
                            'stories_processed': self.metrics['stories_processed'],
                            'uptime_seconds': time.time() - self.metrics['start_time'],
                        }
                    }
                    
                    status_code = 200 if response['status'] == 'healthy' else 503
                    return jsonify(response), status_code
                    
                except Exception as e:
                    return jsonify({'status': 'error', 'error': str(e)}), 500
            
            @app.route('/metrics')
            def metrics():
                """Prometheus-style metrics"""
                try:
                    self._report_metrics()
                    return jsonify(self.metrics), 200
                except Exception as e:
                    return jsonify({'error': str(e)}), 500
            
            @app.route('/cache-stats')
            def cache_stats():
                """Get TTS cache statistics"""
                try:
                    if self.tts_engine:
                        return jsonify(self.tts_engine.get_cache_stats()), 200
                    return jsonify({'error': 'TTS engine not available'}), 503
                except Exception as e:
                    return jsonify({'error': str(e)}), 500
            
            def run_server():
                app.run(
                    host='0.0.0.0',
                    port=self.config['HEALTH_CHECK_PORT'],
                    threaded=True,
                    debug=False
                )
            
            self.health_server_thread = threading.Thread(
                target=run_server,
                daemon=True,
                name="HealthServer"
            )
            self.health_server_thread.start()
            
            self.logger.info(f"🏥 Health server started on port {self.config['HEALTH_CHECK_PORT']}")
            
        except Exception as e:
            self.logger.warning(f"⚠️ Failed to start health server: {e}")
    
    def run(self):
        """Main run method - starts everything"""
        try:
            # 1. Validate configuration
            ProductionConfig.validate(self.config)
            
            # 2. Initialize components
            if not self.initialize_components():
                self.logger.error("❌ Failed to initialize components")
                return False
            
            # 3. Start health server
            if self.config.get('OPERATION_MODE') == 'production':
                self._start_health_server()
            
            # 4. Start background monitoring
            self._start_background_monitoring()
            
            # 5. Main processing loop
            self.logger.info("🚀 Starting main processing loop...")
            self._process_story_tasks()
            
            return True
            
        except KeyboardInterrupt:
            self.logger.info("👋 Keyboard interrupt received")
            return True
        except Exception as e:
            self.logger.error(f"💥 Critical error in run(): {e}")
            self.logger.error(traceback.format_exc())
            return False
        finally:
            self.shutdown()
    
    def shutdown(self):
        """Graceful shutdown"""
        self.logger.info("🔴 Starting graceful shutdown...")
        self.running = False
        self.shutdown_requested = True
        
        # 1. Shutdown SQS worker
        if self.sqs_worker:
            self.sqs_worker.shutdown()
        
        # 2. Shutdown all pipelines
        with self.pipeline_lock:
            for story_id, pipeline in list(self.active_pipelines.items()):
                try:
                    pipeline.shutdown()
                except:
                    pass
            self.active_pipelines.clear()
        
        # 3. Shutdown TTS engine
        if self.tts_engine:
            self.tts_engine.shutdown()
        
        # 4. Shutdown spot handler
        if self.spot_handler:
            self.spot_handler.shutdown()
        
        # 5. Wait for threads
        threads = [
            self.spot_check_thread,
            self.metrics_thread,
            self.health_server_thread
        ]
        
        for thread in threads:
            if thread and thread.is_alive():
                thread.join(timeout=5.0)
        
        # 6. Final metrics report
        self._report_metrics()
        
        self.logger.info("✅ Graceful shutdown complete")
        logging.shutdown()

# ============ SIGNAL HANDLERS ============

def setup_signal_handlers(worker):
    """Setup signal handlers for graceful shutdown"""
    def signal_handler(signum, frame):
        worker.logger.info(f"📶 Signal {signum} received, initiating shutdown...")
        worker.shutdown_requested = True
    
    signal.signal(signal.SIGTERM, signal_handler)
    signal.signal(signal.SIGINT, signal_handler)
    
    # Ignore SIGPIPE to prevent crashes from broken pipes
    signal.signal(signal.SIGPIPE, signal.SIG_IGN)

# ============ MAIN ENTRY POINT ============

def main():
    """Main entry point"""
    # 1. Setup logging
    logger = setup_logging()
    
    logger.info("""
    ╔══════════════════════════════════════════════════════════╗
    ║      🚀 Lunebi GPU Worker - Production Blueprint v1.3    ║
    ║      Instant Story Streaming with <1s TTFA              ║
    ╚══════════════════════════════════════════════════════════╝
    """)
    
    # 2. Load configuration
    config = ProductionConfig.from_environment()
    
    # 3. Create worker instance
    worker = LunebiGPUWorker(config)
    
    # 4. Setup signal handlers
    setup_signal_handlers(worker)
    
    # 5. Run worker
    success = worker.run()
    
    if success:
        logger.info("✅ Worker completed successfully")
        return 0
    else:
        logger.error("❌ Worker failed")
        return 1

if __name__ == "__main__":
    sys.exit(main())