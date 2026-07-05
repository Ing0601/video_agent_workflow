"""剪映转换器 - 主转换逻辑"""

import os
import random
from typing import List, Dict, Any, Optional

from ..pyJianYingDraft import draft_folder as df
from ..pyJianYingDraft import script_file as sf
from ..pyJianYingDraft import video_segment as vs
from ..pyJianYingDraft import audio_segment as aus
from ..pyJianYingDraft import text_segment as ts
from ..pyJianYingDraft import track
from ..pyJianYingDraft import local_materials as lm
from ..pyJianYingDraft import time_util
from ..pyJianYingDraft import metadata

from .config import ConvertConfig
from src.logger.logging import logger


class JianYingConverter:
    """剪映转换器
    
    将场景配置转换为剪映草稿文件
    """
    
    def __init__(self, config: ConvertConfig):
        """初始化转换器
        
        Args:
            config: 转换配置对象
        """
        self.config = config
        self.script: Optional[sf.ScriptFile] = None
        self.draft_folder: Optional[df.DraftFolder] = None
    
    def convert(self, scenes: List[Dict[str, Any]]) -> sf.ScriptFile:
        """执行转换
        
        Args:
            scenes: 场景配置列表
            
        Returns:
            ScriptFile对象
            
        Raises:
            FileNotFoundError: 草稿文件夹路径不存在
            ValueError: 配置参数错误
        """
        # 1. 初始化草稿
        self._init_draft()
        
        # 2. 处理所有场景
        self._process_scenes(scenes)
        
        # 3. 添加全局元素
        self._add_global_elements()
        
        return self.script
    
    def convert_and_save(self, scenes: List[Dict[str, Any]]) -> str:
        """执行转换并保存
        
        Args:
            scenes: 场景配置列表
            
        Returns:
            草稿保存路径
        """
        script = self.convert(scenes)
        script.save()
        return script.save_path
    
    # ===== 初始化 =====
    
    def _init_draft(self):
        """初始化草稿文件"""
        # 验证配置
        if not self.config.draft_folder_path:
            raise ValueError("必须指定 draft_folder_path")
        
        if not os.path.exists(self.config.draft_folder_path):
            raise FileNotFoundError(f"草稿文件夹不存在: {self.config.draft_folder_path}")
        
        # 创建草稿文件夹管理器
        self.draft_folder = df.DraftFolder(self.config.draft_folder_path)
        
        # 创建新草稿
        self.script = self.draft_folder.create_draft(
            self.config.draft_name,
            self.config.width,
            self.config.height,
            self.config.fps,
            allow_replace=self.config.allow_replace,
            platform=self.config.platform
        )
        
        # 创建初始轨道
        self.script.add_track(track.TrackType.video, "main_video")
        self.script.add_track(track.TrackType.audio, "main_audio")
        self.script.add_track(track.TrackType.text, "subtitle")
        
        logger.info(f"初始化草稿: {self.config.draft_name}")
    
    # ===== 场景处理 =====
    
    def _process_scenes(self, scenes: List[Dict]):
        """处理所有场景"""
        logger.info(f"开始处理 {len(scenes)} 个场景...")
        
        for idx, scene in enumerate(scenes, 1):
            scene_id = scene.get("id", f"scene_{idx}")
            logger.debug(f"  [{idx}/{len(scenes)}] 处理场景: {scene_id}")
            
            self._process_scene(scene)
        
        logger.info(f"场景处理完成")
    
    def _process_scene(self, scene: Dict):
        """处理单个场景"""
        # 1. 视频/图片
        if "video" in scene or "image" in scene:
            self._process_video(scene)
        
        # 2. 音频
        if "audio" in scene:
            self._process_audio(scene)
        
        # 3. 字幕
        if "subtitle" in scene:
            self._process_subtitle(scene)
    
    # ===== 视频处理 =====
    
    def _process_video(self, scene: Dict):
        """处理视频/图片"""
        video_config = scene.get("video") or scene.get("image")
        if not video_config:
            return
        
        # 获取文件路径
        media_path = video_config.get("path")
        if not media_path:
            logger.warning("视频/图片配置缺少 'path' 字段")
            return
        
        # 解析时间参数
        start_time = self._parse_time(video_config.get("start", 0))
        duration = self._parse_time(video_config.get("duration", 5))
        clip_start = self._parse_time(video_config.get("clip_start", 0))
        speed = video_config.get("speed", 1.0)
        volume = video_config.get("volume", 1.0)
        
        # 创建素材
        material_duration = video_config.get("material_duration")
        if material_duration:
            material = lm.VideoMaterial(
                media_path,
                duration=self._parse_time(material_duration),
                width=video_config.get("width", self.config.width),
                height=video_config.get("height", self.config.height)
            )
        else:
            material = lm.VideoMaterial(media_path)
        
        # 创建片段
        segment = vs.VideoSegment(
            material,
            time_util.Timerange(start_time, duration),
            source_timerange=time_util.Timerange(clip_start, duration),
            speed=speed,
            volume=volume
        )
        
        # 添加到轨道
        self.script.add_segment(segment, "main_video")
    
    # ===== 音频处理 =====
    
    def _process_audio(self, scene: Dict):
        """处理音频"""
        audio_config = scene.get("audio")
        if not audio_config:
            return
        
        # 获取文件路径
        audio_name = audio_config.get("name")
        if not audio_name:
            return
        
        audio_path = self.config.get_material_path(audio_name)
        
        # 解析参数
        start_time = self._parse_time(audio_config.get("start", 0))
        duration = self._parse_time(audio_config.get("duration", 5))
        volume = audio_config.get("volume", 1.0)
        
        # 创建素材
        material = lm.AudioMaterial(audio_path, duration=duration)
        
        # 创建片段
        segment = aus.AudioSegment(
            material,
            time_util.Timerange(start_time, duration),
            volume=volume
        )
        
        # 查找可用轨道(避免时间冲突)
        track_name = self._find_available_audio_track(start_time, duration)
        self.script.add_segment(segment, track_name)
    
    def _find_available_audio_track(self, start_time: int, duration: int) -> str:
        """查找可用的音频轨道
        
        Args:
            start_time: 开始时间(微秒)
            duration: 持续时间(微秒)
            
        Returns:
            可用的轨道名称
        """
        end_time = start_time + duration
        
        # 遍历现有音频轨道
        for track_obj in self.script.tracks.values():
            if track_obj.track_type != track.TrackType.audio:
                continue
            
            # 检查时间冲突
            has_conflict = False
            for seg in track_obj.segments:
                seg_start = seg.target_timerange.start
                seg_end = seg_start + seg.target_timerange.duration
                
                # 检查是否重叠
                if not (end_time <= seg_start or start_time >= seg_end):
                    has_conflict = True
                    break
            
            if not has_conflict:
                return track_obj.name
        
        # 没有可用轨道，创建新轨道
        new_track_name = self.config.get_unique_track_name("audio")
        self.script.add_track(track.TrackType.audio, new_track_name)
        return new_track_name
    
    # ===== 字幕处理 =====
    
    def _process_subtitle(self, scene: Dict):
        """处理字幕"""
        subtitle_config = scene.get("subtitle")
        if not subtitle_config:
            return
        
        # 获取字幕文本
        text = subtitle_config.get("text")
        if not text:
            return
        
        # 获取时间范围(从video或audio配置中获取)
        time_config = scene.get("video") or scene.get("audio")
        if not time_config:
            return
        
        start_time = self._parse_time(time_config.get("start", 0))
        duration = self._parse_time(time_config.get("duration", 5))
        
        # 解析样式
        style_config = subtitle_config.get("style", {})
        
        # 字体
        font_name = style_config.get("font", "思源中宋")
        try:
            font = metadata.FontType[font_name]
        except KeyError:
            font = metadata.FontType.思源中宋
            logger.warning(f"未找到字体 '{font_name}'，使用默认字体")
        
        # 文本样式
        text_style = ts.TextStyle(
            size=style_config.get("size", 5.0),
            color=tuple(style_config.get("color", [1.0, 1.0, 1.0])),
            align=style_config.get("align", 1),
            bold=style_config.get("bold", False),
            italic=style_config.get("italic", False)
        )
        
        # 位置
        position_y = style_config.get("position_y", -0.8)
        clip_settings = vs.ClipSettings(transform_y=position_y)
        
        # 描边
        border_config = style_config.get("border", {})
        if border_config is None or border_config.get("enabled", True):
            border = ts.TextBorder(
                color=tuple(border_config.get("color", [0.0, 0.0, 0.0])) if border_config else (0.0, 0.0, 0.0),
                width=border_config.get("width", 40.0) if border_config else 40.0,
                alpha=border_config.get("alpha", 1.0) if border_config else 1.0
            )
        else:
            border = None
        
        # 创建片段
        segment = ts.TextSegment(
            text,
            time_util.Timerange(start_time, duration),
            font=font,
            style=text_style,
            clip_settings=clip_settings,
            border=border
        )
        
        # 添加到轨道
        self.script.add_segment(segment, "subtitle")
    
    # ===== 全局元素 =====
    
    def _add_global_elements(self):
        """添加全局元素(文字、角标等)"""
        logger.info("添加全局元素...")
        
        # 全局文字
        if self.config.global_texts:
            self._add_global_texts()
        
        # 角标
        if self.config.overlay_path:
            self._add_overlay()
        
        logger.info("全局元素添加完成")
    
    def _add_global_texts(self):
        """添加全局文字"""
        total_duration = self.script.duration
        if total_duration <= 0:
            logger.warning("视频总时长为0，跳过全局文字")
            return
        
        # 计算全局文字的实际时长（如果配置了尾帧时长，需要排除）
        if self.config.end_frame_duration and self.config.end_frame_duration > 0:
            content_duration = total_duration - self.config.end_frame_duration
            if content_duration <= 0:
                logger.warning("尾帧时长过长，跳过全局文字")
                return
        else:
            content_duration = total_duration
        
        for idx, text_config in enumerate(self.config.global_texts, 1):
            text_content = text_config.get("text")
            if not text_content:
                continue
            
            style_config = text_config.get("style", {})
            
            # 创建轨道
            track_name = f"global_text_{idx}"
            self.script.add_track(track.TrackType.text, track_name)
            
            # 字体
            font_name = style_config.get("font", "台北黑体_Bold")
            try:
                font = metadata.FontType[font_name]
            except KeyError:
                font = metadata.FontType.台北黑体_Bold
            
            # 样式
            text_style = ts.TextStyle(
                size=style_config.get("size", 6.0),
                color=tuple(style_config.get("color", [1.0, 1.0, 1.0])),
                align=style_config.get("align", 1),
                bold=style_config.get("bold", True),
                italic=style_config.get("italic", False),
                vertical=style_config.get("vertical", False)
            )
            
            # 位置
            clip_settings = vs.ClipSettings(
                transform_x=style_config.get("transform_x", 0.0),
                transform_y=style_config.get("transform_y", 0.0)
            )
            
            # 描边
            border_config = style_config.get("border", {})
            if border_config is None or border_config.get("enabled", True):
                border = ts.TextBorder(
                    color=tuple(border_config.get("color", [0.0, 0.0, 0.0])) if border_config else (0.0, 0.0, 0.0),
                    width=border_config.get("width", 40.0) if border_config else 40.0,
                    alpha=border_config.get("alpha", 1.0) if border_config else 1.0
                )
            else:
                border = None
            
            # 创建片段 - 使用计算后的内容时长（排除尾帧）
            segment = ts.TextSegment(
                text_content,
                time_util.Timerange(0, content_duration),
                font=font,
                style=text_style,
                clip_settings=clip_settings,
                border=border
            )
            
            self.script.add_segment(segment, track_name)
            if self.config.end_frame_duration:
                logger.debug(f"添加全局文字: {text_content} (时长: {content_duration/time_util.SEC:.2f}s, 排除尾帧 {self.config.end_frame_duration/time_util.SEC:.2f}s)")
            else:
                logger.debug(f"添加全局文字: {text_content} (时长: {content_duration/time_util.SEC:.2f}s)")
    
    def _add_overlay(self):
        """添加角标图片"""
        # 选择角标路径
        if isinstance(self.config.overlay_path, list):
            if not self.config.overlay_path:
                return
            overlay_path = random.choice(self.config.overlay_path)
        else:
            overlay_path = self.config.overlay_path
        
        total_duration = self.script.duration
        if total_duration <= 0:
            logger.warning("视频总时长为0，跳过角标")
            return
        
        # 计算角标的实际时长（如果配置了尾帧时长，需要排除）
        if self.config.end_frame_duration and self.config.end_frame_duration > 0:
            content_duration = total_duration - self.config.end_frame_duration
            if content_duration <= 0:
                logger.warning("尾帧时长过长，跳过角标")
                return
        else:
            content_duration = total_duration
        
        try:
            full_path = self.config.get_material_path(overlay_path)
            
            # 创建轨道
            track_name = "corner_label"
            self.script.add_track(track.TrackType.video, track_name)
            
            # 创建素材 - 使用计算后的内容时长（排除尾帧）
            material = lm.VideoMaterial(
                full_path,
                duration=content_duration,
                width=self.config.width,
                height=self.config.height
            )
            
            # 创建片段 - 使用计算后的内容时长（排除尾帧）
            segment = vs.VideoSegment(
                material,
                time_util.Timerange(0, content_duration),
                source_timerange=time_util.Timerange(0, content_duration),
                volume=0.0,
                clip_settings=vs.ClipSettings(scale_x=1.0, scale_y=1.0)
            )
            
            self.script.add_segment(segment, track_name)
            if self.config.end_frame_duration:
                logger.info(f"添加角标: {overlay_path} (时长: {content_duration/time_util.SEC:.2f}s, 排除尾帧 {self.config.end_frame_duration/time_util.SEC:.2f}s)")
            else:
                logger.info(f"添加角标: {overlay_path}")
            
        except Exception as e:
            logger.warning(f"添加角标失败: {e}")
    
    # ===== 工具方法 =====
    
    def _parse_time(self, time_value) -> int:
        """解析时间值为微秒
        
        Args:
            time_value: 秒数(int/float)或时间字符串(如"5s")
            
        Returns:
            微秒数
        """
        if isinstance(time_value, str):
            return time_util.tim(time_value)
        else:
            return round(time_value * time_util.SEC)