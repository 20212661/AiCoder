from __future__ import annotations

from pydantic import BaseModel, Field


class ReadFileArgs(BaseModel):
    path: str = Field(description="File path to read")


class WriteFileArgs(BaseModel):
    path: str = Field(description="File path to write")
    content: str = Field(description="New file content")


class EditFileArgs(BaseModel):
    path: str = Field(description="File path to edit")
    search: str = Field(description="Text to search for")
    replace: str = Field(description="Replacement text")


class SearchFilesArgs(BaseModel):
    path: str = Field(default=".", description="Directory to search")
    regex: str = Field(description="Search regex pattern")
    file_pattern: str = Field(default="", description="Optional glob pattern to filter files")


class RunShellArgs(BaseModel):
    command: str = Field(description="Shell command to run")
    timeout: int | None = Field(default=None, description="Optional timeout in seconds")


class AICoderResponse(BaseModel):
    summary: str = Field(description="Short final response")
    changed_files: list[str] = Field(default_factory=list)
    commands_run: list[str] = Field(default_factory=list)
    needs_approval: bool = False
    error: str | None = None
