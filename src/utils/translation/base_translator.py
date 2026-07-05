from __future__ import annotations

from abc import ABC, abstractmethod


class BaseTranslator(ABC):
    """翻译器抽象基类。"""

    @abstractmethod
    def translate_text(
        self,
        text: str,
        target_language: str,
        *,
        max_retries: int = 3,
    ) -> str:
        """
        将纯文本翻译为目标语言，并返回翻译结果（纯文本）。
        """

