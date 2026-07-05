from typing import List, Dict, Any, Optional
from pathlib import Path


def format_time_srt(milliseconds: int) -> str:
    """
    将毫秒转换为SRT时间格式 (HH:MM:SS,mmm)
    
    Args:
        milliseconds: 毫秒数
        
    Returns:
        SRT格式的时间字符串
    """
    total_seconds = milliseconds // 1000
    millis = milliseconds % 1000
    
    hours = total_seconds // 3600
    minutes = (total_seconds % 3600) // 60
    seconds = total_seconds % 60
    
    return f"{hours:02d}:{minutes:02d}:{seconds:02d},{millis:03d}"


def convert_to_srt(sentence_info: List[Dict[str, Any]], output_dir: str) -> str:
    """
    将ASR的句子信息转换为SRT字幕格式并保存到文件

    Args:
        sentence_info: 句子信息列表，每个元素包含 start_time(毫秒), end_time(毫秒), text
        output_dir: 输出目录路径

    Returns:
        保存的文件路径
    """
    srt_lines = []

    for index, sentence in enumerate(sentence_info, start=1):
        start_time = format_time_srt(sentence['start_time'])
        end_time = format_time_srt(sentence['end_time'])
        text = sentence['text']

        # SRT格式：序号、时间轴、文本、空行
        srt_lines.append(f"{index}")
        srt_lines.append(f"{start_time} --> {end_time}")
        srt_lines.append(text)
        srt_lines.append("")  # 空行分隔

    srt_content = "\n".join(srt_lines)

    output_path = Path(output_dir) / "subtitle.srt"
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(srt_content, encoding='utf-8')

    return str(output_path)