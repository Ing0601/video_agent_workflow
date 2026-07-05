"""Utility functions for jianying converter."""

import os
import uuid


def convert_wsl_path_to_windows(wsl_path):
    """Converts WSL path to Windows path format.

    Args:
        wsl_path (str): WSL format path like /mnt/d/T1/file.mp3

    Returns:
        str: Windows format path like D:\\T1\\file.mp3
    """
    if not wsl_path or not isinstance(wsl_path, str):
        return wsl_path

    if wsl_path.startswith("/mnt/"):
        try:
            drive_letter = wsl_path[5].upper()
            windows_path = drive_letter + ":" + wsl_path[6:].replace("/", "\\")
            return windows_path
        except IndexError:
            return wsl_path

    return wsl_path