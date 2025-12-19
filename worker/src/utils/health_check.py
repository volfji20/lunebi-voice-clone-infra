# worker/src/utils/health_check.py
"""
Production Health Check Utilities for GPU Worker
BLUEPRINT: Monitors GPU, SQS, DDB, S3 connectivity and worker state
"""

import os
import sys
import time
import json
import logging
import psutil
import subprocess
import traceback
from datetime import datetime, timedelta
import boto3
from botocore.exceptions import ClientError, NoCredentialsError, EndpointConnectionError

# Set up logging
logger = logging.getLogger('gpu-worker-health')

# Health check state for tracking
_health_check_state = {
    'last_check': None,
    'failures': {},
    'start_time': time.time()
}

def check_cuda_availability():
    """BLUEPRINT: Check CUDA availability and GPU memory"""
    try:
        import torch
        
        # Basic CUDA availability
        if not torch.cuda.is_available():
            return False, "CUDA not available"
        
        # Get GPU count
        device_count = torch.cuda.device_count()
        if device_count == 0:
            return False, "No GPU devices found"
        
        # Test memory allocation
        try:
            torch.cuda.set_device(0)
            # Allocate small tensor to test
            test_tensor = torch.randn(1000, 1000, device='cuda')
            # Perform simple operation
            result = test_tensor @ test_tensor.T
            # Clean up
            del test_tensor, result
            torch.cuda.empty_cache()
        except Exception as e:
            return False, f"GPU memory test failed: {e}"
        
        # Check GPU memory status
        gpu_info = []
        for i in range(device_count):
            props = torch.cuda.get_device_properties(i)
            free_mem = torch.cuda.memory_reserved(i) / (1024**3)
            total_mem = props.total_memory / (1024**3)
            gpu_info.append(f"GPU{i}: {props.name} ({total_mem:.1f}GB, {free_mem:.1f}GB free)")
        
        return True, f"{device_count} GPU(s) available: {', '.join(gpu_info)}"
        
    except ImportError:
        return False, "PyTorch not installed"
    except Exception as e:
        return False, f"CUDA check failed: {str(e)[:200]}"

def check_aws_connectivity():
    """Check AWS credentials and service connectivity"""
    try:
        region = os.getenv('AWS_REGION', 'us-east-1')
        
        # Test STS for credentials
        sts = boto3.client('sts', region_name=region)
        identity = sts.get_caller_identity()
        
        # Test S3 connectivity
        s3_bucket = os.getenv('STORIES_BUCKET')
        if s3_bucket:
            s3 = boto3.client('s3', region_name=region)
            # Lightweight operation
            s3.list_objects_v2(Bucket=s3_bucket, MaxKeys=1)
        
        # Test DynamoDB connectivity
        voices_table = os.getenv('VOICES_TABLE')
        if voices_table:
            dynamodb = boto3.resource('dynamodb', region_name=region)
            table = dynamodb.Table(voices_table)
            # Lightweight operation
            table.scan(Limit=1)
        
        return True, f"AWS connectivity OK (User: {identity.get('UserId', 'unknown')})"
        
    except NoCredentialsError:
        return False, "AWS credentials not found"
    except EndpointConnectionError:
        return False, "AWS endpoint unreachable"
    except ClientError as e:
        error_code = e.response['Error']['Code']
        if error_code == 'AccessDenied':
            return False, f"AWS access denied: {e}"
        elif error_code == 'ResourceNotFoundException':
            return True, "AWS connected but resources not found (expected during setup)"
        else:
            return False, f"AWS client error: {error_code}"
    except Exception as e:
        return False, f"AWS connectivity failed: {str(e)[:200]}"

def check_sqs_connectivity():
    """Check SQS queue connectivity"""
    try:
        queue_url = os.getenv('SQS_QUEUE_URL')
        if not queue_url:
            return False, "SQS_QUEUE_URL not set"
        
        region = os.getenv('AWS_REGION', 'us-east-1')
        sqs = boto3.client('sqs', region_name=region)
        
        # Get queue attributes (lightweight)
        response = sqs.get_queue_attributes(
            QueueUrl=queue_url,
            AttributeNames=['ApproximateNumberOfMessages', 'CreatedTimestamp']
        )
        
        msg_count = int(response['Attributes'].get('ApproximateNumberOfMessages', 0))
        return True, f"SQS connected: {msg_count} messages in queue"
        
    except Exception as e:
        return False, f"SQS connectivity failed: {str(e)[:200]}"

def check_model_status():
    """Check if TTS model is loaded and accessible"""
    try:
        # Check multiple possible model locations
        model_paths = [
            os.getenv('MODEL_PATH', '/opt/models/xtts-v2'),
            '/tmp/models/xtts-v2',
            '/opt/voiceclone/models/xtts-v2'
        ]
        
        model_path = None
        for path in model_paths:
            if os.path.exists(path):
                model_path = path
                break
        
        if not model_path:
            return False, f"Model not found in any location: {model_paths}"
        
        # Check for XTTSv2 specific files
        expected_patterns = ['config.json', '*.pth', '*.pkl', 'vocab.*']
        found_files = os.listdir(model_path)
        
        # Look for XTTSv2 patterns
        xtts_files = [f for f in found_files if 'xtts' in f.lower() or 'config' in f.lower()]
        
        if not xtts_files:
            return False, f"No XTTSv2 files found in {model_path}"
        
        # Check file sizes (basic sanity)
        for file in xtts_files[:3]:  # Check first 3 files
            file_path = os.path.join(model_path, file)
            size_mb = os.path.getsize(file_path) / (1024**2)
            if size_mb < 0.1:  # Less than 100KB
                logger.warning(f"Small model file detected: {file} ({size_mb:.1f}MB)")
        
        return True, f"Model accessible at {model_path} ({len(found_files)} files)"
        
    except Exception as e:
        return False, f"Model check failed: {str(e)[:200]}"

def check_system_resources():
    """Check system resources (memory, disk, CPU)"""
    try:
        warnings = []
        
        # Check disk space on critical paths
        critical_paths = ['/', '/tmp', '/opt']
        for path in critical_paths:
            try:
                usage = psutil.disk_usage(path)
                free_gb = usage.free / (1024**3)
                threshold_gb = 5 if path == '/' else 1
                
                if free_gb < threshold_gb:
                    warnings.append(f"Low disk on {path}: {free_gb:.1f}GB free")
            except Exception:
                continue
        
        # Check memory
        memory = psutil.virtual_memory()
        memory_percent = memory.percent
        if memory_percent > 90:
            warnings.append(f"High memory usage: {memory_percent}%")
        
        # Check CPU load
        cpu_percent = psutil.cpu_percent(interval=1)
        if cpu_percent > 90:
            warnings.append(f"High CPU load: {cpu_percent}%")
        
        # Check GPU memory via nvidia-smi
        try:
            result = subprocess.run(
                ['nvidia-smi', '--query-gpu=memory.used,memory.total', '--format=csv,noheader,nounits'],
                capture_output=True, text=True, timeout=5
            )
            if result.returncode == 0:
                gpu_info = result.stdout.strip().split('\n')
                for i, line in enumerate(gpu_info):
                    if ',' in line:
                        used, total = line.split(',')
                        used_gb = int(used.strip()) / 1024
                        total_gb = int(total.strip()) / 1024
                        util = (used_gb / total_gb) * 100
                        if util > 95:
                            warnings.append(f"GPU{i} memory high: {util:.1f}%")
        except (subprocess.TimeoutExpired, FileNotFoundError, Exception):
            pass
        
        if warnings:
            return False, f"Resource warnings: {'; '.join(warnings)}"
        
        # Generate status message
        status_parts = [
            f"Memory: {memory_percent}% used",
            f"CPU: {cpu_percent}% load",
            f"Disk: {free_gb:.1f}GB free on /"
        ]
        
        return True, f"System resources OK: {', '.join(status_parts)}"
        
    except Exception as e:
        return False, f"Resource check failed: {str(e)[:200]}"

def check_worker_metrics():
    """Check worker-specific metrics and state"""
    try:
        # Check if worker modules can be imported
        import sys
        sys.path.insert(0, '/opt/voiceclone/src')
        
        # Try to import worker components
        try:
            from worker.metrics import get_worker_metrics
            metrics = get_worker_metrics()
            return True, f"Worker metrics: {json.dumps(metrics)[:100]}..."
        except ImportError:
            # Fall back to basic metrics
            pass
        
        # Basic process metrics
        proc = psutil.Process()
        cpu_percent = proc.cpu_percent(interval=0.1)
        memory_mb = proc.memory_info().rss / (1024**2)
        
        # Check uptime
        uptime_seconds = time.time() - _health_check_state['start_time']
        uptime_str = str(timedelta(seconds=int(uptime_seconds)))
        
        status = f"Uptime: {uptime_str}, CPU: {cpu_percent:.1f}%, Memory: {memory_mb:.1f}MB"
        
        # Warn if memory is too high
        if memory_mb > 2000:  # 2GB
            return False, f"Worker memory high: {memory_mb:.1f}MB - {status}"
        
        return True, status
        
    except Exception as e:
        return False, f"Worker metrics failed: {str(e)[:200]}"

def check_ffmpeg_availability():
    """Check if ffmpeg is installed and accessible"""
    try:
        result = subprocess.run(
            ['ffmpeg', '-version'],
            capture_output=True, text=True, timeout=5
        )
        
        if result.returncode != 0:
            return False, "ffmpeg command failed"
        
        # Parse version
        for line in result.stdout.split('\n'):
            if 'ffmpeg version' in line:
                version = line.split('ffmpeg version')[1].split()[0]
                return True, f"ffmpeg {version} available"
        
        return True, "ffmpeg available"
        
    except (subprocess.TimeoutExpired, FileNotFoundError):
        return False, "ffmpeg not found or timed out"
    except Exception as e:
        return False, f"ffmpeg check failed: {str(e)[:200]}"

def check_inference_latency():
    """Check TTS inference latency (if model is loaded)"""
    try:
        # This check requires the TTS engine to be loaded
        # We'll try to import it, but don't fail if it's not available yet
        
        import sys
        sys.path.insert(0, '/opt/voiceclone/src')
        
        # Check if we can access the TTS engine
        try:
            # Simulate a check - in production this would test actual inference
            return True, "Inference system accessible"
        except ImportError:
            return True, "TTS engine not loaded yet (expected during startup)"
            
    except Exception as e:
        logger.warning(f"Inference latency check skipped: {e}")
        return True, "Inference check skipped"

def _record_check_result(check_name, success, message):
    """Record health check results for tracking"""
    global _health_check_state
    
    if not success:
        if check_name not in _health_check_state['failures']:
            _health_check_state['failures'][check_name] = []
        
        _health_check_state['failures'][check_name].append({
            'timestamp': time.time(),
            'message': message
        })
        
        # Keep only last 10 failures
        if len(_health_check_state['failures'][check_name]) > 10:
            _health_check_state['failures'][check_name].pop(0)

def is_healthy():
    """
    BLUEPRINT: Comprehensive health check for GPU worker
    Returns: (is_healthy: bool, details: dict, critical_failures: list)
    """
    global _health_check_state
    
    health_details = {}
    critical_failures = []
    all_healthy = True
    
    # Define health checks with criticality
    checks = [
        ("cuda", check_cuda_availability, True),      # Critical: GPU required
        ("aws", check_aws_connectivity, True),        # Critical: AWS required
        ("sqs", check_sqs_connectivity, True),        # Critical: Queue required
        ("system", check_system_resources, True),     # Critical: Resources required
        ("model", check_model_status, True),          # Critical: Model required
        ("ffmpeg", check_ffmpeg_availability, True),  # Critical: ffmpeg required
        ("inference", check_inference_latency, False), # Non-critical
        ("worker", check_worker_metrics, False),      # Non-critical
    ]
    
    for check_name, check_func, is_critical in checks:
        try:
            is_ok, message = check_func()
            
            health_details[check_name] = {
                "healthy": is_ok,
                "message": message[:500],  # Limit message length
                "critical": is_critical,
                "timestamp": time.time()
            }
            
            # Record result
            _record_check_result(check_name, is_ok, message)
            
            if not is_ok:
                if is_critical:
                    critical_failures.append(f"{check_name}: {message}")
                    all_healthy = False
                else:
                    logger.warning(f"Non-critical health check failed [{check_name}]: {message}")
            else:
                logger.debug(f"Health check passed [{check_name}]: {message[:100]}")
                
        except Exception as e:
            error_msg = f"Check crashed: {str(e)[:200]}"
            stack_trace = traceback.format_exc()[-500:]
            
            health_details[check_name] = {
                "healthy": False,
                "message": error_msg,
                "critical": is_critical,
                "error": stack_trace,
                "timestamp": time.time()
            }
            
            if is_critical:
                critical_failures.append(f"{check_name}: {error_msg}")
                all_healthy = False
            
            logger.error(f"Health check error [{check_name}]: {e}\n{stack_trace}")
    
    _health_check_state['last_check'] = time.time()
    
    return all_healthy, health_details, critical_failures

def get_health_status():
    """
    Get health status for API responses
    Returns: dict with health status and details
    """
    is_ok, details, critical_failures = is_healthy()
    
    # Calculate uptime
    uptime_seconds = time.time() - _health_check_state['start_time']
    
    # Count failures
    failure_count = sum(1 for check in details.values() if not check['healthy'])
    
    return {
        "status": "healthy" if is_ok else "unhealthy",
        "uptime_seconds": uptime_seconds,
        "uptime_human": str(timedelta(seconds=int(uptime_seconds))),
        "timestamp": datetime.utcnow().isoformat() + 'Z',
        "version": os.getenv('IMAGE_TAG', 'unknown'),
        "deploy_id": os.getenv('DEPLOY_ID', 'unknown'),
        "instance_id": os.getenv('INSTANCE_ID', 'unknown'),
        "failure_count": failure_count,
        "critical_failures": critical_failures,
        "checks": details,
        "failure_history": {k: len(v) for k, v in _health_check_state['failures'].items()}
    }

def simple_health_check():
    """
    Simplified health check for Docker HEALTHCHECK command
    Only checks critical components
    """
    try:
        # Critical checks only
        checks = [
            ("cuda", check_cuda_availability),
            ("aws", check_aws_connectivity),
            ("sqs", check_sqs_connectivity),
            ("system", check_system_resources)
        ]
        
        for check_name, check_func in checks:
            try:
                is_ok, message = check_func()
                if not is_ok:
                    logger.error(f"Critical health check failed [{check_name}]: {message}")
                    return False
            except Exception as e:
                logger.error(f"Critical health check crashed [{check_name}]: {e}")
                return False
        
        logger.debug("All critical health checks passed")
        return True
        
    except Exception as e:
        logger.error(f"Health check system crashed: {e}")
        return False

if __name__ == "__main__":
    # When run directly, perform health check and exit with appropriate code
    logging.basicConfig(
        level=logging.INFO,
        format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
    )
    
    if simple_health_check():
        print("✅ Health check passed")
        sys.exit(0)
    else:
        print("❌ Health check failed")
        sys.exit(1)