"""Schemas for automations: Task, TaskRun, InterviewMessage + endpoints' request/response."""

from __future__ import annotations

from typing import Literal

from pydantic import Field

from app.schemas.base import APISchema

TaskSchedule = Literal["manual", "hourly", "daily", "weekly"]
TaskStatus = Literal["idle", "running", "succeeded", "failed", "cancelled"]


class InterviewMessage(APISchema):
    role: Literal["user", "assistant"]
    content: str
    options: list[str] | None = None


class TaskRun(APISchema):
    status: Literal["succeeded", "failed", "cancelled"]
    started_at: int  # unix ms
    ended_at: int  # unix ms
    duration_ms: int
    error: str | None = None


class AssistantStep(APISchema):
    kind: Literal["assistant"]
    text: str


class ToolStep(APISchema):
    kind: Literal["tool"]
    tool: str
    args: str
    result: str
    ok: bool


class TaskPayload(APISchema):
    id: str
    title: str | None = None
    prompt: str
    messages: list[InterviewMessage] = Field(default_factory=list)
    schedule: TaskSchedule = "manual"
    status: TaskStatus = "idle"
    output: str | None = None
    transcript: list[dict] = Field(default_factory=list)
    runs: list[TaskRun] = Field(default_factory=list)
    provider: str
    model: str
    error: str | None = None
    created_at: int  # unix ms
    updated_at: int


class CreateTaskRequest(APISchema):
    id: str
    prompt: str = ""
    schedule: TaskSchedule = "manual"
    provider: str
    model: str


class UpdateTaskRequest(APISchema):
    title: str | None = None
    prompt: str | None = None
    schedule: TaskSchedule | None = None
    status: TaskStatus | None = None
    output: str | None = None
    error: str | None = None
    provider: str | None = None
    model: str | None = None


class ChatTaskRequest(APISchema):
    task_id: str
    message: str


class ChatTaskResponse(APISchema):
    question: str | None = None
    options: list[str] | None = None
    finalized: bool | None = None
    skill: str | None = None
    title: str | None = None


class RunTaskRequest(APISchema):
    task_id: str
