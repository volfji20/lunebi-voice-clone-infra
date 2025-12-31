#!/usr/bin/env python3
"""
🚀 TTS ENGINE - Fixed with model loading bug fix
"""

import os
import time
import json
import logging
import threading
from typing import Dict, Optional, Tuple, Any, List
from collections import OrderedDict
from pathlib import Path

import torch
import numpy as np
import boto3
import base64

logger = logging.getLogger('tts-engine')

class ProductionTTSEngine:
    """Fixed TTS Engine - Model loading bug fixed"""
    
    def __init__(self, cache_size: int = 200, gpu_device: str = "cuda:0"):
        self.voice_cache = OrderedDict()
        self.cache_size = cache_size
        self.cache_lock = threading.RLock()
        
        self.device = gpu_device if torch.cuda.is_available() else "cpu"
        
        self.gpt_cond_len = 30
        self.gpt_cond_dim = 1024
        self.expected_style_elements = self.gpt_cond_len * self.gpt_cond_dim
        
        self.max_concurrent_synthesis = int(os.getenv('MAX_CONCURRENT_SYNTHESIS', '3'))
        self.semaphore = threading.BoundedSemaphore(self.max_concurrent_synthesis)
        
        self.metrics = {
            'cache_hits': 0,
            'cache_misses': 0,
            'synthesis_count': 0,
            'synthesis_time_p95': 0.0,
            'errors': 0,
            'concurrent_in_use': 0
        }
        self.metrics_lock = threading.Lock()
        self.synthesis_times = []
        
        self.model = None
        self.model_loaded = False
        
        self.dynamodb = None
        self.voices_table_name = None
        
        # CRITICAL: Track frequently used voices for pre-warming
        self.frequent_voice_ids: List[str] = []
        
        logger.info(f"🔧 TTS Engine initialized: device={self.device}, cache={cache_size}")

    def initialize(self, model_path: str, dynamodb_client=None, voices_table_name: str = None) -> bool:
        """Initialize engine with dependencies - BUG FIXED"""
        try:
            # CRITICAL BUG FIX: Check if model_path is None
            if not model_path:
                logger.error("❌ model_path is None or empty")
                # Try to get from environment
                model_path = os.getenv('TTS_MODEL_PATH', '/opt/voiceclone/.tts_cache')
                logger.info(f"Using fallback model_path: {model_path}")
            
            # BLUEPRINT: Load XTTSv2 model
            if not self._load_model(model_path):
                logger.error("❌ Model loading failed")
                return False
            
            # BLUEPRINT: Store dependencies
            if dynamodb_client:
                self.dynamodb = dynamodb_client
            else:
                self.dynamodb = boto3.resource('dynamodb', 
                    region_name=os.environ.get('AWS_REGION', 'us-east-1'))
            
            self.voices_table_name = voices_table_name or os.getenv('VOICES_TABLE_NAME')
            
            if not self.voices_table_name:
                logger.warning("⚠️ VOICES_TABLE_NAME not configured")
            
            # CRITICAL FIX: Load always-warm voices from environment
            always_warm_voices = os.getenv('ALWAYS_WARM_VOICES', '')
            self.frequent_voice_ids = [v.strip() for v in always_warm_voices.split(',') if v.strip()]
            
            if self.frequent_voice_ids:
                logger.info(f"🔥 Always-warm voices configured: {self.frequent_voice_ids}")
            
            # BLUEPRINT: Pre-warm cache
            if self.voices_table_name:
                self._pre_warm_cache(preload_count=10)
            
            # NEW: Immediately pre-warm specific voices
            self._pre_warm_specific_voices()
            
            self.model_loaded = True
            logger.info("✅ TTS Engine initialized successfully")
            return True
            
        except Exception as e:
            logger.error(f"❌ Initialization failed: {e}")
            import traceback
            logger.error(traceback.format_exc())
            return False

    def _load_model(self, model_path: str) -> bool:
        """Load XTTSv2 model - UPDATED FOR NEW TTS API"""
        try:
            # Import torch first
            import torch
            
            os.environ["COQUI_TOS_AGREED"] = "1"
            os.environ["TTS_HOME"] = "/opt/voiceclone/.tts_cache"
            
            from TTS.api import TTS
            
            logger.info(f"🔄 Loading TTS model (new API method)")
            
            # Pre-allocate GPU memory if available
            if self.device.startswith('cuda') and torch.cuda.is_available():
                logger.info("🔥 Pre-allocating GPU memory...")
                try:
                    # Allocate ~1GB to reduce fragmentation
                    dummy = torch.randn(512, 512, device=self.device)
                    result = torch.matmul(dummy, dummy)
                    del dummy, result
                    torch.cuda.empty_cache()
                    logger.info("✅ GPU memory pre-warmed")
                except Exception as e:
                    logger.warning(f"GPU pre-allocation warning: {e}")
            
            try:
                logger.info("🔍 Loading XTTSv2 by model name...")
                
                # 🚨 NEW METHOD: Load model then move to GPU
                self.model = TTS("tts_models/multilingual/multi-dataset/xtts_v2")
                
                # 🚨 CRITICAL: Move model to GPU using .to() method
                if self.device.startswith('cuda') and torch.cuda.is_available():
                    logger.info(f"🔄 Moving model to {self.device}...")
                    self.model.to(self.device)
                    
                    # Verify model is on GPU
                    if hasattr(self.model, 'synthesizer') and hasattr(self.model.synthesizer, 'tts_model'):
                        model_device = next(self.model.synthesizer.tts_model.parameters()).device
                        logger.info(f"📌 Model device confirmed: {model_device}")
                    else:
                        logger.info("✅ Model moved to GPU")
                    
                    # Log GPU memory usage
                    allocated = torch.cuda.memory_allocated() / 1024**3
                    cached = torch.cuda.memory_reserved() / 1024**3
                    logger.info(f"📊 GPU Memory: {allocated:.2f}GB allocated, {cached:.2f}GB cached")
                else:
                    logger.info("✅ Model loaded on CPU")
                
                logger.info("✅ XTTSv2 model loaded successfully")
                return True
                
            except Exception as e:
                logger.warning(f"Model name load failed: {e}, trying path...")
                
                # Fallback: Try loading from path
                if model_path and Path(model_path).exists():
                    try:
                        self.model = TTS(model_path=model_path)
                        logger.info(f"✅ Model loaded from path: {model_path}")
                        
                        # Move to GPU
                        if self.device.startswith('cuda') and torch.cuda.is_available():
                            self.model.to(self.device)
                            logger.info(f"🔄 Model moved to {self.device}")
                        
                        return True
                    except Exception as e2:
                        logger.error(f"Path load also failed: {e2}")
                        return False
                else:
                    logger.error(f"Model path invalid or doesn't exist: {model_path}")
                    return False
                    
        except Exception as e:
            logger.error(f"❌ Model loading failed: {e}")
            import traceback
            logger.error(traceback.format_exc())
            return False

    def _move_all_components_to_gpu(self):
        """🚀 Move ALL model components to GPU - UPDATED"""
        try:
            import torch
            
            if not torch.cuda.is_available():
                logger.warning("⚠️ CUDA not available, cannot move to GPU")
                return
            
            logger.info(f"🔧 Moving model to {self.device}...")
            
            # Simple method: Just use .to() method
            self.model.to(self.device)
            
            # Additional verification for XTTS components
            try:
                if hasattr(self.model, 'synthesizer'):
                    # Move synthesizer
                    self.model.synthesizer.to(self.device)
                    
                    # Check inner model if exists
                    if hasattr(self.model.synthesizer, 'tts_model'):
                        device = next(self.model.synthesizer.tts_model.parameters()).device
                        logger.info(f"📌 TTS model on device: {device}")
            except:
                pass  # Some models don't have these attributes
            
            # Log GPU memory
            allocated = torch.cuda.memory_allocated() / 1024**3
            cached = torch.cuda.memory_reserved() / 1024**3
            logger.info(f"📊 GPU Memory: {allocated:.2f}GB allocated, {cached:.2f}GB cached")
            
            logger.info(f"✅ Model moved to {self.device}")
            
        except Exception as e:
            logger.warning(f"⚠️ Could not move model to GPU: {e}")

    def _pre_warm_cache(self, preload_count: int = 10):
        """Pre-warm cache with recent voices"""
        try:
            if not self.voices_table_name or not self.dynamodb:
                return
            
            table = self.dynamodb.Table(self.voices_table_name)
            
            seven_days_ago = int((time.time() - (7 * 24 * 3600)) * 1000)
            
            response = table.scan(
                FilterExpression=boto3.dynamodb.conditions.Attr('created_at').gte(seven_days_ago) &
                                boto3.dynamodb.conditions.Attr('embeddings').exists() &
                                boto3.dynamodb.conditions.Attr('style').exists(),
                Limit=preload_count
            )
            
            loaded = 0
            for item in response.get('Items', []):
                if self._cache_voice_item(item):
                    loaded += 1
            
            logger.info(f"📥 Pre-warmed cache with {loaded} voices")
            
        except Exception as e:
            logger.warning(f"⚠️ Pre-warm failed: {e}")

    def _pre_warm_specific_voices(self):
        """CRITICAL FIX: Pre-warm specific voice IDs immediately"""
        if not self.frequent_voice_ids:
            return
        
        if not self.dynamodb or not self.voices_table_name:
            logger.warning("⚠️ Cannot pre-warm specific voices: DDB not configured")
            return
        
        logger.info(f"🔥 Pre-warming {len(self.frequent_voice_ids)} specific voices...")
        
        loaded = 0
        for voice_id in self.frequent_voice_ids:
            try:
                success = self._load_and_cache_voice(voice_id)
                if success:
                    loaded += 1
                    logger.info(f"  ✅ Pre-warmed: {voice_id}")
                else:
                    logger.warning(f"  ⚠️ Failed to pre-warm: {voice_id}")
            except Exception as e:
                logger.warning(f"  ⚠️ Error pre-warming {voice_id}: {e}")
        
        logger.info(f"🔥 Successfully pre-warmed {loaded}/{len(self.frequent_voice_ids)} voices")
    
    def _load_and_cache_voice(self, voice_id: str) -> bool:
        """Load a single voice from DynamoDB and cache it"""
        try:
            table = self.dynamodb.Table(self.voices_table_name)
            response = table.get_item(Key={'voice_id': voice_id})
            
            if 'Item' not in response:
                logger.debug(f"Voice {voice_id} not found in DynamoDB")
                return False
            
            return self._cache_voice_item(response['Item'])
            
        except Exception as e:
            logger.debug(f"Failed to load voice {voice_id}: {e}")
            return False

    def _cache_voice_item(self, voice_data: Dict) -> bool:
        """Load single voice from DynamoDB item into cache"""
        try:
            voice_id = voice_data.get('voice_id')
            if not voice_id:
                return False
            
            with self.cache_lock:
                if voice_id in self.voice_cache:
                    return True
            
            embeddings_bytes = self._decode_ddb_binary(voice_data.get('embeddings'))
            style_bytes = self._decode_ddb_binary(voice_data.get('style'))
            
            if not embeddings_bytes or not style_bytes:
                return False
            
            embeddings_tensor, style_tensor = self._create_tensors(embeddings_bytes, style_bytes)
            embeddings_tensor = embeddings_tensor.to(self.device)
            style_tensor = style_tensor.to(self.device)
            
            with self.cache_lock:
                self.voice_cache[voice_id] = (embeddings_tensor, style_tensor)
                self.voice_cache.move_to_end(voice_id)
                
                if len(self.voice_cache) > self.cache_size:
                    self.voice_cache.popitem(last=False)
            
            return True
            
        except Exception as e:
            logger.debug(f"Failed to cache voice: {e}")
            return False

    def _create_tensors(self, embeddings_bytes: bytes, style_bytes: bytes) -> Tuple[torch.Tensor, torch.Tensor]:
        """Create properly shaped tensors for XTTSv2 with writable arrays"""
        # Convert bytes to numpy arrays and make them writable
        embeddings_np = np.frombuffer(embeddings_bytes, dtype=np.float32).copy()
        style_np = np.frombuffer(style_bytes, dtype=np.float32).copy()
        
        # Handle embeddings: ensure shape (1, 512, 1) for HiFiGAN decoder
        if embeddings_np.size == 512:
            # Reshape to [1, 512, 1] instead of [1, 512]
            embeddings_tensor = torch.from_numpy(embeddings_np).reshape(1, 512, 1)
        elif embeddings_np.shape == (1, 512, 1):
            embeddings_tensor = torch.from_numpy(embeddings_np)
        elif embeddings_np.shape == (1, 512):
            # Add channel dimension at the end
            embeddings_tensor = torch.from_numpy(embeddings_np).unsqueeze(-1)
        else:
            embeddings_flat = embeddings_np.flatten()[:512]
            if len(embeddings_flat) < 512:
                embeddings_flat = np.pad(embeddings_flat, (0, 512 - len(embeddings_flat)))
            # Reshape to [1, 512, 1]
            embeddings_tensor = torch.from_numpy(embeddings_flat).reshape(1, 512, 1)
        
        # Handle style: ensure shape (1, 30, 1024) for XTTS v2
        if style_np.size == self.expected_style_elements:
            style_reshaped = style_np.reshape(1, self.gpt_cond_len, self.gpt_cond_dim)
            style_tensor = torch.from_numpy(style_reshaped)
        elif style_np.size == (1024 * 1024):  # Legacy format: 1024x1024
            style_2d = style_np.reshape(1024, 1024)
            style_fixed = style_2d[:self.gpt_cond_len, :].copy()  # Take first 30 rows
            style_tensor = torch.from_numpy(style_fixed).unsqueeze(0)
        else:
            style_flat = style_np.flatten()[:self.expected_style_elements]
            if len(style_flat) < self.expected_style_elements:
                style_flat = np.pad(style_flat, (0, self.expected_style_elements - len(style_flat)))
            style_reshaped = style_flat.reshape(1, self.gpt_cond_len, self.gpt_cond_dim)
            style_tensor = torch.from_numpy(style_reshaped)
        
        return embeddings_tensor, style_tensor

    def synthesize(self, text: str, voice_id: str, language: str = "en", speed: float = 1.0):
        """🚀 FIXED: Synthesize audio with proper validation"""
        if not self.model_loaded:
            raise RuntimeError("TTS Engine not initialized")
        
        # Clean and validate text
        text = text.strip()
        if not text:
            raise ValueError("Text cannot be empty")
        
        if len(text) > 500:
            text = text[:500]
            logger.warning(f"Text truncated to {len(text)} characters")
        
        self.semaphore.acquire()
        start_time = time.time()
        
        with self.metrics_lock:
            self.metrics['concurrent_in_use'] += 1
        
        try:
            # Get voice embeddings
            voice_start = time.time()
            embeddings_data, style_data = self._get_voice_embeddings(voice_id)
            if embeddings_data is None or style_data is None:
                raise ValueError(f"Voice embeddings not found: {voice_id}")
            
            voice_time = time.time() - voice_start
            with self.cache_lock:
                was_cache_hit = voice_id in self.voice_cache
            logger.info(f"⏱️ Voice lookup: {voice_time:.3f}s (cache: {was_cache_hit})")
            
            # Prepare tensors
            tensor_start = time.time()

            # 🚨 CRITICAL: Always create fresh tensors and move to GPU
            try:
                if isinstance(embeddings_data, torch.Tensor) and isinstance(style_data, torch.Tensor):
                    # Clone to avoid shared memory issues
                    speaker_embedding = embeddings_data.clone().to(self.device, non_blocking=True)
                    gpt_cond_latent = style_data.clone().to(self.device, non_blocking=True)
                else:
                    # Create new tensors
                    speaker_embedding, gpt_cond_latent = self._create_tensors(embeddings_data, style_data)
                    speaker_embedding = speaker_embedding.to(self.device, non_blocking=True)
                    gpt_cond_latent = gpt_cond_latent.to(self.device, non_blocking=True)
            except Exception as e:
                logger.error(f"❌ Tensor preparation failed: {e}")
                raise

            tensor_time = time.time() - tensor_start
            logger.info(f"⏱️ Tensor prep: {tensor_time:.3f}s")
            
            # Ensure correct shape
            if len(speaker_embedding.shape) == 2:
                speaker_embedding = speaker_embedding.unsqueeze(-1)  # [1, 512, 1]
            
            tensor_time = time.time() - tensor_start
            logger.info(f"⏱️ Tensor prep: {tensor_time:.3f}s")
            
            # Normalize language
            language = language.lower()
            if language.startswith('en'):
                language = 'en'
            elif language.startswith('zh'):
                language = 'zh-cn'
            elif language.startswith('es'):
                language = 'es'
            elif language.startswith('fr'):
                language = 'fr'
            elif language.startswith('de'):
                language = 'de'
            elif language.startswith('it'):
                language = 'it'
            elif language.startswith('pt'):
                language = 'pt'
            else:
                language = 'en'
            
            # Get actual model
            if hasattr(self.model, 'synthesizer') and hasattr(self.model.synthesizer, 'tts_model'):
                actual_model = self.model.synthesizer.tts_model
            elif hasattr(self.model, 'model'):
                actual_model = self.model.model
            elif hasattr(self.model, 'tts_model'):
                actual_model = self.model.tts_model
            else:
                actual_model = self.model
            
            # 🚀 FIXED INFERENCE CALL - REMOVE problem parameters
            inference_start = time.time()
            
            with torch.no_grad():
                # Try different parameter combinations
                try:
                    # Option 1: With text splitting (FASTEST)
                    result = actual_model.inference(
                        text=text,
                        language=language,
                        speaker_embedding=speaker_embedding,
                        gpt_cond_latent=gpt_cond_latent,
                        speed=speed,
                        enable_text_splitting=False,  # ✅ CRITICAL for speed
                        temperature=0.7,
                        do_sample=True,
                        top_k=50,
                        top_p=0.85
                        # ❌ NO early_stopping, length_penalty, or num_beams!
                    )
                    logger.debug("Used inference with text splitting")
                    
                except TypeError as e:
                    if "enable_text_splitting" in str(e):
                        # Option 2: Without enable_text_splitting
                        try:
                            result = actual_model.inference(
                                text=text,
                                language=language,
                                speaker_embedding=speaker_embedding,
                                gpt_cond_latent=gpt_cond_latent,
                                speed=speed,
                                temperature=0.7,
                                do_sample=True,
                                top_k=50,
                                top_p=0.85
                            )
                            logger.debug("Used inference without text splitting")
                        except TypeError as e2:
                            # Option 3: Minimal parameters
                            result = actual_model.inference(
                                text=text,
                                language=language,
                                speaker_embedding=speaker_embedding,
                                gpt_cond_latent=gpt_cond_latent,
                                speed=speed
                            )
                            logger.debug("Used minimal inference")
                    else:
                        raise
            
            inference_time = time.time() - inference_start
            logger.info(f"⏱️ Inference: {inference_time:.3f}s")
            
            # 🚨 CRITICAL FIX: Extract and VALIDATE audio
            audio_tensor = None
            
            if isinstance(result, dict):
                logger.debug(f"Result dict keys: {list(result.keys())}")
                
                # Try common keys
                for key in ['wav', 'audio', 'output_wav', 'waveform']:
                    if key in result:
                        audio_tensor = result[key]
                        logger.debug(f"Found audio in key: '{key}'")
                        break
                
                # If not found, search for any tensor
                if audio_tensor is None:
                    for key, value in result.items():
                        if isinstance(value, torch.Tensor) and value.dim() > 0:
                            audio_tensor = value
                            logger.debug(f"Found tensor in key: '{key}', shape: {value.shape}")
                            break
            
            elif isinstance(result, torch.Tensor):
                audio_tensor = result
                logger.debug(f"Result is tensor, shape: {result.shape}")
            
            elif isinstance(result, (list, tuple)):
                # Try first element that's a tensor
                for item in result:
                    if isinstance(item, torch.Tensor) and item.dim() > 0:
                        audio_tensor = item
                        logger.debug(f"Found tensor in list/tuple, shape: {item.shape}")
                        break
            
            if audio_tensor is None:
                raise ValueError("❌ No audio tensor found in inference result!")
            
            # Convert to numpy
            if isinstance(audio_tensor, torch.Tensor):
                audio = audio_tensor.detach().cpu().numpy()
            else:
                audio = np.array(audio_tensor)
            
            # 🚨 AUDIO VALIDATION - FIX FOR EMPTY AUDIO
            logger.info(f"🎧 Raw audio stats: shape={audio.shape}, dtype={audio.dtype}")
            logger.info(f"🎧 Audio range: min={np.min(audio):.6f}, max={np.max(audio):.6f}, mean={np.mean(np.abs(audio)):.6f}")
            
            # Check if audio is empty or silent
            if audio.size == 0:
                raise ValueError("❌ ERROR: Empty audio array generated!")
            
            if np.max(np.abs(audio)) < 0.0001:
                logger.warning("⚠️ WARNING: Audio amplitude extremely low (near silent)")
                # Try to normalize if all zeros
                if np.max(np.abs(audio)) == 0:
                    raise ValueError("❌ ERROR: Audio is all zeros (silent)!")
            
            # Ensure proper shape (1D mono, 24kHz)
            if len(audio.shape) > 1:
                audio = audio.squeeze()
                logger.debug(f"Squeezed audio shape: {audio.shape}")
            
            if len(audio.shape) != 1:
                logger.warning(f"Audio still not 1D: {audio.shape}, flattening")
                audio = audio.flatten()
            
            # Calculate expected duration
            expected_samples = int(len(text) * 100)  # Rough estimate: 100 samples per character
            actual_samples = len(audio)
            
            logger.info(f"📊 Audio samples: {actual_samples} (expected ~{expected_samples})")
            logger.info(f"⏱️ Duration: {actual_samples/24000:.2f}s @24kHz")
            
            # Warning if audio is too short
            if actual_samples < 1000:  # Less than ~0.04 seconds
                logger.warning(f"⚠️ Audio very short: {actual_samples} samples")
            
            # Normalize audio if too quiet
            max_amplitude = np.max(np.abs(audio))
            if 0.001 < max_amplitude < 0.1:  # Too quiet but not silent
                logger.info(f"🔊 Normalizing audio (amplitude: {max_amplitude:.4f})")
                audio = audio / max_amplitude * 0.9  # Normalize to 90% volume
            
            # Update metrics
            total_time = time.time() - start_time
            with self.metrics_lock:
                self.metrics['synthesis_count'] += 1
                self.synthesis_times.append(total_time)
                if len(self.synthesis_times) > 1000:
                    self.synthesis_times.pop(0)
                if self.synthesis_times:
                    p95_idx = int(len(self.synthesis_times) * 0.95)
                    self.metrics['synthesis_time_p95'] = sorted(self.synthesis_times)[p95_idx]
            
            logger.info(f"✅ Total synthesis: {total_time:.3f}s for {len(text)} chars")
            logger.info(f"🎵 Final audio: {len(audio)} samples ({(len(audio)/24000):.2f}s)")
            
            return audio
            
        except Exception as e:
            with self.metrics_lock:
                self.metrics['errors'] += 1
            logger.error(f"❌ Synthesis failed: {e}")
            import traceback
            logger.error(traceback.format_exc())
            raise
            
        finally:
            self.semaphore.release()
            with self.metrics_lock:
                self.metrics['concurrent_in_use'] -= 1

    def _get_voice_embeddings(self, voice_id: str) -> Tuple[Optional[torch.Tensor], Optional[torch.Tensor]]:
        """Get voice from cache or DynamoDB"""
        with self.cache_lock:
            if voice_id in self.voice_cache:
                embeddings, style = self.voice_cache[voice_id]
                self.voice_cache.move_to_end(voice_id)
                with self.metrics_lock:
                    self.metrics['cache_hits'] += 1
                logger.debug(f"🎯 Cache hit: {voice_id}")
                return embeddings, style
        
        with self.metrics_lock:
            self.metrics['cache_misses'] += 1
        
        if self.dynamodb and self.voices_table_name:
            try:
                table = self.dynamodb.Table(self.voices_table_name)
                response = table.get_item(Key={'voice_id': voice_id})
                
                if 'Item' in response and self._cache_voice_item(response['Item']):
                    with self.cache_lock:
                        if voice_id in self.voice_cache:
                            return self.voice_cache[voice_id]
            except Exception as e:
                logger.warning(f"⚠️ Failed to load voice from DDB: {e}")
        
        logger.warning(f"⚠️ Voice not found: {voice_id}")
        return None, None

    def _decode_ddb_binary(self, binary_data):
        """Decode DynamoDB binary attribute"""
        try:
            if binary_data is None:
                return None
            
            # With boto3.resource.Table.get_item(), binary attributes are returned as Binary objects
            # These have a .value attribute containing the bytes
            
            # Method 1: Check if it's a boto3 Binary object with .value attribute
            if hasattr(binary_data, 'value'):
                value = binary_data.value
                if isinstance(value, bytes):
                    return value
            
            # Method 2: If it's already bytes
            if isinstance(binary_data, bytes):
                return binary_data
            
            # Method 3: Some boto3 Binary objects might be callable
            if callable(binary_data):
                try:
                    result = binary_data()
                    if isinstance(result, bytes):
                        return result
                except:
                    pass
            
            # Method 4: Fallback for other formats
            if isinstance(binary_data, dict) and 'B' in binary_data:
                # Could be base64 string or bytes
                value = binary_data['B']
                if isinstance(value, bytes):
                    return value
                elif isinstance(value, str):
                    import base64
                    return base64.b64decode(value)
            
            # Method 5: If it's a string, assume it's base64
            if isinstance(binary_data, str):
                import base64
                try:
                    return base64.b64decode(binary_data)
                except:
                    return None
            
            return None
            
        except Exception as e:
            import logging
            logger = logging.getLogger('tts-engine')
            logger.debug(f"Binary decode error: {e}, type: {type(binary_data)}")
            return None

    def get_metrics(self) -> Dict[str, Any]:
        """Get observability metrics"""
        with self.metrics_lock:
            metrics_copy = self.metrics.copy()
        
        with self.cache_lock:
            cache_size = len(self.voice_cache)
        
        total = metrics_copy['cache_hits'] + metrics_copy['cache_misses']
        cache_hit_ratio = (metrics_copy['cache_hits'] / total * 100) if total > 0 else 0
        
        return {
            **metrics_copy,
            'cache_size': cache_size,
            'cache_max_size': self.cache_size,
            'cache_hit_ratio_percent': round(cache_hit_ratio, 1),
            'model_loaded': self.model_loaded,
            'device': self.device,
            'concurrent_limit': self.max_concurrent_synthesis,
            'concurrent_available': self.semaphore._value,
            'frequent_voices_configured': len(self.frequent_voice_ids),
            'frequent_voices_cached': sum(1 for vid in self.frequent_voice_ids if vid in self.voice_cache)
        }

    def health_check(self) -> Dict[str, Any]:
        """Health check for monitoring"""
        try:
            healthy = self.model_loaded and torch.cuda.is_available()
            
            health = {
                'healthy': healthy,
                'model_loaded': self.model_loaded,
                'gpu_available': torch.cuda.is_available(),
                'cache_size': len(self.voice_cache),
                'concurrent_in_use': self.metrics['concurrent_in_use'],
                'frequent_voices_pre_warmed': sum(1 for vid in self.frequent_voice_ids if vid in self.voice_cache),
                'timestamp': time.time()
            }
            
            if torch.cuda.is_available():
                health.update({
                    'gpu_memory_allocated_mb': torch.cuda.memory_allocated() / (1024 ** 2),
                    'gpu_memory_cached_mb': torch.cuda.memory_reserved() / (1024 ** 2)
                })
            
            return health
            
        except Exception as e:
            return {'healthy': False, 'error': str(e)}

    def clear_cache(self):
        """Clear voice cache"""
        with self.cache_lock:
            cleared = len(self.voice_cache)
            self.voice_cache.clear()
        
        if torch.cuda.is_available():
            torch.cuda.empty_cache()
        
        logger.info(f"🧹 Cleared {cleared} voices from cache")

    def shutdown(self):
        """Graceful shutdown"""
        logger.info("🔴 Shutting down TTS Engine...")
        
        for _ in range(self.max_concurrent_synthesis):
            self.semaphore.acquire()
        
        self.clear_cache()
        
        self.model = None
        self.model_loaded = False
        
        logger.info("✅ TTS Engine shutdown complete")


# ============ FACTORY FUNCTION ============

def create_production_tts_engine(
    model_path: str = None,
    cache_size: int = 200,
    gpu_device: str = None,
    voices_table_name: str = None
) -> 'ProductionTTSEngine':
    """
    Factory function to create a ProductionTTSEngine instance.
    Returns: ProductionTTSEngine instance
    """
    import logging
    logger = logging.getLogger('tts-engine')
    
    # Get configuration from environment
    if not model_path:
        model_path = os.getenv('TTS_MODEL_PATH', '/opt/voiceclone/.tts_cache')
    
    if not gpu_device:
        gpu_device = os.getenv('GPU_DEVICE', 'cuda:0' if torch.cuda.is_available() else 'cpu')
    
    if not voices_table_name:
        voices_table_name = os.getenv('VOICES_TABLE_NAME')
    
    # Create engine instance
    engine = ProductionTTSEngine(
        cache_size=cache_size,
        gpu_device=gpu_device
    )
    
    # Initialize with dependencies
    success = engine.initialize(
        model_path=model_path,
        voices_table_name=voices_table_name
    )
    
    if not success:
        raise RuntimeError("Failed to initialize TTS Engine")
    
    logger.info("✅ TTS Engine created via factory")
    return engine
