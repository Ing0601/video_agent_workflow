from pathlib import Path
from typing import Any, List
import os
import re


class VideoCollector:
    """
    视频文件路径收集器
    
    将各种形式的输入（单个文件路径、目录路径、路径列表）统一归一化为
    排好序的视频文件路径列表。目录只遍历顶层文件，不递归子目录。
    """

    VIDEO_EXTENSIONS = {".mp4", ".mov", ".mkv", ".avi", ".webm", ".flv", ".ts"}

    def collect(self, input_videos: Any) -> List[str]:
        """
        收集视频文件路径

        Args:
            input_videos: 可以是：
                - str: 单个视频文件路径或目录路径
                - list/tuple: 视频文件路径列表或目录路径列表

        Returns:
            视频文件路径列表（已排序）

        Raises:
            TypeError: 当 input_videos 不是 str / list / tuple 时
        """
        video_paths: List[str] = []

        if isinstance(input_videos, str):
            video_paths.extend(self._collect_from_path(input_videos))
        elif isinstance(input_videos, (list, tuple)):
            for path in input_videos:
                video_paths.extend(self._collect_from_path(str(path)))
        else:
            raise TypeError(
                f"input_videos 类型不支持: {type(input_videos)}，"
                "请传入 str、list 或 tuple"
            )

        return sorted(video_paths)

    def _collect_from_path(self, path: str) -> List[str]:
        """
        从单个路径（文件或目录顶层）收集视频文件

        Args:
            path: 文件路径或目录路径

        Returns:
            该路径下找到的视频文件路径列表
        """
        normalized_path = self._normalize_path_for_platform(path)
        path_obj = Path(normalized_path)
        results: List[str] = []

        if path_obj.is_file():
            if path_obj.suffix.lower() in self.VIDEO_EXTENSIONS:
                results.append(str(path_obj))
        elif path_obj.is_dir():
            for item in path_obj.iterdir():
                if item.is_file() and item.suffix.lower() in self.VIDEO_EXTENSIONS:
                    results.append(str(item))

        return results

    def _normalize_path_for_platform(self, path: str) -> str:
        """
        规范化不同运行环境下的路径格式

        在 Windows 后端中，兼容前端传入的 WSL 路径：
        /mnt/d/xxx -> D:/xxx
        """
        if not path:
            return path

        normalized = path.strip()

        # 兼容 Windows 后端接收到的 WSL 路径
        if os.name == "nt":
            mnt_match = re.match(r"^/mnt/([a-zA-Z])/(.+)$", normalized)
            if mnt_match:
                drive_letter = mnt_match.group(1).upper()
                tail_path = mnt_match.group(2).replace("/", "\\")
                normalized = f"{drive_letter}:\\{tail_path}"

            # 某些输入可能缺失中间层目录（例如少了 videoAgent），
            # 这里尝试按当前仓库根目录做一次对齐修正。
            repo_candidate = self._align_path_with_repo_root(normalized)
            if repo_candidate:
                return repo_candidate

        return normalized

    def _align_path_with_repo_root(self, path: str) -> str | None:
        """
        当输入路径不存在时，尝试对齐到当前仓库目录结构。

        例如:
        D:\General_Video_Agent\input\001.mp4
        -> D:\videoAgent\General_Video_Agent\input\001.mp4
        """
        path_obj = Path(path)
        if path_obj.exists():
            return path

        repo_root = Path(__file__).resolve().parents[2]
        repo_parts = repo_root.parts
        path_parts = path_obj.parts
        if not repo_parts or not path_parts:
            return None

        repo_name = repo_root.name.lower()
        path_parts_lower = [part.lower() for part in path_parts]
        if repo_name not in path_parts_lower:
            return None

        repo_name_index = path_parts_lower.index(repo_name)
        relative_parts = path_parts[repo_name_index + 1 :]
        candidate = repo_root.joinpath(*relative_parts)
        return str(candidate) if candidate.exists() else None
