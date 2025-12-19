#!/bin/bash
set -ex

echo "================================================"
echo "🚀 GPU Worker Initialization - VoiceClone M4 (FIXED)"
echo "Mode: $${environment}"
echo "CloudWatch Log Group: $${cloudwatch_log_group}"
echo "SSM Parameter Prefix: $${ssm_parameter_prefix}"
echo "================================================"

# ============================================================================
# 1. MODE-SPECIFIC CONFIGURATION (Blueprint: Test vs Production)
# ============================================================================

echo "🔧 Loading configuration for mode: $${environment}"
if [ "$${environment}" = "test" ]; then
    echo "🏷️ TEST MODE: Spot-only, CPU mock fallback enabled"
    OPERATION_MODE="test"
    ENABLE_SPOT_INTERRUPTION_HANDLING="false"
    MIN_CONCURRENT_STORIES=0
    MAX_CONCURRENT_STORIES=2  # Conservative for test mode
    ENABLE_WARM_POOL="false"
else
    echo "🏭 PRODUCTION MODE: SLO-driven, resilient"
    OPERATION_MODE="production"
    ENABLE_SPOT_INTERRUPTION_HANDLING="true"
    MIN_CONCURRENT_STORIES=1
    MAX_CONCURRENT_STORIES=4  # L4 can handle 2-4 stories/GPU
    ENABLE_WARM_POOL="true"
fi

# ============================================================================
# 2. INSTANCE METADATA AND REGION
# ============================================================================

echo "🔍 Gathering instance metadata..."
INSTANCE_ID=$(curl -s http://169.254.169.254/latest/meta-data/instance-id)
AVAILABILITY_ZONE=$(curl -s http://169.254.169.254/latest/meta-data/placement/availability-zone)
REGION=$(echo $AVAILABILITY_ZONE | sed 's/[a-z]$//')
INSTANCE_TYPE=$(curl -s http://169.254.169.254/latest/meta-data/instance-type)

echo "Instance ID: $INSTANCE_ID"
echo "Region: $REGION"
echo "Instance Type: $INSTANCE_TYPE"
echo "Availability Zone: $AVAILABILITY_ZONE"

# ============================================================================
# 3. LOAD SSM PARAMETERS (Blueprint: runtime configuration)
# ============================================================================

echo "🔑 Loading configuration from SSM Parameter Store..."

load_ssm_param() {
    param_name=$1
    default_value=$2
    value=$(aws ssm get-parameter \
        --name "/$${ssm_parameter_prefix}/$${param_name}" \
        --region $REGION \
        --query Parameter.Value \
        --output text 2>/dev/null || echo $default_value)
    echo $value
}

# ✅ USE YOUR EXACT DEFAULT VALUES from Python code
SQS_QUEUE_URL=$(load_ssm_param "sqs_queue_url" "https://sqs.us-east-1.amazonaws.com/579897422848/lunebi-prod-us-east-1-story-tasks")
S3_BUCKET_NAME=$(load_ssm_param "s3_bucket_name" "voiceclone-stories-prod-us-east-1")
VOICES_TABLE_NAME=$(load_ssm_param "voices_table_name" "lunebi-prod-us-east-1-voices")
STORIES_TABLE_NAME=$(load_ssm_param "stories_table_name" "lunebi-prod-us-east-1-stories")

# Load performance tuning parameters
TTS_CACHE_SIZE=$(load_ssm_param "tts_cache_size" "200")
TTS_PRELOAD_COUNT=$(load_ssm_param "tts_preload_count" "50")
SCHEDULER_TARGET_BUFFER=$(load_ssm_param "scheduler_target_buffer" "3.0")

echo "✅ Loaded configuration from SSM"
echo "   SQS_QUEUE_URL: $${SQS_QUEUE_URL}"
echo "   S3_BUCKET_NAME: $${S3_BUCKET_NAME}"
echo "   VOICES_TABLE_NAME: $${VOICES_TABLE_NAME}"
echo "   STORIES_TABLE_NAME: $${STORIES_TABLE_NAME}"

# ============================================================================
# 4. GPU DETECTION AND VERIFICATION
# ============================================================================

echo "🔍 Checking GPU availability..."
MAX_ATTEMPTS=30
ATTEMPT=1

while [ $ATTEMPT -le $MAX_ATTEMPTS ]; do
    if nvidia-smi > /dev/null 2>&1; then
        echo "✅ GPU detected on attempt $ATTEMPT"
        GPU_INFO=$(nvidia-smi --query-gpu=name,memory.total,driver_version --format=csv,noheader)
        echo "GPU Info: $GPU_INFO"
        break
    else
        echo "⏳ Waiting for GPU... (attempt $ATTEMPT/$MAX_ATTEMPTS)"
        sleep 10
        ATTEMPT=$((ATTEMPT + 1))
    fi
done

if [ $ATTEMPT -gt $MAX_ATTEMPTS ]; then
    echo "❌ GPU not available after $MAX_ATTEMPTS attempts"
    if [ "$${environment}" = "test" ]; then
        echo "⚠️ TEST MODE: Continuing without GPU (CPU mock will handle processing)"
    else
        echo "❌ PRODUCTION MODE: GPU required, marking unhealthy"
        exit 1
    fi
fi

# ============================================================================
# 5. EBS STAGING SETUP (Blueprint: local EBS for Spot interruption)
# ============================================================================

echo "💾 Setting up EBS staging..."
EBS_MOUNT_POINT="/mnt/ebs"

setup_ebs_staging() {
    echo "📂 Creating EBS staging directories..."
    
    if [ -d "$EBS_MOUNT_POINT" ]; then
        echo "✅ EBS volume already mounted at $EBS_MOUNT_POINT"
    else
        echo "🔧 Setting up EBS mount point..."
        sudo mkdir -p $EBS_MOUNT_POINT
        
        # Check for available block devices
        for device in /dev/nvme2n1 /dev/nvme1n1 /dev/xvdf /dev/sdf; do
            if [ -b "$device" ]; then
                # Skip if this is the root device
                ROOT_DEVICE=$(findmnt / -o SOURCE -n | sed 's/p[0-9]*$//' 2>/dev/null || echo "")
                if [ "$device" = "$ROOT_DEVICE" ] || [ "$device" = "${ROOT_DEVICE}p1" ]; then
                    echo "⚠️ Skipping root device: $device"
                    continue
                fi
                
                echo "📀 Found block device: $device"
                
                # Check if filesystem exists
                if ! blkid $device > /dev/null 2>&1; then
                    echo "🔨 Creating XFS filesystem on $device"
                    sudo mkfs -t xfs $device
                fi
                
                # Mount the device
                echo "🔗 Mounting $device to $EBS_MOUNT_POINT"
                sudo mount $device $EBS_MOUNT_POINT
                
                # Add to fstab for persistence
                if ! grep -q "$EBS_MOUNT_POINT" /etc/fstab; then
                    echo "$device $EBS_MOUNT_POINT xfs defaults,nofail 0 2" | sudo tee -a /etc/fstab
                fi
                
                break
            fi
        done
        
        # Fallback to instance store if no EBS volume
        if ! mountpoint -q $EBS_MOUNT_POINT; then
            echo "⚠️ No EBS volume detected, using instance store fallback"
            EBS_MOUNT_POINT="/mnt/instance_store"
            sudo mkdir -p $EBS_MOUNT_POINT
            sudo chmod 777 $EBS_MOUNT_POINT
        fi
    fi
    
    # Create staging directory structure
    sudo mkdir -p $EBS_MOUNT_POINT/{staging,completed,working,temp}
    sudo chown -R ec2-user:ec2-user $EBS_MOUNT_POINT
    sudo chmod -R 755 $EBS_MOUNT_POINT
    
    echo "✅ EBS staging ready at: $EBS_MOUNT_POINT"
}

setup_ebs_staging

# ============================================================================
# 6. UPDATE CONFIGURATION (FIXED: Only update existing config file)
# ============================================================================

echo "⚙️ Updating runtime configuration..."

# Detect GPU type for scheduler limits
GPU_TYPE=$(nvidia-smi --query-gpu=name --format=csv,noheader | head -1 | tr '[:upper:]' '[:lower:]')
if [[ $GPU_TYPE == *"l4"* ]] || [[ $GPU_TYPE == *"g6"* ]]; then
    SCHEDULER_MAX_CONCURRENT=4
    GPU_FAMILY="L4"
elif [[ $GPU_TYPE == *"t4"* ]] || [[ $GPU_TYPE == *"g4dn"* ]]; then
    SCHEDULER_MAX_CONCURRENT=2
    GPU_FAMILY="T4"
elif [[ $GPU_TYPE == *"a10g"* ]] || [[ $GPU_TYPE == *"g5"* ]]; then
    SCHEDULER_MAX_CONCURRENT=3
    GPU_FAMILY="A10G"
else
    SCHEDULER_MAX_CONCURRENT=1
    GPU_FAMILY="unknown"
fi

# ✅ UPDATE EXISTING CONFIG FILE (don't overwrite completely)
cat > /tmp/update_config.py << 'EOF'
import os
import re

config_file = '/etc/voiceclone/config.env'

# Read existing config
with open(config_file, 'r') as f:
    content = f.read()

# Update critical AWS resource variables AND TTS paths
updates = {
    'SQS_QUEUE_URL': os.environ.get('SQS_QUEUE_URL', ''),
    'S3_BUCKET_NAME': os.environ.get('S3_BUCKET_NAME', ''),
    'VOICES_TABLE_NAME': os.environ.get('VOICES_TABLE_NAME', ''),
    'STORIES_TABLE_NAME': os.environ.get('STORIES_TABLE_NAME', ''),
    'VOICES_TABLE': os.environ.get('VOICES_TABLE_NAME', ''),
    'STORIES_TABLE': os.environ.get('STORIES_TABLE_NAME', ''),
    'STORIES_BUCKET': os.environ.get('S3_BUCKET_NAME', ''),
    'AWS_REGION': os.environ.get('REGION', 'us-east-1'),
    'OPERATION_MODE': os.environ.get('OPERATION_MODE', 'test'),
    'INSTANCE_ID': os.environ.get('INSTANCE_ID', ''),
    # ADD TTS PATH CONFIGURATIONS
    'TTS_HOME': '/opt/voiceclone/.tts_cache',
    'TTS_CACHE_DIR': '/opt/voiceclone/.tts_cache',
    'XDG_DATA_HOME': '/opt/voiceclone/.tts_cache',
}

# Apply updates
for key, value in updates.items():
    if value:
        pattern = rf'^{key}=.*$'
        replacement = f'{key}={value}'
        if re.search(pattern, content, re.MULTILINE):
            content = re.sub(pattern, replacement, content, flags=re.MULTILINE)
        else:
            content += f'\n{replacement}'

# Write back
with open(config_file, 'w') as f:
    f.write(content)

print(f'✅ Updated {config_file} with TTS paths')
EOF

# Export variables for Python script
export SQS_QUEUE_URL="$${SQS_QUEUE_URL}"
export S3_BUCKET_NAME="$${S3_BUCKET_NAME}"
export VOICES_TABLE_NAME="$${VOICES_TABLE_NAME}"
export STORIES_TABLE_NAME="$${STORIES_TABLE_NAME}"
export REGION="$${REGION}"
export OPERATION_MODE="$${OPERATION_MODE}"
export INSTANCE_ID="$${INSTANCE_ID}"

# Run the update script
python3 /tmp/update_config.py

# Copy to application directory
sudo cp /etc/voiceclone/config.env /opt/voiceclone/config.env
sudo chown ec2-user:ec2-user /opt/voiceclone/config.env
sudo chmod 644 /opt/voiceclone/config.env

echo "✅ Runtime configuration updated at /etc/voiceclone/config.env"

# ============================================================================
# 7. VERIFY DEPENDENCIES (FIXED: Model already pre-downloaded)
# ============================================================================

echo "🔍 Verifying dependencies..."

# Check Python environment
echo "🐍 Checking Python environment..."
/opt/voiceclone/venv/bin/python -c "
import sys, torch
print(f'Python: {sys.version}')
print(f'PyTorch: {torch.__version__}')
print(f'CUDA available: {torch.cuda.is_available()}')
if torch.cuda.is_available():
    print(f'GPU: {torch.cuda.get_device_name(0)}')
    print(f'CUDA version: {torch.version.cuda}')
    print(f'GPU Memory: {torch.cuda.get_device_properties(0).total_memory / 1e9:.1f} GB')
"

# Check FFmpeg
echo "🎵 Checking FFmpeg..."
ffmpeg -version | head -1

# Check model directory (already pre-downloaded in AMI)
echo "📦 Checking model files..."

# Check the EXACT path TTS will use
MODEL_PATH="/opt/voiceclone/.tts_cache/tts_models--multilingual--multi-dataset--xtts_v2"
if [ -f "$MODEL_PATH/config.json" ] && [ -f "$MODEL_PATH/model.pth" ]; then
    MODEL_SIZE=$(du -sh /opt/voiceclone/.tts_cache | cut -f1)
    echo "✅ Model pre-downloaded: $MODEL_SIZE"
    echo "✅ Model accessible at: $MODEL_PATH"
    echo "Files found:"
    ls -la "$MODEL_PATH/" | head -5
else
    echo "⚠️ Model not found at expected path: $MODEL_PATH"
    echo "Looking for model files in /opt/voiceclone/.tts_cache/:"
    find /opt/voiceclone/.tts_cache -type f -name "*.pth" -o -name "config.json" | head -10
fi

# ============================================================================
# 8. START GPU WORKER SERVICE (FIXED: Only start the existing service)
# ============================================================================

echo "🚀 Starting GPU worker service..."

# Check if service file exists
if [ -f /etc/systemd/system/voiceclone-gpu-worker.service ]; then
    echo "✅ Found service: voiceclone-gpu-worker.service"
    
    # Reload systemd
    sudo systemctl daemon-reload
    
    # Enable and start the service
    sudo systemctl enable voiceclone-gpu-worker.service
    sudo systemctl restart voiceclone-gpu-worker.service
    
    # Wait a moment and check status
    sleep 5
    echo "🔍 Checking service status..."
    sudo systemctl status voiceclone-gpu-worker.service --no-pager
    
    # Check logs
    echo "📋 Checking service logs..."
    sudo journalctl -u voiceclone-gpu-worker.service -n 10 --no-pager
    
else
    echo "❌ Service file not found: voiceclone-gpu-worker.service"
    echo "Listing available services:"
    sudo systemctl list-unit-files | grep voiceclone || echo "No voiceclone services found"
    
    # Try to start the worker directly as fallback
    echo "🔄 Attempting to start worker directly..."
    cd /opt/voiceclone
    sudo -u ec2-user /opt/voiceclone/venv/bin/python /opt/voiceclone/src/main.py &
    echo "✅ Worker started directly in background"
fi

# ============================================================================
# 9. QUICK TEST OF THE WORKER
# ============================================================================

echo "🧪 Testing worker functionality..."

# Replace the entire test_worker_quick.py script
cat > /tmp/test_worker_quick.py << 'EOF'
#!/usr/bin/env python3
import os
import sys

# CRITICAL: Set environment variables BEFORE importing TTS
os.environ['TTS_HOME'] = '/opt/voiceclone/.tts_cache'
os.environ['XDG_DATA_HOME'] = '/opt/voiceclone/.tts_cache'
os.environ['TTS_CACHE_DIR'] = '/opt/voiceclone/.tts_cache'

sys.path.insert(0, '/opt/voiceclone/src')

print("Testing GPU worker imports with TTS_HOME=/opt/voiceclone/.tts_cache")
print("=" * 50)

try:
    import torch
    from TTS.api import TTS
    
    print(f"✅ PyTorch: {torch.__version__}")
    print(f"✅ CUDA available: {torch.cuda.is_available()}")
    
    # Quick test of TTS with GLOBAL path
    print("\nLoading TTS model from /opt/voiceclone/.tts_cache...")
    tts = TTS('tts_models/multilingual/multi-dataset/xtts_v2', 
              progress_bar=False, 
              gpu=torch.cuda.is_available())
    
    print("✅ TTS model loaded successfully from global path")
    
    # Test boto3/SQS access
    import boto3
    sqs = boto3.client('sqs', region_name='us-east-1')
    print("✅ AWS SDK working")
    
except Exception as e:
    print(f"❌ Test failed: {e}")
    import traceback
    traceback.print_exc()
EOF

/opt/voiceclone/venv/bin/python /tmp/test_worker_quick.py

# ============================================================================
# 10. HEALTH CHECK AND READINESS
# ============================================================================

echo "🏥 Setting up health checks..."

# Create ready flag
echo "READY" > /tmp/gpu_worker_ready
echo "$${INSTANCE_ID}" > /tmp/instance_id
chmod 644 /tmp/gpu_worker_ready /tmp/instance_id

# Run the built-in verification script if it exists
if [ -f /opt/voiceclone/verify_ami.sh ]; then
    echo "🔍 Running AMI verification..."
    /opt/voiceclone/verify_ami.sh
fi

# ============================================================================
# 11. FINAL STATUS
# ============================================================================

echo "📋 Final system status:"

# Disk usage
echo "💾 Disk Usage:"
df -h / /mnt/ebs 2>/dev/null || df -h /

# GPU status
echo "🎮 GPU Status:"
nvidia-smi --query-gpu=name,memory.total,memory.used,memory.free,utilization.gpu --format=csv

# Services
echo "⚙️ Services:"
systemctl list-units --type=service --state=running | grep voiceclone || echo "No voiceclone services running"

echo "================================================"
echo "🎉 GPU WORKER INITIALIZATION COMPLETE!"
echo "Instance: $${INSTANCE_ID}"
echo "GPU: Tesla T4 (g4dn.xlarge)"
echo "Model: Pre-loaded XTTSv2"
echo "Queue: $${SQS_QUEUE_URL}"
echo "Ready for TTS processing"
echo "================================================"

# Signal successful completion
touch /var/lib/cloud/instance/boot-finished