import json
import os
import time
from typing import Any, Dict, List, Optional

import dashscope
from dashscope import Generation
from requests.exceptions import ConnectionError

from src.logger.logging import logger


class QwenLLMClient:
    """Qwen LLM client using the official dashscope SDK.

    A client that provides chat completion functionality using Qwen models
    through the dashscope SDK.

    Attributes:
        api_key: Dashscope API key for authentication.
        model: Default model name for API calls.
        base_http_api_url: API base URL for switching regions.
    """

    def __init__(
        self,
        api_key: Optional[str] = None,
        model: str = "qwen-max-latest",
        base_http_api_url: Optional[str] = None,
    ):
        """Initialize the QwenLLMClient.

        Args:
            api_key: Dashscope API key. If None, reads from DASHSCOPE_API_KEY env var.
            model: Default model name for API calls (default: "qwen-max-latest").
            base_http_api_url: API base URL for switching regions (e.g., Singapore region).

        Raises:
            ValueError: If API key is not provided or found in environment.
        """
        self.api_key = api_key or os.getenv("DASHSCOPE_API_KEY")
        self.model = model

        if not self.api_key:
            raise ValueError(
                "DASHSCOPE_API_KEY is required. Set it via environment variable or pass as argument."
            )

        if base_http_api_url:
            dashscope.base_http_api_url = base_http_api_url

        logger.debug("QwenLLMClient initialized with model: %s", self.model)

    def chat(
        self,
        messages: List[Dict[str, Any]],
        model: Optional[str] = None,
        temperature: float = 0.7,
        response_format: Optional[Dict[str, str]] = None,
        max_tokens: Optional[int] = None,
        max_retries: int = 3,
        **kwargs,
    ) -> Any:
        """Call Qwen LLM for chat completion.

        Sends a chat request to the Qwen API and returns the response.
        Supports various parameters for controlling the generation.

        Args:
            messages: List of conversation messages with role and content.
            model: Model name to use (defaults to instance model).
            temperature: Temperature parameter for generation randomness (default 0.7).
            response_format: Response format specification (e.g., {"type": "json_object"}).
            max_tokens: Maximum number of tokens to generate.
            max_retries: Maximum number of retries on network errors (default 3).
            **kwargs: Additional parameters passed to the API.

        Returns:
            API response object containing the generation result.

        Raises:
            Exception: If API call fails after all retries.
        """
        model = model or self.model

        params = {
            "api_key": self.api_key,
            "model": model,
            "messages": messages,
            "result_format": "message",
            "temperature": temperature,
        }

        if response_format is not None:
            params["response_format"] = response_format

        if max_tokens is not None:
            params["max_tokens"] = max_tokens

        params.update(kwargs)

        logger.debug("Sending request to Qwen API with params: %s", params)
        
        # Retry loop with exponential backoff
        for attempt in range(max_retries):
            try:
                response = Generation.call(**params)
                
                if response.status_code == 200:
                    logger.debug("Response received successfully from Qwen API")
                    return response
                else:
                    error_msg = (
                        f"Model call failed, status code: {response.status_code}, "
                        f"error message: {response.message}"
                    )
                    logger.error(error_msg)
                    raise Exception(error_msg)
            except (ConnectionError, ConnectionResetError) as e:
                if attempt < max_retries - 1:
                    wait_time = 2 ** attempt  # 指数退避: 1s, 2s, 4s
                    logger.warning(
                        "网络连接错误，%d秒后重试 (%d/%d): %s",
                        wait_time, attempt + 1, max_retries, e
                    )
                    time.sleep(wait_time)
                else:
                    logger.error("重试 %d 次后仍失败: %s", max_retries, e)
                    raise
            except Exception as e:
                logger.error("Unexpected error calling Qwen API: %s", e)
                raise

    def completions_with_json(
        self,
        user_content: str,
        system_content: Optional[str] = None,
        model: Optional[str] = None,
        temperature: float = 0.7,
        **kwargs,
    ) -> Optional[Dict[str, Any]]:
        """
        Send a completion request and parse the response as JSON.

        This method wraps a chat-based completion request to the language model
        and attempts to parse its output into a JSON object. It is useful for
        structured generation tasks where the model response is expected to be
        valid JSON.

        Args:
            user_content (str):
                The user message or content prompt sent to the model.
            system_content (Optional[str], optional):
                The system message providing context or role instructions for the model.
                Defaults to None.
            model (Optional[str], optional):
                The model name to use for generation (e.g., "qwen-max-latest").
                Defaults to None.
            temperature (float, optional):
                Sampling temperature for generation randomness.
                Lower values make output more deterministic. Defaults to 0.7.
            **kwargs:
                Additional keyword arguments passed to the underlying `self.chat()` method,
                such as `top_p`, `max_tokens`, etc.

        Returns:
            Optional[Dict[str, Any]]:
                A parsed JSON object if successful, otherwise None if parsing fails.

        Raises:
            Exception: If API call fails.
        """
        messages = []
        if system_content:
            messages.append({"role": "system", "content": system_content})
        messages.append({"role": "user", "content": user_content})

        response = self.chat(
            messages=messages,
            model=model,
            temperature=temperature,
            response_format={"type": "json_object"},
            **kwargs,
        )

        try:
            # Extract response content (dashscope format)
            content = response.output.choices[0].message.content

            # 收集usage信息，但不直接发送，让上层业务处理
            usage = {
                "model": model if model else self.model,
                "input_tokens": response.usage.input_tokens,
                "output_tokens": response.usage.output_tokens,
                "total_tokens": response.usage.total_tokens,
            }

            # Parse JSON
            parsed_json = json.loads(content)
            logger.debug("Successfully parsed JSON response")
            
            # 返回结果时包含usage信息
            return {
                "content": parsed_json,
                "usage": usage
            }
        except (json.JSONDecodeError, KeyError, IndexError, AttributeError) as e:
            logger.warning("Failed to parse response as JSON: %s", e)
            logger.debug("Raw response: %s", response)
            return None

    def completions_with_structured_output(
        self,
        user_content: str,
        response_model: Any,
        system_content: Optional[str] = None,
        model: Optional[str] = None,
        temperature: float = 0.7,
        **kwargs,
    ) -> Optional[Any]:
        """
        Send a completion request with structured output using Pydantic model.

        This method attempts to get structured output by requesting JSON format
        and parsing it into the provided Pydantic model.

        Args:
            user_content (str):
                The user message or content prompt sent to the model.
            response_model (BaseModel):
                Pydantic BaseModel class defining the expected response structure.
            system_content (Optional[str], optional):
                The system message providing context or role instructions for the model.
                Defaults to None.
            model (Optional[str], optional):
                The model name to use. Defaults to None (uses instance model).
            temperature (float, optional):
                Sampling temperature for generation randomness.
                Lower values make output more deterministic. Defaults to 0.7.
            **kwargs:
                Additional keyword arguments passed to the API.

        Returns:
            Optional[BaseModel]:
                A parsed Pydantic model instance if successful, otherwise None.

        Note:
            This uses JSON format response and manual parsing into Pydantic model.
        """
        messages = []
        if system_content:
            messages.append({"role": "system", "content": system_content})
        messages.append({"role": "user", "content": user_content})

        model = model or self.model

        try:
            logger.debug("Sending structured output request with model: %s", response_model)
            response = self.chat(
                messages=messages,
                model=model,
                temperature=temperature,
                response_format={"type": "json_object"},
                **kwargs,
            )
            
            # Extract response content
            content = response.output.choices[0].message.content
            
            # Parse JSON and convert to Pydantic model
            parsed_json = json.loads(content)
            parsed_result = response_model(**parsed_json)
            
            logger.debug("Successfully parsed structured output")
            return parsed_result
        except Exception as e:
            logger.error("Failed to get structured output: %s", e)
            return None