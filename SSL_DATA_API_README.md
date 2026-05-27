# 任务池（Task Pool）对外接口说明

## 基础信息

| 项目 | 值 |
|------|-----|
| 服务名称 | 任务池自动化重构版（task_pool） |
| 服务地址 | `http://<host>:28801` |
| 数据格式 | JSON |

---

## 目录

1. [健康检查](#1-健康检查)
2. [资源 CRUD](#2-资源-crud)
3. [资源检索](#3-资源检索)
4. [生命周期管理](#4-生命周期管理)
5. [数据接入管理](#5-数据接入管理)

---

## 1. 健康检查

### GET /health

**接口说明：** 检测服务运行状态，返回 Zenoh 连接状态、Redis 连接状态、SQLite 可用性。

**响应体（HealthView）：**

| 字段 | 类型 | 说明 |
|------|------|------|
| status | str | 服务状态，`"ok"` 或 `"bad"` |
| ok | bool | 是否全部正常 |
| service | str | 服务名称，固定为 `"task_pool"` |
| zenoh_connected | bool | Zenoh 消息中间件是否已连接 |
| redis_ready | bool | Redis 缓存是否就绪 |
| sqlite_ready | bool | SQLite 数据库是否就绪（固定 `true`）|
| checked_at | datetime | 检查时间戳 |

---

## 2. 资源 CRUD

**基础路径：** `/api/v1/task_pool/resources`

### 2.1 GET /api/v1/task_pool/resources/id_list

**接口说明：** 获取所有资源的 ID 列表。

**查询参数：**

| 参数 | 类型 | 默认值 | 说明 |
|------|------|--------|------|
| include_deleted | bool | false | 是否包含已删除的资源 |
| limit | int | 100 | 返回数量上限 |
| send_notification | bool | false | 是否发送测试通知 |

**响应体：** `list[str]` — 资源 ID 字符串列表。

---

### 2.2 GET /api/v1/task_pool/resources

**接口说明：** 分页获取资源列表。

**查询参数：**

| 参数 | 类型 | 默认值 | 说明 |
|------|------|--------|------|
| include_deleted | bool | false | 是否包含已删除的资源 |
| limit | int | 100 | 返回数量上限 |
| send_notification | bool | false | 是否发送测试通知 |

**响应体（TaskListResponse）：**

| 字段 | 类型 | 说明 |
|------|------|------|
| items | list[TaskView] | 资源对象列表（详见下方 TaskView 说明）|
| total | int | 资源总数 |

---

### 2.3 GET /api/v1/task_pool/resources/{resource_id}

**接口说明：** 根据资源 ID 获取单个资源的详细信息。

**路径参数：**

| 参数 | 类型 | 说明 |
|------|------|------|
| resource_id | str | 资源唯一标识，例如 `tactic:tactic-1001` |

**查询参数：**

| 参数 | 类型 | 默认值 | 说明 |
|------|------|--------|------|
| send_notification | bool | false | 是否发送测试通知 |

**响应体：** `TaskView` — 根据资源的 `task_type` 返回对应的子类型对象。

---

### 2.4 GET /api/v1/task_pool/resources/by_type/{task_type}

**接口说明：** 根据任务类型获取所有该类型的资源列表。

**路径参数：**

| 参数 | 类型 | 说明 |
|------|------|------|
| task_type | str | 任务类型，如 `VEHICLE` / `COMMAND` / `MISSION` / `PLAN` / `TACTIC` / `TEAM` / `STAGE` / `ACTION` / `CAR_ACTIONS` / `KILL_CHAIN` |

**查询参数：**

| 参数 | 类型 | 默认值 | 说明 |
|------|------|--------|------|
| send_notification | bool | false | 是否发送测试通知 |

**响应体：** `list[TaskView]` — 该类型的资源对象列表。

---

### 2.5 PATCH /api/v1/task_pool/resources/{resource_id}

**接口说明：** 更新指定资源的字段（部分更新）。

**路径参数：**

| 参数 | 类型 | 说明 |
|------|------|------|
| resource_id | str | 资源唯一标识 |

**请求体（TaskPatchRequest）：**

| 字段 | 类型 | 必填 | 说明 |
|------|------|------|------|
| title | str \| None | 否 | 资源标题（1~200 字符）|
| description | str \| None | 否 | 资源描述（最长 500 字符）|
| attributes | dict[str, Any] \| None | 否 | 自定义属性字典 |
| search_text | str \| None | 否 | 搜索文本 |
| state | str \| None | 否 | 资源状态字符串 |
| payload | dict[str, Any] \| None | 否 | 原始负载数据 |

**查询参数：**

| 参数 | 类型 | 默认值 | 说明 |
|------|------|--------|------|
| send_notification | bool | false | 是否发送测试通知 |

**响应体：** `TaskView` — 更新后的资源完整对象。

---

### 2.6 POST /api/v1/task_pool/resources/query

**接口说明：** 根据查询条件筛选资源。

**请求体（TaskQueryRequest）：**

| 字段 | 类型 | 默认值 | 说明 |
|------|------|--------|------|
| task_type | str \| None | null | 按任务类型筛选 |
| state | str \| None | null | 按状态筛选 |
| relation_target | str \| None | null | 按关联目标筛选 |
| source_topic | str \| None | null | 按来源主题筛选 |
| keyword | str \| None | null | 按关键词模糊搜索 |
| parent_resource_id | str \| None | null | 按父资源 ID 筛选 |
| include_deleted | bool | false | 是否包含已删除的资源 |
| mission_ids | list[str] \| None | null | 按任务 ID 列表筛选 |
| limit | int | 50 | 返回数量上限（1~500）|

**查询参数：**

| 参数 | 类型 | 默认值 | 说明 |
|------|------|--------|------|
| send_notification | bool | false | 是否发送测试通知 |

**响应体：** `list[TaskView]` — 符合条件的资源对象列表。

---

### 2.7 POST /api/v1/task_pool/resources/search

**接口说明：** 全文搜索资源（使用检索服务）。

**请求体（TaskSearchRequest）：**

| 字段 | 类型 | 必填 | 说明 |
|------|------|------|------|
| query | str | 是 | 搜索关键词（1~200 字符）|
| limit | int | 否 | 返回数量上限（1~100，默认 10）|

**查询参数：**

| 参数 | 类型 | 默认值 | 说明 |
|------|------|--------|------|
| send_notification | bool | false | 是否发送测试通知 |

**响应体（TaskListResponse）：**

| 字段 | 类型 | 说明 |
|------|------|------|
| items | list[TaskView] | 匹配的资源对象列表 |
| total | int | 匹配总数 |

---

## 3. 资源检索

**基础路径：** `/api/v1/task_pool/resources`

### 3.1 POST /api/v1/task_pool/resources/query

**接口说明：** 与 [2.6 POST /query](#26-post-apiv1task_poolresourcesquery) 功能相同，返回格式为带总数的 `TaskListResponse`。

**请求体（TaskQueryRequest）：** 同上。

**响应体（TaskListResponse）：** 同上。

---

### 3.2 POST /api/v1/task_pool/resources/search

**接口说明：** 与 [2.7 POST /search](#27-post-apiv1task_poolresourcessearch) 功能相同。

**请求体（TaskSearchRequest）：** 同上。

**响应体（TaskListResponse）：** 同上。

---

## 4. 生命周期管理

**基础路径：** `/api/v1/task_pool/resources`

### 4.1 POST /api/v1/task_pool/resources/{resource_id}/lifecycle

**接口说明：** 更新资源的状态（生命周期状态转换）。

**路径参数：**

| 参数 | 类型 | 说明 |
|------|------|------|
| resource_id | str | 资源唯一标识 |

**请求体（TaskLifecycleUpdateRequest）：**

| 字段 | 类型 | 默认值 | 说明 |
|------|------|--------|------|
| state | str | `"INIT"` | 目标状态，参见 `BaseState` 枚举 |
| reason | str | `""` | 状态变更原因（最长 500 字符）|

**BaseState 枚举值：**
- `INIT` — 初始状态
- `READY` — 就绪
- `WAITING` — 等待中
- `ACTIVE` — 活跃中
- `INTERUPT` — 中断
- `DONE` — 完成
- `DELETED` — 已删除

**响应体：** `TaskView` — 更新后的资源完整对象。

---

## 5. 数据接入管理

**基础路径：** `/api/v1/task_pool/ingestion`

### 5.1 GET /api/v1/task_pool/ingestion/runtime

**接口说明：** 获取数据接入服务的运行时状态。

**响应体（RuntimeStatusView）：**

| 字段 | 类型 | 说明 |
|------|------|------|
| zenoh_enabled | bool | Zenoh 是否启用 |
| zenoh_connected | bool | Zenoh 是否已连接 |
| worker_running | bool | 异步工作线程是否运行中 |
| commit_worker_running | bool | 提交工作线程是否运行中 |
| default_topics | list[str] | 默认订阅的主题列表 |
| subscribed_topics | list[str] | 当前已订阅的主题列表 |
| pending_count | int | 待提交的缓存键数量 |
| pending_cache_keys | list[str] | 待提交的缓存键列表 |
| received_messages | int | 已接收的消息总数 |
| normalized_messages | int | 已规范化的消息总数 |
| failed_messages | int | 处理失败的消息总数 |
| last_message_at | datetime \| None | 最后一条消息接收时间 |
| last_commit_at | datetime \| None | 最后一次提交时间 |
| last_commit_summary | dict[str, Any] | 最后一次提交的摘要信息 |
| last_error | str | 最近一次错误信息 |

---

### 5.2 GET /api/v1/task_pool/ingestion/cache

**接口说明：** 获取缓存摘要信息。

**响应体（TaskCacheSummaryView）：**

| 字段 | 类型 | 说明 |
|------|------|------|
| total_cache_keys | int | 缓存键总数 |
| pending_cache_keys | list[str] | 待提交的缓存键列表 |
| items | list[TaskCacheSummaryItem] | 每个缓存键的详细信息 |

**TaskCacheSummaryItem：**

| 字段 | 类型 | 说明 |
|------|------|------|
| cache_key | str | 缓存键 |
| aggregate_present | bool | 聚合数据是否存在 |
| typed_tasks | int | 类型化任务数量 |
| pending | bool | 是否待提交 |

---

### 5.3 POST /api/v1/task_pool/ingestion/subscriptions

**接口说明：** 添加新的 Zenoh 主题订阅。

**请求体（TopicSubscriptionRequest）：**

| 字段 | 类型 | 默认值 | 说明 |
|------|------|--------|------|
| topics | list[str] | `[]` | 要订阅的主题列表，支持通配符，如 `c2/task/status/**` |
| ignore_errors | bool | true | 是否忽略错误 |

**响应体（StatusResponse）：**

| 字段 | 类型 | 说明 |
|------|------|------|
| ok | bool | 操作是否成功 |
| message | str | 结果描述信息 |

---

### 5.4 POST /api/v1/task_pool/ingestion/commit

**接口说明：** 手动触发指定缓存键的提交（将 Redis 缓存中的数据持久化到 SQLite）。

**请求体（ManualCommitRequest）：**

| 字段 | 类型 | 默认值 | 说明 |
|------|------|--------|------|
| cache_keys | list[str] | `[]` | 要提交的缓存键列表（空列表表示提交全部待处理键）|
| ignore_errors | bool | true | 是否忽略单个键提交失败 |

**响应体（ManualCommitResult）：**

| 字段 | 类型 | 说明 |
|------|------|------|
| requested_cache_keys | list[str] | 请求提交的缓存键列表 |
| committed_cache_keys | list[str] | 实际成功提交的缓存键列表 |
| generated_resources | int | 生成的资源数量 |
| upserted_resources | int | 更新/插入的资源数量 |
| failures | list[str] | 提交失败的缓存键列表 |
| committed_at | datetime | 提交时间戳 |
| summary | dict[str, Any] | 提交摘要信息 |

---

### 5.5 POST /api/v1/task_pool/ingestion/replay

**接口说明：** 重新回放处理指定的缓存键（重新执行规范化流程）。

**请求体（ReplayRequest）：**

| 字段 | 类型 | 默认值 | 说明 |
|------|------|--------|------|
| cache_keys | list[str] | `[]` | 要回放的缓存键列表（空列表表示全部待处理键）|
| commit_immediately | bool | true | 回放后是否立即提交 |
| ignore_errors | bool | true | 是否忽略错误 |

**响应体（ManualCommitResult）：** 同上。

---

### 5.6 POST /api/v1/task_pool/ingestion/import

**接口说明：** 批量导入资源数据。支持同时导入多种类型的资源，系统会自动进行规范化处理。

**请求体（ImportRequest）：**

| 字段 | 类型 | 默认值 | 说明 |
|------|------|--------|------|
| resources | list[dict[str, Any]] | `[]` | 要导入的资源数据列表，每个元素为包含完整字段的 JSON 对象 |
| return_data_type | str | `"none"` | 返回结果的数据类型控制：`"none"` 不返回 | `"typed"` 返回类型化对象 | `"raw"` 返回原始数据 |
| ignore_errors | bool | true | 是否忽略单个资源的导入错误 |

**查询参数：**

| 参数 | 类型 | 默认值 | 说明 |
|------|------|--------|------|
| send_notification | bool | false | 是否发送测试通知 |

**响应体（ImportResult）：**

| 字段 | 类型 | 说明 |
|------|------|------|
| requested_resources | int | 请求导入的资源总数 |
| normalized_resources | int | 成功规范化的资源数 |
| upserted_resources | int | 成功更新/插入的资源数 |
| failures | list[str] | 导入失败的资源错误信息列表 |
| imported_at | datetime | 导入时间戳 |
| summary | dict[str, Any] | 导入摘要信息 |
| results | list[Any] | 导入结果详情（取决于 `return_data_type`）|

---

### 5.7 POST /api/v1/task_pool/ingestion/execution-feedback

**接口说明：** 提交资源执行的反馈信息（如执行状态、进度等）。

**请求体（ExecutionFeedbackRequest）：**

| 字段 | 类型 | 必填 | 说明 |
|------|------|------|------|
| resource_id | str | 是 | 反馈对应的资源 ID |
| execution_status | str | 是 | 执行状态描述（1~100 字符）|
| progress | float \| None | 否 | 执行进度（0.0 ~ 1.0）|
| message | str | 否 | 反馈消息（最长 500 字符）|
| feedback_payload | dict[str, Any] | 否 | 额外的反馈数据 |

**响应体：** `TaskView` — 更新后的资源完整对象。

---

## 核心数据结构说明

### TaskView（资源视图联合类型）

`TaskView` 是一个类型别名，根据资源的 `task_type` 字段决定具体的子类型：

| task_type 值 | 对应的子类型 | 业务含义 |
|--------------|-------------|----------|
| `VEHICLE` | Vehicle | 车辆/平台 |
| `COMMAND` | Command | 指挥命令 |
| `MISSION` | Mission | 任务 |
| `PLAN` | Plan | 行动方案 |
| `TACTIC` | Tactic | 战术战法 |
| `TEAM` | Team | 编组 |
| `STAGE` | Stage | 阶段 |
| `ACTION` | Action | 单车单个行动（元任务）|
| `CAR_ACTIONS` | CarActions | 单车行动序列 |
| `KILL_CHAIN` | KillChain | 杀伤链 |

---

### 基类：TaskEnvelope

所有资源类型的基类，包含通用字段：

| 字段 | 类型 | 说明 |
|------|------|------|
| resource_id | str | 资源唯一标识 |
| task_type | str | 任务类型 |
| attributes | dict[str, Any] | 自定义属性字典 |
| search_text | str | 全文搜索文本 |
| source | dict[str, Any] | 来源信息（如 `source_topic`, `source_type`, `last_update_at`）|
| raw_payload | dict[str, Any] \| None | 原始完整负载数据 |
| relations | list[TaskRelation] | 关联关系列表 |
| created_at | datetime | 创建时间 |
| updated_at | datetime | 更新时间 |

#### TaskRelation

| 字段 | 类型 | 说明 |
|------|------|------|
| type | str | 关联类型（如 `COORDINATE`, `SUPPORT`）|
| target | str | 关联目标 ID |
| metadata | dict[str, Any] | 关联元数据 |

#### Source 字段说明

`source` 字段为一个字典，通常包含：

| 键 | 类型 | 说明 |
|------|------|------|
| source_data_module | str | 数据来源模块（如 `"task_pool"`）|
| source_topic | str | 来源主题（如 `"api/import"`）|
| source_type | str | 来源类型（如 `"api"`）|
| last_update_at | str | 最后更新时间 |

---

### 基类：TaskAggregateBase

继承自 `TaskEnvelope`，用于聚合型资源：

| 字段 | 类型 | 说明 |
|------|------|------|
| connections | list[Connection] | 连接关系列表 |
| dependencies | list[Dependency] | 依赖关系列表 |

#### Connection

| 字段 | 类型 | 说明 |
|------|------|------|
| connection_type | ConnectionType | 连接类型（枚举）|
| connection_data | list[str] | 连接数据 |

#### Dependency

| 字段 | 类型 | 说明 |
|------|------|------|
| dependency_type | ConnectionType | 依赖类型（枚举）|
| dependency_data | list[str] | 依赖数据 |

**ConnectionType 枚举值：** `COMMAND` / `MISSION` / `PLAN` / `ACTION` / `STAGE` / `TEAM` / `TARGET` / `INSTANT_PLAN`

---

### Vehicle

继承自 `TaskAggregateBase`，`task_type = "VEHICLE"`

| 字段 | 类型 | 说明 |
|------|------|------|
| title | str | 标题 |
| vehicle_id | str | 车辆 ID |
| vmf | str | VMF（车辆型号/标识）|
| mission_id | str | 所属任务 ID |

---

### Command

继承自 `TaskAggregateBase`，`task_type = "COMMAND"`

| 字段 | 类型 | 说明 |
|------|------|------|
| title | str | 命令标题 |
| command_id | str | 命令 ID |
| description | str | 命令描述（默认 `""`）|
| state | BaseState | 状态（默认 `"INIT"`）|

---

### Mission

继承自 `TaskAggregateBase`，`task_type = "MISSION"`

| 字段 | 类型 | 说明 |
|------|------|------|
| title | str | 任务标题 |
| mission_id | str | 任务 ID |
| mission_seq | int | 任务序号（默认 0）|
| command_id | str \| None | 关联命令 ID |
| description | str | 任务描述（默认 `""`）|
| target | str | 目标描述（默认 `""`）|
| duration | int | 任务时长（默认 0）|
| state | BaseState | 状态（默认 `"INIT"`）|

---

### Plan

继承自 `TaskAggregateBase`，`task_type = "PLAN"`

| 字段 | 类型 | 说明 |
|------|------|------|
| title | str | 方案标题 |
| plan_id | str | 方案 ID |
| plan_seq | int | 方案序号（默认 0）|
| mission_ids | list[str] | 关联任务 ID 列表（默认 `[]`）|
| description | str | 方案描述（默认 `""`）|
| teams | list[Team] | 编组列表（默认 `[]`）|
| targets | list[Target_abstract] | 目标列表（默认 `[]`）|
| stages | list[Stage] | 阶段列表（默认 `[]`）|
| tactic | Tactic \| None | 采用的战术战法（可选）|
| state | PlanState | 方案状态（默认 `"INIT"`）|

**PlanState 枚举值：** `INIT` / `READY` / `WAITING` / `ACTIVE` / `INTERUPT` / `DONE` / `DELETED` / `REVIEW` / `DRAFT`

#### Target_abstract

| 字段 | 类型 | 说明 |
|------|------|------|
| target_id | str | 目标 ID |
| target_type | str | 目标类型（默认 `""`）|
| target_name | str \| None | 目标名称（可选）|
| description | str | 目标描述（默认 `""`）|

---

### Tactic

继承自 `TaskEnvelope`，`task_type = "TACTIC"`

| 字段 | 类型 | 说明 |
|------|------|------|
| tactic_id | str | 战术战法 ID |
| title | str | 战术战法标题 |
| main_tactic | str | 主要战术描述（默认 `""`）|
| sub_tactics | list[str] | 子战术列表（默认 `[]`）|
| teams | list[dict[str, Any]] | 编组配置列表（默认 `[]`）|
| suggest_stage | str | 建议的阶段性描述 |
| required_resources | list[str] | 所需资源列表（默认 `[]`）|
| plan_id | str \| None | 所属方案 ID（可选）|
| plan_resource_id | str \| None | 所属方案资源 ID（可选）|

---

### Team

继承自 `TaskEnvelope`，`task_type = "TEAM"`

| 字段 | 类型 | 说明 |
|------|------|------|
| name | str | 编组名称 |
| team_id | str | 编组 ID |
| plan_id | str \| None | 所属方案 ID（可选）|
| description | str | 编组描述（默认 `""`）|
| equipment | list[str] | 装备列表（默认 `[]`）|
| state | BaseState | 状态（默认 `"INIT"`）|

---

### Stage

继承自 `TaskEnvelope`，`task_type = "STAGE"`

| 字段 | 类型 | 说明 |
|------|------|------|
| title | str | 阶段标题 |
| stage_id | str | 阶段 ID |
| plan_id | str | 所属方案 ID |
| plan_resource_id | str | 所属方案资源 ID |
| stage_seq | int | 阶段序号（默认 0）|
| description | str | 阶段描述（默认 `""`）|
| team_actions | list[TeamStageActions] | 各编组的行动序列 |
| target_ids | list[str] | 目标 ID 列表（默认 `[]`）|
| team_ids | list[str] | 编组 ID 列表（默认 `[]`）|
| state | BaseState | 状态（默认 `"INIT"`）|

#### TeamStageActions

| 字段 | 类型 | 说明 |
|------|------|------|
| team_id | str | 编组 ID |
| target_ids | list[str] | 目标 ID 列表 |
| equipment_ids | list[str] | 装备 ID 列表 |
| team_actions | list[CarActions] | 单车行动序列列表 |

---

### Action

继承自 `TaskEnvelope`，`task_type = "ACTION"`

| 字段 | 类型 | 说明 |
|------|------|------|
| action_id | str | 行动 ID |
| name | str | 行动名称 |
| vid | str | 车辆标识 |
| action_seq | int | 行动序号（默认 0）|
| equipment_id | str \| None | 装备 ID（可选）|
| param | dict[str, Any] | 行动参数 |
| dependencies | list[str] | 依赖的行动 ID 列表（默认 `[]`）|
| time_attributes | action_time_attributes | 时间属性（计划和实际起止时间）|
| state | STAGE_CA_ActionState | 行动状态（默认 `"SCHEDULED"`）|
| car_actions_id | str | 所属行动序列 ID |
| car_action_resource_id | str \| None | 所属行动序列资源 ID |

#### action_time_attributes

| 字段 | 类型 | 说明 |
|------|------|------|
| schedule_start_time | timedelta \| None | 计划开始时间（相对偏移）|
| schedule_duration | timedelta \| None | 计划持续时长 |
| actual_start_time | timedelta \| None | 实际开始时间（相对偏移）|
| actual_duration | timedelta \| None | 实际持续时长 |

**STAGE_CA_ActionState 枚举值：** `SCHEDULED` / `ACTIVE` / `DONE` / `PAUSED` / `DELETED`

---

### CarActions

继承自 `TaskEnvelope`，`task_type = "CAR_ACTIONS"`

| 字段 | 类型 | 说明 |
|------|------|------|
| car_actions_id | str | 行动序列 ID |
| vid | str | 车辆标识 |
| equipment_id | str \| None | 装备 ID（可选）|
| plan_id | str \| None | 所属方案 ID（可选）|
| stage_id | str \| None | 所属阶段 ID（可选）|
| stage_resource_id | str \| None | 所属阶段资源 ID（可选）|
| team_id | str \| None | 所属编组 ID（可选）|
| action_ids | list[str] | 行动 ID 列表（默认 `[]`）|
| actions | list[Action] | 行动对象列表（默认 `[]`）|
| state | STAGE_CA_ActionState | 状态（默认 `"SCHEDULED"`）|

---

### KillChain

继承自 `TaskAggregateBase`，`task_type = "KILL_CHAIN"`

| 字段 | 类型 | 说明 |
|------|------|------|
| title | str | 杀伤链标题 |
| kill_chain_id | str | 杀伤链 ID |
| description | str | 描述（默认 `""`）|
| raw_entries | list[KillChainEntry] | 原始条目列表 |
| assigned_entries | list[KillChainEntry] | 已分配的条目列表 |
| resource_ids | list[str] | 资源 ID 列表 |
| target_ids | list[str] | 目标 ID 列表 |
| mapped_plan_ids | list[str] | 映射的方案 ID 列表 |
| mapping_summary | dict[str, Any] | 映射总结 |
| state | BaseState | 状态 |

#### KillChainEntry

| 字段 | 类型 | 说明 |
|------|------|------|
| entry_id | str | 条目 ID |
| phase | `"RAW"` \| `"ASSIGNED"` | 阶段（原始 / 已分配）|
| entry_seq | int | 序号 |
| target_ids | list[str] | 目标 ID 列表 |
| operation | str | 作战行动描述 |
| executor_options | list[KillChainExecutorOption] | 执行器选项列表 |
| selected_executor | str \| None | 选中的执行器 ID |
| locked | bool | 是否锁定 |
| is_valid | bool | 是否有效（默认 true）|
| notes | str | 备注 |

#### KillChainExecutorOption

| 字段 | 类型 | 说明 |
|------|------|------|
| executor_id | str | 执行器 ID |
| allocation_count | int | 分配数量（默认 0）|
| locked | bool | 是否锁定（默认 false）|
| note | str | 备注（默认 `""`）|

---

### 枚举值汇总

| 枚举 | 值 |
|------|-----|
| BaseState | `INIT` / `READY` / `WAITING` / `ACTIVE` / `INTERUPT` / `DONE` / `DELETED` |
| PlanState | `INIT` / `READY` / `WAITING` / `ACTIVE` / `INTERUPT` / `DONE` / `DELETED` / `REVIEW` / `DRAFT` |
| TaskType | `VEHICLE` / `COMMAND` / `MISSION` / `PLAN` / `CAR_ACTIONS` / `ACTION` / `STAGE` / `TEAM` / `TARGET` / `TACTIC` / `KILL_CHAIN` |
| ConnectionType | `COMMAND` / `MISSION` / `PLAN` / `ACTION` / `STAGE` / `TEAM` / `TARGET` / `INSTANT_PLAN` |
| STAGE_CA_ActionState | `SCHEDULED` / `ACTIVE` / `DONE` / `PAUSED` / `DELETED` |
