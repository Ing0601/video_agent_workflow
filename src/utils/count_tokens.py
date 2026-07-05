from typing import List, Dict, Any


def count_tokens(text: str) -> int:
    ascii_chars = sum(1 for c in text if ord(c) < 128)
    non_ascii = len(text) - ascii_chars
    # 英文/ASCII：4字符≈1 token；非ASCII（中文等）：1字≈1 token
    return (ascii_chars + 3) // 4 + non_ascii


def aggregate_usage(usage_list: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """
    聚合统计 API 调用的 usage 信息，按 model + provider 组合进行聚合
    
    Args:
        usage_list: API 调用的 usage 信息列表，每个元素包含 model、provider（可选）和使用量信息
    
    Returns:
        聚合后的usage列表:
        [
            {
                "model": str,
                "provider": str,  # 可选
                "calls": int,
                "input_tokens": int,  # 可选
                "output_tokens": int,  # 可选
                "total_tokens": int,  # 可选
                "total_duration_ms": int  # 可选，ASR专用
            },
            ...
        ]
    
    Example:
        >>> usage_list = [
        ...     {"model": "qwen3-max", "provider": "dashscope", "input_tokens": 100, "output_tokens": 50, "total_tokens": 150},
        ...     {"model": "qwen3-max", "provider": "dashscope", "input_tokens": 200, "output_tokens": 100, "total_tokens": 300},
        ...     {"model": "qwen3-max", "provider": "openai", "input_tokens": 500, "output_tokens": 250, "total_tokens": 750},
        ... ]
        >>> result = aggregate_usage(usage_list)
        >>> len(result)
        2
        >>> # dashscope 的 qwen3-max 和 openai 的 qwen3-max 分开聚合
    """
    aggregated = {}
    
    for usage in usage_list:
        model = usage.get("model", "unknown")
        provider = usage.get("provider", "")
        
        # 使用 (model, provider) 作为聚合的 key
        key = (model, provider)
        
        if key not in aggregated:
            aggregated[key] = {
                "model": model,
                "calls": 0,
                "input_tokens": 0,
                "output_tokens": 0,
                "total_tokens": 0,
                "total_duration_ms": 0
            }
            # 如果有 provider，添加到结果中
            if provider:
                aggregated[key]["provider"] = provider
        
        aggregated[key]["calls"] += 1
        
        # 累加token（LLM/VLM）
        if "input_tokens" in usage:
            aggregated[key]["input_tokens"] += usage.get("input_tokens", 0)
        if "output_tokens" in usage:
            aggregated[key]["output_tokens"] += usage.get("output_tokens", 0)
        if "total_tokens" in usage:
            aggregated[key]["total_tokens"] += usage.get("total_tokens", 0)
        
        # 累加时长（ASR）
        if "total_duration_ms" in usage:
            aggregated[key]["total_duration_ms"] += usage.get("total_duration_ms", 0)
    
    # 清理值为0的字段（除了 model, provider, calls）
    for stats in aggregated.values():
        stats_copy = stats.copy()
        for key, value in stats_copy.items():
            if key not in ("model", "provider", "calls") and value == 0:
                del stats[key]
    
    # 直接返回聚合后的列表
    return list(aggregated.values())