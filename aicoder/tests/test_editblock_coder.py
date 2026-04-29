"""
Unit tests for editblock_coder.py matching algorithms.

Tests the multi-tier SEARCH/REPLACE matching strategy:
    exact match -> whitespace-tolerant -> ... ellipsis -> fuzzy SequenceMatcher
"""
import pytest
from pathlib import Path
import tempfile
import os

from aicoder.coders.editblock_coder import (
    prep,
    perfect_replace,
    perfect_or_whitespace,
    replace_part_with_missing_leading_whitespace,
    match_but_for_leading_whitespace,
    try_dotdotdots,
    replace_closest_edit_distance,
    replace_most_similar_chunk,
    do_replace,
    strip_filename,
    strip_quoted_wrapping,
    find_similar_lines,
    find_original_update_blocks,
)


# ---- Tests for prep() ----

def test_prep_empty():
    content, lines = prep("")
    assert content == ""
    assert lines == []


def test_prep_no_newline():
    content, lines = prep("hello")
    assert content == "hello\n"
    assert lines == ["hello\n"]


def test_prep_with_newline():
    content, lines = prep("hello\n")
    assert content == "hello\n"
    assert lines == ["hello\n"]


def test_prep_multiline():
    content, lines = prep("line1\nline2")
    assert content == "line1\nline2\n"
    assert len(lines) == 2


# ---- Tests for perfect_replace() ----

def test_perfect_replace_exact_match():
    whole = ["def foo():\n", "    pass\n", "\n"]
    part = ["    pass\n"]
    replace = ["    return 42\n"]
    result = perfect_replace(whole, part, replace)
    assert result == "def foo():\n    return 42\n\n"


def test_perfect_replace_no_match():
    whole = ["def foo():\n", "    pass\n"]
    part = ["    return 1\n"]
    replace = ["    return 2\n"]
    assert perfect_replace(whole, part, replace) is None


def test_perfect_replace_first_occurrence():
    whole = ["x = 1\n", "x = 2\n", "x = 1\n"]
    part = ["x = 1\n"]
    replace = ["x = 99\n"]
    result = perfect_replace(whole, part, replace)
    assert result == "x = 99\nx = 2\nx = 1\n"


# ---- Tests for match_but_for_leading_whitespace() ----

def test_match_whitespace_exact():
    whole = ["    pass\n"]
    part = ["pass\n"]
    result = match_but_for_leading_whitespace(whole, part)
    assert result == "    "


def test_match_whitespace_no_match():
    whole = ["    pass\n"]
    part = ["    return\n"]
    assert match_but_for_leading_whitespace(whole, part) is None


def test_match_whitespace_inconsistent():
    whole = ["  pass\n", "    pass\n"]
    part = ["pass\n", "pass\n"]
    # Different leading whitespace on different lines => no single offset
    assert match_but_for_leading_whitespace(whole, part) is None


# ---- Tests for replace_part_with_missing_leading_whitespace() ----

def test_whitespace_tolerant_replace():
    whole = ["def foo():\n", "    x = 1\n", "    return x\n"]
    part = ["x = 1\n"]  # missing 4-space indent
    replace = ["y = 2\n"]
    result = replace_part_with_missing_leading_whitespace(whole, part, replace)
    assert result is not None
    assert "y = 2" in result


def test_whitespace_tolerant_no_match():
    whole = ["def foo():\n", "    x = 1\n"]
    part = ["z = 99\n"]
    replace = ["y = 2\n"]
    result = replace_part_with_missing_leading_whitespace(whole, part, replace)
    assert result is None


# ---- Tests for try_dotdotdots() ----

def test_dotdotdots_simple():
    whole = "line1\nline2\nline3\n"
    part = "line1\n...\nline3\n"
    replace = "line1\n...\nmodified\n"
    result = try_dotdotdots(whole, part, replace)
    assert result == "line1\nline2\nmodified\n"


def test_dotdotdots_unpaired():
    whole = "line1\nline2\n"
    part = "line1\n...\n"
    replace = "line1\nmodified\n"
    with pytest.raises(ValueError, match="Unpaired"):
        try_dotdotdots(whole, part, replace)


def test_dotdotdots_no_dots():
    whole = "line1\nline2\n"
    part = "line1\n"
    replace = "replaced\n"
    result = try_dotdotdots(whole, part, replace)
    assert result is None  # No ... means nothing to do


def test_dotdotdots_ambiguous():
    whole = "dup\nline2\ndup\n"
    part = "dup\n...\n"
    replace = "dup\n...\n"
    with pytest.raises(ValueError):
        try_dotdotdots(whole, part, replace)


# ---- Tests for replace_closest_edit_distance() ----

def test_fuzzy_match_high_similarity():
    whole = ["def foo(x):\n", "    return x + 1\n", "\n"]
    part = "def foo(x):\n    return x + 2\n"
    replace_lines = ["def foo(x):\n", "    return x * 2\n"]
    result = replace_closest_edit_distance(whole, part, ["def foo(x):\n", "    return x + 2\n"], replace_lines)
    assert result is not None
    assert "x * 2" in result


def test_fuzzy_match_low_similarity():
    whole = ["def foo(x):\n", "    return x + 1\n"]
    part = "completely different content that does not match at all"
    replace_lines = ["new content\n"]
    result = replace_closest_edit_distance(whole, part, ["completely different content that does not match at all\n"], replace_lines)
    assert result is None  # Below similarity threshold


# ---- Tests for replace_most_similar_chunk() ----

def test_most_similar_exact():
    whole = "line1\nline2\nline3\n"
    part = "line2\n"
    replace = "LINE2\n"
    result = replace_most_similar_chunk(whole, part, replace)
    assert result == "line1\nLINE2\nline3\n"


def test_most_similar_whitespace_flex():
    whole = "def foo():\n    x = 1\n    return x\n"
    part = "x = 1\n"  # missing indent
    replace = "y = 2\n"
    result = replace_most_similar_chunk(whole, part, replace)
    assert result is not None
    assert "y = 2" in result


def test_most_similar_skip_blank():
    whole = "header\n\nbody\n"
    part = "\nbody\n"
    replace = "\nBODY\n"
    result = replace_most_similar_chunk(whole, part, replace)
    assert result == "header\n\nBODY\n"


def test_most_similar_no_match():
    whole = "aaaaaaaaaa\nbbbbbbbbbb\n"
    part = "zzzzzzzzzz\n"
    replace = "yyyyyyyyyy\n"
    result = replace_most_similar_chunk(whole, part, replace)
    assert result is None


# ---- Tests for strip_filename() ----

def test_strip_filename_plain():
    fence = ("```", "```")
    assert strip_filename("src/main.py", fence) == "src/main.py"


def test_strip_filename_with_fence():
    fence = ("```", "```")
    result = strip_filename("```src/main.py", fence)
    assert result == "src/main.py"


def test_strip_filename_with_markdown():
    fence = ("```", "```")
    assert strip_filename("# filename.py", fence) == "filename.py"
    assert strip_filename("*filename.py*", fence) == "filename.py"
    assert strip_filename("`filename.py`", fence) == "filename.py"


def test_strip_filename_ellipsis():
    fence = ("```", "```")
    assert strip_filename("...", fence) is None


# ---- Tests for strip_quoted_wrapping() ----

def test_strip_wrapping_no_fence():
    fence = ("```", "```")
    result = strip_quoted_wrapping("plain content\n", None, fence)
    assert result == "plain content\n"


def test_strip_wrapping_with_fence():
    fence = ("```", "```")
    result = strip_quoted_wrapping("```\ncode\n```\n", None, fence)
    assert result == "code\n"


def test_strip_wrapping_with_filename():
    fence = ("```", "```")
    result = strip_quoted_wrapping("main.py\ncode\n", "main.py", fence)
    assert result == "code\n"


# ---- Tests for find_similar_lines() ----

def test_find_similar_lines_perfect():
    search = "def foo():\n    pass\n"
    content = "def foo():\n    pass\n\n"
    result = find_similar_lines(search, content)
    assert "def foo()" in result


def test_find_similar_lines_close():
    search = "def foo():\n    return 1\n"
    content = "def foo():\n    pass\n\n"
    result = find_similar_lines(search, content)
    assert "def foo()" in result


def test_find_similar_lines_no_match():
    search = "zzzzzzzzzzzzzzzzzzzzz\n"
    content = "def foo():\n    pass\n"
    result = find_similar_lines(search, content)
    assert result == ""


# ---- Tests for do_replace() ----

def test_do_replace_new_file():
    with tempfile.TemporaryDirectory() as tmpdir:
        fname = Path(tmpdir) / "new_file.py"
        # File doesn't exist, before_text is empty => create and append
        result = do_replace(str(fname), None, "", "print('hello')\n")
        assert result == "print('hello')\n"


def test_do_replace_existing_file():
    with tempfile.TemporaryDirectory() as tmpdir:
        fname = Path(tmpdir) / "test.py"
        fname.write_text("def foo():\n    pass\n")
        result = do_replace(
            str(fname),
            "def foo():\n    pass\n",
            "    pass\n",
            "    return 42\n",
        )
        assert result is not None
        assert "return 42" in result


def test_do_replace_no_match():
    with tempfile.TemporaryDirectory() as tmpdir:
        fname = Path(tmpdir) / "test.py"
        fname.write_text("def foo():\n    pass\n")
        result = do_replace(
            str(fname),
            "def foo():\n    pass\n",
            "zzzzzzzzzz\n",
            "yyyyyyyyyy\n",
        )
        assert result is None


# ---- Tests for find_original_update_blocks() ----

def test_parse_simple_editblock():
    content = """test.py
<<<<<<< SEARCH
old line
=======
new line
>>>>>>> REPLACE
"""
    edits = list(find_original_update_blocks(content, valid_fnames=["test.py"]))
    assert len(edits) == 1
    assert edits[0][0] == "test.py"
    assert edits[0][1].strip() == "old line"
    assert edits[0][2].strip() == "new line"


def test_parse_editblock_with_fence():
    content = """test.py
```python
<<<<<<< SEARCH
old
=======
new
>>>>>>> REPLACE
```
"""
    edits = list(find_original_update_blocks(content, valid_fnames=["test.py"]))
    assert len(edits) == 1


def test_parse_shell_command():
    content = """```bash
echo hello
```
"""
    edits = list(find_original_update_blocks(content))
    assert len(edits) == 1
    assert edits[0][0] is None  # shell command
    assert "echo hello" in edits[0][1]


def test_parse_multiple_edits():
    content = """file1.py
<<<<<<< SEARCH
a
=======
b
>>>>>>> REPLACE

file2.py
<<<<<<< SEARCH
x
=======
y
>>>>>>> REPLACE
"""
    edits = list(find_original_update_blocks(
        content, valid_fnames=["file1.py", "file2.py"]
    ))
    assert len(edits) == 2


def test_parse_missing_filename_error():
    content = """<<<<<<< SEARCH
something
=======
else
>>>>>>> REPLACE
"""
    with pytest.raises(ValueError):
        list(find_original_update_blocks(content, valid_fnames=[]))
