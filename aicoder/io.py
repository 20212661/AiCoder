"""
终端输入输出模块
使用 prompt_toolkit 和 rich 增强终端体验
"""
import sys

try:
    from prompt_toolkit import prompt as pt_prompt
    from prompt_toolkit.history import InMemoryHistory
    HAS_PROMPT_TOOLKIT = True
except ImportError:
    HAS_PROMPT_TOOLKIT = False

try:
    from rich.console import Console
    from rich.markdown import Markdown
    HAS_RICH = True
except ImportError:
    HAS_RICH = False


class InputOutput:
    """终端 I/O 管理，处理用户输入和输出显示"""

    def __init__(self, pretty=True, yes=False):
        self.pretty = pretty and HAS_RICH
        self.yes = yes
        self.encoding = "utf-8"

        if HAS_RICH:
            self.console = Console()
        else:
            self.console = None

        if HAS_PROMPT_TOOLKIT:
            self.history = InMemoryHistory()
        else:
            self.history = None

    def read_text(self, filename):
        """读取文件内容，失败返回 None"""
        try:
            with open(filename, "r", encoding="utf-8", errors="ignore") as f:
                return f.read()
        except (FileNotFoundError, IsADirectoryError, PermissionError):
            return None

    def write_text(self, filename, content):
        """写入文件内容"""
        with open(filename, "w", encoding="utf-8") as f:
            f.write(content)

    def get_input(self, root, inchat_files, addable_files, commands, read_only_fnames, edit_format=""):
        """获取用户输入"""
        rel_root = root
        prompt_str = f"\n{rel_root}> "

        if HAS_PROMPT_TOOLKIT:
            try:
                return pt_prompt(
                    prompt_str,
                    history=self.history,
                    multiline=False,
                )
            except EOFError:
                raise
        else:
            try:
                return input(prompt_str)
            except EOFError:
                raise

    def tool_output(self, message="", bold=False):
        """工具输出（正常信息）"""
        if self.console and self.pretty:
            if bold:
                self.console.print(f"[bold]{message}[/bold]")
            else:
                self.console.print(message)
        else:
            print(message)

    def tool_error(self, message=""):
        """工具输出（错误信息）"""
        if self.console and self.pretty:
            self.console.print(f"[red]Error:[/red] {message}")
        else:
            print(f"Error: {message}", file=sys.stderr)

    def tool_warning(self, message=""):
        """工具输出（警告信息）"""
        if self.console and self.pretty:
            self.console.print(f"[yellow]Warning:[/yellow] {message}")
        else:
            print(f"Warning: {message}", file=sys.stderr)

    def user_input(self, message, log_only=True):
        """记录用户输入"""
        pass

    def confirm_ask(self, question, default="y"):
        """确认提问"""
        if self.yes:
            return True
        if self.console and self.pretty:
            self.console.print(f"[bold]{question}[/bold] [Y/n] ", end="")
        else:
            print(f"{question} [Y/n] ", end="", flush=True)
        response = input().strip().lower()
        return response in ("", "y", "yes")

    def print_assistant_output(self, text):
        """打印助手输出（支持 Markdown 渲染）"""
        if self.console and self.pretty:
            self.console.print(Markdown(text))
        else:
            print(text)

    def print_streaming(self, chunk):
        """流式打印"""
        print(chunk, end="", flush=True)
