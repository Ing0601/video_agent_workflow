
def font_resize(basic_config: dict):
    """
    转换 global_texts 中的字号

    当 size <= 1.0 时，size 是比例（rate），需要转换为真实字号:
    - 竖屏（width/height=9/16）: font_size = 217.7495 * rate + 1.5214
    - 横屏（width/height=16/9）:  font_size = 68.9143 * rate + 0.5920

    Args:
        basic_config: 配置字典，包含 global_texts 配置

    Returns:
        dict: 转换后的 basic_config
    """
    # 检测 basic_config 是否有 global_texts
    global_texts = basic_config.get("global_texts")
    if not global_texts:
        return basic_config

    # 获取视频尺寸，判断横屏还是竖屏
    width = basic_config.get("width", 1920)
    height = basic_config.get("height", 1080)

    # 判断横竖屏：检查 width/height 是否接近 9/16
    ratio = width / height if height != 0 else 0
    portrait_ratio = 9 / 16   # 0.5625
    tolerance = 0.1  # 容差范围

    # 判断是否为竖屏（接近 9/16）
    is_portrait = abs(ratio - portrait_ratio) < tolerance

    # 遍历所有文字配置
    for text_item in global_texts:
        style = text_item.get("style", {})
        size = style.get("size")
        # 检查是否存在 size 且小于等于 1.0
        if size is not None and size <= 1.0:
            if is_portrait:
                # 竖屏转换公式
                new_size = int(217.7495 * size + 1.5214)
            else:
                # 横屏转换公式
                new_size = int(68.9143 * size + 0.5920)

            # 更新 size 值
            style["size"] = new_size

    return basic_config
