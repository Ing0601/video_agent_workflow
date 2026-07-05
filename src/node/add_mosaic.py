from typing import Union, List, Dict, Optional
from pathlib import Path
from ..logger import logger
from ..utils.ffmpeg_utils import get_ffmpeg_path, run_ffmpeg_command

class AddMosaic():
    """ 
    对字幕进行马赛克处理;
    字幕遮盖器;
    """

    def __init__(self, blur_strength: int = 10, expand_ratio: float = 1.1):
        """
        初始化

        Args: 
            blur_strength: 模糊强度, 越大越模糊, 取值范围[0, 100];
            expand_ratio: 扩展比例, 越大越扩展;
        """
        self.blur_strength = max(blur_strength, 1)
        self.expand_ratio = expand_ratio

    def remove_subtitle(
        self,
        video_path: str,
        regions: Union[Dict, List[Dict]],
        output_path: Optional[str] = None,
    ) -> Optional[str]:
        """
        遮盖固定区域的字幕
        
        Args:
            video_path: 视频路径
            regions: 要遮盖的区域
            output_path: 输出路径
            
        Returns:
            输出视频路径
        """
        if output_path is None:
            video_file = Path(video_path)
            output_path = str(video_file.parent / f"{video_file.stem}_no_subtitle{video_file.suffix}")
        
        # 标准化区域格式
        region_list = self._normalize_regions(regions)
        if not region_list:
            logger.warning("没有有效的遮盖区域")
            return None
        
        # 生成FFmpeg滤镜
        filter_complex = self._build_filter_complex(region_list)
        
        # 构建FFmpeg命令
        ffmpeg_path = get_ffmpeg_path()
        command = [
            ffmpeg_path,
            '-y',  # 覆盖输出文件
            '-i', video_path,
            '-filter_complex', filter_complex,
            '-map', '[out]',  # 使用滤镜输出（视频）
            '-map', '0:a?',   # 映射音频流（如果存在）
            '-c:a', 'copy',   # 音频直接复制
            output_path
        ]
        
        logger.info(f"开始遮盖字幕: {video_path} -> {output_path}")
        
        if run_ffmpeg_command(command):
            logger.info("字幕遮盖完成")
            return output_path
        else:
            logger.error("字幕遮盖失败")
            return None

    def _normalize_regions(self, regions: Union[Dict, List[Dict]]) -> List[Dict]:
        """标准化区域格式"""
        if isinstance(regions, dict):
            # 如果是检测结果字典
            if 'subtitle_regions' in regions:
                return regions['subtitle_regions']
            elif all(key in regions for key in ['x_min', 'y_min', 'x_max', 'y_max']):
                return [regions]
            else:
                return []
        elif isinstance(regions, list):
            return [r for r in regions if self._is_valid_region(r)]
        else:
            return []

    def _is_valid_region(self, region: Dict) -> bool:
        """检查区域是否有效"""
        required_keys = ['x_min', 'y_min', 'x_max', 'y_max']
        return all(key in region for key in required_keys)

    def _build_filter_complex(self, regions: List[Dict]) -> str:
        """
        构建固定区域的FFmpeg滤镜
        采用两阶段策略（与动态模式逻辑一致）：
        1. 第一阶段：从原始视频裁剪所有区域并创建模糊滤镜
        2. 第二阶段：依次叠加所有模糊区域到视频上
        """
        if not regions:
            return "[0:v]copy[out]"
        
        filters = []
        
        # 第一阶段：为所有区域创建模糊滤镜（都从原始视频 [0:v] 裁剪）
        for i, region in enumerate(regions):
            expanded = self._expand_region(region)
            
            width = expanded['x_max'] - expanded['x_min']
            height = expanded['y_max'] - expanded['y_min']
            
            # 从原始视频裁剪区域并模糊
            crop_blur_filter = f"[0:v]crop={width}:{height}:{expanded['x_min']}:{expanded['y_min']},boxblur={self.blur_strength}:{self.blur_strength}[blur{i}]"
            filters.append(crop_blur_filter)
        
        # 第二阶段：依次叠加所有模糊区域
        current_input = "[0:v]"
        for i, region in enumerate(regions):
            expanded = self._expand_region(region)
            
            if i == len(regions) - 1:
                # 最后一个区域，直接输出到 [out]
                overlay_filter = f"{current_input}[blur{i}]overlay={expanded['x_min']}:{expanded['y_min']}[out]"
            else:
                # 中间区域，输出到临时标签
                overlay_filter = f"{current_input}[blur{i}]overlay={expanded['x_min']}:{expanded['y_min']}[v{i}]"
                current_input = f"[v{i}]"
            
            filters.append(overlay_filter)
        
        return ";".join(filters)

    def _expand_region(self, region: Dict, video_width: int = 1920, video_height: int = 1080) -> Dict:
        """
        扩展区域范围，确保不超出视频边界
        
        对于字幕（subtitles），横向扩展到全屏宽度
        对于其他类型，按比例扩展
        """
        width = region['x_max'] - region['x_min']
        height = region['y_max'] - region['y_min']
        
        # 获取区域类别
        category = region.get('category', '')
        
        # 高度方向的扩展
        expand_h = int(height * (self.expand_ratio - 1) / 2)
        y_min = max(0, region['y_min'] - expand_h)
        y_max = min(video_height, region['y_max'] + expand_h)
        
        # 宽度方向的处理
        if category == 'subtitles':
            # 字幕：扩展到全屏宽度
            x_min = 0
            x_max = video_width
            logger.debug(f"字幕区域扩展到全屏宽度: 0-{video_width}")
        else:
            # 其他类型：按比例扩展
            expand_w = int(width * (self.expand_ratio - 1) / 2)
            x_min = max(0, region['x_min'] - expand_w)
            x_max = min(video_width, region['x_max'] + expand_w)
            logger.debug(f"区域({category})按比例扩展: {x_min}-{x_max}")
        
        return {
            'x_min': x_min,
            'y_min': y_min,
            'x_max': x_max,
            'y_max': y_max
        }

        