import asyncio
import os
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo
from dotenv import load_dotenv
from discord import Intents, Client, Embed, Colour, Activity, ActivityType, Status, File
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.date import DateTrigger
from apscheduler.events import EVENT_JOB_MISSED, EVENT_JOB_ERROR, EVENT_JOB_EXECUTED, EVENT_JOB_MAX_INSTANCES
from telethon import TelegramClient
from telethon.tl.types import MessageMediaPhoto, MessageMediaDocument
from telethon.tl.functions.messages import SendReactionRequest
import json
import io
import tempfile
import subprocess
from math import ceil

load_dotenv()
default_channel = "992565170633199706"

def save_to_json(data, filename="state.json"):
    with open(filename, "w") as f:
        json.dump(data, f, default=str)

def load_from_json(filename="state.json"):
    try:
        with open(filename, "r") as f:
            return json.load(f)
    except FileNotFoundError:
        return {}

operational_data = {
    'planned_end': datetime.utcnow().timestamp(),
    'last_tg_message_id': 0,
    'total_messages': 0
}

data = load_from_json()
for item in operational_data:
    if item in data:
        operational_data[item] = data[item]

from datetime import timezone
operational_data['planned_end'] = datetime.fromtimestamp(operational_data['planned_end'], tz=timezone.utc)
print(operational_data)

class MemePoster(Client):
    def __init__(self):
        intents = Intents.all()
        intents.message_content = True
        super().__init__(intents=intents)

        self.is_running = False
        self.is_processing_message = False  # Flag to prevent job recreation during processing
        self.tz = ZoneInfo("Europe/Moscow")
        self.target_size = 10 * 1024 * 1024  # 10MB
        self.max_attempts = 5

        self.temp_dir = os.getenv("TEMP_DIR", None)

        self.tg = TelegramClient(
            'user_session',
            int(os.getenv("TELEGRAM_API_ID")),
            os.getenv("TELEGRAM_API_HASH")
        )

    async def get_remaining_count(self):
        """Count messages from last_id to now"""
        global operational_data
        
        channel = os.getenv("TELEGRAM_CHANNEL")
        count = 0
        
        async for msg in self.tg.iter_messages(
            channel, 
            min_id=operational_data['last_tg_message_id'],
            limit=None
        ):
            if self.is_valid_message(msg):
                count += 1
        
        operational_data['total_messages'] = count
        return count

    def is_valid_message(self, msg) -> bool:
        if msg.action:
            return False
        if not msg.text and not msg.media:
            return False
        return True

    async def get_next_message(self):
        """Get next valid TG message after last_id"""
        global operational_data
        
        channel = os.getenv("TELEGRAM_CHANNEL")
        
        async for msg in self.tg.iter_messages(
            channel,
            min_id=operational_data['last_tg_message_id'],
            reverse=True,
            limit=100
        ):
            if self.is_valid_message(msg):
                return msg
        
        return None

    async def convert_to_webp(self, input_bytes):
        """Convert image to webp"""
        with tempfile.NamedTemporaryFile(suffix='.tmp', delete=False, dir=self.temp_dir) as input_file:
            input_file.write(input_bytes)
            input_path = input_file.name
        
        with tempfile.NamedTemporaryFile(suffix='.webp', delete=False, dir=self.temp_dir) as output_file:
            output_path = output_file.name
        
        try:
            cmd = [
                "ffmpeg", "-i", input_path,
                "-c:v", "libwebp",
                "-lossless", "0",
                "-quality", "80",
                "-y",
                "-hide_banner",
                "-loglevel", "error",
                output_path
            ]
            
            process = await asyncio.create_subprocess_exec(
                *cmd,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE
            )
            
            await process.communicate()
            
            if process.returncode == 0:
                with open(output_path, 'rb') as f:
                    return f.read()
            else:
                print("WebP conversion failed, using original")
                return input_bytes
        
        finally:
            try:
                os.unlink(input_path)
                os.unlink(output_path)
            except:
                pass

    async def run_ffmpeg_with_progress(self, cmd, operation_name):
        """Run ffmpeg command with periodic progress logging"""
        start_time = datetime.now()
        print(f"[{start_time}] Starting {operation_name}...")

        process = await asyncio.create_subprocess_exec(
            *cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.STDOUT
        )

        last_log_time = start_time
        last_line = ""

        # Read output and log periodically
        async for line in process.stdout:
            line_str = line.decode('utf-8', errors='ignore').rstrip()
            last_line = line_str

            # Log progress every 15 seconds
            now = datetime.now()
            if (now - last_log_time).total_seconds() >= 15:
                elapsed = (now - start_time).total_seconds()
                print(f"[{now}] {operation_name} running for {elapsed:.0f}s | {line_str[:100]}")
                last_log_time = now

        await process.wait()

        end_time = datetime.now()
        elapsed = (end_time - start_time).total_seconds()
        print(f"[{end_time}] {operation_name} completed in {elapsed:.0f}s (exit code: {process.returncode})")

        return process.returncode

    async def convert_to_webm(self, input_bytes, keep_file=False, target_size=None):
        """Convert video to webm with audio

        Args:
            input_bytes: Video data
            keep_file: If True, return (bytes, file_path) instead of just bytes
            target_size: Target file size in bytes (defaults to self.target_size)
        """
        if target_size is None:
            target_size = self.target_size

        with tempfile.NamedTemporaryFile(suffix='.tmp', delete=False, dir=self.temp_dir) as input_file:
            input_file.write(input_bytes)
            input_path = input_file.name

        with tempfile.NamedTemporaryFile(suffix='.webm', delete=False, dir=self.temp_dir) as output_file:
            output_path = output_file.name

        try:
            # Get video duration and calculate target bitrate
            duration = await self.get_duration(input_path)

            if duration > 0:
                # Calculate bitrate to fit target size
                # Formula: bitrate (kbps) = (target_size * 8) / duration / 1000
                # Apply 0.9 safety factor for audio overhead
                target_bitrate_kbps = int((target_size * 8 * 0.9) / duration / 1000)
                print(f"Duration: {duration:.1f}s, calculated target bitrate: {target_bitrate_kbps}k")
                bitrate_args = ["-b:v", f"{target_bitrate_kbps}k"]
            else:
                # Fallback to CRF if duration detection fails
                print("Could not detect duration, using CRF mode")
                bitrate_args = ["-b:v", "0", "-crf", "30"]

            cmd = [
                "ffmpeg", "-i", input_path,
                "-c:v", "libvpx-vp9",
                "-c:a", "libopus",
                *bitrate_args,
                "-y",
                "-hide_banner",
                "-stats",
                output_path
            ]

            returncode = await self.run_ffmpeg_with_progress(cmd, "WebM conversion")

            if returncode == 0:
                with open(output_path, 'rb') as f:
                    data = f.read()
                if keep_file:
                    os.unlink(input_path)
                    return data, output_path
                else:
                    os.unlink(input_path)
                    os.unlink(output_path)
                    return data
            else:
                print("WebM conversion failed, using original")
                if keep_file:
                    os.unlink(input_path)
                    os.unlink(output_path)
                    return input_bytes, None
                else:
                    os.unlink(input_path)
                    os.unlink(output_path)
                    return input_bytes

        except Exception as e:
            print(f"WebM conversion error: {e}")
            try:
                os.unlink(input_path)
                os.unlink(output_path)
            except:
                pass
            if keep_file:
                return input_bytes, None
            else:
                return input_bytes

    async def get_bitrate(self, file_path):
        """Get video bitrate using ffprobe"""
        process = await asyncio.create_subprocess_exec(
            "ffprobe", "-v", "error", "-select_streams", "v:0",
            "-show_entries", "stream=bit_rate",
            "-of", "default=noprint_wrappers=1:nokey=1", file_path,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.DEVNULL
        )
        stdout, _ = await process.communicate()
        try:
            return int(stdout.decode().strip())
        except:
            return 0

    async def get_duration(self, file_path):
        """Get video duration in seconds using ffprobe"""
        process = await asyncio.create_subprocess_exec(
            "ffprobe", "-v", "error", "-show_entries",
            "format=duration",
            "-of", "default=noprint_wrappers=1:nokey=1", file_path,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.DEVNULL
        )
        stdout, _ = await process.communicate()
        try:
            return float(stdout.decode().strip())
        except:
            return 0

    async def transcode_video(self, input_file, output_file, bitrate):
        """Transcode video with specified bitrate"""
        encoders = ['h264_nvenc', 'libx264']

        for encoder in encoders:
            cmd = [
                "ffmpeg", "-i", input_file,
                "-b:v", f"{bitrate}k",
                "-c:v", encoder,
                "-c:a", "copy",
                "-y",
                "-hide_banner",
                "-stats",
                output_file
            ]

            returncode = await self.run_ffmpeg_with_progress(
                cmd,
                f"Transcode with {encoder} @ {bitrate}k"
            )

            if returncode == 0:
                return True
            elif encoder == 'h264_nvenc':
                print(f"NVENC failed, falling back to libx264")
                continue

        return False

    async def compress_video(self, input_bytes, original_size):
        """Iteratively compress video to target size"""
        with tempfile.NamedTemporaryFile(suffix='.mp4', delete=False, dir=self.temp_dir) as input_file:
            input_file.write(input_bytes)
            input_path = input_file.name
        
        with tempfile.NamedTemporaryFile(suffix='.mp4', delete=False, dir=self.temp_dir) as output_file:
            output_path = output_file.name
        
        try:
            original_bitrate = await self.get_bitrate(input_path)
            if original_bitrate == 0:
                original_bitrate = (original_size * 8) // 1
            
            scale_factor = self.target_size / original_size
            target_bitrate = ceil(original_bitrate * scale_factor / 1000)
            
            if original_size < self.target_size:
                target_bitrate = original_bitrate // 1000
            
            print(f"scale_factor {scale_factor}, bitrate src/dst {original_bitrate}/{target_bitrate}k")
            
            attempt = 1
            while attempt <= self.max_attempts:
                print(f"Attempt {attempt}: Transcoding with bitrate {target_bitrate}k")
                
                success = await self.transcode_video(input_path, output_path, target_bitrate)
                if not success:
                    print("Transcoding failed")
                    return None
                
                output_size = os.path.getsize(output_path)
                print(f"Output size: {output_size / (1024*1024):.2f}MB")
                
                if output_size <= self.target_size:
                    print("Successfully compressed to target size")
                    break
                else:
                    error_factor = self.target_size / output_size
                    target_bitrate = target_bitrate - ceil(target_bitrate * (1 - error_factor)) * 2
                    print(f"Adjusting bitrate to {target_bitrate}k")
                    attempt += 1
            
            if attempt > self.max_attempts:
                print("Failed to compress within max attempts")
                return None
            
            with open(output_path, 'rb') as f:
                return f.read()
        
        finally:
            try:
                os.unlink(input_path)
                os.unlink(output_path)
            except:
                pass

    async def process_video(self, media_bytes, keep_file=False):
        """Process video: compress if needed, then convert to webm

        Args:
            media_bytes: Video data
            keep_file: If True, return (bytes, file_path) instead of just bytes

        Returns:
            bytes or (bytes, file_path): Processed video data and optionally file path
        """
        original_size = len(media_bytes)

        # Pre-compress if source is too large
        if original_size > self.target_size:
            print(f"Video size {original_size / (1024*1024):.2f}MB exceeds limit, pre-compressing...")
            compressed = await self.compress_video(media_bytes, original_size)
            if compressed:
                media_bytes = compressed
            else:
                print("Pre-compression failed, using original")

        # Convert to webm with iterative compression
        webm_bytes = None
        webm_path = None
        current_target = self.target_size
        attempt = 1

        while attempt <= self.max_attempts:
            print(f"WebM conversion attempt {attempt} with target size {current_target / (1024*1024):.2f}MB...")

            if keep_file:
                webm_bytes, webm_path = await self.convert_to_webm(
                    media_bytes,
                    keep_file=True,
                    target_size=current_target
                )
            else:
                webm_bytes = await self.convert_to_webm(
                    media_bytes,
                    keep_file=False,
                    target_size=current_target
                )

            webm_size = len(webm_bytes)
            print(f"WebM size: {webm_size / (1024*1024):.2f}MB")

            if webm_size <= self.target_size:
                print("WebM conversion successful")
                break
            else:
                # WebM still too large - reduce target and try again
                print(f"WebM too large ({webm_size / (1024*1024):.2f}MB), retrying...")

                # Delete temp file if it exists
                if keep_file and webm_path:
                    try:
                        os.unlink(webm_path)
                        webm_path = None
                    except:
                        pass

                # Reduce target size by the overshoot ratio
                overshoot_ratio = self.target_size / webm_size
                current_target = int(current_target * overshoot_ratio * 0.9)  # 0.9 safety factor
                attempt += 1

        if attempt > self.max_attempts:
            print(f"WARNING: Failed to fit WebM in target size after {self.max_attempts} attempts")

        if keep_file:
            return webm_bytes, webm_path
        else:
            return webm_bytes

    async def download_media(self, msg):
        """Download media from TG message

        Returns:
            tuple: (media_bytes, filename, mime_type, file_path)
                   file_path is None for non-video files
        """
        if not msg.media:
            return None, None, None, None

        # Start keepalive monitor for long operations
        stop_event = asyncio.Event()
        keepalive_task = asyncio.create_task(self.keepalive_monitor(stop_event))

        try:
            media_bytes = await msg.download_media(file=bytes)

            if not media_bytes:
                return None, None, None, None

            if isinstance(msg.media, MessageMediaPhoto):
                # Photo - convert to webp
                print(f"Converting photo to webp...")
                webp_bytes = await self.convert_to_webp(media_bytes)
                filename = f"photo_{msg.id}.webp"
                return webp_bytes, filename, "image/webp", None

            elif isinstance(msg.media, MessageMediaDocument):
                doc = msg.document
                mime_type = doc.mime_type

                # Process video - keep file for inspection
                if mime_type and mime_type.startswith('video/'):
                    print(f"Processing video...")
                    processed, file_path = await self.process_video(media_bytes, keep_file=True)
                    return processed, f"video_{msg.id}.webm", "video/webm", file_path

                # Convert images to webp
                elif mime_type and mime_type.startswith('image/'):
                    print(f"Converting image to webp...")
                    webp_bytes = await self.convert_to_webp(media_bytes)
                    return webp_bytes, f"image_{msg.id}.webp", "image/webp", None
                else:
                    # Other files - keep as is
                    filename = None
                    for attr in doc.attributes:
                        if hasattr(attr, 'file_name'):
                            filename = attr.file_name
                            break
                    if not filename:
                        filename = f"media_{msg.id}.bin"
                    return media_bytes, filename, mime_type, None
            else:
                return None, None, None, None

        except Exception as e:
            print(f"Failed to download media: {e}")
            import traceback
            traceback.print_exc()
            return None, None, None, None
        finally:
            # Stop keepalive monitor
            stop_event.set()
            try:
                await keepalive_task
            except:
                pass

    async def send_reaction(self, msg, emoji='❤'):
        """Send reaction to TG message"""
        try:
            # Method 1: Try using built-in react method (newer Telethon)
            try:
                await msg.react(emoji)
                print(f"Reaction {emoji} sent (method 1)")
                return
            except AttributeError:
                pass

            # Method 2: Try using SendReactionRequest with proper types
            try:
                from telethon.tl.types import ReactionEmoji
                channel = await self.tg.get_entity(os.getenv("TELEGRAM_CHANNEL"))
                await self.tg(SendReactionRequest(
                    peer=channel,
                    msg_id=msg.id,
                    reaction=[ReactionEmoji(emoticon=emoji)]
                ))
                print(f"Reaction {emoji} sent (method 2)")
                return
            except (ImportError, AttributeError):
                pass

            # Method 3: Try plain string
            channel = await self.tg.get_entity(os.getenv("TELEGRAM_CHANNEL"))
            await self.tg(SendReactionRequest(
                peer=channel,
                msg_id=msg.id,
                reaction=[emoji]
            ))
            print(f"Reaction {emoji} sent (method 3)")

        except Exception as e:
            print(f"Failed to send reaction: {e}")
            import traceback
            traceback.print_exc()

    async def keepalive_monitor(self, stop_event):
        """Monitor and maintain connections during long operations"""
        while not stop_event.is_set():
            try:
                # Check Discord connection
                if not self.is_closed():
                    # Update status to keep connection alive
                    if self.scheduler and self.scheduler.get_job("autoposting"):
                        await self.update_status()
                else:
                    print(f"[{datetime.now()}] KEEPALIVE: Discord connection lost!")

                # Check Telegram connection
                if self.tg and self.tg.is_connected():
                    pass  # TG handles its own keepalive
                else:
                    print(f"[{datetime.now()}] KEEPALIVE: Telegram connection lost! Reconnecting...")
                    try:
                        await self.tg.connect()
                    except Exception as e:
                        print(f"KEEPALIVE: TG reconnect failed: {e}")

            except Exception as e:
                print(f"KEEPALIVE: Error in monitor: {e}")

            # Wait before next check
            await asyncio.sleep(30)  # Check every 30 seconds

    async def watchdog(self):
        """Periodically check if scheduler is running, has jobs, and connections are alive"""
        while True:
            await asyncio.sleep(120)  # Check every 2 minutes
            if not self.is_running:
                continue

            try:
                # Check Discord connection
                if self.is_closed():
                    print(f"[{datetime.now()}] WATCHDOG: Discord connection closed!")

                # Check Telegram connection
                if self.tg and not self.tg.is_connected():
                    print(f"[{datetime.now()}] WATCHDOG: Telegram disconnected! Reconnecting...")
                    try:
                        await self.tg.connect()
                        if not await self.tg.is_user_authorized():
                            await self.tg.start()
                        print(f"[{datetime.now()}] WATCHDOG: Telegram reconnected successfully")
                    except Exception as e:
                        print(f"[{datetime.now()}] WATCHDOG: Telegram reconnect failed: {e}")

                # Check scheduler and job
                if self.scheduler:
                    if not self.scheduler.running:
                        print(f"[{datetime.now()}] WATCHDOG: Scheduler stopped! Restarting...")
                        self.scheduler.start()

                    job = self.scheduler.get_job("autoposting")
                    if job is None:
                        # Job missing - this can happen if message_cycle is still running
                        # and will create the next job when it completes
                        print(f"[{datetime.now()}] WATCHDOG: Job missing (may be running). Will be recreated by message_cycle.")
                    else:
                        # Job exists - log next run time
                        from datetime import timezone
                        time_until = job.next_run_time - datetime.now(timezone.utc)
                        print(f"[{datetime.now()}] WATCHDOG: All OK. Next post in {time_until.total_seconds():.0f}s")

                # Check for new messages in Telegram channel
                try:
                    old_count = operational_data['total_messages']
                    new_count = await self.get_remaining_count()

                    if new_count > old_count:
                        diff = new_count - old_count
                        print(f"[{datetime.now()}] WATCHDOG: Detected {diff} new messages in TG channel")

                        # Optionally reset planned_end if RESET_END_DATE is not set to false
                        reset_end = os.getenv("RESET_END_DATE", "true").lower() == "true"
                        if reset_end:
                            from datetime import timezone
                            planning_days = int(os.getenv("PLANNING_FOR_DAYS", 3))
                            operational_data["planned_end"] = datetime.now(timezone.utc) + timedelta(days=planning_days)
                            print(f"[{datetime.now()}] WATCHDOG: Reset planned_end to +{planning_days} days")

                            # Save updated state
                            save_to_json({
                                'planned_end': operational_data['planned_end'].timestamp(),
                                'last_tg_message_id': operational_data['last_tg_message_id'],
                                'total_messages': operational_data['total_messages']
                            })

                        # Reschedule next post with new timing (only if not currently processing)
                        if not self.is_processing_message:
                            await self.schedule_next_post()
                except Exception as check_err:
                    print(f"[{datetime.now()}] WATCHDOG: Error checking new messages: {check_err}")

            except Exception as e:
                print(f"[{datetime.now()}] WATCHDOG: Error during check: {e}")
                import traceback
                traceback.print_exc()

    async def message_cycle(self, created_at):
        global operational_data

        cycle_start = datetime.now()
        print(f"\n{'#'*60}")
        print(f"[{cycle_start}] MESSAGE_CYCLE STARTED")
        print(f"{'#'*60}\n")

        self.is_processing_message = True
        try:
            await self._message_cycle_impl(created_at, cycle_start)
        finally:
            self.is_processing_message = False

    async def _message_cycle_impl(self, created_at, cycle_start):
        global operational_data

        try:
            msg = await self.get_next_message()

            if not msg:
                print("No more messages in queue")
                await asyncio.sleep(3600)
                await self.schedule_next_post()
                print(f"[{datetime.now()}] MESSAGE_CYCLE ENDED (no messages)")
                return

            channel_id = int(os.getenv("DISCORD_CHANNEL_ID", default_channel))
            channel = await self.fetch_channel(channel_id)
        except Exception as e:
            print(f"Error in message_cycle setup: {e}")
            import traceback
            traceback.print_exc()
            await asyncio.sleep(60)
            await self.schedule_next_post()
            print(f"[{datetime.now()}] MESSAGE_CYCLE ENDED (error in setup)")
            return

        # Build TG link
        tg_channel = os.getenv("TELEGRAM_CHANNEL")
        if tg_channel.startswith('-100'):
            tg_link = f"https://t.me/c/{tg_channel.replace('-100', '')}/{msg.id}"
        else:
            tg_link = f"https://t.me/{tg_channel.lstrip('@')}/{msg.id}"

        print(f"\n{'='*60}")
        print(f"Processing TG message ID: {msg.id}")
        print(f"Link: {tg_link}")
        print(f"{'='*60}")

        # Calculate ETA
        from datetime import timezone
        now = datetime.now(timezone.utc)
        diff = operational_data["planned_end"] - now
        remaining = operational_data['total_messages']
        ETA_string = f"(ETA {diff.days}d {int(diff.seconds / 3600)}h)"

        temp_file_path = None
        try:
            text = msg.text or ""
            media_bytes, filename, mime_type, temp_file_path = await self.download_media(msg)

            if media_bytes:
                if mime_type and mime_type.startswith('image/'):
                    # Image (webp) - use embed
                    embed = Embed(
                        description=text[:4096] if text else None,
                        colour=Colour.blue(),
                        timestamp=msg.date
                    )
                    embed.set_author(name="Telegram", url=tg_link)
                    embed.set_image(url=f"attachment://{filename}")
                    embed.set_footer(text=f"{remaining} {ETA_string}")

                    file = File(io.BytesIO(media_bytes), filename=filename)
                    await channel.send(embed=embed, file=file)
                else:
                    # Video (webm) or other - send as file
                    # Log file info before sending
                    if temp_file_path:
                        file_size = os.path.getsize(temp_file_path)
                        print(f"Sending file: {temp_file_path}, size: {file_size / (1024*1024):.2f}MB")

                    file = File(io.BytesIO(media_bytes), filename=filename)
                    content = f"{remaining} [src](<{tg_link}>) {ETA_string}\n{text}"
                    await channel.send(content=content[:2000], file=file)

                    # Delete temp file after successful send
                    if temp_file_path:
                        try:
                            os.unlink(temp_file_path)
                            print(f"Deleted temp file: {temp_file_path}")
                        except Exception as cleanup_err:
                            print(f"Failed to delete temp file {temp_file_path}: {cleanup_err}")
            else:
                # Text only
                await channel.send(content=f"{remaining} [src](<{tg_link}>) {ETA_string}\n{text}"[:2000])

            # Send reaction to original TG message
            await self.send_reaction(msg, emoji='❤')

            operational_data['last_tg_message_id'] = msg.id
            operational_data['total_messages'] = max(0, remaining - 1)

            planned_end = operational_data["planned_end"]
            operational_data["planned_end"] = planned_end.timestamp()
            save_to_json(operational_data)
            operational_data["planned_end"] = planned_end

        except Exception as e:
            print(f"Error sending message: {e}")
            if temp_file_path and os.path.exists(temp_file_path):
                file_size = os.path.getsize(temp_file_path)
                print(f"Temp file kept for inspection: {temp_file_path} ({file_size / (1024*1024):.2f}MB)")
            import traceback
            traceback.print_exc()
            await asyncio.sleep(10)
            # Try to continue even after error
            try:
                await self.schedule_next_post()
            except Exception as schedule_err:
                print(f"Failed to schedule next post: {schedule_err}")

            cycle_end = datetime.now()
            cycle_duration = (cycle_end - cycle_start).total_seconds()
            print(f"[{cycle_end}] MESSAGE_CYCLE ENDED (error after {cycle_duration:.0f}s)")
            return

        # Verify connections and scheduler after long operation
        try:
            # Check Discord connection
            if self.is_closed():
                print(f"[{datetime.now()}] WARNING: Discord disconnected after processing!")

            # Check Telegram connection
            if self.tg and not self.tg.is_connected():
                print(f"[{datetime.now()}] WARNING: Telegram disconnected after processing! Reconnecting...")
                try:
                    await self.tg.connect()
                    if not await self.tg.is_user_authorized():
                        await self.tg.start()
                    print(f"[{datetime.now()}] Telegram reconnected successfully")
                except Exception as e:
                    print(f"[{datetime.now()}] Telegram reconnect failed: {e}")

            # Check scheduler
            if self.scheduler and not self.scheduler.running:
                print(f"[{datetime.now()}] WARNING: Scheduler stopped! Restarting...")
                self.scheduler.start()

        except Exception as verify_err:
            print(f"Error verifying connections: {verify_err}")

        try:
            await self.schedule_next_post()
        except Exception as schedule_err:
            print(f"Error scheduling next post: {schedule_err}")
            import traceback
            traceback.print_exc()

        cycle_end = datetime.now()
        cycle_duration = (cycle_end - cycle_start).total_seconds()
        print(f"\n{'#'*60}")
        print(f"[{cycle_end}] MESSAGE_CYCLE COMPLETED in {cycle_duration:.0f}s")
        print(f"{'#'*60}\n")

    async def get_time_next_post(self):
        global operational_data
        from datetime import timezone

        curr_time = datetime.now(timezone.utc)
        remaining = operational_data['total_messages']

        if remaining <= 0:
            return curr_time, 60, 60

        planned_end = operational_data["planned_end"]

        minutes_wait = max(
            int((planned_end - curr_time).total_seconds() / 60 / remaining),
            5
        )

        sleep_until = (curr_time + timedelta(minutes=minutes_wait)).replace(second=10)
        return sleep_until, minutes_wait, minutes_wait

    async def update_status(self):
        global operational_data

        job = self.scheduler.get_job("autoposting")
        if not job:
            return

        # Convert UTC to Moscow time for display
        next_run_utc = job.next_run_time
        next_run_moscow = next_run_utc.astimezone(self.tz)
        next_run = next_run_moscow.strftime('%d/%m/%Y %H:%M:%S')

        await self.change_presence(
            status=Status.online,
            activity=Activity(
                type=ActivityType.playing,
                name=f"Next: {next_run}; Remaining: {operational_data['total_messages']}"
            )
        )

    async def schedule_next_post(self, min_wait=False):
        global operational_data
        from datetime import timezone

        curr_time = datetime.now(timezone.utc)

        if min_wait:
            sleep_until = curr_time + timedelta(seconds=5)
        else:
            sleep_until, minutes_wait, drift = await self.get_time_next_post()
            print(f"drift {drift}; minutes_wait {minutes_wait}; sleep_until {sleep_until}")

        self.scheduler.add_job(
            self.message_cycle,
            DateTrigger(run_date=sleep_until),
            id="autoposting",
            kwargs={"created_at": curr_time},
            replace_existing=True,
            max_instances=1,
            misfire_grace_time=None  # Never consider the job misfired
        )

        # Convert to Moscow time for display
        sleep_until_moscow = sleep_until.astimezone(self.tz)
        print(f"Post planned on {sleep_until_moscow.strftime('%d/%m/%Y %H:%M:%S')} MSK")
        await self.update_status()

    async def on_message(self, message):
        global operational_data
        from datetime import timezone

        if message.author == self.user or message.author.bot:
            return

        if message.channel.id == int(os.getenv("DISCORD_CHANNEL_ID", default_channel)):
            curr_time = datetime.now(timezone.utc)
            job = self.scheduler.get_job("autoposting")

            if job is None:
                return

            old_job_time_diff = curr_time - job.kwargs.get("created_at")

            sleep_until, minutes_wait, drift = await self.get_time_next_post()

            operational_data["planned_end"] = operational_data["planned_end"] + old_job_time_diff

            # Convert to Moscow time for display
            planned_end_moscow = operational_data['planned_end'].astimezone(self.tz)
            print(f"Shifted by {old_job_time_diff}; new end: {planned_end_moscow.strftime('%d/%m/%Y %H:%M:%S')} MSK")

            new_kwargs = dict(job.kwargs)
            new_kwargs["created_at"] = curr_time
            job.modify(next_run_time=sleep_until, kwargs=new_kwargs)

            await self.update_status()

    async def on_disconnect(self):
        print(f"[{datetime.now()}] Discord disconnected!")
        # Check Telegram connection
        if self.tg and not self.tg.is_connected():
            print(f"[{datetime.now()}] Telegram also disconnected, attempting reconnect...")
            try:
                await self.tg.connect()
                print(f"[{datetime.now()}] Telegram reconnected successfully")
            except Exception as e:
                print(f"[{datetime.now()}] Telegram reconnect failed: {e}")

    async def on_resumed(self):
        print(f"[{datetime.now()}] Discord connection resumed")

        # Check and restore Telegram connection
        if self.tg and not self.tg.is_connected():
            print(f"[{datetime.now()}] Telegram disconnected, reconnecting...")
            try:
                await self.tg.connect()
                if not await self.tg.is_user_authorized():
                    await self.tg.start()
                print(f"[{datetime.now()}] Telegram reconnected successfully")
            except Exception as e:
                print(f"[{datetime.now()}] Telegram reconnect failed: {e}")

        # Check if scheduler job still exists after reconnect
        if self.is_running and self.scheduler:
            job = self.scheduler.get_job("autoposting")
            if job is None:
                # Don't recreate job if message is currently being processed
                if self.is_processing_message:
                    print(f"[{datetime.now()}] Job missing but message_cycle is running - will be recreated when it completes")
                else:
                    print(f"[{datetime.now()}] WARNING: Scheduler job lost during reconnect, recovering...")
                    await self.schedule_next_post(True)
            else:
                print(f"[{datetime.now()}] Scheduler job OK, next run: {job.next_run_time}")
            await self.update_status()

    async def on_ready(self):
        if self.is_running:
            print(f"[{datetime.now()}] Already running (reconnect)")
            if self.scheduler.get_job("autoposting") is None:
                # Don't recreate job if message is currently being processed
                if self.is_processing_message:
                    print("Job missing but message_cycle is running - will be recreated when it completes")
                else:
                    print("WARNING: Scheduler job missing, recreating...")
                    await self.schedule_next_post(True)
            await self.update_status()
            return

        self.is_running = True

        # Start TG user client
        await self.tg.start()
        me = await self.tg.get_me()
        print(f"TG logged in as {me.first_name} (@{me.username})")

        # Initialize count if needed
        if operational_data['last_tg_message_id'] == 0:
            channel = os.getenv("TELEGRAM_CHANNEL")
            async for msg in self.tg.iter_messages(channel, limit=1):
                operational_data['last_tg_message_id'] = msg.id
                print(f"Initialized from message {msg.id}")
                break

        # Count remaining messages
        await self.get_remaining_count()

        # Set/reset planned end
        from datetime import timezone
        reset_end = os.getenv("RESET_END_DATE", "true").lower() == "true"
        if reset_end or operational_data['planned_end'] <= datetime.now(timezone.utc):
            planning_days = int(os.getenv("PLANNING_FOR_DAYS", 3))
            operational_data["planned_end"] = datetime.now(timezone.utc) + timedelta(days=planning_days)
            print(f"Planned end set to +{planning_days} days")

        save_to_json({
            'planned_end': operational_data['planned_end'].timestamp(),
            'last_tg_message_id': operational_data['last_tg_message_id'],
            'total_messages': operational_data['total_messages']
        })

        self.scheduler = AsyncIOScheduler()

        # Add event listeners for better debugging
        def job_missed_listener(event):
            print(f"[{datetime.now()}] SCHEDULER: Job {event.job_id} MISSED (scheduled: {event.scheduled_run_time})")

        def job_error_listener(event):
            print(f"[{datetime.now()}] SCHEDULER: Job {event.job_id} ERROR: {event.exception}")
            import traceback
            traceback.print_exception(type(event.exception), event.exception, event.exception.__traceback__)

        def job_executed_listener(event):
            # Don't log here - message_cycle already logs completion
            pass

        def job_max_instances_listener(event):
            print(f"[{datetime.now()}] SCHEDULER: Job {event.job_id} SKIPPED - max instances reached!")
            print(f"[{datetime.now()}] SCHEDULER: Previous message_cycle is still running. This is normal for long video processing.")

        self.scheduler.add_listener(job_missed_listener, EVENT_JOB_MISSED)
        self.scheduler.add_listener(job_error_listener, EVENT_JOB_ERROR)
        self.scheduler.add_listener(job_executed_listener, EVENT_JOB_EXECUTED)
        self.scheduler.add_listener(job_max_instances_listener, EVENT_JOB_MAX_INSTANCES)

        self.scheduler.start()

        print(f'Discord logged in as {self.user}')

        await self.change_presence(
            status=Status.dnd,
            activity=Activity(type=ActivityType.playing, name="Startup...")
        )
        await self.schedule_next_post(True)

        # Start watchdog task
        asyncio.create_task(self.watchdog())

if __name__ == '__main__':
    print("Starting...")
    token = os.getenv("DISCORD_TOKEN")
    bot = MemePoster()
    bot.run(token)