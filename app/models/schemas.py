"""
Pydantic 模型定义
"""

from pydantic import BaseModel, Field
from typing import List, Optional, Dict, Any, Literal
from datetime import datetime


# ========== 通用基类 ==========

class Connection(BaseModel):
    connection_type: str
    connection_data: List[str] = []


class Dependency(BaseModel):
    dependency_type: str
    dependency_data: List[str] = []


class TaskRelation(BaseModel):
    type: str
    target: str
    metadata: Dict[str, Any] = {}


# ========== 杀伤链条目 ==========

class KillChainExecutorOption(BaseModel):
    executor_id: str
    allocation_count: int = 0
    locked: bool = False
    note: str = ""


class KillChainEntry(BaseModel):
    entry_id: str
    phase: Literal["RAW", "ASSIGNED"] = "RAW"
    entry_seq: int = 0
    target_ids: List[str] = []
    operation: str = ""
    executor_options: List[KillChainExecutorOption] = []
    selected_executor: Optional[str] = None
    locked: bool = False
    is_valid: bool = True
    notes: str = ""


# ========== 杀伤链 ==========

class KillChainCreate(BaseModel):
    title: str
    description: str = ""
    targets: List[Dict[str, str]] = []  # [{"target_id": "", "target_name": ""}]


class KillChainUpdate(BaseModel):
    title: Optional[str] = None
    description: Optional[str] = None
    raw_entries: Optional[List[KillChainEntry]] = None
    assigned_entries: Optional[List[KillChainEntry]] = None
    resource_ids: Optional[List[str]] = None
    target_ids: Optional[List[str]] = None
    mapped_plan_ids: Optional[List[str]] = None
    mapping_summary: Optional[Dict[str, Any]] = None
    network: Optional[Dict[str, Any]] = None
    state: Optional[str] = None


class KillChainEntryCreate(BaseModel):
    entry_seq: int
    target_ids: List[str]
    operation: str
    notes: str = ""


class KillChainEntryDelete(BaseModel):
    entry_id: str


class ResourceAllocate(BaseModel):
    selected_executor: str
    allocation_type: Literal["auto", "manual"] = "manual"
    reason: str = ""


class KillChainDispatchEntry(BaseModel):
    entry_id: str
    selected_executor: Optional[str] = None
    executor_assignments: List[Dict[str, Any]] = []


class KillChainDispatchRequest(BaseModel):
    entries: List[KillChainDispatchEntry] = []


class AutoAllocateRequest(BaseModel):
    operation: str
    target_ids: List[str]
    constraints: Dict[str, Any] = Field(default_factory=dict)


class GeneratePlanRequest(BaseModel):
    selected_entry_ids: List[str]
    plan_config: Dict[str, str] = Field(default_factory=dict)


class ResourceQuery(BaseModel):
    operation: Optional[str] = None
    target_ids: Optional[List[str]] = None
    keyword: Optional[str] = None
    limit: int = 20
    exclude_allocated_in_kill_chain: Optional[str] = None


# ========== 资源候选 ==========

class ResourceCandidate(BaseModel):
    executor_id: str
    resource_name: str
    resource_type: str
    allocation_count: int = 0
    locked: bool = False
    note: str = ""


# ========== Plan 方案 ==========

class Team(BaseModel):
    team_id: str
    name: str
    equipment: List[str] = []
    description: str = ""
    state: str = "READY"


class TargetAbstract(BaseModel):
    target_id: str
    target_type: str = ""
    target_name: str = ""
    description: str = ""


class Stage(BaseModel):
    stage_id: str
    title: str
    description: str = ""
    stage_seq: int = 0
    target_ids: List[str] = []
    team_ids: List[str] = []
    state: str = "SCHEDULED"


class PlanCreate(BaseModel):
    resource_id: str
    title: str
    description: str = ""
    teams: List[Team] = []
    targets: List[TargetAbstract] = []
    stages: List[Stage] = []
    state: str = "DRAFT_EDITING"


# ========== SSL 地图数据 ==========

class SSLMapObject(BaseModel):
    order: int
    object_id: str
    object_type: str
    name: str
    lon: float
    lat: float
    properties: Dict[str, Any] = {}


class SSLMapDataRequest(BaseModel):
    method: List[str] = []
    resource_list: List[List[str]] = []
    object_list: List[SSLMapObject] = []


# ========== SSE 事件 ==========

class SSEEvent(BaseModel):
    event: str
    data: Dict[str, Any]


# ========== 通用响应 ==========

class ApiResponse(BaseModel):
    code: int = 200
    message: str = "success"
    data: Optional[Any] = None
