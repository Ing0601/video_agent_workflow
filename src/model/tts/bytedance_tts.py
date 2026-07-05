import base64
import json
import time
import uuid
from pathlib import Path
from typing import Any, Dict, Optional, Union

import requests  # type: ignore

from ...logger.logging import logger as default_logger
from .base import BaseTTSModel
from .text_splitter import TextSplitter
from .utils import merge_chunked_outputs,enhance_timestamps_with_sentences

class UnauthorizedError(Exception):
    """Exception raised when API returns 401 Unauthorized."""
    pass

class ByteDanceTTSModel(BaseTTSModel):
    """ByteDance TTS model implementation using HTTP API.

    This class provides text-to-speech synthesis using ByteDance's TTS service
    with support for automatic text splitting, timestamp generation, and retry mechanism.
    """

    def __init__(
        self,
        name: str = "bytedance_tts",
        config: Optional[Dict[str, Any]] = None,
        api_key: Optional[str] = None,
        **kwargs,
    ):
        """Initializes ByteDance TTS model.

        Args:
            name (str): Model name identifier.
            config (Optional[Dict[str, Any]]): Configuration dictionary containing
                app_id, access_token, secret_key, http_url, voice_type, etc.
            api_key (Optional[str]): API access token (can also be in config).
            **kwargs: Additional arguments passed to base class.
        """
        # Set ByteDance-specific defaults
        config = config or {}
        config.setdefault("app_id", "2331750539")
        config.setdefault("http_url", "https://openspeech.bytedance.com/api/v1/tts")
        config.setdefault("voice_type", "zh_female_sajiaonvyou_moon_bigtts")
        config.setdefault("speed_ratio", 1.24)
        config.setdefault("sample_rate", 24000)
        config.setdefault("encoding", "mp3")

        # Long-text handling configuration (enabled by default)
        config.setdefault("auto_split", True)  # Enable auto-split by default
        config.setdefault("max_text_bytes", 1024)  # Max bytes per request
        config.setdefault("min_chunk_ratio", 0.3)  # Min chunk size ratio
        config.setdefault("max_retries", 3)  # Max retries per chunk
        config.setdefault("retry_delay", 2.0)  # Retry delay in seconds
        config.setdefault("chunk_delay", 0.5)  # Delay between chunks in seconds

        # Initialize with unified config
        super().__init__(name, config, api_key, **kwargs)

        # Use provided logger or create a default one
        self._logger = kwargs.get("logger") or default_logger

        # Initialize text splitter
        self._text_splitter = TextSplitter(
            max_bytes=self.config.max_text_bytes,
            min_chunk_ratio=self.config.min_chunk_ratio,
            logger=self._logger,
        )
        
        # Usage tracking
        self._total_chars_synthesized = 0

    def synthesize(
        self,
        text: str,
        output_path: Union[str, Path],
        **kwargs,
    ) -> bool:
        """Synthesizes text to speech using ByteDance TTS API.

        Args:
            text (str): Text to synthesize.
            output_path (str | Path): Path where audio file will be saved.
            **kwargs: Additional synthesis parameters including:
                - auto_split (bool): Whether to auto-split long text (default: True)
                - max_retries (int): Maximum retry attempts
                - Other TTS parameters

        Returns:
            bool: True if synthesis successful, False otherwise.

        Note:
            - Short text: synthesized as single file
            - Long text with auto_split=True: split into multiple files
              (format: xxx_part001.mp3, xxx_part002.mp3, ...)
            - Usage information is saved to a JSON file alongside the audio file
        """
        auto_split = kwargs.pop("auto_split", self.config.auto_split)
        text_bytes = len(text.encode("utf-8"))
        text_chars = len(text)
        
        # Reset usage counter for this synthesis
        self._total_chars_synthesized = 0

        # Short text or auto-split disabled: synthesize directly
        if not auto_split or text_bytes <= self.config.max_text_bytes:
            success = self._synthesize_single(text, output_path, **kwargs)
            if success:
                self._total_chars_synthesized = text_chars
                self._save_usage(output_path, text_chars)
            return success

        # Long text: auto-split and synthesize in chunks
        self._logger.info(f"Detected long text ({text_bytes} bytes), starting chunked synthesis")
        success = self._synthesize_chunked(text, output_path, **kwargs)
        if success:
            self._total_chars_synthesized = text_chars
            self._save_usage(output_path, text_chars)
        return success

    def _synthesize_single(self, text: str, output_path: Union[str, Path], **kwargs) -> bool:
        """Synthesize single text with retry mechanism.

        Args:
            text (str): Text to synthesize.
            output_path (str | Path): Output file path.
            **kwargs: Additional synthesis parameters.

        Returns:
            bool: True if successful, False otherwise.
        """
        max_retries = kwargs.pop("max_retries", self.config.max_retries)
        retry_delay = kwargs.pop("retry_delay", self.config.retry_delay)

        for attempt in range(max_retries):
            try:
                success = self._do_synthesize(text, output_path, **kwargs)
                if success:
                    return True

                self._logger.warning(f"Synthesis failed (attempt {attempt + 1}/{max_retries})")
            except Exception as e:
                # Catch specific auth error and re-raise to stop retries and trigger logout
                if "Unauthorized" in str(e) or "401" in str(e):
                    raise e
                self._logger.error(f"Synthesis error (attempt {attempt + 1}/{max_retries}): {e}")

            # Wait before retry
            if attempt < max_retries - 1:
                wait_time = retry_delay * (attempt + 1)
                self._logger.info(f"Waiting {wait_time}s before retry...")
                time.sleep(wait_time)

        return False

    def _synthesize_chunked(self, text: str, output_path: Union[str, Path], **kwargs) -> bool:
        """Synthesize long text in chunks.

        Args:
            text (str): Text to synthesize.
            output_path (str | Path): Base output file path.
            **kwargs: Additional synthesis parameters.

        Returns:
            bool: True if all chunks successful, False otherwise.
        """
        output_path = Path(output_path)
        output_dir = output_path.parent
        base_name = output_path.stem
        extension = output_path.suffix or ".mp3"

        # Ensure output directory exists
        output_dir.mkdir(parents=True, exist_ok=True)

        # Split text
        chunks = self._text_splitter.split(text)
        if not chunks:
            self._logger.error("Text splitting failed, no chunks generated")
            return False

        total_chunks = len(chunks)
        success_count = 0
        failed_indices = []

        self._logger.info(f"Starting chunked synthesis for {total_chunks} parts")

        # Synthesize each chunk
        for i, chunk in enumerate(chunks, 1):
            chunk_filename = f"{base_name}_part{i:03d}{extension}"
            chunk_path = output_dir / chunk_filename

            self._logger.info(
                f"Synthesizing [{i}/{total_chunks}]: "
                f"{len(chunk)} chars, {len(chunk.encode('utf-8'))} bytes"
            )

            success = self._synthesize_single(chunk, chunk_path, **kwargs)

            if success:
                success_count += 1
                self._logger.info(f"✓ Part {i} succeeded: {chunk_filename}")
            else:
                failed_indices.append(i)
                self._logger.error(f"✗ Part {i} failed")

            # Delay between chunks to avoid rate limiting
            if i < total_chunks:
                time.sleep(self.config.chunk_delay)  # type: ignore[attr-defined]

        # Log summary
        self._logger.info(f"Chunked synthesis completed: {success_count}/{total_chunks} succeeded")

        if failed_indices:
            self._logger.warning(f"Failed parts: {failed_indices}")
            return False

        # Merge chunked outputs if all succeeded
        chunk_files = [
            output_dir / f"{base_name}_part{i:03d}{extension}" for i in range(1, total_chunks + 1)
        ]

        merge_result = merge_chunked_outputs(
            chunk_files=chunk_files,
            output_path=output_path,
            logger=self._logger,  # type: ignore[arg-type]
        )

        if merge_result.get("audio_merged"):
            self._logger.info("✓ Chunked outputs merged successfully")
        else:
            self._logger.warning(
                f"Merge completed with warnings: {merge_result.get('error', 'Unknown')}"
            )

        return True

    def _do_synthesize(self, text: str, output_path: Union[str, Path], **kwargs) -> bool:
        """Execute actual TTS synthesis (original logic).

        Args:
            text (str): Text to synthesize.
            output_path (str | Path): Output file path.
            **kwargs: Additional synthesis parameters.

        Returns:
            bool: True if successful, False otherwise.
        """
        payload = self._build_payload(text, **kwargs)
        headers = self._build_headers()

        try:
            response = requests.post(
                self.config.http_url,
                headers=headers,
                json=payload,
                timeout=kwargs.get("timeout", 30),
            )

            if response.status_code == 401:
                self._logger.error("API returned 401 Unauthorized")
                raise UnauthorizedError("API returned 401 Unauthorized")

            # 只在失败时记录详细日志
            if response.status_code == 200:
                return self._process_response(response, text, output_path)
            else:
                self._logger.error(f"Request failed: {response.status_code}, {response.text}")
                return False

        except Exception as e:
            # Propagate UnauthorizedError
            if "Unauthorized" in str(e) or "401" in str(e):
                raise e
            self._logger.error(f"Synthesis failed: {str(e)}")
            return False

    def _build_payload(self, text: str, **kwargs) -> Dict[str, Any]:
        """Builds the request payload for TTS API.

        Args:
            text (str): Text to synthesize.
            **kwargs: Additional parameters to override defaults.

        Returns:
            Dict[str, Any]: Complete payload for API request.
        """
        return {
            "app": {
                "appid": self.config.app_id,
                "token": self.config.access_token,
                "cluster": kwargs.get("cluster", "volcano_tts"),
            },
            "user": {"uid": kwargs.get("user_id", "test_user_123")},
            "audio": {
                "voice_type": kwargs.get("voice_type", self.config.voice_type),
                "encoding": kwargs.get("encoding", self.config.encoding),
                "speed_ratio": kwargs.get("speed_ratio", self.config.speed_ratio),
                "rate": kwargs.get("sample_rate", self.config.sample_rate),
            },
            "request": {
                "reqid": str(uuid.uuid4()),
                "text": text,
                "operation": "query",
                "with_timestamp": 1,
            },
        }

    def _build_headers(self) -> Dict[str, str]:
        """Builds HTTP headers for API request.

        Returns:
            Dict[str, str]: Headers dictionary.
        """
        headers = {
            "Content-Type": "application/json",
        }
        
        # If an auth_token is provided (e.g. from login), use it.
        # Check if auth_token exists in config (via Pydantic model extra fields)
        if hasattr(self.config, "auth_token") and self.config.auth_token:
            headers["Authorization"] = self.config.auth_token
        else:
            headers["Authorization"] = f"Bearer;{self.config.access_token}"
            
        return headers

    def _process_response(
        self,
        response: requests.Response,
        text: str,
        output_path: Union[str, Path],
    ) -> bool:
        """Processes the TTS API response and saves audio file.

        Args:
            response (requests.Response): API response object.
            text (str): Original text that was synthesized.
            output_path (str | Path): Path to save audio file.

        Returns:
            bool: True if processing successful, False otherwise.
        """
        try:
            result = response.json()

            addition = result.get("addition", {})
            duration = addition.get("duration", "N/A")

            if result.get("data"):
                audio_data = base64.b64decode(result["data"])
                Path(output_path).write_bytes(audio_data)
            else:
                self._logger.error("No audio data returned")
                return False

            self._save_enhanced_timestamps(output_path, text, addition, duration=duration)
            return True

        except Exception as e:
            self._logger.error(f"Response processing failed: {str(e)}")
            return False

    def _save_enhanced_timestamps(
        self,
        output_path: Union[str, Path],
        text: str,
        addition: Dict[str, Any],
        duration: Optional[Union[str, int]] = None,
    ) -> Optional[str]:
        """Saves enhanced timestamps with sentence-level information.

        Args:
            output_path (str | Path): Original audio file path.
            text (str): The synthesized text.
            addition (Dict[str, Any]): Addition data from TTS response.
            duration (Optional[Union[str, int]]): Audio duration in milliseconds.

        Returns:
            Optional[str]: Path to saved timestamp JSON file, None if failed.
        """
        try:
            # Extract character-level timestamps from response
            timestamps = None
            frontend_data = addition.get("frontend")

            if frontend_data:
                if isinstance(frontend_data, str):
                    frontend_json = json.loads(frontend_data)
                else:
                    frontend_json = frontend_data
                timestamps = frontend_json.get("words", [])
            else:
                self._logger.warning("No frontend data in response")
                return None

            if not timestamps:
                self._logger.warning("No timestamps found in response")
                return None

            enhanced_data = enhance_timestamps_with_sentences(
                text=text,
                char_timestamps=timestamps,
                total_duration=(int(duration) if duration != "N/A" and duration is not None else 0),
            )

            # 转换为 ASR 兼容格式
            result_data = {
                "text": enhanced_data.get("text", ""),
                "utterances": enhanced_data.get("sentence_info", []),
            }

            usage_data = {
                "model": "bytedance-tts",
                "total_duration_ms": enhanced_data.get("total_duration_ms", 0),
            }

            output_data = [
                {
                    "file_url": str(output_path),
                    "status": "success",
                    "transcription": {
                        "result": result_data,
                        "usage": usage_data,
                    },
                }
            ]

            timestamp_path = Path(output_path).with_suffix(".json")
            with open(timestamp_path, "w", encoding="utf-8") as f:
                json.dump(output_data, f, ensure_ascii=False, indent=2)

            return str(timestamp_path)

        except Exception as e:
            self._logger.error(f"Failed to save enhanced timestamps: {str(e)}")
            return None
    
    def _save_usage(self, output_path: Union[str, Path], total_chars: int) -> Optional[str]:
        """Saves TTS usage information.

        Args:
            output_path (Union[str, Path]): Original audio file path.
            total_chars (int): Total number of characters synthesized.

        Returns:
            Optional[str]: Path to saved usage JSON file, None if failed.
        """
        try:
            timestamp_path = Path(output_path).with_suffix(".json")

            if timestamp_path.exists():
                # Read existing data and update usage
                with open(timestamp_path, "r", encoding="utf-8") as f:
                    existing_data = json.load(f)

                if isinstance(existing_data, list) and len(existing_data) > 0:
                    # 新格式不需要额外操作，usage 已完整
                    pass
                else:
                    existing_data["usage"] = {"model": "bytedance-tts"}

                with open(timestamp_path, "w", encoding="utf-8") as f:
                    json.dump(existing_data, f, ensure_ascii=False, indent=2)
            else:
                # If timestamp file doesn't exist, create a new one with usage only
                usage_data = {
                    "model": "bytedance-tts",
                }
                with open(timestamp_path, "w", encoding="utf-8") as f:
                    json.dump({"file_url": str(output_path), "usage": usage_data}, f, ensure_ascii=False, indent=2)

            self._logger.debug(f"TTS usage saved: {total_chars} chars")
            return str(timestamp_path)
            
        except Exception as e:
            self._logger.error(f"Failed to save TTS usage: {str(e)}")
            return None
    
    def get_usage(self) -> Dict[str, Any]:
        """Gets the usage information for the last synthesis.
        
        Returns:
            Dict[str, Any]: Usage information with model and char_count.
        """
        return {
            "model": "bytedance-tts",
            "char_count": self._total_chars_synthesized
        }
