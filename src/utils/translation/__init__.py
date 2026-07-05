from __future__ import annotations

import os
import time
from typing import Callable, Optional

from .providers import SiliconFlowHunyuanMT7BTranslator


def validate_inputs(*, text: str, target_language: str) -> tuple[str, str]:
    """校验输入，并返回去首尾空格后的值。"""

    if text is None or not isinstance(text, str) or not text.strip():
        raise ValueError("参数 --text 不能为空")
    if target_language is None or not isinstance(target_language, str) or not target_language.strip():
        raise ValueError("参数 --target 不能为空")
    return text.strip(), target_language.strip()


def build_prompt(*, text: str, target_language: str) -> str:
    """
    构建固定中文 prompt 模板，确保模型只输出翻译文本。
    """

    return (
        "把下面的文本翻译成"
        f"{target_language}，不要额外解释。\n\n"
        f"{text}"
    )


def clean_translation_output(content: Optional[str]) -> str:
    """
    清洗模型输出为“纯翻译文本”：
    - strip 去首尾空白
    - 若多行，取第一个非空行
    """

    if content is None:
        return ""

    cleaned = str(content).strip()
    if not cleaned:
        return ""

    for line in cleaned.splitlines():
        line = line.strip()
        if line:
            return line
    return ""


def translate_text(
    *,
    text: str,
    target_language: str,
    max_retries: int = 3,
    request_func: Optional[Callable[[str], str]] = None,
    sleep_func: Callable[[float], None] = time.sleep,
) -> str:
    """
    翻译纯文本：只返回翻译结果。

    - request_func: 注入式请求函数（prompt -> 原始 content），用于测试。
    - sleep_func: 注入式 sleep（避免单测慢）。
    """

    text, target_language = validate_inputs(text=text, target_language=target_language)

    if request_func is None:
        api_key = os.getenv("SILICONFLOW_API_KEY", "")
        if not api_key:
            raise ValueError("缺少环境变量 SILICONFLOW_API_KEY")
        translator = SiliconFlowHunyuanMT7BTranslator(api_key=api_key)
        request_func = translator.get_request_func()

    prompt = build_prompt(text=text, target_language=target_language)

    last_error: Optional[Exception] = None
    for attempt in range(max_retries):
        try:
            raw = request_func(prompt)
            cleaned = clean_translation_output(raw)
            if cleaned:
                return cleaned
            last_error = ValueError("空翻译结果")
        except Exception as e:  # noqa: BLE001 - 主链路只需重试与最终错误
            last_error = e

        if attempt < max_retries - 1:
            # 1s -> 2s -> 4s ...
            sleep_seconds = 2 ** attempt
            sleep_func(sleep_seconds)

    raise RuntimeError(f"调用翻译失败：{last_error}")


__all__ = [
    "validate_inputs",
    "build_prompt",
    "clean_translation_output",
    "translate_text",
]

