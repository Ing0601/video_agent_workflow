from ..tts.base import BaseTTSModel
from typing import Optional, Dict, Any
import os
import dashscope
import json
from dashscope.audio.tts_v2 import SpeechSynthesizer
from pathlib import Path
from typing import Union

from ..asr.bytedance_llm_asr import ByteDanceASR
from ...utils.upload_files import upload_file_tos
from .voice_manager import VoiceManager

class CosyVoiceTTSModel(BaseTTSModel):
    """CosyVoice TTS model implementation with voice cloning support.
    
    This class provides text-to-speech synthesis using Alibaba's CosyVoice service
    with support for custom voice cloning and predefined voices.
    """
    
    def __init__(
        self,
        name: str = "cosyvoice_tts", 
        config: Optional[Dict[str, Any]] = None,
        api_key: Optional[str] = None,
        **kwargs,
    ):
        """Initializes CosyVoice TTS model.
        
        Args:
            name: Model name identifier.
            config: Configuration dictionary containing model settings.
            api_key: API key for DashScope service.
            **kwargs: Additional arguments passed to base class.
        """
        # Set CosyVoice-specific defaults
        config = config or {}
        config.setdefault("model", "cosyvoice-v3-plus")
        config.setdefault("voice_poll_attempts", 30)
        config.setdefault("voice_poll_interval", 10)
        
        # Voice source defaults
        voice_source = config.setdefault("voice_source", {})
        voice_source.setdefault("mode", "clone")  # "clone" or "existing"
        
        # ASR configuration for timestamp generation
        config.setdefault("enable_asr_timestamps", True)
        
        super().__init__(name, config, api_key, **kwargs)
        
        # Initialize DashScope API
        api_key = api_key or self.config.access_token or os.getenv("DASHSCOPE_API_KEY")
        if not api_key:
            raise ValueError("DASHSCOPE_API_KEY environment variable or api_key parameter required")
        
        dashscope.api_key = api_key
        
        # Initialize voice manager
        self.voice_manager = VoiceManager(self.config.dict(), self._logger)
        
        # Initialize ASR for timestamp generation if enabled
        self._asr_client = None
        if self.config.enable_asr_timestamps:
            self._init_asr_client()

    def _init_asr_client(self):
        """Initializes ASR client for timestamp generation."""
        try:
            # Get ASR configuration from environment or config (支持多种环境变量名)
            # 优先使用 BYTEDANCE_APP_ID/ACCESS_TOKEN，与 ByteDanceASR 保持一致
            app_id = (os.getenv("BYTEDANCE_APP_ID") or 
                     os.getenv("VOLCANO_ASR_APP_ID") or 
                     os.getenv("ASR_APP_ID") or 
                     getattr(self.config, 'asr_app_id', None))
            access_token = (os.getenv("BYTEDANCE_ACCESS_TOKEN") or 
                           os.getenv("VOLCANO_ASR_ACCESS_TOKEN") or 
                           os.getenv("ASR_ACCESS_TOKEN") or 
                           getattr(self.config, 'asr_access_token', None))
            
            # TOS configuration for file upload
            tos_config = {
                "access_key": os.getenv("TOS_ACCESS_KEY") or getattr(self.config, 'tos_access_key', None),
                "secret_key": os.getenv("TOS_SECRET_KEY") or getattr(self.config, 'tos_secret_key', None),
                "bucket_name": os.getenv("TOS_BUCKET_NAME") or getattr(self.config, 'tos_bucket_name', None),
                "endpoint": os.getenv("TOS_ENDPOINT", "tos-cn-beijing.volces.com"),
                "region": os.getenv("TOS_REGION", "cn-beijing"),
            }
            
            if app_id and access_token and tos_config["access_key"] and tos_config["secret_key"] and tos_config["bucket_name"]:
                self._asr_client = ByteDanceASR(
                    app_id=app_id,
                    access_token=access_token
                )
                # 保存 TOS 配置供后续上传使用
                self._tos_config = tos_config
                self._logger.info("ASR client initialized for timestamp generation")
            else:
                self._tos_config = None
                self._logger.warning("ASR configuration incomplete, timestamps will not be generated")
                self._logger.warning("Required: BYTEDANCE_APP_ID (or VOLCANO_ASR_APP_ID), BYTEDANCE_ACCESS_TOKEN (or VOLCANO_ASR_ACCESS_TOKEN), TOS_ACCESS_KEY, TOS_SECRET_KEY, TOS_BUCKET_NAME")
                
        except Exception as e:
            self._logger.warning(f"Failed to initialize ASR client: {e}")
            self._asr_client = None
            self._tos_config = None

    def synthesize(
        self,
        text: str,
        output_path: Union[str, Path],
        **kwargs,
    ) -> bool:
        """Synthesizes input text to audio using CosyVoice.
        
        Args:
            text: The text to synthesize.
            output_path: Path where the audio file will be saved.
            **kwargs: Additional parameters including voice configuration.
            
        Returns:
            bool: True if synthesis was successful, False otherwise.
        """
        try:
            # Ensure voice is ready for synthesis
            voice_id = self.voice_manager.ensure_voice_ready(**kwargs)
            
            # Perform synthesis
            return self._do_synthesize(text, output_path, voice_id, **kwargs)
            
        except Exception as e:
            self._logger.error(f"CosyVoice synthesis failed: {e}")
            return False

    def _do_synthesize(
        self, 
        text: str, 
        output_path: Union[str, Path], 
        voice_id: str,
        **kwargs
    ) -> bool:
        """Performs the actual text-to-speech synthesis.
        
        Args:
            text: Text to synthesize.
            output_path: Output file path.
            voice_id: Voice ID for synthesis.
            **kwargs: Additional synthesis parameters.
            
        Returns:
            bool: True if successful, False otherwise.
        """
        try:
            model = self.config.model
            synthesizer = SpeechSynthesizer(model=model, voice=voice_id)
            
            self._logger.info(f"Synthesizing text with voice: {voice_id}")
            
            # Perform synthesis
            audio_data = synthesizer.call(text)
            
            # Save audio file
            output_path = Path(output_path)
            output_path.parent.mkdir(parents=True, exist_ok=True)
            
            with open(output_path, "wb") as f:
                f.write(audio_data)
            
            self._logger.info(f"Audio saved to: {output_path}")
            
            # Generate timestamps using ASR if enabled
            if self.config.enable_asr_timestamps and self._asr_client:
                self._generate_timestamps_with_asr(text, output_path)
            
            return True
            
        except Exception as e:
            self._logger.error(f"Synthesis failed: {e}")
            return False

    def _generate_timestamps_with_asr(self, text: str, audio_file: Union[str, Path]):
        """Generate timestamps using ASR and save to JSON file.
        
        Args:
            text: Original text that was synthesized.
            audio_file: Path to the audio file.
        """
        if not self._asr_client:
            self._logger.warning("ASR client not initialized, skipping timestamp generation")
            return
        
        try:
            self._logger.info("Generating timestamps using ASR...")
            
            # Upload audio file to TOS first to get a public URL
            audio_file_str = str(audio_file)
            audio_url = None
            
            if self._tos_config:
                audio_url = upload_file_tos(
                    file_path=audio_file_str,
                    tos_config=self._tos_config,
                    folder="cosyvoice_asr_audio"
                )
            
            if not audio_url:
                self._logger.warning("Failed to upload audio file to TOS, cannot generate timestamps")
                return
            
            # Call ASR transcribe method with include_words=True for word-level timestamps
            asr_results = self._asr_client.transcribe(
                audio_url,
                include_words=True,
                enable_speaker_info=False,
                enable_punc=True,
                enable_itn=False,  # Keep original text form for timestamp matching
            )
            
            if not asr_results or len(asr_results) == 0:
                self._logger.warning("ASR returned no results")
                return
            
            asr_result = asr_results[0]
            
            # Check if transcription was successful
            if asr_result.get("status") != "success":
                self._logger.warning(f"ASR transcription failed: {asr_result.get('error', 'Unknown error')}")
                return
            
            transcription = asr_result.get("transcription", {})
            result_data = transcription.get("result", {})
            
            # Get utterances (sentence-level info)
            utterances = result_data.get("utterances", [])
            
            # Get usage info for total duration
            usage = transcription.get("usage", {})
            total_duration_ms = usage.get("total_duration_ms", 0)
            total_duration_seconds = total_duration_ms / 1000.0 if total_duration_ms else 0
            
            if not utterances:
                self._logger.warning("No utterances found in ASR result")
                return
            
            # Convert utterances to sentence_info format
            sentence_info_list = []
            for utterance in utterances:
                sentence_info_list.append({
                    "start": utterance.get("start_time", 0),
                    "end": utterance.get("end_time", 0),
                    "text": utterance.get("text", "")
                })
            
            # Collect word-level timestamps from all utterances
            word_info_list = []
            for utterance in utterances:
                words = utterance.get("words", [])
                word_info_list.extend(words)
            
            # Use word-level info as character-level timestamps if available
            char_timestamps = []
            if word_info_list:
                # ASR word_info contains word-level timestamps
                char_timestamps = word_info_list
                self._logger.info(f"Using {len(char_timestamps)} word-level timestamps from ASR")
            else:
                # Fallback: convert sentence-level to character-level
                char_timestamps = self._convert_sentences_to_char_timestamps(text, sentence_info_list)
                self._logger.info(f"Generated {len(char_timestamps)} character-level timestamps from sentences")
            
            # Calculate total duration from sentence info if not available from usage
            if total_duration_ms == 0 and sentence_info_list:
                total_duration_ms = int(max(s.get("end", 0) for s in sentence_info_list))
                total_duration_seconds = total_duration_ms / 1000.0
            
            # Convert sentence_info timestamps from milliseconds to seconds (3 decimal places)
            converted_sentence_info = []
            for sentence in sentence_info_list:
                converted_sentence_info.append({
                    "start": round(sentence.get("start", 0) / 1000.0, 3),
                    "end": round(sentence.get("end", 0) / 1000.0, 3),
                    "text": sentence.get("text", "")
                })
            
            # Create timestamps in the same format as ByteDance TTS
            timestamps = {
                "text": text,
                "total_duration_ms": total_duration_ms,
                "total_duration_seconds": total_duration_seconds,
                "char_count": len(text),
                "sentence_count": len(converted_sentence_info),
                "char_timestamps": char_timestamps,
                "sentence_timestamps": [],  # Keep empty like ByteDance TTS
                "sentence_info": converted_sentence_info
            }
            
            # Save timestamps to JSON file
            timestamp_file = audio_file_str.replace('.mp3', '.json')
            with open(timestamp_file, 'w', encoding='utf-8') as f:
                json.dump(timestamps, f, ensure_ascii=False, indent=2)
                
            self._logger.info(f"Timestamps saved to: {timestamp_file}")
            
        except Exception as e:
            self._logger.warning(f"ASR processing failed, no timestamps generated: {e}")

    def _convert_sentences_to_char_timestamps(self, text: str, sentence_info: list) -> list:
        """Converts sentence-level timestamps to character-level timestamps.
        
        Args:
            text: Original text.
            sentence_info: List of sentence info from ASR with start_time/end_time times.
            
        Returns:
            list: List of character-level timestamps compatible with enhance_timestamps_with_sentences.
        """
        char_timestamps = []
        
        for sentence in sentence_info:
            sentence_text = sentence.get("text", "")
            # ByteDanceASR uses start_time/end_time
            start_time_ms = sentence.get("start_time", 0) or sentence.get("start", 0)
            end_time_ms = sentence.get("end_time", 0) or sentence.get("end", 0)
            
            # Distribute time evenly across characters in the sentence
            sentence_length = len(sentence_text)
            if sentence_length > 0:
                time_per_char = (end_time_ms - start_time_ms) / sentence_length
                
                for i, char in enumerate(sentence_text):
                    char_start = start_time_ms + int(i * time_per_char)
                    char_end = start_time_ms + int((i + 1) * time_per_char)
                    
                    char_timestamps.append({
                        "word": char,
                        "start_time": char_start,
                        "end_time": char_end,
                        "confidence": 0.9  # Set a default confidence
                    })
        
        return char_timestamps