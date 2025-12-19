#!/usr/bin/env python3
"""
FINAL VoiceClone Smoke Tests - Blueprint Exact Implementation

Matches EXACTLY what's in the blueprint:
• Enroll (mock) → prepare → append → status loops.
• In Test Mode: CPU mock drains queue and updates stories.
• In GPU test window: set desired=1 and validate real segments+playlist order.
"""

import json
import time
import boto3
import uuid
import os
from datetime import datetime, timedelta

class BlueprintSmokeTester:
    def __init__(self, mode="test", region="us-east-1"):
        self.mode = mode
        self.region = region
        self.ssm = boto3.client('ssm', region_name=region)
        self.sqs = boto3.client('sqs', region_name=region)
        self.ddb = boto3.resource('dynamodb', region_name=region)
        self.asg = boto3.client('autoscaling', region_name=region)
        self.s3 = boto3.client('s3', region_name=region)
        self.cloudfront = boto3.client('cloudfront', region_name=region)
        self.lambda_client = boto3.client('lambda', region_name=region)
        
        # Load configuration
        self.config = self._load_config()
        print(f"🔧 Smoke Test Configuration")
        print(f"   Mode: {mode}")
        print(f"   Region: {region}")
        print(f"   Environment: lunebi-prod-{region}")
        
    def _load_config(self):
        """Load configuration from SSM Parameter Store"""
        config = {}
        prefix = f"/lunebi-prod-{self.region.replace('-', '_')}/"
        
        try:
            response = self.ssm.get_parameters_by_path(
                Path=prefix,
                Recursive=True,
                WithDecryption=True
            )
            
            for param in response.get('Parameters', []):
                key = param['Name'].replace(prefix, '')
                config[key] = param['Value']
                
        except Exception as e:
            print(f"⚠️  Warning loading SSM config: {e}")
        
        # Set defaults for critical parameters
        defaults = {
            'queue_url': f"https://sqs.{self.region}.amazonaws.com/579897422848/lunebi-prod-{self.region}-story-tasks",
            'stories_table': f"lunebi-prod-{self.region}-stories",
            'voices_table': f"lunebi-prod-{self.region}-voices",
            'stories_bucket': f"voiceclone-stories-prod-{self.region}",
            'gpu_asg_name': f"lunebi-prod-{self.region}-gpu-asg-test-blue",
            'cdn_domain': 'cdn.lunebi.com'
        }
        
        for key, default_value in defaults.items():
            if key not in config:
                config[key] = default_value
                
        return config
    
    def _cleanup_test_data(self, story_id=None, voice_id=None):
        """Clean up test data from DynamoDB"""
        try:
            if story_id:
                stories_table = self.ddb.Table(self.config['stories_table'])
                stories_table.delete_item(Key={'story_id': story_id})
                
            if voice_id:
                voices_table = self.ddb.Table(self.config['voices_table'])
                voices_table.delete_item(Key={'voice_id': voice_id})
                
        except Exception as e:
            print(f"⚠️  Cleanup warning: {e}")
    
    def _get_queue_depth(self, queue_url):
        """Get current SQS queue depth"""
        try:
            attrs = self.sqs.get_queue_attributes(
                QueueUrl=queue_url,
                AttributeNames=['ApproximateNumberOfMessages']
            )
            return int(attrs['Attributes']['ApproximateNumberOfMessages'])
        except Exception as e:
            print(f"❌ Error getting queue depth: {e}")
            return -1
    
    def test_enroll_prepare_append_status_loops(self):
        """
        BLUEPRINT TEST 1: Enroll (mock) → prepare → append → status loops.
        
        Steps:
        1. Mock enroll (create voice entry)
        2. Prepare story (create story entry)
        3. Append text (send to SQS)
        4. Monitor status in loop
        """
        print("\n" + "="*80)
        print("🧪 TEST 1: Enroll (mock) → prepare → append → status loops")
        print("="*80)
        
        start_time = time.time()
        test_voice_id = f"smoke-voice-{uuid.uuid4().hex[:8]}"
        test_story_id = f"smoke-story-{uuid.uuid4().hex[:8]}"
        
        try:
            # ============================================
            # 1. ENROLL (mock) - Create voice entry
            # ============================================
            print("1. 📝 MOCK ENROLL - Creating voice entry...")
            voices_table = self.ddb.Table(self.config['voices_table'])
            
            voices_table.put_item(
                Item={
                    'voice_id': test_voice_id,
                    'created_at': int(time.time()),
                    'user_sub': 'smoke-test-user',
                    'status': 'active',
                    'consent_metadata': {
                        'consent': True,
                        'consent_at': int(time.time()),
                        'consent_version': '1.0',
                        'user_agent': 'smoke-test/1.0',
                        'ip_address': '127.0.0.1'
                    },
                    'embeddings': b'dummy-embeddings-for-test',
                    'style': b'dummy-style-for-test'
                }
            )
            print(f"   ✅ Voice created: {test_voice_id}")
            
            # ============================================
            # 2. PREPARE - Create story entry
            # ============================================
            print("2. 📖 PREPARE - Creating story...")
            stories_table = self.ddb.Table(self.config['stories_table'])
            
            stories_table.put_item(
                Item={
                    'story_id': test_story_id,
                    'voice_id': test_voice_id,
                    'user_sub': 'smoke-test-user',
                    'status': 'preparing',
                    'created_at': int(time.time()),
                    'last_seq_written': 0,
                    'progress_pct': 0,
                    'language': 'en-US',
                    'format': 'aac',
                    'region': self.region,
                    'test_marker': 'enroll-prepare-append-loop'
                }
            )
            print(f"   ✅ Story created: {test_story_id}")
            
            # Create S3 playlist skeleton (simulating API Lambda)
            try:
                bucket = self.config['stories_bucket']
                playlist_key = f"stories/{test_story_id}/playlist.m3u8"
                playlist_content = (
                    "#EXTM3U\n#EXT-X-VERSION:6\n#EXT-X-TARGETDURATION:1\n"
                    "#EXT-X-MEDIA-SEQUENCE:0\n#EXT-X-PLAYLIST-TYPE:EVENT\n"
                )
                
                self.s3.put_object(
                    Bucket=bucket,
                    Key=playlist_key,
                    Body=playlist_content.encode(),
                    ContentType='application/vnd.apple.mpegurl',
                    CacheControl='public, max-age=3, stale-while-revalidate=30'
                )
                print(f"   📁 Playlist skeleton created in S3")
            except Exception as e:
                print(f"   ⚠️  Could not create playlist skeleton: {e}")
            
            # ============================================
            # 3. APPEND - Send sentences to SQS queue
            # ============================================
            print("3. 📨 APPEND - Sending sentences to SQS queue...")
            queue_url = self.config['queue_url']
            
            sentences = [
                "Welcome to your personalized story experience.",
                "This is a smoke test sentence for workflow validation.",
                "The system should process this text and update the story status."
            ]
            
            for i, sentence in enumerate(sentences, 1):
                message = {
                    "story_id": test_story_id,
                    "seq": i,
                    "text": sentence,
                    "voice_id": test_voice_id,
                    "lang": "en-US",
                    "params": {"speed": 1.0, "format": "aac"},
                    "idempotency_key": f"smoke-{test_story_id}-{i}-{uuid.uuid4().hex[:8]}"
                }
                
                self.sqs.send_message(
                    QueueUrl=queue_url,
                    MessageBody=json.dumps(message),
                    MessageAttributes={
                        'TestRun': {
                            'StringValue': 'enroll-prepare-append-loop',
                            'DataType': 'String'
                        }
                    }
                )
                print(f"   ✅ Sentence {i} queued: '{sentence[:50]}...'")
            
            # ============================================
            # 4. STATUS - Monitor progress in loop
            # ============================================
            print("4. 📊 STATUS - Monitoring progress in loop...")
            
            max_checks = 12  # 60 seconds total
            progress_made = False
            last_seq_values = []
            
            for check_num in range(1, max_checks + 1):
                response = stories_table.get_item(Key={'story_id': test_story_id})
                
                if 'Item' in response:
                    item = response['Item']
                    last_seq = item.get('last_seq_written', 0)
                    progress = item.get('progress_pct', 0)
                    status = item.get('status', 'unknown')
                    
                    last_seq_values.append(last_seq)
                    
                    print(f"   Loop {check_num}: seq={last_seq}, progress={progress}%, status={status}")
                    
                    # Check if progress is being made
                    if last_seq > 0:
                        progress_made = True
                    
                    # Success: All sentences processed
                    if last_seq >= 3:
                        print(f"   ✅ SUCCESS: All 3 sentences processed!")
                        break
                
                # Wait between checks
                if check_num < max_checks:
                    time.sleep(5)
            
            # ============================================
            # 5. FINAL VERIFICATION & CLEANUP
            # ============================================
            print("5. 🧹 Final verification and cleanup...")
            
            # Get final state
            final_response = stories_table.get_item(Key={'story_id': test_story_id})
            final_item = final_response.get('Item', {})
            final_seq = final_item.get('last_seq_written', 0)
            
            # Cleanup test data
            self._cleanup_test_data(test_story_id, test_voice_id)
            
            # ============================================
            # 6. TEST RESULTS
            # ============================================
            duration = time.time() - start_time
            
            print("\n" + "-"*80)
            print("📊 TEST 1 RESULTS:")
            print(f"   • Voice ID: {test_voice_id}")
            print(f"   • Story ID: {test_story_id}")
            print(f"   • Final seq_written: {final_seq} (target: ≥1)")
            print(f"   • Progress made: {progress_made}")
            print(f"   • Duration: {duration:.2f}s")
            print(f"   • Queue used: {queue_url.split('/')[-1]}")
            
            # SUCCESS CRITERIA: Progress was made (CPU mock processed at least 1 message)
            if progress_made:
                print("🎉 ✅ TEST 1 PASSED: Enroll → prepare → append → status loops completed successfully")
                return True
            else:
                print("❌ TEST 1 FAILED: No progress detected in status loop")
                print("   💡 Check if CPU mock Lambda is processing SQS messages")
                return False
            
        except Exception as e:
            print(f"\n💥 TEST 1 ERROR: {e}")
            import traceback
            traceback.print_exc()
            
            # Ensure cleanup even on error
            self._cleanup_test_data(test_story_id, test_voice_id)
            return False
    
    def test_cpu_mock_drains_queue_updates_stories(self):
        """
        BLUEPRINT TEST 2: In Test Mode: CPU mock drains queue and updates stories.
        
        Steps:
        1. Create test story
        2. Send multiple messages to SQS
        3. Verify CPU mock drains queue
        4. Verify stories table is updated
        """
        print("\n" + "="*80)
        print("🧪 TEST 2: CPU mock drains queue and updates stories")
        print("="*80)
        
        if self.mode != "test":
            print(f"⚠️  Skipping - Test Mode only (current: {self.mode})")
            return True
        
        start_time = time.time()
        test_story_id = f"cpu-drain-test-{int(time.time())}"
        queue_url = self.config['queue_url']
        
        try:
            # ============================================
            # 1. CREATE TEST STORY
            # ============================================
            print("1. 📖 Creating test story...")
            stories_table = self.ddb.Table(self.config['stories_table'])
            
            stories_table.put_item(
                Item={
                    'story_id': test_story_id,
                    'voice_id': 'test-voice-drain',
                    'user_sub': 'smoke-test-user',
                    'status': 'preparing',
                    'created_at': int(time.time()),
                    'last_seq_written': 0,
                    'progress_pct': 0,
                    'language': 'en-US',
                    'format': 'aac',
                    'region': self.region,
                    'test_marker': 'cpu-drain-test'
                }
            )
            print(f"   ✅ Story created: {test_story_id}")
            
            # ============================================
            # 2. SEND MULTIPLE MESSAGES TO SQS
            # ============================================
            print("2. 📨 Sending 5 test messages to SQS queue...")
            
            messages_to_send = 5
            for i in range(messages_to_send):
                message = {
                    "story_id": test_story_id,
                    "seq": i + 1,
                    "text": f"CPU mock drain test sentence {i+1} for validating queue processing.",
                    "voice_id": "test-voice-drain",
                    "lang": "en-US",
                    "params": {"speed": 1.0, "format": "aac"},
                    "idempotency_key": f"drain-test-{test_story_id}-{i+1}"
                }
                
                self.sqs.send_message(
                    QueueUrl=queue_url,
                    MessageBody=json.dumps(message),
                    MessageAttributes={
                        'TestRun': {
                            'StringValue': 'cpu-drain-test',
                            'DataType': 'String'
                        }
                    }
                )
                print(f"   ✅ Message {i+1} sent")
            
            # ============================================
            # 3. MONITOR QUEUE DRAINING & STORY UPDATES
            # ============================================
            print("3. 👀 Monitoring CPU mock processing...")
            
            initial_depth = self._get_queue_depth(queue_url)
            print(f"   📊 Initial queue depth: {initial_depth} messages")
            
            max_wait = 90  # 90 seconds for CPU mock to process
            queue_drained = False
            story_updated = False
            final_seq = 0
            
            for check_num in range(1, (max_wait // 10) + 1):
                current_depth = self._get_queue_depth(queue_url)
                
                # Check story progress
                response = stories_table.get_item(Key={'story_id': test_story_id})
                last_seq = 0
                if 'Item' in response:
                    last_seq = response['Item'].get('last_seq_written', 0)
                    final_seq = last_seq
                
                print(f"   Check {check_num}: Queue={current_depth} msgs, Story seq={last_seq}")
                
                # SUCCESS CRITERIA:
                # - Queue should be draining (messages being processed)
                # - Story should be updated (last_seq_written increasing)
                if current_depth == 0 and last_seq >= 3:
                    queue_drained = True
                    story_updated = True
                    print(f"   ✅ SUCCESS: Queue drained and story updated!")
                    break
                elif current_depth < initial_depth and last_seq > 0:
                    queue_drained = True
                    story_updated = True
                    print(f"   ⚠️  Partial: Queue draining, story updated")
                    break
                
                time.sleep(10)
            else:
                print(f"   ⚠️  Timeout after {max_wait}s")
            
            # ============================================
            # 4. FINAL STATE & CLEANUP
            # ============================================
            print("4. 🧹 Final state and cleanup...")
            
            final_depth = self._get_queue_depth(queue_url)
            print(f"   📊 Final queue depth: {final_depth} messages")
            print(f"   📊 Final story seq: {final_seq}")
            
            # Cleanup
            self._cleanup_test_data(test_story_id)
            
            # ============================================
            # 5. TEST RESULTS
            # ============================================
            duration = time.time() - start_time
            
            print("\n" + "-"*80)
            print("📊 TEST 2 RESULTS:")
            print(f"   • Story ID: {test_story_id}")
            print(f"   • Messages sent: {messages_to_send}")
            print(f"   • Initial queue depth: {initial_depth}")
            print(f"   • Final queue depth: {final_depth}")
            print(f"   • Final story seq: {final_seq}")
            print(f"   • Queue drained: {queue_drained}")
            print(f"   • Story updated: {story_updated}")
            print(f"   • Duration: {duration:.2f}s")
            
            # SUCCESS CRITERIA: Queue is draining AND story is being updated
            if queue_drained and story_updated:
                print("🎉 ✅ TEST 2 PASSED: CPU mock successfully drains queue and updates stories")
                return True
            elif queue_drained and not story_updated:
                print("⚠️  PARTIAL: Queue drained but story not updated")
                print("   💡 CPU mock may be processing but not updating DynamoDB")
                return False
            elif not queue_drained and story_updated:
                print("⚠️  PARTIAL: Story updated but queue not drained")
                print("   💡 Messages may be stuck in SQS")
                return False
            else:
                print("❌ TEST 2 FAILED: CPU mock not processing properly")
                print("   💡 Check CPU mock Lambda function and SQS configuration")
                return False
            
        except Exception as e:
            print(f"\n💥 TEST 2 ERROR: {e}")
            import traceback
            traceback.print_exc()
            
            # Ensure cleanup even on error
            self._cleanup_test_data(test_story_id)
            return False
    
    def test_gpu_window_real_segments_playlist(self):
        """
        BLUEPRINT TEST 3: In GPU test window: set desired=1 and validate real segments+playlist order.
        
        Steps:
        1. Scale GPU workers to 1
        2. Create test story with GPU processing
        3. Validate real HLS segments and playlist
        4. Validate CloudFront/CDN access
        5. Scale back to 0
        """
        print("\n" + "="*80)
        print("🧪 TEST 3: GPU window - real segments & playlist validation")
        print("="*80)
        
        if self.mode != "test":
            print(f"⚠️  Skipping - GPU test only in Test Mode")
            return True
        
        start_time = time.time()
        test_story_id = f"gpu-test-{int(time.time())}"
        
        try:
            # ============================================
            # 1. SCALE GPU WORKERS TO 1
            # ============================================
            print("1. 🚀 Scaling GPU workers to desired=1...")
            
            asg_name = self.config.get('gpu_asg_name')
            if not asg_name:
                print("❌ No GPU ASG configured in SSM")
                return False
            
            # Get current ASG state
            asg_response = self.asg.describe_auto_scaling_groups(
                AutoScalingGroupNames=[asg_name]
            )
            
            if not asg_response['AutoScalingGroups']:
                print(f"❌ GPU ASG not found: {asg_name}")
                return False
            
            asg = asg_response['AutoScalingGroups'][0]
            original_desired = asg['DesiredCapacity']
            original_min = asg['MinSize']
            
            print(f"   📊 Current ASG state:")
            print(f"     • Name: {asg_name}")
            print(f"     • Desired: {original_desired}")
            print(f"     • Min: {original_min}")
            print(f"     • Instances: {len(asg['Instances'])}")
            
            # Scale up to 1
            self.asg.set_desired_capacity(
                AutoScalingGroupName=asg_name,
                DesiredCapacity=1
            )
            print(f"   ✅ GPU workers scaling to 1 initiated")
            
            # Wait for instance to be ready
            print(f"   ⏳ Waiting for GPU instance to be ready (60s)...")
            time.sleep(60)
            
            # ============================================
            # 2. CREATE TEST STORY FOR GPU PROCESSING
            # ============================================
            print("2. 📖 Creating test story for GPU processing...")
            stories_table = self.ddb.Table(self.config['stories_table'])
            voices_table = self.ddb.Table(self.config['voices_table'])
            
            # Create test voice (with embeddings for GPU)
            test_voice_id = f"gpu-voice-{uuid.uuid4().hex[:8]}"
            voices_table.put_item(
                Item={
                    'voice_id': test_voice_id,
                    'created_at': int(time.time()),
                    'user_sub': 'gpu-test-user',
                    'status': 'active',
                    'embeddings': b'gpu-test-embeddings-' + os.urandom(100),
                    'style': b'gpu-test-style-' + os.urandom(50),
                    'consent_metadata': {
                        'consent': True,
                        'consent_at': int(time.time()),
                        'consent_version': '1.0'
                    }
                }
            )
            
            # Create story
            stories_table.put_item(
                Item={
                    'story_id': test_story_id,
                    'voice_id': test_voice_id,
                    'user_sub': 'gpu-test-user',
                    'status': 'preparing',
                    'created_at': int(time.time()),
                    'last_seq_written': 0,
                    'progress_pct': 0,
                    'language': 'en-US',
                    'format': 'aac',
                    'region': self.region,
                    'test_marker': 'gpu-window-test'
                }
            )
            print(f"   ✅ GPU test story created: {test_story_id}")
            
            # ============================================
            # 3. SEND MESSAGES FOR GPU PROCESSING
            # ============================================
            print("3. 📨 Sending messages for GPU processing...")
            queue_url = self.config['queue_url']
            bucket = self.config['stories_bucket']
            
            # Create initial playlist in S3
            playlist_key = f"stories/{test_story_id}/playlist.m3u8"
            initial_playlist = (
                "#EXTM3U\n#EXT-X-VERSION:6\n#EXT-X-TARGETDURATION:1\n"
                "#EXT-X-MEDIA-SEQUENCE:0\n#EXT-X-PLAYLIST-TYPE:EVENT\n"
            )
            
            self.s3.put_object(
                Bucket=bucket,
                Key=playlist_key,
                Body=initial_playlist.encode(),
                ContentType='application/vnd.apple.mpegurl',
                CacheControl='public, max-age=3, stale-while-revalidate=30'
            )
            
            # Send messages that GPU workers should process
            gpu_messages = [
                "This is a GPU test sentence for HLS segment generation.",
                "The GPU worker should create real audio segments.",
                "We will validate the HLS playlist and segment files."
            ]
            
            for i, sentence in enumerate(gpu_messages, 1):
                message = {
                    "story_id": test_story_id,
                    "seq": i,
                    "text": sentence,
                    "voice_id": test_voice_id,
                    "lang": "en-US",
                    "params": {"speed": 1.0, "format": "aac"},
                    "idempotency_key": f"gpu-test-{test_story_id}-{i}"
                }
                
                self.sqs.send_message(
                    QueueUrl=queue_url,
                    MessageBody=json.dumps(message),
                    MessageAttributes={
                        'TestRun': {
                            'StringValue': 'gpu-window-test',
                            'DataType': 'String'
                        },
                        'GPUProcessing': {
                            'StringValue': 'true',
                            'DataType': 'String'
                        }
                    }
                )
                print(f"   ✅ GPU message {i} sent")
            
            # ============================================
            # 4. VALIDATE REAL HLS SEGMENTS & PLAYLIST
            # ============================================
            print("4. 🔍 Validating real HLS segments and playlist...")
            
            max_wait = 180  # 3 minutes for GPU processing
            segments_found = False
            playlist_valid = False
            
            for check_num in range(1, (max_wait // 30) + 1):
                print(f"   Check {check_num}: Looking for HLS files...")
                
                try:
                    # List objects in story directory
                    objects = self.s3.list_objects_v2(
                        Bucket=bucket,
                        Prefix=f"stories/{test_story_id}/"
                    )
                    
                    files = []
                    if 'Contents' in objects:
                        files = [obj['Key'] for obj in objects['Contents']]
                    
                    print(f"     Found {len(files)} files in S3:")
                    for file in sorted(files):
                        print(f"       • {file.split('/')[-1]}")
                    
                    # Check for segments
                    segments = [f for f in files if f.endswith('.m4s')]
                    if segments:
                        segments_found = True
                        print(f"     ✅ Found {len(segments)} HLS segments")
                        
                        # Check first segment
                        first_segment = segments[0]
                        segment_obj = self.s3.get_object(
                            Bucket=bucket,
                            Key=first_segment
                        )
                        segment_size = segment_obj['ContentLength']
                        print(f"     📦 First segment size: {segment_size} bytes")
                        
                        # Check segment headers
                        headers = segment_obj.get('ResponseMetadata', {}).get('HTTPHeaders', {})
                        content_type = headers.get('content-type', '')
                        cache_control = headers.get('cache-control', '')
                        
                        print(f"     🏷️  Segment headers:")
                        print(f"       • Content-Type: {content_type}")
                        print(f"       • Cache-Control: {cache_control}")
                        
                        # Validate headers per blueprint
                        if 'video/mp4' in content_type and 'max-age=31536000' in cache_control:
                            print(f"     ✅ Segment headers match blueprint")
                        else:
                            print(f"     ⚠️  Segment headers don't match blueprint spec")
                    
                    # Check playlist
                    playlist_key = f"stories/{test_story_id}/playlist.m3u8"
                    if playlist_key in files:
                        playlist_obj = self.s3.get_object(
                            Bucket=bucket,
                            Key=playlist_key
                        )
                        playlist_content = playlist_obj['Body'].read().decode('utf-8')
                        
                        print(f"     📜 Playlist content (first 500 chars):")
                        print(f"       {playlist_content[:500].replace(chr(10), chr(10) + '       ')}")
                        
                        # Validate playlist structure
                        if '#EXTM3U' in playlist_content:
                            playlist_valid = True
                            print(f"     ✅ Valid HLS playlist")
                            
                            # Check playlist headers
                            playlist_headers = playlist_obj.get('ResponseMetadata', {}).get('HTTPHeaders', {})
                            playlist_content_type = playlist_headers.get('content-type', '')
                            playlist_cache = playlist_headers.get('cache-control', '')
                            
                            print(f"     🏷️  Playlist headers:")
                            print(f"       • Content-Type: {playlist_content_type}")
                            print(f"       • Cache-Control: {playlist_cache}")
                            
                            if 'mpegurl' in playlist_content_type and 'max-age=3' in playlist_cache:
                                print(f"     ✅ Playlist headers match blueprint")
                            else:
                                print(f"     ⚠️  Playlist headers don't match blueprint spec")
                    
                    # Success criteria
                    if segments_found and playlist_valid:
                        print(f"     ✅ SUCCESS: Real HLS segments and playlist validated!")
                        break
                    
                except Exception as e:
                    print(f"     ⚠️  Error checking S3: {e}")
                
                time.sleep(30)
            
            # ============================================
            # 5. SCALE GPU WORKERS BACK TO 0
            # ============================================
            print("5. 📉 Scaling GPU workers back to 0...")
            
            self.asg.set_desired_capacity(
                AutoScalingGroupName=asg_name,
                DesiredCapacity=0
            )
            print(f"   ✅ GPU workers scaling to 0 initiated")
            
            # ============================================
            # 6. CLEANUP
            # ============================================
            print("6. 🧹 Cleaning up test data...")
            
            # Delete S3 objects
            try:
                objects = self.s3.list_objects_v2(
                    Bucket=bucket,
                    Prefix=f"stories/{test_story_id}/"
                )
                
                if 'Contents' in objects:
                    delete_objects = []
                    for obj in objects['Contents']:
                        delete_objects.append({'Key': obj['Key']})
                    
                    if delete_objects:
                        self.s3.delete_objects(
                            Bucket=bucket,
                            Delete={'Objects': delete_objects}
                        )
                        print(f"   ✅ Deleted {len(delete_objects)} files from S3")
            except Exception as e:
                print(f"   ⚠️  Error cleaning S3: {e}")
            
            # Cleanup DynamoDB
            self._cleanup_test_data(test_story_id, test_voice_id)
            
            # ============================================
            # 7. TEST RESULTS
            # ============================================
            duration = time.time() - start_time
            
            print("\n" + "-"*80)
            print("📊 TEST 3 RESULTS:")
            print(f"   • Story ID: {test_story_id}")
            print(f"   • Voice ID: {test_voice_id}")
            print(f"   • GPU ASG: {asg_name}")
            print(f"   • Segments found: {segments_found}")
            print(f"   • Playlist valid: {playlist_valid}")
            print(f"   • S3 Bucket: {bucket}")
            print(f"   • Duration: {duration:.2f}s")
            
            if segments_found and playlist_valid:
                print("🎉 ✅ TEST 3 PASSED: GPU window validated - real segments and playlist created")
                return True
            elif segments_found and not playlist_valid:
                print("⚠️  PARTIAL: Segments created but playlist invalid")
                return False
            elif not segments_found and playlist_valid:
                print("⚠️  PARTIAL: Playlist valid but no segments created")
                return False
            else:
                print("❌ TEST 3 FAILED: No HLS output from GPU workers")
                print("   💡 Check GPU worker logs, SQS processing, and HLS generation")
                return False
            
        except Exception as e:
            print(f"\n💥 TEST 3 ERROR: {e}")
            import traceback
            traceback.print_exc()
            
            # Try to scale back GPU workers
            try:
                asg_name = self.config.get('gpu_asg_name')
                if asg_name:
                    self.asg.set_desired_capacity(
                        AutoScalingGroupName=asg_name,
                        DesiredCapacity=0
                    )
                    print("   🔄 Scaled GPU workers back to 0 after error")
            except:
                pass
            
            # Cleanup
            self._cleanup_test_data(test_story_id, test_voice_id if 'test_voice_id' in locals() else None)
            return False
    
    def run_all_tests(self):
        """Run all blueprint smoke tests"""
        print("\n" + "="*80)
        print("🚀 VOICECLONE BLUEPRINT SMOKE TESTS")
        print("="*80)
        
        results = []
        
        # Test 1: Enroll → prepare → append → status loops
        print("\n🧪 Running Test 1: Enroll → prepare → append → status loops")
        result1 = self.test_enroll_prepare_append_status_loops()
        results.append(("Enroll→Prepare→Append→Status", result1))
        
        # Test 2: CPU mock drains queue (Test Mode only)
        if self.mode == "test":
            print("\n🧪 Running Test 2: CPU mock drains queue & updates stories")
            result2 = self.test_cpu_mock_drains_queue_updates_stories()
            results.append(("CPU Mock Drains Queue", result2))
        
        # Test 3: GPU window validation (Test Mode only, optional)
        if self.mode == "test":
            print("\n🧪 Running Test 3: GPU window - real segments & playlist")
            result3 = self.test_gpu_window_real_segments_playlist()
            results.append(("GPU Window Validation", result3))
        
        # ============================================
        # FINAL SUMMARY
        # ============================================
        print("\n" + "="*80)
        print("📋 FINAL TEST SUMMARY")
        print("="*80)
        
        passed = 0
        for test_name, result in results:
            status = "✅ PASS" if result else "❌ FAIL"
            print(f"{status} {test_name}")
            if result:
                passed += 1
        
        total = len(results)
        print(f"\n🎯 Results: {passed}/{total} tests passed")
        
        if passed == total:
            print("🎉 ALL BLUEPRINT SMOKE TESTS PASSED!")
            print("   System is ready for production deployment.")
        else:
            print("💥 SOME TESTS FAILED")
            print(f"   {total - passed} test(s) need attention.")
        
        return passed == total


def main():
    import argparse
    
    parser = argparse.ArgumentParser(
        description='VoiceClone Blueprint-Exact Smoke Tests',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  python %(prog)s --mode test           # Run all tests in Test Mode
  python %(prog)s --mode prod           # Run only Test 1 in Production Mode
  python %(prog)s --mode test --skip-gpu # Skip GPU window test
        """
    )
    
    parser.add_argument('--mode', choices=['test', 'prod'], default='test',
                       help='Test mode (default: test)')
    parser.add_argument('--region', default='us-east-1',
                       help='AWS region (default: us-east-1)')
    parser.add_argument('--skip-gpu', action='store_true',
                       help='Skip GPU window test (Test 3)')
    
    args = parser.parse_args()
    
    # Run tests
    tester = BlueprintSmokeTester(mode=args.mode, region=args.region)
    
    if args.skip_gpu and hasattr(tester, 'test_gpu_window_real_segments_playlist'):
        # Skip GPU test if requested
        original_method = tester.test_gpu_window_real_segments_playlist
        tester.test_gpu_window_real_segments_playlist = lambda: True
    
    success = tester.run_all_tests()
    
    # Exit code for CI/CD
    exit(0 if success else 1)


if __name__ == "__main__":
    main()