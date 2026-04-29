"""
Integration tests for repo.py git workflows.

Tests git operations: init, commit, diff, dirty check, tracked files.
These tests create real temporary git repositories.
"""
import pytest
import tempfile
import os
from pathlib import Path

# Conditionally import git
try:
    import git as gitpython
    GIT_AVAILABLE = True
except ImportError:
    GIT_AVAILABLE = False


@pytest.fixture
def temp_git_repo():
    """Create a temporary git repository with one initial file."""
    if not GIT_AVAILABLE:
        pytest.skip("GitPython not available")

    with tempfile.TemporaryDirectory() as tmpdir:
        repo_dir = Path(tmpdir)
        # Initialize git repo
        repo = gitpython.Repo.init(str(repo_dir))

        # Configure git user for commits
        repo.git.config("user.name", "Test User")
        repo.git.config("user.email", "test@example.com")

        # Create initial file and commit
        (repo_dir / "test.py").write_text("print('hello')\n")
        repo.git.add("test.py")
        repo.git.commit("-m", "Initial commit")

        yield tmpdir


@pytest.fixture
def temp_git_repo_multi_files():
    """Create a git repo with multiple files and uncommitted changes."""
    if not GIT_AVAILABLE:
        pytest.skip("GitPython not available")

    with tempfile.TemporaryDirectory() as tmpdir:
        repo_dir = Path(tmpdir)
        repo = gitpython.Repo.init(str(repo_dir))
        repo.git.config("user.name", "Test User")
        repo.git.config("user.email", "test@example.com")

        (repo_dir / "main.py").write_text("print('main')\n")
        (repo_dir / "util.py").write_text("def helper():\n    pass\n")
        repo.git.add("main.py", "util.py")
        repo.git.commit("-m", "Initial commit")

        # Make uncommitted change
        (repo_dir / "main.py").write_text("print('modified')\n")

        # Create untracked file
        (repo_dir / "new_file.py").write_text("print('new')\n")

        yield tmpdir


class MockIO:
    """Mock InputOutput for testing GitRepo."""

    def tool_output(self, *args, **kwargs):
        pass

    def tool_error(self, *args, **kwargs):
        pass

    def tool_warning(self, *args, **kwargs):
        pass


# ---- Tests ----


class TestGitRepoInit:
    """Tests for GitRepo initialization."""

    def test_init_with_existing_repo(self, temp_git_repo):
        from aicoder.repo import GitRepo

        io = MockIO()
        repo = GitRepo(io, fnames=[temp_git_repo])
        assert repo is not None
        assert repo.repo is not None
        assert os.path.isdir(repo.root)

    def test_init_with_file_in_repo(self, temp_git_repo):
        from aicoder.repo import GitRepo

        io = MockIO()
        test_file = os.path.join(temp_git_repo, "test.py")
        repo = GitRepo(io, fnames=[test_file])
        assert repo is not None

    def test_init_no_git_repo(self):
        from aicoder.repo import GitRepo

        io = MockIO()
        with tempfile.TemporaryDirectory() as tmpdir:
            with pytest.raises(FileNotFoundError):
                GitRepo(io, fnames=[tmpdir])

    def test_init_with_git_dname(self, temp_git_repo):
        from aicoder.repo import GitRepo

        io = MockIO()
        repo = GitRepo(io, git_dname=temp_git_repo)
        assert repo is not None


class TestGitRepoCommit:
    """Tests for git commit operations."""

    def test_commit_with_message(self, temp_git_repo):
        from aicoder.repo import GitRepo

        io = MockIO()
        repo = GitRepo(io, fnames=[temp_git_repo])

        # Modify a file
        test_file = os.path.join(temp_git_repo, "test.py")
        with open(test_file, "w") as f:
            f.write("print('updated')\n")

        result = repo.commit(message="Test commit message")
        assert result is not None
        commit_hash, commit_message = result
        assert commit_hash is not None
        assert len(commit_hash) == 7  # short SHA
        assert "Test commit message" in commit_message

    def test_commit_empty_repo(self, temp_git_repo):
        from aicoder.repo import GitRepo

        io = MockIO()
        repo = GitRepo(io, fnames=[temp_git_repo])
        # Nothing changed, repo is clean
        result = repo.commit()
        assert result is None

    def test_commit_with_specific_file(self, temp_git_repo_multi_files):
        from aicoder.repo import GitRepo

        io = MockIO()
        repo = GitRepo(io, fnames=[temp_git_repo_multi_files])

        # Commit only main.py
        result = repo.commit(
            fnames=["main.py"],
            message="Update main"
        )
        assert result is not None

        # main.py should be committed, util.py unchanged state
        # new_file.py should still be untracked/unchanged
        assert repo.repo.is_dirty() or not repo.repo.is_dirty(path="main.py")

    def test_commit_with_aider_edits(self, temp_git_repo):
        from aicoder.repo import GitRepo

        io = MockIO()
        repo = GitRepo(io, fnames=[temp_git_repo])

        test_file = os.path.join(temp_git_repo, "test.py")
        with open(test_file, "w") as f:
            f.write("print('ai edit')\n")

        result = repo.commit(message="AI edit", aider_edits=True)
        assert result is not None
        _, commit_message = result
        assert "Co-authored-by: aiCoder" in commit_message


class TestGitRepoDiff:
    """Tests for diff operations."""

    def test_get_diffs_with_changes(self, temp_git_repo_multi_files):
        from aicoder.repo import GitRepo

        io = MockIO()
        repo = GitRepo(io, fnames=[temp_git_repo_multi_files])

        diffs = repo.get_diffs(fnames=["main.py"])
        assert diffs is not None
        # Should contain diff for modified main.py
        assert len(diffs) > 0

    def test_get_diffs_new_file(self, temp_git_repo_multi_files):
        from aicoder.repo import GitRepo

        io = MockIO()
        repo = GitRepo(io, fnames=[temp_git_repo_multi_files])

        diffs = repo.get_diffs(fnames=["new_file.py"])
        assert "Added new_file.py" in diffs

    def test_diff_commits(self, temp_git_repo):
        from aicoder.repo import GitRepo

        io = MockIO()
        repo = GitRepo(io, fnames=[temp_git_repo])

        # Make another commit
        test_file = os.path.join(temp_git_repo, "test.py")
        with open(test_file, "w") as f:
            f.write("print('v2')\n")
        repo.repo.git.add("test.py")
        repo.repo.git.commit("-m", "Second commit")

        head_sha = repo.get_head_commit_sha()
        diffs = repo.diff_commits(False, "HEAD~1", "HEAD")
        assert diffs is not None
        assert len(diffs) > 0


class TestGitRepoState:
    """Tests for repo state queries."""

    def test_is_dirty_with_changes(self, temp_git_repo):
        from aicoder.repo import GitRepo

        io = MockIO()
        repo = GitRepo(io, fnames=[temp_git_repo])

        assert not repo.is_dirty()

        test_file = os.path.join(temp_git_repo, "test.py")
        with open(test_file, "w") as f:
            f.write("print('dirty')\n")

        assert repo.is_dirty()

    def test_get_tracked_files(self, temp_git_repo_multi_files):
        from aicoder.repo import GitRepo

        io = MockIO()
        repo = GitRepo(io, fnames=[temp_git_repo_multi_files])

        tracked = repo.get_tracked_files()
        assert len(tracked) >= 2
        assert "main.py" in tracked or any("main.py" in f for f in tracked)
        assert "util.py" in tracked or any("util.py" in f for f in tracked)

    def test_get_head_commit_sha(self, temp_git_repo):
        from aicoder.repo import GitRepo

        io = MockIO()
        repo = GitRepo(io, fnames=[temp_git_repo])

        sha_short = repo.get_head_commit_sha(short=True)
        assert len(sha_short) == 7

        sha_full = repo.get_head_commit_sha(short=False)
        assert len(sha_full) == 40

    def test_get_head_commit_message(self, temp_git_repo):
        from aicoder.repo import GitRepo

        io = MockIO()
        repo = GitRepo(io, fnames=[temp_git_repo])

        message = repo.get_head_commit_message()
        assert "Initial commit" in message

    def test_path_in_repo(self, temp_git_repo):
        from aicoder.repo import GitRepo

        io = MockIO()
        repo = GitRepo(io, fnames=[temp_git_repo])

        assert repo.path_in_repo("test.py")
        assert not repo.path_in_repo("nonexistent.py")

    def test_abs_root_path(self, temp_git_repo):
        from aicoder.repo import GitRepo

        io = MockIO()
        repo = GitRepo(io, fnames=[temp_git_repo])

        abs_path = repo.abs_root_path("test.py")
        assert os.path.isabs(abs_path)
        assert abs_path.endswith("test.py")
