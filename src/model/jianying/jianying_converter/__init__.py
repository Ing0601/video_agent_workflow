from .converter import JianYingConverter
from .config import ConvertConfig

__version__ = "2.0.0"
__all__ = ["JianYingConverter", "ConvertConfig"]


def convert_json_to_jianying(
    json_data,
    draft_folder_path: str,
    draft_name: str = "draft",
    **kwargs
):
    """便捷函数：从JSON创建剪映草稿
    
    Args:
        json_data: JSON字符串、字典对象或JSON文件路径
        draft_folder_path: 草稿保存路径
        draft_name: 草稿名称
        **kwargs: 其他配置参数(会传递给ConvertConfig)
        
    Returns:
        ScriptFile对象
        
    Example:
        >>> script = convert_json_to_jianying(
        ...     "config.json",
        ...     draft_folder_path="/path/to/drafts",
        ...     draft_name="my_video",
        ...     width=1920,
        ...     height=1080
        ... )
        >>> script.save()
    """
    import json
    import os
    
    # 如果是文件路径，读取文件
    if isinstance(json_data, str) and os.path.exists(json_data):
        with open(json_data, 'r', encoding='utf-8') as f:
            data = json.load(f)
    elif isinstance(json_data, str):
        data = json.loads(json_data)
    else:
        data = json_data
    
    # 从JSON中提取配置，优先使用函数参数
    json_config = data.get("config", {})
    
    # 合并配置(函数参数优先级更高)
    config_dict = {
        "draft_folder_path": draft_folder_path,
        "draft_name": draft_name,
        **json_config,
        **kwargs
    }
    
    config = ConvertConfig(**config_dict)
    
    # 提取场景数据
    scenes = data.get("scenes", [])
    
    # 执行转换
    converter = JianYingConverter(config)
    return converter.convert(scenes)