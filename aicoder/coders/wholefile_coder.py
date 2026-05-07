"""
WholeFile Coder - 整体文件输出格式
LLM 返回完整文件内容，Coder 负责解析并写入文件
参考 Aider 的 wholefile_coder.py
"""
import os
from pathlib import Path

from .base_coder import Coder
from .wholefile_prompts import WholeFilePrompts


class WholeFileCoder(Coder):
    """整体文件编辑 Coder：LLM 输出完整文件，解析后直接覆盖写入"""

    edit_format = "whole"
    gpt_prompts = WholeFilePrompts()

    def process_response(self):
        """处理 LLM 响应，解析 whole 格式的文件编辑并应用"""
        content = self.multi_response_content
        if not content:
            return

        edits = self.get_edits(content)
        if edits:
            self.apply_edits(edits)
            for path, _source, _lines in edits:
                self.io.tool_output(f"Applied edit to {path}")
        elif self.verbose:
            self.io.tool_output("(No file edits detected in response)")

    def get_edits(self, content):
        """从 LLM 响应中解析出文件编辑

        解析格式：
        filename.py
        ```
        file content...
        ```

        Returns:
            list of (filename, fname_source, lines) 元组
        """
        chat_files = self.get_inchat_relative_files()

        edits = []
        lines = content.splitlines(keepends=True)

        saw_fname = None
        fname = None
        fname_source = None
        new_lines = []

        for i, line in enumerate(lines):
            if line.startswith(self.fence[0]) or line.rstrip().startswith(self.fence[1]):
                if fname is not None:
                    # 结束一个代码块 → 保存编辑
                    saw_fname = None
                    edits.append((fname, fname_source, new_lines))
                    fname = None
                    fname_source = None
                    new_lines = []
                    continue

                # 开始新的代码块 → 前一行可能是文件名
                if i > 0:
                    fname_source = "block"
                    fname = lines[i - 1].strip()
                    fname = fname.strip("*").rstrip(":").strip("`").lstrip("#").strip()

                    # 文件名过长则忽略
                    if len(fname) > 250:
                        fname = ""

                    # 如果 LLM 加了多余的目录前缀，尝试只取文件名
                    if fname and fname not in chat_files and Path(fname).name in chat_files:
                        fname = Path(fname).name

                if not fname:
                    # 尝试用之前提到的文件名
                    if saw_fname:
                        fname = saw_fname
                        fname_source = "saw"
                    elif len(chat_files) == 1:
                        fname = chat_files[0]
                        fname_source = "chat"
                    else:
                        # 无法确定文件名，跳过
                        continue

            elif fname is not None:
                new_lines.append(line)
            else:
                # 在代码块外，检测可能被提及的文件名
                for word in line.strip().split():
                    word = word.rstrip(".:,;!")
                    for chat_file in chat_files:
                        quoted = f"`{chat_file}`"
                        if word == quoted:
                            saw_fname = chat_file

        # 处理最后一个未关闭的代码块
        if fname and new_lines:
            edits.append((fname, fname_source, new_lines))

        # 去重：按优先级 block > saw > chat，每个文件只保留最高优先级的编辑
        seen = set()
        refined = []
        for source in ("block", "saw", "chat"):
            for fname, fname_source, new_lines in edits:
                if fname_source != source:
                    continue
                if fname in seen:
                    continue
                seen.add(fname)
                refined.append((fname, fname_source, new_lines))

        return refined

    def apply_edits(self, edits):
        """应用编辑：将新内容写入文件"""
        for path, fname_source, new_lines in edits:
            full_path = self.abs_root_path(path)
            new_content = "".join(new_lines)

            # 跳过无效路径：目录、空路径、无扩展名且不在聊天文件中的路径
            if not path or os.path.isdir(full_path):
                if self.verbose:
                    self.io.tool_output(f"Skipping invalid path: {path}")
                continue

            # 确保目录存在
            Path(full_path).parent.mkdir(parents=True, exist_ok=True)

            self.io.write_text(full_path, new_content)

            # 如果是新文件，加入 abs_fnames
            abs_path = str(Path(full_path).resolve())
            if abs_path not in self.abs_fnames:
                self.abs_fnames.add(abs_path)
                self.io.tool_output(f"Added new file: {path}")