"""
通用工具函数
"""
import os
from pathlib import Path


def safe_abs_path(path):
    """安全地获取绝对路径"""
    try:
        return str(Path(path).resolve())
    except (OSError, ValueError):
        return str(path)


def is_image_file(fname):
    """检查是否是图片文件"""
    image_extensions = {".png", ".jpg", ".jpeg", ".gif", ".bmp", ".webp", ".svg"}
    return Path(fname).suffix.lower() in image_extensions


def format_messages(messages):
    """格式化消息列表用于调试"""
    lines = []
    for i, msg in enumerate(messages):
        role = msg.get("role", "?")
        content = msg.get("content", "")
        if isinstance(content, str):
            preview = content[:100] + "..." if len(content) > 100 else content
        else:
            preview = str(content)[:100]
        lines.append(f"  [{i}] {role}: {preview}")
    return "\n".join(lines)
