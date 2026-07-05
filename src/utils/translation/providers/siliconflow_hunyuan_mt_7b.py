from __future__ import annotations

import os
from typing import Callable, Optional

from ..base_translator import BaseTranslator

BASE_URL = "https://api.siliconflow.cn/v1"
MODEL = "tencent/Hunyuan-MT-7B"


def _default_request_func_factory(*, api_key: str) -> Callable[[str], str]:
    """
    生成默认请求函数：prompt -> 模型返回原始 content。
    这里保持为闭包，便于 translate_text 做重试控制。
    """

    # 延迟导入：避免单测不装 openai 时导入失败
    from openai import OpenAI  # type: ignore

    client = OpenAI(
        api_key=api_key,
        base_url=BASE_URL,
    )

    def request(prompt: str) -> str:
        resp = client.chat.completions.create(
            model=MODEL,
            messages=[{"role": "user", "content": prompt}],
            temperature=0.2,
        )
        # 按文档约定：从 response.choices[0].message.content 取内容
        content: Optional[str] = (
            resp.choices[0].message.content if resp.choices and resp.choices[0].message else None
        )
        return content or ""

    return request


class SiliconFlowHunyuanMT7BTranslator(BaseTranslator):
    """SiliconFlow 上的 tencent/Hunyuan-MT-7B 文本翻译器。"""

    def __init__(self, *, api_key: Optional[str] = None):
        self.api_key = api_key or os.getenv("SILICONFLOW_API_KEY", "")
        if not self.api_key:
            raise ValueError("缺少环境变量 SILICONFLOW_API_KEY")

    def translate_text(
        self,
        text: str,
        target_language: str,
        *,
        max_retries: int = 3,
    ) -> str:
        # 具体重试/清洗逻辑由外层的 translate_text() 统一控制
        raise NotImplementedError(
            "本实现仅提供默认请求函数；请直接使用 translation.translate_text()。"
        )

    def get_request_func(self) -> Callable[[str], str]:
        return _default_request_func_factory(api_key=self.api_key)

