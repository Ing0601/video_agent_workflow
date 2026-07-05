from ..logger.logging import logger
from ..node.asr_transcribe import ASRTranscriber
from ..node.add_mosaic import AddMosaic
from ..utils.translation import translate_text
from ..utils.srt_convert import convert_to_srt
from ..utils.ffmpeg_utils import add_subtitle
from dotenv import load_dotenv
from pathlib import Path
from typing import Union, Dict, List

# 加载环境变量
load_dotenv()

class SubtitleConversion:
    """字幕转换工作流"""

    def __init__(self):
        """初始化"""
        self.logger = logger
        self._asr_transcriber = ASRTranscriber()  # ASR转录节点
        self._add_mosaic = AddMosaic()            # 字幕遮盖节点
    
    def process_video(self, video_path: str, regions: Union[Dict, List[Dict]], language: str="English", output_path: str=None):
        """处理视频"""
        try:
            # 检查输入路径
            if not video_path:
                raise ValueError("输入路径不能为空")
            
            if  output_path is None:
                video_file = Path(video_path)
                output_path = str(video_file.parent / f"{video_file.stem}_{language.lower()}_subtitle{video_file.suffix}")
            else:
                output_path = str(output_path)  # 转为字符串

            # 步骤1: ASR识别
            self.logger.info(f"\n[步骤 1/2] 开始ASR识别...")
            asr_result = self._asr_transcriber.transcribe_video(video_path)
            if not asr_result["success"]:
                raise Exception(f"ASR识别失败: {asr_result.get('error')}")
            
            # 步骤2: 字幕遮盖
            self.logger.info(f"\n[步骤 2/2] 开始字幕遮盖...")
            output_path_with_mosaic = str(Path(output_path).parent / f"{Path(output_path).stem}_with_mosaic{Path(output_path).suffix}")
            result = self._add_mosaic.remove_subtitle(video_path, regions, output_path_with_mosaic)
            if not result:
                raise Exception("字幕遮盖失败")
            
            # 步骤3: 返回字幕
            text_list = asr_result.get("utterances", [])
            if len(text_list) == 0:
                raise Exception("ASR识别失败，未返回结果")
            
            translated_text_list = text_list.copy()
            try:
                for i, text_item in enumerate(text_list):
                    text = text_item.get("text")
                    if not text:
                        continue
                    translated_text = translate_text(text=text, target_language="English")
                    translated_text_list[i]["text"] = translated_text
            except Exception as e:
                self.logger.error(f"翻译失败: {e}")
                return False
            
            # 步骤4: 转换成字幕文件SRT
            output_dir = str(Path(output_path).parent)
            srt_path = convert_to_srt(translated_text_list, output_dir)

            # 步骤5: 加入字幕到视频中
            self.logger.info(f"\n[步骤 5/5] 开始加入字幕到视频中...")
            output_path_with_subtitle = output_path
            
            result = add_subtitle(output_path_with_mosaic, srt_path, output_path_with_subtitle)
            if not result:
                raise Exception("加入字幕失败")

            return output_path_with_subtitle

        except Exception as e:
            self.logger.error(f"处理视频失败: {e}")
            return False