from typing import List

from ...logger.logging import logger as default_logger


class TextSplitter:
    """Smart text splitter that segments text based on byte size and punctuation priority."""

    # Punctuation priority: lower number = higher priority
    PUNCTUATION_PRIORITY = {
        "。": 1,
        "！": 2,
        "？": 2,
        "；": 3,
        "：": 3,
        "，": 4,
        "、": 4,
    }

    def __init__(
        self,
        max_bytes: int = 1024,
        min_chunk_ratio: float = 0.3,
        logger=None,
    ):
        """Initialize text splitter.

        Args:
            max_bytes: Maximum bytes per chunk (UTF-8 encoded).
            min_chunk_ratio: Minimum chunk size ratio to avoid too small chunks.
            logger: Logger instance.
        """
        self.max_bytes = max_bytes
        self.min_chunk_ratio = min_chunk_ratio
        self._logger = logger or default_logger

    def split(self, text: str) -> List[str]:
        """Split text into multiple chunks intelligently.

        Args:
            text: Text to split.

        Returns:
            List of text chunks.
        """
        if not text.strip():
            return []

        text_bytes = len(text.encode("utf-8"))

        if text_bytes <= self.max_bytes:
            return [text]

        self._logger.info(f"Text needs splitting: {len(text)} chars, {text_bytes} bytes")

        chunks = []
        start_pos = 0
        text_len = len(text)

        while start_pos < text_len:
            byte_limit_pos = self._find_byte_limit_position(text, start_pos, self.max_bytes)

            best_split_pos = self._find_best_split_point(text, start_pos, byte_limit_pos)

            chunk = text[start_pos:best_split_pos].strip()
            if chunk:
                chunk_bytes = len(chunk.encode("utf-8"))
                chunks.append(chunk)
                self._logger.debug(
                    f"Chunk {len(chunks)}: {len(chunk)} chars, "
                    f"{chunk_bytes} bytes, ends with: '{chunk[-1] if chunk else ''}'"
                )

            start_pos = best_split_pos

            if start_pos >= text_len:
                break

        self._logger.info(f"Text split into {len(chunks)} chunks")
        return chunks

    def _find_byte_limit_position(self, text: str, start: int, max_bytes: int) -> int:
        """Find the maximum position from start without exceeding max_bytes.

        Args:
            text: Full text.
            start: Start position.
            max_bytes: Maximum bytes allowed.

        Returns:
            Position that doesn't exceed byte limit.
        """
        current_bytes = 0
        position = start

        for i in range(start, len(text)):
            char_bytes = len(text[i].encode("utf-8"))
            if current_bytes + char_bytes <= max_bytes:
                current_bytes += char_bytes
                position = i + 1
            else:
                break

        if position == start and start < len(text):
            position = start + 1

        return position

    def _find_best_split_point(self, text: str, start: int, byte_limit: int) -> int:
        """Find the best split point within reasonable range (prefer punctuation).

        Args:
            text: Full text.
            start: Start position.
            byte_limit: Byte limit position.

        Returns:
            Best split position.
        """
        if byte_limit >= len(text):
            return len(text)

        min_size = max(
            int((byte_limit - start) * self.min_chunk_ratio),
            10,  # At least 10 characters
        )
        search_start = start + min_size

        best_pos = byte_limit
        best_priority = float("inf")

        for i in range(byte_limit - 1, search_start - 1, -1):
            char = text[i]
            if char in self.PUNCTUATION_PRIORITY:
                priority = self.PUNCTUATION_PRIORITY[char]
                if priority < best_priority:
                    best_priority = priority
                    best_pos = i + 1  # Include the punctuation
                    if priority == 1:
                        break

        return best_pos
