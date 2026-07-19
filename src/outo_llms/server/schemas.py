"""Pydantic v2 request/response schemas for the HTTP API."""

from __future__ import annotations

from pydantic import BaseModel, Field


class SignupRequest(BaseModel):
    username: str = Field(min_length=1, max_length=64)


class SignupResponse(BaseModel):
    user_id: int
    username: str
    workspace: str
    api_key: str


class WorkspaceCreate(BaseModel):
    name: str = Field(min_length=1, max_length=64)


class WorkspaceOut(BaseModel):
    id: int
    name: str
    created_at: str


class KeyCreate(BaseModel):
    label: str = ""


class KeyOut(BaseModel):
    api_key: str
    label: str
    workspace: str


class KeyMeta(BaseModel):
    id: int
    label: str
    created_at: str
    revoked: bool


class ModelUsage(BaseModel):
    model: str
    requests: int
    prompt_tokens: int
    completion_tokens: int
    total_tokens: int


class UsageSummary(BaseModel):
    workspace: str
    total_requests: int
    total_tokens: int
    by_model: list[ModelUsage]


class ServerInfo(BaseModel):
    host: str
    port: int
    https: bool
    domain: str


class EngineStatus(BaseModel):
    engine: str
    installed: bool
    running: bool
    pid: int | None
    model: str | None
    port: int | None
    base_url: str | None


class Counts(BaseModel):
    users: int
    workspaces: int
    models: int


class StatusOut(BaseModel):
    version: str
    server: ServerInfo
    engine: EngineStatus
    counts: Counts
