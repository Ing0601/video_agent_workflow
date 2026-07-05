import json
import os
import re
import subprocess
import tempfile
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence, Union


def convert_char_timestamps_to_sentences(
    text: str, char_timestamps: List[Dict[str, Any]]
) -> List[Dict[str, Any]]:
    """Converts character-level timestamps to sentence-level timestamps.

    This function takes a text string and its corresponding character-level timestamps,
    then groups them into sentences based on punctuation marks and calculates
    sentence-level timing information.

    Args:
        text (str): The complete text string.
        char_timestamps (List[Dict[str, Any]]): List of character-level timestamps.
            Each timestamp dict should contain: 'word' (character), 'start_time' (ms),
            'end_time' (ms), and optionally 'confidence'.

    Returns:
        List[Dict[str, Any]]: List of sentence-level timestamps. Each dict contains:
            - text (str): The sentence text
            - start_time (int): Sentence start time in milliseconds
            - end_time (int): Sentence end time in milliseconds
            - start_seconds (float): Sentence start time in seconds
            - end_seconds (float): Sentence end time in seconds
            - duration_ms (int): Sentence duration in milliseconds
            - duration_seconds (float): Sentence duration in seconds
            - char_count (int): Number of characters in the sentence
            - char_timestamps (List[Dict]): Character timestamps within the sentence
            - avg_confidence (float): Average confidence score for the sentence

    Example:
        >>> text = "这是第一句。这是第二句！"
        >>> char_timestamps = [
        ...     {'word': '这', 'start_time': 100, 'end_time': 200, 'confidence': 0.9},
        ...     {'word': '是', 'start_time': 200, 'end_time': 300, 'confidence': 0.8},
        ...     # ... more timestamps
        ... ]
        >>> sentences = convert_char_timestamps_to_sentences(text, char_timestamps)
        >>> print(sentences[0]['text'])  # "这是第一句。"
    """
    if not text or not char_timestamps:
        return []

    sentence_timestamps = []
    current_sentence_start_time = None
    current_sentence_end_time = None
    current_sentence_chars = []
    current_sentence_timestamps = []
    confidence_scores = []

    sentence_ending_pattern = re.compile(r"[。！？\.!?；;，,]+")

    for i, timestamp in enumerate(char_timestamps):
        word = timestamp.get("word", "")
        if not word:
            continue

        if current_sentence_start_time is None:
            current_sentence_start_time = timestamp.get("start_time")

        current_sentence_end_time = timestamp.get("end_time")
        current_sentence_chars.append(word)
        current_sentence_timestamps.append(timestamp)

        confidence = timestamp.get("confidence")
        if confidence is not None:
            confidence_scores.append(confidence)

        if sentence_ending_pattern.search(word):
            sentence_text = "".join(current_sentence_chars)

            if current_sentence_start_time is not None and current_sentence_end_time is not None:
                avg_confidence = (
                    sum(confidence_scores) / len(confidence_scores) if confidence_scores else 0.0
                )

                sentence_timestamps.append(
                    {
                        "text": sentence_text,
                        "start_time": current_sentence_start_time,
                        "end_time": current_sentence_end_time,
                        "start_seconds": current_sentence_start_time / 1000.0,
                        "end_seconds": current_sentence_end_time / 1000.0,
                        "duration_ms": current_sentence_end_time - current_sentence_start_time,
                        "duration_seconds": (
                            current_sentence_end_time - current_sentence_start_time
                        )
                        / 1000.0,
                        "char_count": len(current_sentence_chars),
                        "char_timestamps": current_sentence_timestamps.copy(),
                        "avg_confidence": avg_confidence,
                    }
                )

            current_sentence_start_time = None
            current_sentence_end_time = None
            current_sentence_chars = []
            current_sentence_timestamps = []
            confidence_scores = []

    if (
        current_sentence_chars
        and current_sentence_start_time is not None
        and current_sentence_end_time is not None
    ):
        sentence_text = "".join(current_sentence_chars)
        avg_confidence = (
            sum(confidence_scores) / len(confidence_scores) if confidence_scores else 0.0
        )

        sentence_timestamps.append(
            {
                "text": sentence_text,
                "start_time": current_sentence_start_time,
                "end_time": current_sentence_end_time,
                "start_seconds": current_sentence_start_time / 1000.0,
                "end_seconds": current_sentence_end_time / 1000.0,
                "duration_ms": current_sentence_end_time - current_sentence_start_time,
                "duration_seconds": (current_sentence_end_time - current_sentence_start_time)
                / 1000.0,
                "char_count": len(current_sentence_chars),
                "char_timestamps": current_sentence_timestamps,
                "avg_confidence": avg_confidence,
            }
        )

    return sentence_timestamps


def enhance_timestamps_with_sentences(
    text: str,
    char_timestamps: List[Dict[str, Any]],
    total_duration: Optional[int] = None,
) -> Dict[str, Any]:
    """Enhances character-level timestamp data with sentence-level information.

    This function takes the original timestamp data and adds sentence-level
    groupings, making it easier to work with sentence-based operations
    while preserving the original character-level details.

    Args:
        text (str): The complete text string.
        char_timestamps (List[Dict[str, Any]]): Character-level timestamps from TTS/ASR.
        total_duration (int, optional): Total duration in milliseconds. If not provided,
            it will be calculated from the last character's end_time.

    Returns:
        Dict[str, Any]: Enhanced timestamp data containing:
            - text (str): Original text
            - total_duration_ms (int): Total duration in milliseconds
            - total_duration_seconds (float): Total duration in seconds
            - char_count (int): Total character count
            - sentence_count (int): Total sentence count
            - char_timestamps (List[Dict]): Original character timestamps
            - sentence_timestamps (List[Dict]): Sentence-level timestamps
            - sentence_info (List[Dict]): Formatted sentence info (ASR compatible)

    Example:
        >>> result = enhance_timestamps_with_sentences(text, timestamps, 5000)
        >>> print(f"Found {result['sentence_count']} sentences")
        >>> print(f"Total duration: {result['total_duration_seconds']:.2f}s")
    """
    if not text or not char_timestamps:
        return {
            "text": text,
            "total_duration_ms": total_duration or 0,
            "total_duration_seconds": (total_duration or 0) / 1000.0,
            "char_count": len(text) if text else 0,
            "sentence_count": 0,
            "char_timestamps": char_timestamps,
            "sentence_timestamps": [],
            "sentence_info": [],
        }

    sentence_timestamps = convert_char_timestamps_to_sentences(text, char_timestamps)

    if total_duration is None and char_timestamps:
        total_duration = max(ts.get("end_time", 0) for ts in char_timestamps)

    sentence_info = []
    for sentence in sentence_timestamps:
        sentence_info.append(
            {
                "text": sentence["text"],
                "start_time": sentence["start_time"],
                "end_time": sentence["end_time"],
                "speaker": "1",
            }
        )

    return {
        "text": text,
        "total_duration_ms": total_duration or 0,
        "total_duration_seconds": (total_duration or 0) / 1000.0,
        "char_count": len(text),
        "sentence_count": len(sentence_timestamps),
        "char_timestamps": char_timestamps,
        "sentence_timestamps": sentence_timestamps,
        "sentence_info": sentence_info,
    }


def merge_timestamp_files(
    json_files: Sequence[Union[str, Path]],
    output_path: Union[str, Path],
    logger: Optional[Any] = None,
) -> bool:
    """Merge multiple timestamp JSON files into a single file.

    The merge logic:
    - text: Direct concatenation of all texts
    - total_duration_ms: Sum of all durations
    - utterances: All sentences with cumulative time offsets
        - 1st file: timestamps unchanged
        - 2nd file: timestamps += duration of 1st file
        - 3rd file: timestamps += duration of (1st + 2nd) files
        - And so on...

    Args:
        json_files: List of JSON file paths to merge (in order).
        output_path: Path where merged JSON file will be saved.
        logger: Optional logger instance.

    Returns:
        bool: True if merge successful, False otherwise.
    """
    if not json_files:
        return False

    try:
        merged_text = ""
        merged_utterances = []
        total_duration_ms = 0
        cumulative_duration_ms = 0

        for json_file in json_files:
            if logger:
                logger.debug(f"Processing timestamp file: {json_file}")

            with open(json_file, "r", encoding="utf-8") as f:
                data = json.load(f)

            # Handle both old format (dict) and new format (list)
            file_duration_ms = 0
            if isinstance(data, list) and len(data) > 0:
                item = data[0]
                transcription = item.get("transcription", {})
                result = transcription.get("result", {})
                usage = transcription.get("usage", {})

                merged_text += result.get("text", "")
                file_duration_ms = usage.get("total_duration_ms", 0)
                total_duration_ms += file_duration_ms
                sentences = result.get("utterances", [])
            else:
                merged_text += data.get("text", "")
                file_duration_ms = data.get("total_duration_ms", 0)
                total_duration_ms += file_duration_ms
                sentences = data.get("sentence_info", data.get("utterances", []))

            for sentence in sentences:
                adjusted_sentence = sentence.copy()
                adjusted_sentence["start_time"] = sentence["start_time"] + cumulative_duration_ms
                adjusted_sentence["end_time"] = sentence["end_time"] + cumulative_duration_ms
                merged_utterances.append(adjusted_sentence)

            cumulative_duration_ms += file_duration_ms

        # Output in ASR format
        merged_data = [
            {
                "status": "success",
                "transcription": {
                    "result": {
                        "text": merged_text,
                        "utterances": merged_utterances,
                    },
                    "usage": {
                        "model": "bytedance-tts",
                        "total_duration_ms": total_duration_ms,
                    },
                },
            }
        ]

        with open(output_path, "w", encoding="utf-8") as f:
            json.dump(merged_data, f, ensure_ascii=False, indent=2)

        return True

    except Exception as e:
        if logger:
            logger.error(f"Timestamp merge error: {e}")
        return False


def merge_audio_files(
    audio_files: Sequence[Union[str, Path]],
    output_path: Union[str, Path],
) -> bool:
    """Merge multiple audio files into a single file using ffmpeg.

    Args:
        audio_files: List of audio file paths to merge (in order).
        output_path: Path where merged audio file will be saved.

    Returns:
        bool: True if merge successful, False otherwise.
    """
    if not audio_files:
        return False

    try:
        with tempfile.NamedTemporaryFile(mode='w', suffix='.txt', delete=False) as f:
            for audio_file in audio_files:
                f.write(f"file '{Path(audio_file).absolute()}'\n")
            concat_file = f.name

        try:
            result = subprocess.run(
                [
                    'ffmpeg', '-y', '-f', 'concat', '-safe', '0',
                    '-i', concat_file, '-c', 'copy', str(output_path)
                ],
                capture_output=True,
                text=True,
                timeout=300
            )
            return result.returncode == 0
        finally:
            os.unlink(concat_file)

    except Exception:
        return False


def merge_chunked_outputs(
    chunk_files: Sequence[Union[str, Path]],
    output_path: Union[str, Path],
    logger: Optional[Any] = None,
    cleanup: bool = True,
) -> Dict[str, Any]:
    """Merge chunked TTS outputs (both audio and timestamp files).

    Args:
        chunk_files: List of audio chunk file paths (e.g., part001.mp3, part002.mp3).
        output_path: Base output path for merged files.
        logger: Optional logger instance.
        cleanup: Whether to delete intermediate chunk files after successful merge (default: True).

    Returns:
        Dict containing merge results:
            - audio_merged: bool
            - audio_path: str (if successful)
            - timestamps_merged: bool
            - timestamps_path: str (if successful)
            - error: str (if failed)
    """
    result: Dict[str, Any] = {
        "audio_merged": False,
        "timestamps_merged": False,
    }

    if not chunk_files:
        result["error"] = "No chunk files provided"
        return result

    output_path = Path(output_path)

    try:
        if logger:
            logger.info(f"Merging {len(chunk_files)} audio chunks using ffmpeg...")

        audio_merged = merge_audio_files(chunk_files, output_path)

        if audio_merged:
            result["audio_merged"] = audio_merged
            result["audio_path"] = str(output_path)
            if logger:
                logger.info(f"✓ Audio merged successfully: {output_path}")
        else:
            if logger:
                logger.warning("✗ Audio merge failed (check if ffmpeg is installed)")
            result["error"] = "Audio merge failed"

    except Exception as e:
        if logger:
            logger.error(f"Audio merge error: {e}")
        result["error"] = str(e)

    json_files = []
    try:
        json_files = [Path(f).with_suffix(".json") for f in chunk_files]
        existing_json_files = [f for f in json_files if f.exists()]

        if existing_json_files:
            if logger:
                logger.info(f"Merging {len(existing_json_files)} timestamp files...")

            timestamps_output = output_path.with_suffix(".json")
            timestamps_merged = merge_timestamp_files(
                existing_json_files, timestamps_output, logger=logger
            )

            if timestamps_merged:
                result["timestamps_merged"] = timestamps_merged
                result["timestamps_path"] = str(timestamps_output)
                if logger:
                    logger.info(f"✓ Timestamps merged successfully: {timestamps_output}")
            else:
                if logger:
                    logger.warning("✗ Timestamp merge failed")
        else:
            if logger:
                logger.info("No timestamp files found to merge")

    except Exception as e:
        if logger:
            logger.error(f"Timestamp merge error: {e}")
        if "error" not in result:
            result["error"] = str(e)

    if cleanup and result["audio_merged"]:
        try:
            if logger:
                logger.info(f"Cleaning up {len(chunk_files)} intermediate files...")

            cleaned_count = 0
            for chunk_file in chunk_files:
                chunk_path = Path(chunk_file)
                if chunk_path.exists():
                    chunk_path.unlink()
                    cleaned_count += 1

                json_path = chunk_path.with_suffix(".json")
                if json_path.exists():
                    json_path.unlink()
                    cleaned_count += 1

            if logger:
                logger.info(f"✓ Cleaned up {cleaned_count} intermediate files")

        except Exception as e:
            if logger:
                logger.warning(f"Cleanup warning: {e}")

    return result
