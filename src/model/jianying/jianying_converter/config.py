"""转换配置类"""

from dataclasses import dataclass, field
from typing import Optional, List, Dict, Any, Union, Literal


@dataclass
class ConvertConfig:
    """剪映转换器配置
    
    基础配置：
        platform: 操作系统平台 (win/mac/linux)
        material_base_path: 素材文件基础路径
        draft_folder_path: 草稿保存路径
        draft_name: 草稿名称
        
    视频参数：
        width: 视频宽度 (默认1920)
        height: 视频高度 (默认1080)
        fps: 帧率 (默认30)
        
    可选功能：
        global_texts: 全局文字配置列表
        overlay_path: 角标图片路径
        allow_replace: 是否允许替换同名草稿
    """
    
    # ===== 基础配置 =====
    platform: Literal["win", "mac", "linux"] = "win"
    """操作系统平台"""
    
    material_base_path: str = ""
    """素材文件的基础路径，用于拼接相对路径"""
    
    draft_folder_path: str = ""
    """剪映草稿文件夹路径"""
    
    draft_name: str = "converted_draft"
    """草稿名称"""
    
    # ===== 视频参数 =====
    width: int = 1920
    """视频宽度"""
    
    height: int = 1080
    """视频高度"""
    
    fps: int = 30
    """帧率"""
    
    # ===== 可选功能 =====
    allow_replace: bool = True
    """是否允许替换同名草稿"""
    
    global_texts: Optional[List[Dict[str, Any]]] = None
    """全局文字配置列表
    
    Example:
        [
            {
                "text": "第1集",
                "style": {
                    "font": "台北黑体_Bold",
                    "size": 6.0,
                    "color": [1.0, 1.0, 1.0],
                    "transform_x": -0.8,
                    "transform_y": 0.8
                }
            }
        ]
    """
    
    overlay_path: Optional[Union[str, List[str]]] = None
    """角标图片路径，可以是单个路径或路径列表(随机选择)"""
    
    end_frame_duration: Optional[float] = None
    """尾帧时长（秒）。如果指定，全局文字将不会覆盖最后这段时长"""
    
    # ===== 内部使用 =====
    _track_counter: Dict[str, int] = field(default_factory=dict, init=False, repr=False)
    """轨道计数器(内部使用，用于生成唯一轨道名)"""
    
    def __post_init__(self):
        """配置验证"""
        if self.width <= 0 or self.height <= 0:
            raise ValueError(f"视频尺寸必须为正数: width={self.width}, height={self.height}")
        
        if self.fps <= 0:
            raise ValueError(f"帧率必须为正数: fps={self.fps}")
        
        if self.platform not in ["win", "mac", "linux"]:
            raise ValueError(f"不支持的平台: {self.platform}")
    
    def get_material_path(self, filename: str) -> str:
        """获取素材完整路径
        
        Args:
            filename: 素材文件名或相对路径
            
        Returns:
            完整的素材路径
        """
        import os
        
        # 检查是否为绝对路径
        # Windows绝对路径：C:/... 或 C:\... 
        is_windows_abs = len(filename) >= 3 and filename[1] == ':' and filename[0].isalpha()
        
        if os.path.isabs(filename) or is_windows_abs:
            return filename
        
        # 相对路径，拼接base_path
        if not self.material_base_path:
            return filename
        
        # 根据平台选择分隔符
        separator = '\\' if self.platform == "win" else '/'
        
        # 处理base_path末尾分隔符
        base = self.material_base_path.rstrip('/\\')
        
        return f"{base}{separator}{filename}"
    
    def get_unique_track_name(self, prefix: str) -> str:
        """获取唯一的轨道名称
        
        Args:
            prefix: 轨道名称前缀 (如 "main_audio", "subtitle")
            
        Returns:
            唯一的轨道名称
        """
        if prefix not in self._track_counter:
            self._track_counter[prefix] = 0
        
        self._track_counter[prefix] += 1
        count = self._track_counter[prefix]
        
        return f"{prefix}_{count}" if count > 1 else prefix


# ===== 预定义配置 =====

def get_vertical_video_config(**kwargs) -> ConvertConfig:
    """获取竖屏视频配置 (9:16)
    
    Returns:
        ConvertConfig对象
    """
    return ConvertConfig(
        width=1080,
        height=1920,
        **kwargs
    )


def get_horizontal_video_config(**kwargs) -> ConvertConfig:
    """获取横屏视频配置 (16:9)
    
    Returns:
        ConvertConfig对象
    """
    return ConvertConfig(
        width=1920,
        height=1080,
        **kwargs
    )


def get_square_video_config(**kwargs) -> ConvertConfig:
    """获取方形视频配置 (1:1)
    
    Returns:
        ConvertConfig对象
    """
    return ConvertConfig(
        width=1080,
        height=1080,
        **kwargs
    )