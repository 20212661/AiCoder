"""
Git 仓库集成 - 自动 commit、undo、diff 等
参考 Aider 的 repo.py，简化版
"""
import contextlib
import os
from pathlib import Path, PurePosixPath

try:
    import git
    ANY_GIT_ERROR = [
        git.exc.ODBError,
        git.exc.GitError,
        git.exc.InvalidGitRepositoryError,
        git.exc.GitCommandNotFound,
    ]
except ImportError:
    git = None
    ANY_GIT_ERROR = []

ANY_GIT_ERROR += [
    OSError,
    IndexError,
    TypeError,
    ValueError,
    AttributeError,
    TimeoutError,
]
ANY_GIT_ERROR = tuple(ANY_GIT_ERROR)

from .utils import safe_abs_path


@contextlib.contextmanager
def set_git_env(var_name, value, original_value):
    """临时设置 Git 环境变量"""
    os.environ[var_name] = value
    try:
        yield
    finally:
        if original_value is not None:
            os.environ[var_name] = original_value
        elif var_name in os.environ:
            del os.environ[var_name]


class GitRepo:
    """Git 仓库封装，提供自动提交、撤销、差异比较等功能"""

    def __init__(self, io, fnames=None, git_dname=None):
        self.io = io
        self.normalized_path = {}
        self.tree_files = {}

        if git_dname:
            check_fnames = [git_dname]
        elif fnames:
            check_fnames = fnames
        else:
            check_fnames = ["."]

        repo_paths = []
        for fname in check_fnames:
            fname = Path(fname)
            fname = fname.resolve()

            if not fname.exists() and fname.parent.exists():
                fname = fname.parent

            try:
                repo_path = git.Repo(fname, search_parent_directories=True).working_dir
                repo_path = safe_abs_path(repo_path)
                repo_paths.append(repo_path)
            except ANY_GIT_ERROR:
                pass

        if not repo_paths:
            raise FileNotFoundError("No git repository found")

        if len(set(repo_paths)) > 1:
            self.io.tool_error("Files are in different git repos.")
            raise FileNotFoundError

        self.repo = git.Repo(repo_paths.pop(), odbt=git.GitDB)
        self.root = safe_abs_path(self.repo.working_tree_dir)

    def commit(self, fnames=None, context=None, message=None, aider_edits=False, coder=None):
        """提交更改

        Args:
            fnames: 要提交的文件列表，None 表示所有更改
            context: 上下文信息
            message: 显式提交消息，None 则用 LLM 生成
            aider_edits: 是否为 AI 编辑（影响归属标记）
            coder: Coder 实例

        Returns:
            (commit_hash, commit_message) 或 None
        """
        if not fnames and not self.repo.is_dirty():
            return

        diffs = self.get_diffs(fnames)
        if not diffs:
            return

        if message:
            commit_message = message
        else:
            commit_message = self.get_commit_message(diffs, context)

        if not commit_message:
            commit_message = "(no commit message provided)"

        # AI 归属标记
        if aider_edits:
            full_commit_message = commit_message + "\n\nCo-authored-by: aiCoder <aicoder@ai>"
        else:
            full_commit_message = commit_message

        cmd = ["-m", full_commit_message]

        if fnames:
            fnames = [str(self.abs_root_path(fn)) for fn in fnames]
            for fname in fnames:
                try:
                    self.repo.git.add(fname)
                except ANY_GIT_ERROR as err:
                    self.io.tool_error(f"Unable to add {fname}: {err}")
            cmd += ["--"] + fnames
        else:
            cmd += ["-a"]

        try:
            self.repo.git.commit(cmd)
            commit_hash = self.get_head_commit_sha(short=True)
            self.io.tool_output(f"Commit {commit_hash} {commit_message}")
            return commit_hash, commit_message
        except ANY_GIT_ERROR as err:
            self.io.tool_error(f"Unable to commit: {err}")
            return None

    def get_commit_message(self, diffs, context=None):
        """用 LLM 生成 commit 消息"""
        from .prompts import commit_system

        diffs = "# Diffs:\n" + diffs
        content = ""
        if context:
            content += context + "\n"
        content += diffs

        messages = [
            dict(role="system", content=commit_system),
            dict(role="user", content=content),
        ]

        try:
            from .models import Model
            weak_model = Model()
            commit_message = weak_model.simple_send(messages)
            if commit_message:
                commit_message = commit_message.strip()
                if commit_message and commit_message[0] == '"' and commit_message[-1] == '"':
                    commit_message = commit_message[1:-1].strip()
                return commit_message
        except Exception as e:
            self.io.tool_warning(f"Failed to generate commit message: {e}")

        return None

    def get_diffs(self, fnames=None):
        """获取 diff"""
        current_branch_has_commits = False
        try:
            active_branch = self.repo.active_branch
            try:
                commits = self.repo.iter_commits(active_branch)
                current_branch_has_commits = any(commits)
            except ANY_GIT_ERROR:
                pass
        except (TypeError,) + ANY_GIT_ERROR:
            pass

        if not fnames:
            fnames = []

        diffs = ""
        for fname in fnames:
            if not self.path_in_repo(fname):
                diffs += f"Added {fname}\n"

        try:
            if current_branch_has_commits:
                args = ["HEAD", "--"] + list(fnames)
                diffs += self.repo.git.diff(*args)
                return diffs

            wd_args = ["--"] + list(fnames)
            index_args = ["--cached"] + wd_args

            diffs += self.repo.git.diff(*index_args)
            diffs += self.repo.git.diff(*wd_args)

            return diffs
        except ANY_GIT_ERROR as err:
            self.io.tool_error(f"Unable to diff: {err}")
            return ""

    def diff_commits(self, pretty, from_commit, to_commit):
        """两个 commit 之间的 diff"""
        args = ["--color=never", from_commit, to_commit]
        diffs = self.repo.git.diff(*args)
        return diffs

    def get_tracked_files(self):
        """获取 git 追踪的文件列表"""
        if not self.repo:
            return []

        try:
            commit = self.repo.head.commit
        except (ValueError,) + ANY_GIT_ERROR:
            commit = None

        files = set()
        if commit:
            if commit in self.tree_files:
                files = self.tree_files[commit]
            else:
                try:
                    for blob in commit.tree.traverse():
                        if blob.type == "blob":
                            files.add(blob.path)
                except ANY_GIT_ERROR:
                    pass
                files = set(self.normalize_path(path) for path in files)
                self.tree_files[commit] = set(files)

        try:
            index = self.repo.index
            staged_files = [path for path, _ in index.entries.keys()]
            files.update(self.normalize_path(path) for path in staged_files)
        except ANY_GIT_ERROR:
            pass

        return list(files)

    def normalize_path(self, path):
        """规范化路径"""
        if path in self.normalized_path:
            return self.normalized_path[path]

        path = str(Path(PurePosixPath((Path(self.root) / path).relative_to(self.root))))
        self.normalized_path[path] = path
        return path

    def path_in_repo(self, path):
        """检查路径是否在仓库中"""
        if not self.repo or not path:
            return False
        tracked_files = set(self.get_tracked_files())
        normalized = self.normalize_path(path)
        return normalized in tracked_files

    def abs_root_path(self, path):
        """解析路径为仓库根目录下的绝对路径"""
        res = Path(self.root) / path
        return safe_abs_path(res)

    def is_dirty(self, path=None):
        """检查是否有未提交的更改"""
        if path and not self.path_in_repo(path):
            return True
        return self.repo.is_dirty(path=path)

    def get_head_commit(self):
        """获取 HEAD commit"""
        try:
            return self.repo.head.commit
        except (ValueError,) + ANY_GIT_ERROR:
            return None

    def get_head_commit_sha(self, short=False):
        """获取 HEAD commit SHA"""
        commit = self.get_head_commit()
        if not commit:
            return None
        if short:
            return commit.hexsha[:7]
        return commit.hexsha

    def get_head_commit_message(self, default=None):
        """获取 HEAD commit 消息"""
        commit = self.get_head_commit()
        if not commit:
            return default
        return commit.message
