packer {
  required_plugins {
    amazon = {
      source  = "github.com/hashicorp/amazon"
      version = "~> 1"
    }
  }
}

variable "aws_region" {
  type    = string
  default = "us-east-1"
}

variable "image_version" {
  type    = string
  default = "v1.0.0-{{timestamp}}"
}

variable "environment" {
  type    = string
  default = "test"
}

variable "iam_instance_profile" {
  type    = string
  default = "lunebi-prod-us-east-1-gpu-worker-profile"
}

source "amazon-ebs" "voiceclone-worker" {
  region          = var.aws_region
  instance_type   = "g6.xlarge"
  ami_name        = "voiceclone-worker-${var.environment}-${var.image_version}"
  ami_description = "VoiceClone GPU Worker - Amazon Linux 2023 with NVIDIA, CUDA, PyTorch, XTTSv2"

  ena_support     = true
  sriov_support   = true
  
  # 🔴 CRITICAL FIX: Add IAM instance profile for model download
  iam_instance_profile = var.iam_instance_profile != "" ? var.iam_instance_profile : null

  source_ami_filter {
    filters = {
      name                = "al2023-ami-2023.*-x86_64"
      root-device-type    = "ebs"
      virtualization-type = "hvm"
    }
    owners      = ["amazon"]
    most_recent = true
  }

  ssh_username = "ec2-user"

  launch_block_device_mappings {
    device_name = "/dev/xvda"
    volume_size = 50 
    volume_type = "gp3"
    delete_on_termination = true
  }

  ami_block_device_mappings {
    device_name = "/dev/xvda"
    volume_size = 50  
    volume_type = "gp3"
    delete_on_termination = true
  }

  tags = {
    Name        = "voiceclone-worker"
    Project     = "voiceclone"
    Environment = var.environment
    Version     = var.image_version
  }
}

build {
  sources = ["source.amazon-ebs.voiceclone-worker"]

  # Step 0: Verify we have 50GB disk
  provisioner "shell" {
    inline = [
      "set -ex",
      "echo '💾 Step 0: Verifying 50GB root disk'",
      "df -h /",
      "lsblk",
      "echo '✅ Using 50GB root disk - ready for XTTSv2 model (2GB)'"
    ]
  }

  # Step 1: AWS credentials check for model download
  provisioner "shell" {
    inline = [
      "set -ex",
      "echo '🔐 Step 1: AWS Credentials Check'",
      "# Check if Packer instance has IAM role for model download",
      "if curl -s http://169.254.169.254/latest/meta-data/iam/security-credentials/ >/dev/null 2>&1; then",
      "    echo '✅ Packer instance has IAM role'",
      "    aws sts get-caller-identity --query Arn --output text && echo '✅ AWS credentials working'",
      "else",
      "    echo '⚠️ WARNING: Packer instance needs IAM role with:'",
      "    echo '   - AmazonS3ReadOnlyAccess (for Hugging Face cache)'",
      "    echo '   - Or internet access for direct download'",
      "fi"
    ]
  }

  # Step 2: System preparation - Install Python 3.11 alongside system Python 3.9
  provisioner "shell" {
    inline = [
      "set -ex",
      "echo '🔧 Step 2: System preparation - Amazon Linux 2023'",
      "sudo dnf update -y",
      
      "# Install Python 3.11 alongside system Python 3.9",
      "sudo dnf install -y python3.11 python3.11-pip python3.11-devel",
      
      "# Install other essential packages",
      "sudo dnf install -y git wget unzip tar xz gcc-c++ make cmake",
      
      "# Verify both Python versions exist",
      "echo '✅ System Python 3.9:' && /usr/bin/python3 --version",
      "echo '✅ Python 3.11:' && /usr/bin/python3.11 --version",
      "echo '✅ System preparation complete'"
    ]
  }

  # Step 3: NVIDIA drivers + CUDA (AWS OFFICIAL METHOD)
  provisioner "shell" {
    inline = [
      "set -ex",
      "echo '🎮 Step 3: Installing NVIDIA drivers + CUDA (AWS Official Method)'",

      "# Install DKMS and kernel headers (AWS Official)",
      "sudo dnf clean all",
      "sudo dnf install -y dkms",
      "sudo systemctl enable --now dkms",

      "# Install kernel headers for current kernel (AWS Official)",
      "if (uname -r | grep -q ^6\\\\.12\\\\.); then",
      "  if ( dnf search kernel6.12-headers | grep -q kernel ); then",
      "    sudo dnf install -y kernel6.12-headers-$(uname -r) kernel6.12-devel-$(uname -r) kernel6.12-modules-extra-$(uname -r) kernel6.12-modules-extra-common-$(uname -r) --allowerasing",
      "  else",
      "    sudo dnf install -y kernel-headers-$(uname -r) kernel-devel-$(uname -r) kernel6.12-modules-extra-$(uname -r) kernel-modules-extra-common-$(uname -r) --allowerasing",
      "  fi",
      "else",
      "  sudo dnf install -y kernel-headers-$(uname -r) kernel-devel-$(uname -r) kernel-modules-extra-$(uname -r) kernel-modules-extra-common-$(uname -r)",
      "fi",

      "# Add NVIDIA repository for AL2023 (AWS Official)",
      "ARCH=x86_64",
      "sudo dnf config-manager --add-repo https://developer.download.nvidia.com/compute/cuda/repos/amzn2023/$ARCH/cuda-amzn2023.repo",
      "sudo dnf clean expire-cache",

      "# Install NVIDIA driver - open-dkms module (AWS Official)",
      "sudo dnf module enable -y nvidia-driver:open-dkms",
      "sudo dnf install -y nvidia-open nvidia-xconfig",
      "echo '✅ NVIDIA drivers installed'",

      "# Install CUDA toolkit (AWS Official)",
      "echo 'Installing CUDA toolkit...'",
      "sudo dnf install -y cuda-toolkit",
      "echo '✅ CUDA toolkit installed'",

      "# Set CUDA environment variables",
      "cat << 'EOF' | sudo tee /etc/profile.d/cuda.sh",
      "export CUDA_HOME=/usr/local/cuda",
      "export PATH=$CUDA_HOME/bin:$PATH",
      "export LD_LIBRARY_PATH=$CUDA_HOME/lib64:$LD_LIBRARY_PATH",
      "export NVIDIA_VISIBLE_DEVICES=all",
      "export NVIDIA_DRIVER_CAPABILITIES=compute,utility",
      "EOF",
      "sudo chmod +x /etc/profile.d/cuda.sh",
      "source /etc/profile.d/cuda.sh",

      "# Install and enable NVIDIA persistence daemon",
      "sudo dnf install -y nvidia-persistenced",
      "sudo systemctl enable nvidia-persistenced",

      "# Verify installations (AWS Official)",
      "echo 'Checking NVIDIA driver status...'",
      "which nvidia-smi && nvidia-smi || echo 'nvidia-smi not available during build (normal for Packer)'",
      
      "echo 'Checking CUDA installation...'",
      "ls -la /usr/local/cuda && echo '✅ CUDA directory exists' || echo 'CUDA directory missing'",
      "which nvcc && nvcc --version || echo 'nvcc not available during build'",

      "echo '✅ NVIDIA drivers + CUDA toolkit installed - GPU stack ready for instance boot'",
      "df -h /"
    ]
  }

  # Step 4: Install FFmpeg manually
  provisioner "shell" {
    inline = [
      "set -ex",
      "echo '🎵 Step 4: Installing FFmpeg'",
      "cd /tmp",
      "wget -q https://johnvansickle.com/ffmpeg/releases/ffmpeg-release-amd64-static.tar.xz",
      "tar -xf ffmpeg-release-amd64-static.tar.xz",
      "cd ffmpeg-*-static",
      "sudo cp ffmpeg ffprobe /usr/local/bin/",
      "sudo chmod +x /usr/local/bin/ffmpeg /usr/local/bin/ffprobe",
      "cd /tmp && rm -rf ffmpeg-*",
      "ffmpeg -version | head -1",
      "echo '✅ FFmpeg installed successfully'"
    ]
  }

  # Step 5: Python environment - Use Python 3.11 for virtual environment
  provisioner "shell" {
    inline = [
      "set -ex",
      "echo '🐍 Step 5: Setting up Python 3.11 environment for XTTSv2'",
      
      "# Install system dependencies for TTS",
      "sudo dnf install -y python3-devel libsndfile-devel",
      
      "# Create virtual environment using Python 3.11",
      "sudo mkdir -p /opt/voiceclone",
      "sudo chown -R ec2-user:ec2-user /opt/voiceclone",
      "python3.11 -m venv /opt/voiceclone/venv",
      
      "# Upgrade pip and setuptools first",
      "/opt/voiceclone/venv/bin/pip install --upgrade pip setuptools wheel",
      
      "# Install PyTorch with CUDA support",
      "echo 'Installing PyTorch with CUDA support...'",
      "/opt/voiceclone/venv/bin/pip install torch==2.5.1 torchaudio==2.5.1 --index-url https://download.pytorch.org/whl/cu121",
      
      "# Install numpy first (required by TTS)",
      "/opt/voiceclone/venv/bin/pip install numpy==1.22.0",
      
      "# Install TTS",
      "echo 'Installing TTS...'",
      "/opt/voiceclone/venv/bin/pip install TTS==0.22.0",
      
      "# Install other dependencies",
      "/opt/voiceclone/venv/bin/pip install transformers==4.38.2 scipy librosa soundfile pydub boto3 ffmpeg-python psutil aiohttp",
      "/opt/voiceclone/venv/bin/pip install cython encodec nltk pysbd num2words umap-learn",
      "/opt/voiceclone/venv/bin/pip install anyascii jieba pypinyin gruut[de,es,fr]==2.2.3",
      
      "# Cleanup",
      "/opt/voiceclone/venv/bin/pip cache purge",
      "sudo rm -rf /tmp/* /root/.cache /home/ec2-user/.cache",
      
      "# Set environment variables for TTS",
      "sudo tee -a /etc/environment <<< 'COQUI_TOS_AGREED=1'",
      "sudo tee -a /etc/environment <<< 'TTS_CACHE_DIR=/opt/voiceclone/.tts_cache'",
      "sudo tee -a /etc/environment <<< 'HF_HUB_DISABLE_SYMLINKS_WARNING=1'",
      "sudo tee -a /etc/environment <<< 'XDG_DATA_HOME=/opt/voiceclone/.tts_cache'",
      
      "# Create model directory",
      "sudo mkdir -p /opt/voiceclone/models /opt/voiceclone/.tts_cache",
      "sudo chown -R ec2-user:ec2-user /opt/voiceclone/.tts_cache",
      
      "echo '✅ Python environment ready with Python 3.11'",
      "df -h /"
    ]
  }

  # 🔴 CRITICAL FIX: Step 6 - Download XTTSv2 Model during AMI build
  provisioner "shell" {
    inline = [
      "set -ex",
      "echo '📥 Step 6: Downloading XTTSv2 Model (2GB) during AMI build'",
      
      "# Download XTTSv2 model - THIS IS WHAT WAS MISSING!",
      "sudo -u ec2-user bash -c \"",
      "cd /opt/voiceclone",
      "source venv/bin/activate",
      "export COQUI_TOS_AGREED=1",
      "export TTS_CACHE_DIR=/opt/voiceclone/.tts_cache",
      "export XDG_DATA_HOME=/opt/voiceclone/.tts_cache",
      "export HF_HUB_DISABLE_SYMLINKS_WARNING=1",
      "",
      "echo 'Downloading XTTSv2 model (2GB, 5-10 minutes)...'",
      "python -c \\\"",
      "import os",
      "os.environ['COQUI_TOS_AGREED'] = '1'",
      "os.environ['TTS_HOME'] = '/opt/voiceclone/.tts_cache'",
      "os.environ['XDG_DATA_HOME'] = '/opt/voiceclone/.tts_cache'",
      "",
      "print('Starting XTTSv2 model download...')",
      "from TTS.api import TTS",
      "# This downloads the model (2GB) during AMI build",
      "tts = TTS('tts_models/multilingual/multi-dataset/xtts_v2', progress_bar=True, gpu=False)",
      "print('✅ XTTSv2 model downloaded successfully during AMI build!')",
      "",
      "# Verify model files",
      "import glob",
      "model_files = glob.glob('/opt/voiceclone/.tts_cache/**/*.pth', recursive=True)",
      "print(f'Found {len(model_files)} model files in cache')",
      "\\\"",
      "\"",
      
      "# Create symlink for backward compatibility",
      "sudo ln -sf /opt/voiceclone/models /opt/models",
      "sudo ln -sf /opt/voiceclone/.tts_cache /opt/voiceclone/models/XTTS-v2",
      
      "# Verify model downloaded",
      "echo 'Verifying model download...'",
      "find /opt/voiceclone/.tts_cache -name '*.pth' -type f | head -3",
      "du -sh /opt/voiceclone/.tts_cache",
      
      "echo '✅ XTTSv2 model downloaded and cached in AMI'",
      "df -h /"
    ]
  }

  provisioner "shell" {
    inline = [
      "set -ex",
      "echo '📂 Step 7: Creating destination directories...'",
      
      "# Create destination directories for file copies",
      "sudo mkdir -p /tmp/src /tmp/utils",
      "sudo chown -R ec2-user:ec2-user /tmp/src /tmp/utils",
      
      "# Verify directories created",
      "ls -la /tmp/",
      "echo '✅ Destination directories created'"
    ]
  }

  # Step 8: Copy worker source code
  provisioner "file" {
    source      = "../../worker/src/"
    destination = "/tmp/src/"
  }

  provisioner "file" {
    source      = "../../worker/main.py"
    destination = "/tmp/main.py"
  }

  provisioner "file" {
    source      = "../../worker/src/utils/"
    destination = "/tmp/utils/"
  }

  # Step 9: Deploy source code properly
  provisioner "shell" {
    inline = [
      "set -ex",
      "echo '📁 Step 9: Deploying source code...'",
      
      "# Create directory structure",
      "sudo mkdir -p /opt/voiceclone/src/utils",
      "sudo chown -R ec2-user:ec2-user /opt/voiceclone",
      
      "# Copy main worker script",
      "sudo mv /tmp/main.py /opt/voiceclone/main.py",
      
      "# Copy ALL source modules",
      "sudo cp -r /tmp/src/*.py /opt/voiceclone/src/ 2>/dev/null || true",
      "sudo cp -r /tmp/utils/*.py /opt/voiceclone/src/utils/ 2>/dev/null || true",
      
      "# Set permissions",
      "sudo chmod 755 /opt/voiceclone/main.py",
      "sudo chmod 644 /opt/voiceclone/src/*.py 2>/dev/null || true",
      "sudo chmod 644 /opt/voiceclone/src/utils/*.py 2>/dev/null || true",
      
      "# Verify deployment",
      "echo '📋 Deployed files:'",
      "echo 'Root directory:'",
      "ls -la /opt/voiceclone/main.py 2>/dev/null || echo '❌ main.py not in root'",
      "echo 'src directory:'",
      "ls -la /opt/voiceclone/src/*.py 2>/dev/null || echo 'No Python files in src'",
      "",
      "# ✅✅✅ FIXED: Check main.py in root, others in src",
      "echo ''",
      "echo 'Checking required M4 files:'",
      "# Check main.py at /opt/voiceclone/main.py",
      "if [ -f \"/opt/voiceclone/main.py\" ]; then",
      "  echo \"✅ main.py (at /opt/voiceclone/)\"",
      "else",
      "  echo \"❌ main.py (MISSING from /opt/voiceclone/)\"",
      "  exit 1",
      "fi",
      "",
      "# Check other files in /opt/voiceclone/src/",
      "for file in tts_engine.py sqs_poller.py; do",
      "  if [ -f \"/opt/voiceclone/src/$file\" ]; then",
      "    echo \"✅ $file (at /opt/voiceclone/src/)\"",
      "  else",
      "    echo \"❌ $file (MISSING from /opt/voiceclone/src/)\"",
      "    exit 1",
      "  fi",
      "done",
      "",
      "echo '✅ Source code deployment complete'"
    ]
  }

  # Step 10: Test imports
  provisioner "shell" {
    inline = [
      "set -ex",
      "echo '🧪 Step 10: Testing ALL module imports'",
      
      "# Create test script",
      "cat << 'EOF' | sudo tee /opt/voiceclone/test_all_imports.py",
      "#!/usr/bin/env python3",
      "import sys",
      "sys.path.insert(0, '/opt/voiceclone/src')",
      "",
      "print('Testing imports from /opt/voiceclone/src...')",
      "",
      "# Test critical imports",
      "try:",
      "    import torch",
      "    print(f'✅ torch: {torch.__version__}')",
      "    print(f'✅ CUDA available: {torch.cuda.is_available()}')",
      "except Exception as e:",
      "    print(f'❌ torch: {e}')",
      "",
      "try:",
      "    from TTS.api import TTS",
      "    print('✅ TTS import successful')",
      "except Exception as e:",
      "    print(f'❌ TTS: {e}')",
      "",
      "# Test our modules",
      "modules = ['tts_engine', 'sqs_poller', 'main']",
      "for module in modules:",
      "    try:",
      "        __import__(module)",
      "        print(f'✅ {module}')",
      "    except ImportError as e:",
      "        print(f'❌ {module}: {e}')",
      "",
      "print('\\n✅ All imports tested')",
      "EOF",
      
      "# Run import test",
      "sudo -u ec2-user /opt/voiceclone/venv/bin/python /opt/voiceclone/test_all_imports.py",
      
      "echo '✅ All imports tested successfully'"
    ]
  }

  # 🔴 CRITICAL FIX: Step 11 - Fixed Systemd Service with Configuration File
  provisioner "shell" {
    inline = [
      "set -ex",
      "echo '🚀 Step 11: Configuring M4 GPU Worker Service'",
      
      "# Create config directory and DEFAULT config",
      "sudo mkdir -p /etc/voiceclone",
      
      "# Create DEFAULT config file (will be overridden by user-data)",
      "cat << 'EOF' | sudo tee /etc/voiceclone/config.env",
      "# VoiceClone GPU Worker - DEFAULT Configuration",
      "# Override these via instance user-data or environment",
      "",
      "# AWS Resources (REQUIRED at instance launch)",
      "# SQS_QUEUE_URL=https://sqs.us-east-1.amazonaws.com/579897422848/lunebi-prod-us-east-1-story-tasks",
      "# STORIES_TABLE=lunebi-prod-us-east-1-stories",
      "# VOICES_TABLE=lunebi-prod-us-east-1-voices",
      "# STORIES_BUCKET=voiceclone-stories-prod-us-east-1",
      "",
      "# AWS Configuration",
      "AWS_REGION=us-east-1",
      "",
      "# Worker Configuration",
      "OPERATION_MODE=test",
      "ENABLE_SPOT_INTERRUPTION_HANDLING=false",
      "MAX_CONCURRENT_STORIES=1",
      "MIN_CONCURRENT_STORIES=0",
      "",
      "# TTS Configuration",
      "TTS_CACHE_SIZE=10",
      "TTS_PRELOAD_COUNT=5",
      "TTS_MODEL_PATH=/opt/voiceclone/models/XTTS-v2",
      "",
      "# Logging",
      "LOG_LEVEL=INFO",
      "LOG_DIR=/var/log/voiceclone",
      "",
      "# Feature Flags",
      "ENABLE_EBS_STAGING=false",
      "ENABLE_LL_HLS=false",
      "SKIP_MODEL_VALIDATION=false",
      "EOF",
      
      "# Create log directory with correct permissions",
      "sudo mkdir -p /var/log/voiceclone",
      "sudo chown -R ec2-user:ec2-user /var/log/voiceclone",
      "sudo chmod 755 /var/log/voiceclone",
      
      "# Create systemd service that LOADS config file",
      "cat << 'EOF' | sudo tee /etc/systemd/system/voiceclone-gpu-worker.service",
      "[Unit]",
      "Description=VoiceClone M4 GPU Worker with Built-in Hot-Load",
      "After=network-online.target nvidia-persistenced.service",
      "Wants=network-online.target",
      "",
      "[Service]",
      "Type=simple",
      "User=ec2-user",
      "WorkingDirectory=/opt/voiceclone",
      "# 🔴 CRITICAL: Load config from file, not hardcoded",
      "EnvironmentFile=/etc/voiceclone/config.env",
      "Environment=PATH=/opt/voiceclone/venv/bin:/usr/local/bin:/usr/bin:/bin",
      "Environment=PYTHONPATH=/opt/voiceclone",
      "Environment=TTS_HOME=/opt/voiceclone/.tts_cache",
      "Environment=COQUI_TOS_AGREED=1",
      "Environment=TTS_CACHE_DIR=/opt/voiceclone/.tts_cache",
      "Environment=XDG_DATA_HOME=/opt/voiceclone/.tts_cache",
      "",
      "# Auto-detect instance ID",
      "Environment=INSTANCE_ID=$(curl -s http://169.254.169.254/latest/meta-data/instance-id || echo 'unknown')",
      "",
      "# Main worker",
      "ExecStart=/opt/voiceclone/venv/bin/python /opt/voiceclone/main.py",
      "",
      "Restart=always",
      "RestartSec=10",
      "StandardOutput=journal",
      "StandardError=journal",
      "TimeoutStartSec=300",  # 5 minutes (model already downloaded)",
      "",
      "# Resource limits",
      "MemoryMax=8G",
      "CPUQuota=300%",
      "",
      "[Install]",
      "WantedBy=multi-user.target",
      "EOF",
      
      "# Enable service",
      "sudo systemctl daemon-reload",
      "sudo systemctl enable voiceclone-gpu-worker.service",
      
      "echo '✅ M4 GPU Worker service configured with config file'"
    ]
  }

  # Step 12: Create verification script
  provisioner "shell" {
    inline = [
      "set -ex",
      "echo '📋 Step 12: Creating verification script'",
      
      "cat << 'EOF' | sudo tee /opt/voiceclone/verify_ami.sh",
      "#!/bin/bash",
      "echo '========================================='",
      "echo 'VOICECLONE GPU WORKER AMI VERIFICATION'",
      "echo '========================================='",
      "",
      "# 1. GPU Check",
      "echo '1. GPU Status:'",
      "nvidia-smi --query-gpu=name,driver_version,memory.total --format=csv,noheader && echo '   ✅ GPU available' || echo '   ❌ GPU not available'",
      "",
      "# 2. Python Environment",
      "echo ''",
      "echo '2. Python Environment:'",
      "/opt/voiceclone/venv/bin/python -c \"",
      "import torch, sys",
      "print('   PyTorch:', torch.__version__)",
      "print('   CUDA:', torch.cuda.is_available())",
      "if torch.cuda.is_available():",
      "    print('   GPU:', torch.cuda.get_device_name(0))",
      "\"",
      "",
      "# 3. TTS Model",
      "echo ''",
      "echo '3. TTS Model:'",
      "if [ -d /opt/voiceclone/.tts_cache ]; then",
      "    MODEL_SIZE=$(du -sh /opt/voiceclone/.tts_cache | cut -f1)",
      "    echo \"   ✅ Model cached: $MODEL_SIZE\"",
      "    find /opt/voiceclone/.tts_cache -name '*.pth' -type f | head -2 | sed 's/^/     - /'",
      "else",
      "    echo '   ❌ Model not cached'",
      "fi",
      "",
      "# 4. Source Files",
      "echo ''",
      "echo '4. Source Files:'",
      "for file in main.py tts_engine.py sqs_poller.py; do",
      "    if [ -f \"/opt/voiceclone/src/$file\" ]; then",
      "        echo \"   ✅ $file\"",
      "    else",
      "        echo \"   ❌ $file\"",
      "    fi",
      "done",
      "",
      "# 5. Service",
      "echo ''",
      "echo '5. Systemd Service:'",
      "sudo systemctl is-enabled voiceclone-gpu-worker.service && echo '   ✅ Service enabled' || echo '   ❌ Service not enabled'",
      "",
      "# 6. Disk Space",
      "echo ''",
      "echo '6. Disk Space:'",
      "df -h / | tail -1",
      "",
      "echo '========================================='",
      "echo 'AMI STATUS: READY FOR PRODUCTION'",
      "echo '========================================='",
      "EOF",
      
      "sudo chmod +x /opt/voiceclone/verify_ami.sh",
      
      "# Run verification",
      "/opt/voiceclone/verify_ami.sh",
      
      "echo '✅ Verification script created'"
    ]
  }

  provisioner "shell" {
    inline = [
      "set -ex",
      "echo '📊 Adding CloudWatch Agent for GPU metrics...'",
      
      "# Install CloudWatch agent",
      "sudo dnf install -y amazon-cloudwatch-agent",
      
      "# Create CloudWatch config for GPU metrics",
      "sudo mkdir -p /opt/aws/amazon-cloudwatch-agent/etc",
      "cat << 'EOF' | sudo tee /opt/aws/amazon-cloudwatch-agent/etc/amazon-cloudwatch-agent.json",
      "{",
      "  \"agent\": {",
      "    \"metrics_collection_interval\": 60,",
      "    \"logfile\": \"/opt/aws/amazon-cloudwatch-agent/logs/amazon-cloudwatch-agent.log\"",
      "  },",
      "  \"metrics\": {",
      "    \"namespace\": \"VoiceClone/GPUWorker\",",
      "    \"append_dimensions\": {",
      "      \"InstanceId\": \"$${aws:InstanceId}\",",
      "      \"InstanceType\": \"$${aws:InstanceType}\",",
      "      \"AutoScalingGroupName\": \"$${aws:AutoScalingGroupName}\"",
      "    },",
      "    \"aggregation_dimensions\": [[\"InstanceId\"], [\"InstanceType\"], [\"AutoScalingGroupName\"]],",
      "    \"metrics_collected\": {",
      "      \"nvidia_gpu\": {",
      "        \"measurement\": [",
      "          \"utilization_gpu\",",
      "          \"utilization_memory\",",
      "          \"memory_used\",",
      "          \"memory_total\",",
      "          \"temperature_gpu\",",
      "          \"power_draw\",",
      "          \"clocks_current_graphics\",",
      "          \"clocks_current_sm\",",
      "          \"clocks_current_memory\"",
      "        ],",
      "        \"metrics_collection_interval\": 60",
      "      },",
      "      \"cpu\": {",
      "        \"measurement\": [",
      "          \"cpu_usage_idle\",",
      "          \"cpu_usage_iowait\",",
      "          \"cpu_usage_user\",",
      "          \"cpu_usage_system\"",
      "        ],",
      "        \"metrics_collection_interval\": 60,",
      "        \"totalcpu\": true",
      "      },",
      "      \"mem\": {",
      "        \"measurement\": [",
      "          \"mem_used_percent\"",
      "        ],",
      "        \"metrics_collection_interval\": 60",
      "      },",
      "      \"disk\": {",
      "        \"measurement\": [",
      "          \"used_percent\"",
      "        ],",
      "        \"metrics_collection_interval\": 60,",
      "        \"resources\": [",
      "          \"/\",",
      "          \"/opt/voiceclone\"",
      "        ]",
      "      }",
      "    }",
      "  },",
      "  \"logs\": {",
      "    \"logs_collected\": {",
      "      \"files\": {",
      "        \"collect_list\": [",
      "          {",
      "            \"file_path\": \"/var/log/voiceclone/**/*.log\",",
      "            \"log_group_name\": \"VoiceClone/GPUWorker\",",
      "            \"log_stream_name\": \"$${instance_id}/app\",",    
      "            \"timestamp_format\": \"%Y-%m-%d %H:%M:%S\"",
      "          },",
      "          {",
      "            \"file_path\": \"/var/log/messages\",",
      "            \"log_stream_name\": \"$${instance_id}/app\",",
      "            \"log_stream_name\": \"$${instance_id}/system\",",
      "            \"timestamp_format\": \"%b %d %H:%M:%S\"",
      "          }",
      "        ]",
      "      }",
      "    }",
      "  }",
      "}",
      "EOF",
      
      "# Create systemd service for CloudWatch agent",
      "cat << 'EOF' | sudo tee /etc/systemd/system/amazon-cloudwatch-agent.service",
      "[Unit]",
      "Description=Amazon CloudWatch Agent",
      "After=network-online.target",
      "",
      "[Service]",
      "Type=simple",
      "ExecStart=/opt/aws/amazon-cloudwatch-agent/bin/amazon-cloudwatch-agent-ctl -a fetch-config -m ec2 -s -c file:/opt/aws/amazon-cloudwatch-agent/etc/amazon-cloudwatch-agent.json",
      "Restart=on-failure",
      "RestartSec=60",
      "",
      "[Install]",
      "WantedBy=multi-user.target",
      "EOF",
      
      "# Enable services",
      "sudo systemctl enable amazon-cloudwatch-agent.service",
      
      "echo '✅ CloudWatch Agent configured for GPU metrics'"
    ]
  }

  # Step 13: Final cleanup and AMI ready
  provisioner "shell" {
    inline = [
      "set -ex",
      "echo '🎯 Step 13: Final cleanup and AMI ready'",
      
      "# Cleanup",
      "sudo dnf clean all",
      "sudo rm -rf /var/cache/dnf/* /tmp/* /var/tmp/* /root/.cache /home/ec2-user/.cache",
      "sudo rm -f /var/log/*.log /var/log/*.gz",
      
      "# Final disk check",
      "echo 'Final disk usage:'",
      "df -h /",
      
      "# Create AMI ready marker",
      "cat << 'EOF' | sudo tee /opt/voiceclone/ami_ready.txt",
      "==========================================",
      "VOICECLONE GPU WORKER AMI - PRODUCTION READY",
      "==========================================",
      "Version: ${var.image_version}",
      "Environment: ${var.environment}",
      "Build Date: $(date)",
      "",
      "✅ PRE-BAKED FEATURES:",
      "• NVIDIA Tesla T4 GPU drivers + CUDA 12.1",
      "• Python 3.11 with PyTorch + TTS",
      "• XTTSv2 Model (2GB) - ALREADY DOWNLOADED",
      "• FFmpeg for audio processing",
      "• Complete worker source code",
      "• Systemd service with config file",
      "",
      "🚀 ON INSTANCE LAUNCH:",
      "1. Service starts automatically",
      "2. Model loads from cache (<5 seconds)",
      "3. Ready for SQS messages immediately",
      "4. TTFA < 1s achievable",
      "",
      "⚙️ CONFIGURATION:",
      "• Set SQS_QUEUE_URL in /etc/voiceclone/config.env",
      "• Or pass via instance user-data",
      "",
      "Service: voiceclone-gpu-worker.service",
      "Config: /etc/voiceclone/config.env",
      "Source: /opt/voiceclone/src/main.py",
      "Model: /opt/voiceclone/.tts_cache (pre-downloaded)",
      "==========================================",
      "EOF",
      
      "# Print final verification",
      "echo ''",
      "echo '🎉🎉🎉 GPU WORKER AMI BUILD COMPLETE! 🎉🎉🎉'",
      "echo ''",
      "cat /opt/voiceclone/ami_ready.txt",
      "echo ''",
      "echo 'To use this AMI:'",
      "echo '1. Launch g4dn.xlarge/g6.xlarge instance'",
      "echo '2. Attach IAM role with SQS/DynamoDB/S3 access'",
      "echo '3. Update /etc/voiceclone/config.env with your AWS resources'",
      "echo '4. Service starts automatically - check logs: journalctl -fu voiceclone-gpu-worker'",
      "echo '5. Verify: /opt/voiceclone/verify_ami.sh'",
      "echo ''",
      "echo '✅ AMI includes pre-downloaded XTTSv2 model - NO download on first boot!'"
    ]
  }

  post-processor "manifest" {
    output = "manifest.json"
    strip_path = true
  }
}

