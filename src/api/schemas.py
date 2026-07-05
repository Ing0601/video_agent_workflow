from pydantic import BaseModel, Field
from typing import Optional, Any, List, Dict


class UserRequest(BaseModel):
    """用户请求模型"""
    user_id: str = Field(..., description="用户ID")
    session_id: str = Field(..., description="会话ID")
    user_message: str = Field(..., description="用户消息")

class HighlightWorkflowRequest(BaseModel):
    """高光片段提取工作流请求模型"""
    input_videos: Any = Field(..., description="输入视频路径列表")
    output_base_dir: Optional[str] = Field(None, description="输出基础目录")
    fps: Optional[float] = Field(None, description="视频分析的帧率")
    max_workers: Optional[int] = Field(None, description="并发处理的最大线程数")
    save_intermediate: Optional[bool] = Field(None, description="是否保存中间结果到每个视频的output_dir/result目录")
    generate_draft: Optional[bool] = Field(False, description="是否在高光分析后生成剪映草稿")
    draft_output_dir: Optional[str] = Field(None, description="剪映草稿输出目录")
    goal_times: Optional[List[int]] = Field(None, description="目标时长列表")
    base_config: Optional[Dict[str, Any]] = Field(default_factory=dict, description="剪映草稿基础配置")
    config: Optional[Dict[str, Any]] = Field(default_factory=dict, description="额外 workflow 配置")

class HighlightDraftRequest(BaseModel):
    """高光片段提取工作流请求模型"""
    highlight_json_path: str = Field(..., description="高光片段提取工作流结果路径")
    base_config: Any = Field(..., description="基础配置")
    draft_output_dir: str = Field(..., description="剪映草稿输出目录")
    goal_times: List[int] = Field(..., description="目标时长列表")


class CommentaryWorkflowRequest(BaseModel):
    """解说词/信息流广告生成请求。第一版支持 demo_info/template 模式。"""

    demo_info: Optional[List[Dict[str, Any]]] = Field(None, description="模板结构")
    demo_info_path: Optional[str] = Field(None, description="模板结构 JSON 路径")
    input_videos: Optional[Any] = Field(None, description="输入视频路径，预留给直接视频理解模式")
    text_template: Optional[Any] = Field(None, description="文字模板配置")
    material_path: Optional[Dict[str, str]] = Field(None, description="素材文件夹映射")
    corner_badge_files: Optional[List[str]] = Field(None, description="角标文件")
    tail_frame_files: Optional[List[str]] = Field(None, description="尾帧文件")
    user_demand: str = Field("请用第三人称解说", description="用户需求")
    work_dir: Optional[str] = Field(None, description="工作目录")
    output_dir: Optional[str] = Field(None, description="输出目录")
    draft_name: Optional[str] = Field("解说前贴", description="草稿名称")
    voice_type: Optional[str] = Field("BV411_streaming", description="TTS 音色")
    speed_ratio: Optional[float] = Field(1.2, description="语速")
    target_duration: Optional[float] = Field(None, description="目标时长")
    alignment_strategy: Optional[str] = Field("video_fit_audio", description="video_fit_audio 或 audio_fit_video")
    config: Optional[Dict[str, Any]] = Field(default_factory=dict, description="额外配置")
