import os
import subprocess
import time
from typing import Dict, Optional
from dashscope.audio.tts_v2 import VoiceEnrollmentService

from ...logger.logging import logger as default_logger
from ...utils.upload_files import upload_file_tos as real_upload_file_tos
from ...utils.ffmpeg_utils import get_ffmpeg_path




class VoiceManager:
    """Manages voice lifecycle for CosyVoice TTS including creation, caching and status monitoring."""
    
    def __init__(self, config: Dict, logger=None):
        """Initializes voice manager with configuration.
        
        Args:
            config: Configuration dictionary containing voice settings.
            logger: Optional logger instance.
        """
        self.config = config
        self._logger = logger or default_logger
        self._service = VoiceEnrollmentService()
        self._voice_cache = {}  # Simple in-memory cache

    def ensure_voice_ready(self, **kwargs) -> str:
        """Ensures voice is ready for synthesis and returns voice ID.
        
        Args:
            **kwargs: Additional parameters that may contain voice configuration.
            
        Returns:
            str: Voice ID ready for synthesis.
            
        Raises:
            RuntimeError: If voice creation or polling fails.
        """
        voice_config = self._get_voice_config(**kwargs)
        
        # Check if we already have a voice for this configuration
        cache_key = self._get_cache_key(voice_config)
        if cache_key in self._voice_cache:
            voice_id = self._voice_cache[cache_key]
            self._logger.info(f"Using cached voice: {voice_id}")
            return voice_id
            
        # Create new voice if needed
        if voice_config.get("mode") == "existing" and voice_config.get("voice_id"):
            # Use existing voice ID directly
            voice_id = voice_config["voice_id"]
            self._voice_cache[cache_key] = voice_id
            return voice_id
        else:
            # Create new voice through cloning
            return self._create_and_wait_voice(voice_config, cache_key)

    def _get_voice_config(self, **kwargs) -> Dict:
        """Extracts voice configuration from config and kwargs.
        
        Args:
            **kwargs: Additional parameters.
            
        Returns:
            dict: Voice configuration.
        """
        voice_source = self.config.get("voice_source", {})
        
        # Override with kwargs if provided
        if "voice_source" in kwargs:
            voice_source.update(kwargs["voice_source"])
            
        return voice_source

    def _get_cache_key(self, voice_config: Dict) -> str:
        """Generates cache key for voice configuration.
        
        Args:
            voice_config: Voice configuration dictionary.
            
        Returns:
            str: Cache key for the configuration.
        """
        mode = voice_config.get("mode", "clone")
        if mode == "existing":
            return f"existing_{voice_config.get('voice_id')}"
        else:
            # For cloning mode, use audio source as cache key
            audio_url = voice_config.get("audio_url", "")
            audio_file = voice_config.get("audio_file", "")
            prefix = voice_config.get("voice_prefix", "default")
            
            # Use file path or URL for cache key
            audio_source = audio_file if audio_file else audio_url
            return f"clone_{prefix}_{hash(audio_source)}"


    def _create_and_wait_voice(self, voice_config: Dict, cache_key: str) -> str:
        """Creates new voice and waits for completion.
        
        Args:
            voice_config: Voice configuration dictionary.
            cache_key: Cache key for storing the result.
            
        Returns:
            str: Voice ID ready for synthesis.
            
        Raises:
            RuntimeError: If voice creation or polling fails.
        """
        target_model = self.config.get("model", "cosyvoice-v3-plus")
        voice_prefix = voice_config.get("voice_prefix", "voice")

        # Sanitize prefix to only contain alphanumeric characters (CosyVoice API requirement)
        import re
        voice_prefix = re.sub(r'[^a-zA-Z0-9]', '', voice_prefix)
        if not voice_prefix:
            voice_prefix = "voice"

        # Handle audio source - either URL or local file
        audio_url = voice_config.get("audio_url")
        audio_file = voice_config.get("audio_file")
        
        if not audio_url and not audio_file:
            raise ValueError("Either audio_url or audio_file is required for voice cloning")
        
        # If local file is provided, upload to TOS first
        if audio_file and not audio_url:
            self._logger.info(f"Uploading local audio file: {audio_file}")
            audio_url = self._upload_audio_file(audio_file)
            if not audio_url:
                raise RuntimeError(f"Failed to upload audio file: {audio_file}")
        
        self._logger.info(f"Creating voice with prefix: {voice_prefix}, audio URL: {audio_url}")
        
        try:
            voice_id = self._service.create_voice(
                target_model=target_model,
                prefix=voice_prefix,
                url=audio_url
            )
            self._logger.info(f"Voice creation submitted. Voice ID: {voice_id}")
        except Exception as e:
            self._logger.error(f"Failed to create voice: {e}")
            raise RuntimeError(f"Voice creation failed: {e}")
        
        # Wait for voice to be ready
        voice_id = self._wait_for_voice_ready(voice_id)
        
        # Cache the result
        self._voice_cache[cache_key] = voice_id
        return voice_id

    def _wait_for_voice_ready(self, voice_id: str) -> str:
        """Waits for voice to be ready through polling.
        
        Args:
            voice_id: Voice ID to check status for.
            
        Returns:
            str: Voice ID when ready.
            
        Raises:
            RuntimeError: If voice fails to deploy or polling times out.
        """
        max_attempts = self.config.get("voice_poll_attempts", 30)
        poll_interval = self.config.get("voice_poll_interval", 10)
        
        self._logger.info(f"Polling voice status for: {voice_id}")
        
        for attempt in range(max_attempts):
            try:
                voice_info = self._service.query_voice(voice_id=voice_id)
                status = voice_info.get("status")
                self._logger.debug(f"Attempt {attempt + 1}/{max_attempts}: Status '{status}'")
                
                if status == "OK":
                    self._logger.info(f"Voice is ready: {voice_id}")
                    return voice_id
                elif status == "UNDEPLOYED":
                    error_msg = f"Voice processing failed with status: {status}"
                    self._logger.error(error_msg)
                    raise RuntimeError(error_msg)
                
                # Continue waiting for other statuses like "DEPLOYING"
                time.sleep(poll_interval)
                
            except Exception as e:
                self._logger.warning(f"Error during status polling: {e}")
                time.sleep(poll_interval)
        
        error_msg = f"Voice polling timed out after {max_attempts} attempts"
        self._logger.error(error_msg)
        raise RuntimeError(error_msg)

    def _upload_audio_file(self, audio_file_path: str) -> Optional[str]:
        """Uploads local audio file to TOS and returns public URL.

        Args:
            audio_file_path: Path to local audio file.

        Returns:
            str: Public URL of uploaded audio file, None if failed.
        """
        try:
            # Preprocess audio file if too large (> 10MB)
            audio_file_path = self._preprocess_audio(audio_file_path)

            # Load TOS configuration from environment variables
            tos_config = {
                "access_key": os.getenv("TOS_ACCESS_KEY"),
                "secret_key": os.getenv("TOS_SECRET_KEY"),
                "bucket_name": os.getenv("TOS_BUCKET_NAME"),
                "endpoint": os.getenv("TOS_ENDPOINT", "tos-cn-beijing.volces.com"),
                "region": os.getenv("TOS_REGION", "cn-beijing"),
            }

            # Validate config
            if not all([tos_config["access_key"], tos_config["secret_key"], tos_config["bucket_name"]]):
                self._logger.error("TOS configuration incomplete. Required: TOS_ACCESS_KEY, TOS_SECRET_KEY, TOS_BUCKET_NAME")
                return None

            # Upload file to TOS
            audio_url = real_upload_file_tos(
                file_path=audio_file_path,
                tos_config=tos_config,
                folder="cosyvoice_audio"
            )

            if audio_url:
                self._logger.info(f"Audio uploaded successfully: {audio_url}")
                return audio_url
            else:
                self._logger.error(f"Failed to upload audio file: {audio_file_path}")
                return None

        except Exception as e:
            self._logger.error(f"Error uploading audio file: {e}")
            return None

    def _preprocess_audio(self, audio_file_path: str, max_size_mb: int = 10, max_duration_sec: int = 30) -> str:
        """Preprocess audio file to meet CosyVoice API requirements.

        Args:
            audio_file_path: Path to the audio file.
            max_size_mb: Maximum file size in MB (default 10MB).
            max_duration_sec: Maximum duration in seconds (default 30s).

        Returns:
            str: Path to the processed audio file (may be the original if no processing needed).
        """
        import tempfile

        # Check file size
        file_size_mb = os.path.getsize(audio_file_path) / (1024 * 1024)

        if file_size_mb <= max_size_mb:
            return audio_file_path

        self._logger.info(f"Audio file ({file_size_mb:.1f}MB) exceeds {max_size_mb}MB limit, preprocessing...")

        # Create temp directory for processed audio
        temp_dir = tempfile.mkdtemp(prefix="cosyvoice_")
        processed_path = os.path.join(temp_dir, "processed_audio.wav")

        try:
            ffmpeg_path = get_ffmpeg_path()
            if not ffmpeg_path:
                self._logger.error("ffmpeg not found, cannot preprocess audio")
                return audio_file_path

            # Use ffmpeg to:
            # 1. Limit duration to max_duration_sec
            # -ss before -i seeks to the start
            # 2. Convert to WAV with suitable sample rate
            cmd = [
                ffmpeg_path,
                "-y",  # Overwrite output
                "-ss", "0",  # Start from beginning
                "-t", str(max_duration_sec),  # Limit duration
                "-i", audio_file_path,
                "-ar", "16000",  # Sample rate 16kHz (CosyVoice preference)
                "-ac", "1",  # Mono
                "-c:a", "pcm_s16le",  # PCM format
                processed_path
            ]

            self._logger.info(f"Running ffmpeg: {' '.join(cmd)}")
            result = subprocess.run(cmd, capture_output=True, text=True, timeout=120)

            if result.returncode != 0:
                self._logger.error(f"ffmpeg failed: {result.stderr}")
                return audio_file_path

            # Check processed file size
            processed_size_mb = os.path.getsize(processed_path) / (1024 * 1024)
            self._logger.info(f"Processed audio: {processed_size_mb:.1f}MB")

            if processed_size_mb > max_size_mb:
                self._logger.warning(f"Processed file still too large, trying more aggressive compression...")
                # Try MP3 with lower bitrate
                processed_mp3 = os.path.join(temp_dir, "processed_audio.mp3")
                cmd_mp3 = [
                    ffmpeg_path,
                    "-y",
                    "-ss", "0",
                    "-t", str(max_duration_sec),
                    "-i", audio_file_path,
                    "-ar", "16000",
                    "-ac", "1",
                    "-b:a", "64k",  # 64kbps
                    processed_mp3
                ]
                result = subprocess.run(cmd_mp3, capture_output=True, text=True, timeout=120)
                if result.returncode == 0:
                    processed_path = processed_mp3

            return processed_path

        except subprocess.TimeoutExpired:
            self._logger.error("ffmpeg timeout during audio preprocessing")
            return audio_file_path
        except Exception as e:
            self._logger.error(f"Audio preprocessing error: {e}")
            return audio_file_path