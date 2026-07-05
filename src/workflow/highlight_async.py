import asyncio
import json
import os
from pathlib import Path
from typing import Any, AsyncGenerator, Callable, Dict, List, Optional
from concurrent.futures import ThreadPoolExecutor

from ..model.llm.qwen_chat import QwenLLMClient
from ..utils.video_utils import VideoUtils
from ..utils.count_tokens import aggregate_usage
from ..logger.logging import logger
from ..node.group_segments import SubtitleGrouper
from ..node.collect_videos import VideoCollector
from ..node.asr_transcribe import ASRTranscriber
from ..node.video_splitter import VideoSplitter
from ..node.content_clipper import ContentClipper
from ..node.segment_analyzer import SegmentAnalyzer


class HighlightWorkflowAsync:
    """
    高光片段提取工作流（异步版本）

    完整处理流程：
    1. ASR识别获取字幕
    2. LLM分析字幕生成切片方案
    3. 根据切片时间戳分割视频
    4. 对每个片段进行视觉理解
    5. 合并分析结果
    """

    def __init__(self):
        """初始化工作流"""
        self.logger = logger
        self._usage_list: List[Dict[str, Any]] = []  # 收集所有usage信息
        self._result_dir: Optional[Path] = None  # 中间结果保存目录
        self._subtitle_grouper = SubtitleGrouper()  # 字幕分组器
        self._video_collector = VideoCollector()    # 视频路径收集器
        self._asr_transcriber = ASRTranscriber()    # ASR转录节点
        self._video_splitter = VideoSplitter()      # 视频切分节点
        self._content_clipper = ContentClipper()    # 内容切片节点
        self._segment_analyzer = SegmentAnalyzer()  # 分段分析节点

    async def run(
        self,
        input_videos: Any,  # 支持单个视频路径(str)或多个视频路径(list)
        output_base_dir: str = None,
        qwen_api_key: str = None,
        qwen_model: str = "qwen3-max",
        temperature: float = 0.7,
        fps: float = 2.0,
        max_workers: int = 3,
        save_intermediate: bool = False,
        **kwargs
    ) -> AsyncGenerator[Dict[str, Any], None]:
        """
        执行高光片段提取工作流（支持单视频或批量处理）

        这是一个异步生成器，会在处理过程中持续 yield 进度事件，最后 yield 最终结果。

        进度事件格式：
            # 工作流启动
            {"type": "start", "total_videos": int, "message": str}

            # 单个视频的步骤进度
            {
                "type": "video_progress",
                "video_name": str,
                "step": int,        # 1-5
                "step_name": str,   # 步骤名称
                "status": "started" | "completed" | "failed",
                "message": str
            }

            # 单个视频处理完毕
            {
                "type": "video_done",
                "video_name": str,
                "success": bool,
                "completed": int,   # 已完成视频数
                "total": int        # 总视频数
            }

            # 最终结果（最后一条事件）
            {
                "type": "result",
                "success": bool,
                "message": str,
                "context_updates": {
                    "highlight_results": [
                        {
                            "id": int,
                            "success": True,
                            "video_name": str,
                            "video_path": str,
                            "video_duration": float,
                            "highlights": [
                                {"start": str, "end": str, "reason": str},
                                ...
                            ]
                        },
                        ...
                    ]
                },
                "usage": [...]
            }

        Args:
            input_videos: 输入视频路径（str）或视频路径列表（list）或目录路径
            output_base_dir: 输出基础目录（如果为None，默认为第一个视频所在目录/highlight_results）
            qwen_api_key: Qwen API密钥（如果为None，从环境变量获取）
            qwen_model: Qwen模型名称
            temperature: LLM温度参数
            fps: 视频分析的帧率
            max_workers: 并发处理的最大线程数
            save_intermediate: 是否保存中间结果到每个视频的output_dir/result目录，默认为False
            **kwargs: 其他参数
        """
        # 1. 收集视频文件列表
        video_paths = self._video_collector.collect(input_videos)

        if not video_paths:
            received_paths = input_videos if isinstance(input_videos, (list, tuple, str)) else str(input_videos)
            yield {
                "type": "result",
                "success": False,
                "message": "No video files found",
                "error": f"No valid video files to process, received: {received_paths}",
            }
            return

        # 2. 设置输出基础目录
        if output_base_dir is None:
            output_base_dir = Path(video_paths[0]).parent / "highlight_results"
        else:
            output_base_dir = Path(output_base_dir)
        output_base_dir.mkdir(parents=True, exist_ok=True)

        self.logger.info("=" * 80)
        self.logger.info("开始批量高光片段提取工作流")
        self.logger.info(f"待处理视频数量: {len(video_paths)}")
        self.logger.info(f"输出基础目录: {output_base_dir}")
        self.logger.info(f"并发数: {max_workers}")
        self.logger.info("=" * 80)

        yield {
            "type": "start",
            "total_videos": len(video_paths),
            "message": f"开始处理 {len(video_paths)} 个视频，并发数: {max_workers}",
        }

        # 3. 使用 asyncio.Queue 在线程与异步生成器之间传递进度事件
        loop = asyncio.get_running_loop()
        progress_queue: asyncio.Queue = asyncio.Queue()

        _SENTINEL = object()  # 用来标记所有任务已完成

        def make_progress_callback(video_name: str) -> Callable[[Dict[str, Any]], None]:
            """为每个视频创建线程安全的进度回调"""
            def callback(event: Dict[str, Any]) -> None:
                event.setdefault("video_name", video_name)
                loop.call_soon_threadsafe(progress_queue.put_nowait, event)
            return callback

        # 4. 在线程池中并发处理所有视频，完成后投入哨兵
        highlight_results: List[Dict[str, Any]] = []
        completed_count = 0
        executor = ThreadPoolExecutor(max_workers=max_workers)

        async def run_one_video(video_path: str) -> None:
            """在 executor 中运行单个视频，完成后发送 video_done 事件"""
            nonlocal completed_count
            video_name = Path(video_path).name
            video_output_dir = output_base_dir / Path(video_path).stem
            progress_callback = make_progress_callback(video_name)
            try:
                result = await loop.run_in_executor(
                    executor,
                    lambda: self._process_single_video(
                        video_path=video_path,
                        output_dir=video_output_dir,
                        qwen_api_key=qwen_api_key,
                        qwen_model=qwen_model,
                        temperature=temperature,
                        fps=fps,
                        save_intermediate=save_intermediate,
                        progress_callback=progress_callback,
                        **kwargs,
                    ),
                )
                if result.get("success"):
                    highlight_results.append(result)
                else:
                    self.logger.warning(
                        f"视频处理失败: {video_path}, 错误: {result.get('error')}"
                    )
                success = result.get("success", False)
            except Exception as exc:
                self.logger.error(f"视频处理异常: {video_path}, {exc}")
                success = False
            finally:
                completed_count += 1
                progress_queue.put_nowait({
                    "type": "video_done",
                    "video_name": video_name,
                    "success": success,
                    "completed": completed_count,
                    "total": len(video_paths),
                })

        async def run_all_videos() -> None:
            try:
                await asyncio.gather(
                    *(run_one_video(vp) for vp in video_paths),
                    return_exceptions=True,
                )
            finally:
                executor.shutdown(wait=False)
                progress_queue.put_nowait(_SENTINEL)

        # 启动后台任务
        bg_task = asyncio.create_task(run_all_videos())

        # 5. 持续从队列读取事件并 yield，直到哨兵出现
        while True:
            event = await progress_queue.get()
            if event is _SENTINEL:
                break
            yield event

        # 确保后台任务已完成（正常情况下此时已结束）
        await bg_task

        # 6. 排序并分配 id
        if highlight_results:
            highlight_results.sort(key=lambda x: os.path.basename(x.get("video_path", "")))
            for idx, res in enumerate(highlight_results, 1):
                res["id"] = idx

        self.logger.info(f"\n{'=' * 80}")
        self.logger.info("✓ 批量工作流完成！")
        self.logger.info(f"✓ 成功处理 {len(highlight_results)}/{len(video_paths)} 个视频")
        self.logger.info(f"{'=' * 80}\n")

        # 7. yield 最终结果
        aggregated_usage = aggregate_usage(self._usage_list)
        
        if highlight_results:
            yield {
                "type": "result",
                "success": True,
                "message": f"Successfully generated highlight results for {len(highlight_results)} video(s)",
                "context_updates": {"highlight_results": highlight_results},
                "usage": aggregated_usage,
                "raw_usage": self._usage_list,
            }
        else:
            yield {
                "type": "result",
                "success": False,
                "message": "No videos processed successfully",
                "error": "All videos failed processing",
                "usage": aggregated_usage,
                "raw_usage": self._usage_list,
            }

    def _process_single_video(
        self,
        video_path: str,
        output_dir: Path,
        qwen_api_key: str = None,
        qwen_model: str = "qwen3-max",
        temperature: float = 0.7,
        fps: float = 2.0,
        save_intermediate: bool = False,
        progress_callback: Optional[Callable[[Dict[str, Any]], None]] = None,
        **kwargs
    ) -> Dict[str, Any]:
        """
        处理单个视频的完整流程

        Args:
            progress_callback: 可选的进度回调函数，每个步骤开始/完成时调用。
                接收一个 dict，格式为：
                {
                    "type": "video_progress",
                    "video_name": str,
                    "step": int,
                    "step_name": str,
                    "status": "started" | "completed" | "failed",
                    "message": str
                }

        Returns:
            Agent格式的结果
        """
        import shutil

        video_name = Path(video_path).name
        self.logger.info(f"\n{'='*60}")
        self.logger.info(f"开始处理视频: {video_name}")
        self.logger.info(f"{'='*60}")

        def _report(step: int, step_name: str, status: str, message: str) -> None:
            """向进度队列发送一条进度事件（线程安全由调用方的 loop.call_soon_threadsafe 保证）"""
            if progress_callback is not None:
                progress_callback({
                    "type": "video_progress",
                    "video_name": video_name,
                    "step": step,
                    "step_name": step_name,
                    "status": status,
                    "message": message,
                })

        try:
            output_dir.mkdir(parents=True, exist_ok=True)

            # 设置中间结果保存目录
            result_dir = None
            if save_intermediate:
                result_dir = output_dir / "result"
                result_dir.mkdir(parents=True, exist_ok=True)
                self._result_dir = result_dir

            # 获取视频时长
            video_duration = VideoUtils.get_video_duration_seconds(video_path)
            self.logger.info(f"视频时长: {video_duration:.2f}秒")

            # 步骤1: ASR识别
            _report(1, "ASR识别", "started", "开始语音识别...")
            self.logger.info(f"\n[步骤 1/5] 开始ASR识别...")
            asr_result = self._asr_transcriber.transcribe_video(video_path)
            if asr_result.get("usage"):
                self._usage_list.append(asr_result["usage"])
            if not asr_result["success"]:
                _report(1, "ASR识别", "failed", f"ASR识别失败: {asr_result.get('error')}")
                raise Exception(f"ASR识别失败: {asr_result.get('error')}")
            _report(1, "ASR识别", "completed",
                    f"识别完成，共 {len(asr_result.get('utterances', []))} 个句子")

            if save_intermediate:
                self._save_step_result("step1_asr_result.json", asr_result)

            # 步骤2: LLM分析字幕生成切片方案
            _report(2, "LLM切片", "started", "开始分析字幕并生成切片方案...")
            self.logger.info(f"\n[步骤 2/5] 开始分析字幕并生成切片方案...")
            slicing_result = self._content_clipper.generate_slices(
                utterances=asr_result["utterances"],
                system_prompt=self._build_slicing_system_prompt(),
                api_key=qwen_api_key,
                model=qwen_model,
                temperature=temperature
            )

            # 收集 usage
            if slicing_result.get("usage"):
                self._usage_list.append(slicing_result["usage"])

            if not slicing_result["success"]:
                _report(2, "LLM切片", "failed", f"切片方案生成失败: {slicing_result.get('error')}")
                raise Exception(f"切片方案生成失败: {slicing_result.get('error')}")

            slices = slicing_result["slices"]
            self.logger.info(f"✓ 生成了 {len(slices)} 个切片方案")
            _report(2, "LLM切片", "completed", f"生成了 {len(slices)} 个切片方案")

            if save_intermediate:
                self._save_step_result("step2_slicing_result.json", slicing_result)

            # 步骤3: 根据切片方案分割视频
            _report(3, "视频分割", "started", f"开始分割视频，共 {len(slices)} 个切片...")
            self.logger.info(f"\n[步骤 3/5] 开始分割视频...")
            video_segments = self._video_splitter.split_video(video_path, slices, output_dir)
            if not video_segments:
                _report(3, "视频分割", "failed", "视频分割失败")
                raise Exception("视频分割失败")

            # 步骤3.5: 将ASR字幕插入到对应的片段中
            self.logger.info(f"\n[步骤 3.5/5] 将ASR字幕插入到片段中...")
            video_segments = self._subtitle_grouper.insert_asr_to_segments(
                video_segments,
                asr_result.get("utterances", [])
            )
            _report(3, "视频分割", "completed",
                    f"成功分割 {len(video_segments)}/{len(slices)} 个片段并插入字幕")

            if save_intermediate:
                self._save_step_result("step3_video_segments.json", {
                    "success": True,
                    "segments": video_segments
                })

            # 步骤4: 对每个片段进行视觉理解分析（并发处理）
            _report(4, "视觉分析", "started",
                    f"开始对 {len(video_segments)} 个片段进行视觉理解分析...")
            self.logger.info(
                f"\n[步骤 4/5] 开始对 {len(video_segments)} 个片段进行视觉分析（并发数: 3）..."
            )
            analyzed_segments = self._segment_analyzer.analyze_segments(
                segments=video_segments,
                prompt=self._build_segment_analysis_prompt(),
                fps=fps,
                max_workers=3  # 单视频内部的并发数固定为3
            )

            # 收集 usage 信息
            for seg in analyzed_segments:
                if seg.get("vlm_usage"):
                    self._usage_list.append(seg["vlm_usage"])

            if not analyzed_segments:
                _report(4, "视觉分析", "failed", "片段视觉分析失败")
                raise Exception("片段分析失败")
            _report(4, "视觉分析", "completed",
                    f"成功分析 {len(analyzed_segments)}/{len(video_segments)} 个片段")

            if save_intermediate:
                self._save_step_result("step4_analyzed_segments.json", {
                    "success": True,
                    "segments": analyzed_segments
                })

            # 步骤5: 使用LLM筛选符合短视频传播逻辑的片段
            _report(5, "高光筛选", "started",
                    f"开始筛选高光片段（共 {len(analyzed_segments)} 个候选）...")
            self.logger.info(f"\n[步骤 5/5] 开始筛选符合短视频传播逻辑的片段...")
            selected_indices = self._step5_select_viral_segments(
                analyzed_segments,
                qwen_api_key=qwen_api_key,
                qwen_model=qwen_model,
                temperature=temperature,
                batch_size=kwargs.get("selection_batch_size", 5)
            )
            _report(5, "高光筛选", "completed",
                    f"筛选完成，选出 {len(selected_indices)} 个高光片段")

            if save_intermediate:
                self._save_step_result("step5_selected_indices.json", {
                    "success": True,
                    "selected_indices": selected_indices,
                    "total_segments": len(analyzed_segments)
                })

            # 6. 转换为 Agent 格式
            self.logger.info(f"\n[步骤 6/6] 转换结果为Agent格式...")
            # 构建 segment_index -> segment 的映射，避免直接用索引值当列表下标
            segment_map = {seg["segment_index"]: seg for seg in analyzed_segments}
            highlights = []
            for seg_idx in selected_indices:
                segment = segment_map.get(seg_idx)
                if segment is None:
                    self.logger.warning(
                        f"selected_indices 中的 segment_index={seg_idx} 在 analyzed_segments 中不存在，跳过"
                    )
                    continue

                # 构建reason: content_summary + " + " + scene_description
                content_summary = segment.get("content_summary", "").strip()
                scene_description = segment.get("visual_analysis", {}).get("scene_description", "").strip()

                if content_summary and scene_description:
                    reason = f"{content_summary} + {scene_description}"
                elif content_summary:
                    reason = content_summary
                elif scene_description:
                    reason = scene_description
                else:
                    reason = "高光片段"

                highlights.append({
                    "start": f"{segment['start_time']:.1f}",
                    "end": f"{segment['end_time']:.1f}",
                    "reason": reason
                })

            self.logger.info(f"✓ 视频 {video_name} 处理完成！筛选出 {len(highlights)} 个高光片段")

            # 7. 清理输出目录（删除切分的视频文件，保留result目录）
            try:
                for item in output_dir.iterdir():
                    if item.is_file():
                        item.unlink()
                    elif item.is_dir() and item.name != "result":
                        shutil.rmtree(item)
                self.logger.info(f"✓ 已清理临时文件")
            except Exception as e:
                self.logger.warning(f"清理临时文件失败: {e}")

            return {
                "success": True,
                "video_name": video_name,
                "video_path": video_path,
                "video_duration": video_duration,
                "highlights": highlights
            }

        except Exception as e:
            import traceback
            self.logger.error(f"视频 {video_name} 处理失败: {e}")
            self.logger.error(f"堆栈:\n{traceback.format_exc()}")

            # 失败时也清理输出目录
            try:
                if output_dir.exists():
                    shutil.rmtree(output_dir)
            except:
                pass

            return {
                "success": False,
                "video_name": video_name,
                "video_path": video_path,
                "error": str(e)
            }

    def _save_step_result(self, filename: str, data: Dict[str, Any]) -> None:
        """
        保存步骤中间结果到JSON文件

        Args:
            filename: 文件名
            data: 要保存的数据
        """
        if self._result_dir is None:
            return

        try:
            filepath = self._result_dir / filename
            with open(filepath, 'w', encoding='utf-8') as f:
                json.dump(data, f, ensure_ascii=False, indent=2)
            self.logger.info(f"✓ 中间结果已保存: {filepath}")
        except Exception as e:
            self.logger.warning(f"保存中间结果失败 {filename}: {e}")

    def _step5_select_viral_segments(
        self,
        analyzed_segments: List[Dict[str, Any]],
        qwen_api_key: str = None,
        qwen_model: str = "qwen3-max",
        temperature: float = 0.7,
        batch_size: int = 5
    ) -> List[int]:
        """
        步骤5: 使用LLM筛选符合短视频传播逻辑的片段

        按批次调用LLM，每批处理batch_size个片段

        Args:
            analyzed_segments: 已分析的片段列表
            qwen_api_key: Qwen API密钥
            qwen_model: Qwen模型名称
            temperature: 温度参数
            batch_size: 每批处理的片段数量，默认5

        Returns:
            选中的片段索引列表
        """
        try:
            if not analyzed_segments:
                return []

            # 初始化LLM客户端
            api_key = qwen_api_key or os.getenv("DASHSCOPE_API_KEY")
            llm_client = QwenLLMClient(api_key=api_key, model=qwen_model)

            # 分批处理
            all_selected_indices = []
            raw_results = []  # 保存每个批次的原始结果
            total_batches = (len(analyzed_segments) + batch_size - 1) // batch_size

            for batch_idx in range(0, len(analyzed_segments), batch_size):
                batch_segments = analyzed_segments[batch_idx:batch_idx + batch_size]
                batch_num = batch_idx // batch_size + 1

                self.logger.info(f"处理批次 {batch_num}/{total_batches}，包含 {len(batch_segments)} 个片段...")

                # 准备输入数据（只提取需要的字段）
                segments_for_llm = []
                for seg in batch_segments:
                    segments_for_llm.append({
                        "segment_index": seg["segment_index"],
                        "content_summary": seg.get("content_summary", ""),
                        "subtitle": seg.get("subtitle", ""),
                        "scene_description": seg.get("visual_analysis", {}).get("scene_description", "")
                    })

                system_prompt = self._build_selection_system_prompt()
                user_prompt = self._build_selection_user_prompt(segments_for_llm)

                llm_result = llm_client.completions_with_json(
                    user_content=user_prompt,
                    system_content=system_prompt,
                    temperature=temperature
                )

                if llm_result is None:
                    self.logger.warning(f"批次 {batch_num} LLM返回结果为空，跳过")
                    continue

                if isinstance(llm_result, dict) and "content" in llm_result:
                    result = llm_result.get("content")
                    usage = llm_result.get("usage")
                    if usage:
                        self._usage_list.append(usage)
                else:
                    result = llm_result

                batch_raw_result = {
                    "batch_num": batch_num,
                    "segment_indices_in_batch": [seg["segment_index"] for seg in batch_segments],
                    "selected_indices": result.get("selected_indices", []),
                    "reasoning": result.get("reasoning", "")
                }
                raw_results.append(batch_raw_result)

                # 提取selected_indices
                selected = result.get("selected_indices", [])
                if isinstance(selected, list):
                    all_selected_indices.extend(selected)
                    self.logger.info(f"✓ 批次 {batch_num} 选中 {len(selected)} 个片段: {selected}")
                    if result.get("reasoning"):
                        self.logger.info(f"  理由: {result['reasoning']}")
                else:
                    self.logger.warning(f"批次 {batch_num} 返回格式错误: {result}")

            # 去重并排序
            all_selected_indices = sorted(list(set(all_selected_indices)))

            self.logger.info(f"✓ 总共选中 {len(all_selected_indices)} 个片段: {all_selected_indices}")

            if self._result_dir is not None:
                self._save_step_result("step5_raw_results.json", {
                    "total_batches": total_batches,
                    "batch_size": batch_size,
                    "raw_results": raw_results,
                    "final_selected_indices": all_selected_indices
                })

            return all_selected_indices

        except Exception as e:
            import traceback
            self.logger.error(f"片段筛选异常: {e}")
            self.logger.error(f"堆栈:\n{traceback.format_exc()}")
            return []

    def _build_segment_analysis_prompt(self) -> str:
        """构建视频片段分析的提示词"""
        return """请详细分析这个视频片段的视觉内容。
请从以下维度进行分析：
1. 场景描述：重点描述场景发生的事情。即人物，动作，事件。

请以JSON格式输出分析结果：
{
  "scene_description": "场景描述"
}
确保输出能被 Python 的 json.loads() 正确解析。"""

    def _build_slicing_system_prompt(self) -> str:
        """构建切片分析的系统提示词"""
        return """# 角色及任务：
你是一位资深的电影剧本分析师和剪辑专家，输入电影的字幕句子信息（JSON格式），分析其中的关键情节及时刻且尽可能连续的片段并裁剪出来，输出裁剪的情节片段；
并将情节片段中在时间上连续的多个句子及它们的时间戳合并为一条，且对情节中多个句子尽可能地进行分析与总结。

# 输入格式：
输入是JSON数组，每个元素包含：
- start: 开始时间（秒，浮点数）
- end: 结束时间（秒，浮点数）
- text: 字幕文本
- speaker: 说话人ID（可选）

# 步骤：
1）首先，基于字幕进行关键情节进行总结，对情节下包含的所有时间戳进行合并；
2）对每个切片下包含的内容进行言简意赅地总结，但要包含必要信息，并精确记录每个切片的时间戳，切片长度保持5s-15s；

# 注意：
1）关键情节信息量充足，保证情节时间戳与其的正确匹配；
2）不同情节或片段间时间范围不要出现重合，禁止出现时序错误；
3）所有的情节片段要尽可能覆盖全部视频时长，不留空白；

# 输出：
输出需严格按照如下Json格式，且能被`json.loads`解析:
[
  {
    "start": 0.00,
    "end": 5.20,
    "content": "末日闪电劈下，营造紧张氛围，吸引观众注意。"
  },
  {
    "start": 6.20,
    "end": 11.10,
    "content": "老夫妇被丧尸追赶，呼救声引发情感共鸣和危机感。"
  }
]

确保输出能被 Python 的 json.loads() 正确解析。注意：start和end字段的值是数字类型，不要加引号。"""

    def _build_selection_system_prompt(self) -> str:
        """构建片段筛选的系统提示词"""
        return """# 角色及任务：
你是一位资深的短视频内容策划专家，精通抖音、快手等短视频平台的传播规律。
你的任务是从给定的视频片段中，筛选出最有可能在短视频平台爆火的片段。

# 筛选标准：
1. **节奏快**：情节推进迅速，信息密度高，不拖沓
2. **冲突强**：有明显的矛盾、反转、悬念或情绪爆点
3. **视觉冲击**：画面有冲击力，动作、特效、表情等有吸引力
4. **情感共鸣**：能引发观众强烈的情感反应（惊讶、愤怒、感动、好奇等）

# 输入格式：
JSON数组，每个元素包含：
- segment_index: 片段索引
- content_summary: 内容摘要
- subtitle: 字幕内容（含说话人）
- scene_description: 视觉场景描述

# 输出格式：
返回JSON对象，包含：
- selected_indices: 选中的片段索引数组（按传播潜力从高到低排序）
- reasoning: 简要说明筛选理由

示例：
{
  "selected_indices": [2, 5],
  "reasoning": "片段2有强烈冲突和反转；片段5情感爆点明显..."
}

注意：
1. 不要选择所有片段，只选择真正有爆款潜力的，一般为1-2个。
2. 如果没有特别突出的片段，可以少选甚至不选
"""

    def _build_selection_user_prompt(self, segments: List[Dict[str, Any]]) -> str:
        """构建片段筛选的用户提示词"""
        segments_json = json.dumps(segments, ensure_ascii=False, indent=2)

        return f"""请从以下视频片段中，筛选出最有可能在短视频平台爆火的片段：

{segments_json}

请按照短视频传播规律，严格按照JSON格式返回筛选结果。"""


async def run_highlight_workflow_async(
    input_videos: Any,
    output_base_dir: str = None,
    qwen_api_key: str = None,
    qwen_model: str = "qwen3-max",
    temperature: float = 0.7,
    fps: float = 2.0,
    max_workers: int = 3,
    save_intermediate: bool = False,
    **kwargs
) -> AsyncGenerator[Dict[str, Any], None]:
    """
    运行高光片段提取工作流的便捷函数（支持批量处理）

    这是一个异步生成器，用法示例：

        async for event in run_highlight_workflow_async("video.mp4"):
            if event["type"] == "video_progress":
                print(f"[{event['video_name']}] 步骤{event['step']} {event['step_name']}: {event['message']}")
            elif event["type"] == "video_done":
                print(f"完成 {event['completed']}/{event['total']}: {event['video_name']}")
            elif event["type"] == "result":
                result = event  # 最终结果

    Args:
        input_videos: 输入视频路径（str）或视频路径列表（list）或目录路径
        output_base_dir: 输出基础目录
        qwen_api_key: Qwen API密钥
        qwen_model: Qwen模型名称
        temperature: LLM温度参数
        fps: 视频分析的帧率
        max_workers: 并发处理的最大线程数
        save_intermediate: 是否保存中间结果到每个视频的output_dir/result目录，默认为False
        **kwargs: 其他参数

    Yields:
        进度事件 dict 及最终结果 dict（详见 HighlightWorkflowAsync.run 文档）
    """
    workflow = HighlightWorkflowAsync()
    async for event in workflow.run(
        input_videos=input_videos,
        output_base_dir=output_base_dir,
        qwen_api_key=qwen_api_key,
        qwen_model=qwen_model,
        temperature=temperature,
        fps=fps,
        max_workers=max_workers,
        save_intermediate=save_intermediate,
        **kwargs
    ):
        yield event
