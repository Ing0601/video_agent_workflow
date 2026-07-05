"""
短剧混剪自动生成处理器
重构自 highlight2.py，采用面向对象设计
"""

import json
import os
import random
from typing import Dict, List, Optional
from src.model.jianying.jianying_converter import convert_json_to_jianying
from src.model.jianying.pyJianYingDraft import time_util
from src.utils.media_utils import time_to_seconds
from src.utils.video_utils import VideoUtils
from src.logger.logging import logger


class ShortDramaProcessor:
    """短剧混剪自动生成处理器"""

    def __init__(self, tolerance: float = 25.0):
        """
        初始化处理器

        参数:
            tolerance: 时长容忍度（秒），默认 25 秒
        """
        self.tolerance = tolerance
        self.base_config = {}
        self.video_data = []
        self.video_durations = {}
        self.video_highlights = {}
        self.video_names = {}
        self.video_paths = {}
    
    def load_data(self, highlight_results: List[Dict]) -> None:
        """
        加载高光片段分析结果
        
        参数:
            highlight_results: 高光片段分析结果列表，每个元素包含：
                - video_name: 视频文件名
                - video_path: 视频完整路径
                - video_duration: 视频时长（秒或字符串）
                - highlights: 高光片段列表
                - success: 是否成功（可选）
                - id: 视频ID（可选）
        """
        self.video_data = highlight_results
        self._parse_video_data()
        logger.info(f"成功加载 {len(self.video_data)} 个视频的高光片段数据")
    
    def _parse_video_data(self) -> None:
        """解析视频数据，提取时长、高光片段等信息"""
        for idx, video in enumerate(self.video_data, start=1):
            # 跳过失败的视频
            if not video.get('success', True):
                continue
                
            video_id = idx
            
            # 处理视频时长（可能是数字或字符串）
            duration = video.get('video_duration', 0)
            if isinstance(duration, str):
                self.video_durations[video_id] = time_to_seconds(duration)
            else:
                self.video_durations[video_id] = float(duration)
            
            self.video_highlights[video_id] = []
            self.video_names[video_id] = video.get('video_name', f"{video_id:03d}.mp4")
            self.video_paths[video_id] = video.get('video_path', 
                                                   video.get('video_name', f"{video_id:03d}.mp4"))
            
            # 解析高光片段
            for highlight in video.get('highlights', []):
                # 处理 start 和 end（可能是字符串或数字）
                start = highlight.get('start', 0)
                end = highlight.get('end', 0)
                
                if isinstance(start, str):
                    start_sec = float(start)
                else:
                    start_sec = float(start)
                    
                if isinstance(end, str):
                    end_sec = float(end)
                else:
                    end_sec = float(end)
                
                self.video_highlights[video_id].append({
                    'start': start_sec,
                    'end': end_sec,
                    'reason': highlight.get('reason', '')
                })
    
    def find_segments(self, goal_time: float) -> List[Dict]:
        """
        找出所有满足目标时长的连续片段组合
        
        算法思路：
        1. 从每个高光片段作为起点
        2. 从起始片段开始，先计算到该集结束的时长
        3. 然后累加完整集的时长，直到接近目标
        4. 结尾必须是某一集的结尾
        5. 允许短于或超过目标时长，在容忍度范围内
        
        参数:
            goal_time: 目标时长（秒）
        
        返回:
            包含所有可行组合的列表
        """
        if not self.video_highlights:
            return []
        
        all_solutions = []
        min_time = goal_time - self.tolerance
        max_time = goal_time + self.tolerance
        
        for start_video_id in sorted(self.video_highlights.keys()):
            for start_highlight in self.video_highlights[start_video_id]:
                start_time = start_highlight['start']
                accumulated_time = self.video_durations[start_video_id] - start_time
                
                # 检查单个视频是否满足条件
                if min_time <= accumulated_time <= max_time:
                    all_solutions.append(self._create_solution(
                        start_video_id, start_time, start_video_id,
                        self.video_durations[start_video_id], goal_time
                    ))
                
                if accumulated_time > max_time:
                    continue
                
                # 累加后续视频
                current_video_id = start_video_id + 1
                max_video_id = max(self.video_highlights.keys())
                
                while current_video_id <= max_video_id and accumulated_time < min_time:
                    accumulated_time += self.video_durations[current_video_id]
                    current_video_id += 1
                
                if accumulated_time < min_time or accumulated_time > max_time:
                    continue
                
                end_video_id = current_video_id - 1
                all_solutions.append(self._create_solution(
                    start_video_id, start_time, end_video_id,
                    self.video_durations[end_video_id], goal_time
                ))
        
        return all_solutions
    
    def _create_solution(self, start_id: int, start_time: float,
                        end_id: int, end_time: float, goal_time: float) -> Dict:
        """创建解决方案字典"""
        actual_duration = self.video_durations[start_id] - start_time
        for vid in range(start_id + 1, end_id + 1):
            actual_duration += self.video_durations[vid]
        
        return {
            'start_id': start_id,
            'start_time': start_time,
            'end_id': end_id,
            'end_time': end_time,
            'actual_duration': actual_duration,
            'goal_time': goal_time,
            'video_durations': self.video_durations,
            'video_names': self.video_names,
            'video_paths': self.video_paths
        }
    
    def generate_plan(self, result: Dict, plan_id: int) -> Dict:
        """
        根据分析结果生成单个 plan 的 JSON 配置
        
        参数:
            result: 单个分析结果，包含 start_id, start_time, end_id, end_time 等
            plan_id: plan 的 ID
        
        返回:
            plan 的 JSON 配置
        """
        start_id = result['start_id']
        start_time = result['start_time']
        end_id = result['end_id']
        video_durations = result['video_durations']
        video_names = result.get('video_names', {})
        video_paths = result.get('video_paths', {})
        video_ratio = self.base_config.get('video_ratio', 1.0)
        global_speed = self.base_config.get('global_speed', 1.0)
        
        # 构建转换器配置
        converter_config = {
            "draft_name": self.base_config.get("draft_name", "draft"),
            "width": self.base_config.get("width", 1920),
            "height": self.base_config.get("height", 1080),
            "fps": self.base_config.get("fps", 30),
            "platform": self.base_config.get("platform", "win"),
            "material_base_path": self.base_config.get("material_base_path", ""),
            "allow_replace": self.base_config.get("allow_replace", True),
        }
        
        # 可选参数
        if "global_texts" in self.base_config:
            converter_config["global_texts"] = self.base_config["global_texts"]
        if "overlay_path" in self.base_config:
            converter_config["overlay_path"] = self.base_config["overlay_path"]
        
        plan_data = {
            "config": converter_config,
            "scenes": []
        }
        
        current_time = 0
        
        # 构建场景
        for video_id in range(start_id, end_id + 1):
            video_name = video_names.get(video_id, f"{video_id:03d}.mp4")
            video_path = video_paths.get(video_id, video_name)
            
            # 计算裁剪信息
            if video_id == start_id and video_id == end_id:
                clip_start = start_time
                clip_end = video_durations[video_id]
            elif video_id == start_id:
                clip_start = start_time
                clip_end = video_durations[video_id]
            elif video_id == end_id:
                clip_start = 0
                clip_end = video_durations[video_id]
            else:
                clip_start = 0
                clip_end = video_durations[video_id]
            
            # 提早0.2秒防止ASR时间偏移
            if clip_start > 0:
                clip_start = max(0, clip_start - 0.2)
            
            duration = clip_end - clip_start
            actual_duration = duration / global_speed
            
            scene = {
                "id": f"scene_{video_id:03d}",
                "video": {
                    "name": video_name,
                    "path": video_path,
                    "start": current_time,
                    "duration": duration,
                    "clip_start": clip_start,
                    "volume": 1.0,
                    "width": self.base_config.get('width', 1920),
                    "height": self.base_config.get('height', 1080),
                    "material_duration": video_durations[video_id],
                    "scale_x": video_ratio,
                    "scale_y": video_ratio,
                    "speed": global_speed
                }
            }
            
            plan_data['scenes'].append(scene)
            current_time += actual_duration
        
        # 添加尾帧动画
        end_frame_duration = self._add_end_frame(plan_data, current_time)
        if end_frame_duration > 0:
            # 将秒转换为微秒，因为转换器内部使用微秒单位
            plan_data['config']['end_frame_duration'] = int(end_frame_duration * time_util.SEC)
        
        return plan_data
    
    def _add_end_frame(self, plan_data: Dict, current_time: float) -> float:
        """
        添加尾帧动画到 plan_data
        
        参数:
            plan_data: plan 数据字典
            current_time: 当前时间位置
        
        返回:
            尾帧时长（秒）
        """
        end_path_config = self.base_config.get('end_path')
        if not end_path_config:
            return 0.0
        
        # 处理列表或字符串配置
        if isinstance(end_path_config, list):
            if not end_path_config:
                return 0.0
            end_path = random.choice(end_path_config)
        else:
            end_path = end_path_config
        
        if not end_path:
            return 0.0
        
        # 选择视频文件
        if os.path.isdir(end_path):
            mp4_files = [f for f in os.listdir(end_path) if f.lower().endswith('.mp4')]
            if not mp4_files:
                return 0.0
            selected_video = os.path.join(end_path, random.choice(mp4_files))
        else:
            selected_video = end_path
        
        # 获取尾帧视频的真实时长
        try:
            end_duration = VideoUtils.get_video_duration_seconds(selected_video)
            logger.debug(f"尾帧视频时长: {end_duration:.2f}秒，路径: {selected_video}")
        except Exception as e:
            logger.warning(f"无法获取尾帧视频时长，使用默认值5秒: {str(e)}")
            end_duration = 5.0
        
        end_video_name = os.path.basename(selected_video)
        
        end_scene = {
            "id": "scene_end",
            "video": {
                "name": end_video_name,
                "path": selected_video,
                "start": current_time,
                "duration": end_duration,
                "clip_start": 0,
                "volume": 1.0,
                "width": self.base_config.get('width', 1920),
                "height": self.base_config.get('height', 1080),
                "material_duration": end_duration,
                "speed": 1.0  # 尾帧保持正常速度
            }
        }
        
        plan_data['scenes'].append(end_scene)
        return end_duration
    
    def convert_to_draft(self, plan_data: Dict, output_folder: str) -> bool:
        """
        将 plan 数据转换为剪映草稿
        
        参数:
            plan_data: plan 数据字典
            output_folder: 输出文件夹路径
        
        返回:
            转换是否成功
        """
        try:
            os.makedirs(output_folder, exist_ok=True)
            config = plan_data.get("config", {})
            draft_name = config.get("draft_name", "draft")
            
            script = convert_json_to_jianying(
                plan_data,
                draft_folder_path=output_folder,
                draft_name=draft_name
            )
            script.save()
            return True
            
        except Exception as e:
            logger.error(f"转换草稿失败: {str(e)}", exc_info=True)
            return False
    
    def process(self, highlight_results: List[Dict], goal_times: List[int],
                output_dir: str = 'output', convert_to_draft: bool = True,
                config: Optional[Dict] = None) -> int:
        """
        完整的短剧处理流程：加载 → 分析 → 生成 → 转换

        参数:
            highlight_results: 高光片段分析结果列表
            goal_times: 目标时长列表（秒）
            output_dir: 输出目录
            convert_to_draft: 是否转换为剪映草稿
            config: 基础配置（包含视频参数、路径等）

        返回:
            生成的 plan 总数
        """
        logger.info("短剧混剪自动生成系统")

        # 设置配置
        if config is not None:
            self.base_config = config

        self.load_data(highlight_results)
        os.makedirs(output_dir, exist_ok=True)
        
        total_plans = 0
        
        for goal_time in goal_times:
            logger.info(f"分析高光片段，目标时长: {goal_time}秒 ({goal_time/60:.2f}分钟)")
            logger.info(f"容忍范围: {goal_time - self.tolerance:.1f}秒 - {goal_time + self.tolerance:.1f}秒")
            
            results = self.find_segments(goal_time)
            
            if not results:
                logger.warning(f"没有找到满足 {goal_time}秒 目标时长的片段组合")
                continue
            
            logger.info(f"找到 {len(results)} 个满足条件的组合:")
            for idx, result in enumerate(results, 1):
                logger.info(f"  方案 {idx}: 第{result['start_id']}集({result['start_time']:.1f}s) → "
                           f"第{result['end_id']}集({result['end_time']:.1f}s) | "
                           f"实际时长: {result['actual_duration']:.1f}秒 ({result['actual_duration']/60:.2f}分钟)")
            
            logger.info("生成配置并转换为剪映草稿")
            drama_name_prefix = self.base_config.get('draft_name', '')
            if drama_name_prefix:
                drama_name_prefix = drama_name_prefix + "_"
            
            for idx, result in enumerate(results, 1):
                # 设置草稿名称
                config = self.base_config.copy()
                draft_name = f"{drama_name_prefix}{idx}_{goal_time}"
                config['draft_name'] = draft_name
                
                # 临时更新配置
                original_config = self.base_config
                self.base_config = config
                
                # 生成 plan
                plan_data = self.generate_plan(result, idx)
                
                # 恢复原配置
                self.base_config = original_config
                
                # 转换或保存
                if convert_to_draft:
                    if self.convert_to_draft(plan_data, output_dir):
                        logger.info(f"  ✓ {draft_name}")
                        total_plans += 1
                    else:
                        logger.error(f"  ✗ {draft_name}")
                else:
                    output_path = os.path.join(output_dir, f'plan_{idx}_{goal_time}.json')
                    with open(output_path, 'w', encoding='utf-8') as f:
                        json.dump(plan_data, f, ensure_ascii=False, indent=4)
                    logger.info(f"  ✓ {draft_name} -> {output_path}")
                    total_plans += 1
        
        if convert_to_draft:
            logger.info(f"所有处理完成! 共生成 {total_plans} 个剪映草稿")
            logger.info(f"草稿保存路径: {output_dir}")
        else:
            logger.info(f"所有处理完成! 共生成 {total_plans} 个配置文件")
            logger.info(f"配置文件保存路径: {output_dir}")
        
        return total_plans