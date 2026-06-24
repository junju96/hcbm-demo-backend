# applications0.2 API 接口说明

## 1. 文档范围

本文档基于以下目录中的当前代码生成：

- `resource_pool_refactor/api`
- `resource_pool_refactor/models/schemas.py`
- `situation_pool/api`
- `situation_pool/models/schemas.py`
- `task_pool/api`
- `task_pool/models/schemas.py`

说明：

- 本文档描述的是当前代码里**实际挂载到 FastAPI 应用上的接口**。
- 若某些 `routers/*.py` 文件存在但没有在 `api/router.py` 中 `include_router()`，则不作为当前对外接口的一部分。
- 三个服务都各自提供独立的 `GET /health` 健康检查接口。

---

## 2. 通用约定

### 2.1 返回时间字段

常见时间字段：

- `created_at`：资源创建时间
- `updated_at`：资源更新时间
- `checked_at`：健康检查时间
- `imported_at`：导入完成时间
- `committed_at`：提交完成时间

### 2.2 通用状态返回

`StatusResponse`

| 字段 | 类型 | 说明 |
| --- | --- | --- |
| `ok` | `bool` | 是否执行成功 |
| `message` | `str` | 结果说明 |

### 2.3 健康检查返回

`HealthView`

| 字段 | 类型 | 说明 |
| --- | --- | --- |
| `status` | `str` | 服务整体状态，常见值为 `ok` / `bad` |
| `ok` | `bool` | 健康结果 |
| `service` | `str` | 服务名称 |
| `zenoh_connected` | `bool` | Zenoh 是否连接成功 |
| `redis_ready` | `bool` | Redis 或降级缓存是否可用 |
| `sqlite_ready` | `bool` | SQLite 是否可用 |
| `checked_at` | `datetime` | 检查时间 |

---

## 3. 资源池 API

服务目录：

- `resource_pool_refactor`

资源接口前缀：

- `/api/v1/resource_pool/resources`
- `/api/v1/resource_pool/ingestion`
- `/health`

### 3.1 接口列表

| 方法 | 路径 | 说明 | 请求体 | 响应体 |
| --- | --- | --- | --- | --- |
| `GET` | `/health` | 资源池健康检查 | 无 | `HealthView` |
| `GET` | `/api/v1/resource_pool/resources` | 获取顶层资源列表 | 无 | `list[TopLevelResource]` |
| `GET` | `/api/v1/resource_pool/resources/all` | 获取所有顶层资源列表 | 无 | `list[TopLevelResource]` |
| `GET` | `/api/v1/resource_pool/resources/get_pick` | 快速获取资源轻量字段 | 无 | `list[dict[str, Any]]` |
| `GET` | `/api/v1/resource_pool/resources/{resource_id}` | 获取单个资源详情 | 无 | `TypedResource` |
| `GET` | `/api/v1/resource_pool/resources/getall/{resource_id}` | 获取资源原始聚合内容 | 无 | `str` |
| `POST` | `/api/v1/resource_pool/resources/query` | 条件查询资源 | `ResourceQueryRequest` | `list[TypedResource]` |
| `POST` | `/api/v1/resource_pool/resources/search` | 全文检索顶层资源 | `ResourceSearchRequest` | `list[TopLevelResource]` |
| `POST` | `/api/v1/resource_pool/resources/pick` | 按字段选择资源信息 | `list[str]` | `list[dict[str, Any]]` |
| `GET` | `/api/v1/resource_pool/ingestion/runtime` | 获取接入运行状态 | 无 | `RuntimeStatusView` |
| `GET` | `/api/v1/resource_pool/ingestion/cache` | 获取缓存摘要 | 无 | `CacheSummaryView` |
| `POST` | `/api/v1/resource_pool/ingestion/subscriptions` | 订阅主题 | `TopicSubscriptionRequest` | `StatusResponse` |
| `POST` | `/api/v1/resource_pool/ingestion/commit` | 手动提交缓存 | `ManualCommitRequest` | `ManualCommitResult` |
| `POST` | `/api/v1/resource_pool/ingestion/replay` | 回放待提交缓存 | `ReplayRequest` | `ManualCommitResult` |

### 3.2 资源查询接口说明

#### 3.2.1 `GET /api/v1/resource_pool/resources`

说明：查询资源池中的顶层资源，当前顶层资源类型主要为 `equipment`、`supply`。

查询参数：

| 参数 | 类型 | 默认值 | 说明 |
| --- | --- | --- | --- |
| `include_deleted` | `bool` | `false` | 是否包含已删除资源 |
| `limit` | `int` | `100` | 返回条数上限 |
| `is_online` | `bool` | `false` | 是否按在线状态过滤 |
| `send_notification` | `bool` | `false` | 是否触发通知 |

响应：`list[TopLevelResource]`

#### 3.2.2 `GET /api/v1/resource_pool/resources/all`

说明：查询全部顶层资源列表。

查询参数：

| 参数 | 类型 | 默认值 | 说明 |
| --- | --- | --- | --- |
| `include_deleted` | `bool` | `false` | 是否包含已删除资源 |
| `limit` | `int` | `100` | 返回条数上限 |
| `send_notification` | `bool` | `false` | 是否触发通知 |

响应：`list[TopLevelResource]`

#### 3.2.3 `GET /api/v1/resource_pool/resources/get_pick`

说明：返回固定字段 `resource_id`、`resource_name`、`model_type` 的轻量结果，用于下拉框、选择器等场景。

响应示例：

```json
[
  {
    "resource_id": "equipment:ZD04",
    "resource_name": "ZD04",
    "model_type": {
      "type": "vehicle",
      "description": "无人车"
    }
  }
]
```

#### 3.2.4 `GET /api/v1/resource_pool/resources/{resource_id}`

说明：按资源 ID 返回完整类型化资源。

路径参数：

| 参数 | 类型 | 说明 |
| --- | --- | --- |
| `resource_id` | `str` | 资源唯一标识 |

查询参数：

| 参数 | 类型 | 默认值 | 说明 |
| --- | --- | --- | --- |
| `send_notification` | `bool` | `false` | 是否触发通知 |

响应：`TypedResource`

#### 3.2.5 `GET /api/v1/resource_pool/resources/getall/{resource_id}`

说明：返回资源的原始聚合字符串结果。

路径参数：

| 参数 | 类型 | 说明 |
| --- | --- | --- |
| `resource_id` | `str` | 资源唯一标识 |

响应：`str`

#### 3.2.6 `POST /api/v1/resource_pool/resources/query`

说明：按结构化条件过滤类型化资源。

请求体：`ResourceQueryRequest`

| 字段 | 类型 | 说明 |
| --- | --- | --- |
| `entity_kind` | `str \| null` | 资源实体类型，如 `equipment`、`platform`、`payload` |
| `resource_type` | `str \| null` | 资源业务类型 |
| `resource_tag` | `str \| null` | 资源标签 |
| `lifecycle_status` | `LifecycleStatus \| null` | 生命周期状态 |
| `relation_target` | `str \| null` | 关联目标 ID |
| `source_topic` | `str \| null` | 来源主题 |
| `keyword` | `str \| null` | 关键字 |
| `include_deleted` | `bool` | 是否包含已删除资源 |
| `limit` | `int` | 最大返回数量，范围 `1~500` |

响应：`list[TypedResource]`

#### 3.2.7 `POST /api/v1/resource_pool/resources/search`

说明：按全文关键字检索顶层资源。

请求体：`ResourceSearchRequest`

| 字段 | 类型 | 说明 |
| --- | --- | --- |
| `query` | `str` | 检索关键字，长度 `1~200` |
| `limit` | `int` | 最大返回数量，范围 `1~100` |

响应：`list[TopLevelResource]`

#### 3.2.8 `POST /api/v1/resource_pool/resources/pick`

说明：传入字段名列表，返回匹配字段的轻量资源集合。

请求体：`list[str]`

示例：

```json
["resource_id", "resource_name", "model_type"]
```

查询参数：

| 参数 | 类型 | 默认值 | 说明 |
| --- | --- | --- | --- |
| `include_deleted` | `bool` | `false` | 是否包含已删除资源 |
| `limit` | `int` | `100` | 返回条数上限 |
| `send_notification` | `bool` | `false` | 是否触发通知 |

响应：`list[dict[str, Any]]`

### 3.3 接入管理接口说明

#### 3.3.1 `GET /api/v1/resource_pool/ingestion/runtime`

响应：`RuntimeStatusView`

| 字段 | 类型 | 说明 |
| --- | --- | --- |
| `zenoh_enabled` | `bool` | 是否启用 Zenoh |
| `zenoh_connected` | `bool` | Zenoh 是否已连接 |
| `worker_running` | `bool` | 消费线程是否运行 |
| `commit_worker_running` | `bool` | 提交线程是否运行 |
| `default_topics` | `list[str]` | 默认订阅主题 |
| `subscribed_topics` | `list[str]` | 当前订阅主题 |
| `pending_count` | `int` | 待提交缓存数量 |
| `pending_cache_keys` | `list[str]` | 待提交缓存键 |
| `received_messages` | `int` | 收到消息数 |
| `normalized_messages` | `int` | 规范化成功消息数 |
| `failed_messages` | `int` | 失败消息数 |
| `last_message_at` | `datetime \| null` | 最后消息时间 |
| `last_commit_at` | `datetime \| null` | 最后提交时间 |
| `last_commit_summary` | `dict[str, Any]` | 最后提交摘要 |
| `last_error` | `str` | 最近错误信息 |

#### 3.3.2 `GET /api/v1/resource_pool/ingestion/cache`

响应：`CacheSummaryView`

| 字段 | 类型 | 说明 |
| --- | --- | --- |
| `total_cache_keys` | `int` | 缓存键总数 |
| `pending_cache_keys` | `list[str]` | 待提交缓存键列表 |
| `items` | `list[CacheSummaryItem]` | 缓存项摘要 |

`CacheSummaryItem`

| 字段 | 类型 | 说明 |
| --- | --- | --- |
| `cache_key` | `str` | 缓存键 |
| `aggregate_present` | `bool` | 是否存在聚合缓存 |
| `typed_resources` | `int` | 类型化资源数量 |
| `pending` | `bool` | 是否待提交 |

#### 3.3.3 `POST /api/v1/resource_pool/ingestion/subscriptions`

请求体：`TopicSubscriptionRequest`

| 字段 | 类型 | 说明 |
| --- | --- | --- |
| `topics` | `list[str]` | 要订阅的主题列表 |
| `ignore_errors` | `bool` | 遇错是否继续 |

响应：`StatusResponse`

#### 3.3.4 `POST /api/v1/resource_pool/ingestion/commit`

请求体：`ManualCommitRequest`

| 字段 | 类型 | 说明 |
| --- | --- | --- |
| `cache_keys` | `list[str]` | 指定提交的缓存键列表，空列表表示由服务决定 |
| `ignore_errors` | `bool` | 遇错是否继续 |

响应：`ManualCommitResult`

#### 3.3.5 `POST /api/v1/resource_pool/ingestion/replay`

请求体：`ReplayRequest`

| 字段 | 类型 | 说明 |
| --- | --- | --- |
| `cache_keys` | `list[str]` | 指定重放的缓存键列表 |
| `commit_immediately` | `bool` | 重放后是否立即提交 |
| `ignore_errors` | `bool` | 遇错是否继续 |

响应：`ManualCommitResult`

### 3.4 资源模型定义

#### 3.4.1 通用基础模型 `BaseResource`

| 字段 | 类型 | 说明 |
| --- | --- | --- |
| `resource_id` | `str` | 资源唯一 ID |
| `resource_name` | `str` | 资源名称 |
| `resource_tag` | `str` | 资源标签 |
| `resource_type` | `str` | 资源类型 |
| `resource_level` | `int` | 资源层级 |
| `model_type` | `ModelType \| null` | 型号信息 |
| `created_at` | `datetime` | 创建时间 |
| `updated_at` | `datetime` | 更新时间 |
| `create_source` | `ResourceSource` | 创建来源 |
| `last_update_source` | `ResourceSource` | 最近更新来源 |
| `lifecycle_status` | `LifecycleStatus` | 生命周期状态 |
| `search_text` | `str` | 检索文本 |
| `attributes` | `dict[str, Any]` | 扩展属性 |
| `state` | `dict[str, Any]` | 当前状态 |
| `relations` | `list[ResourceRelation]` | 关联资源 |
| `timestamp` | `int` | 原始时间戳 |
| `source` | `ResourceSource` | 来源描述 |
| `raw_payload` | `Any \| null` | 原始载荷 |

`ModelType`

| 字段 | 类型 | 说明 |
| --- | --- | --- |
| `type` | `str` | 型号类别 |
| `description` | `str` | 型号描述 |

`ResourceSource`

| 字段 | 类型 | 说明 |
| --- | --- | --- |
| `source_module` | `str` | 来源模块 |
| `source_topic` | `str` | 来源主题 |
| `source_type` | `str` | 来源类型 |
| `last_update_at` | `datetime \| null` | 最近更新时间 |

#### 3.4.2 类型化资源 `TypedResource`

`TypedResource` 为带判别字段 `entity_kind` 的联合类型，当前包括：

- `EquipmentResource`
- `Platform`
- `Payload`
- `Component`
- `Ammo`
- `Sensor`
- `SupplyResource`
- `TargetResource`

其中常用结构如下。

`EquipmentResource`

| 字段 | 类型 | 说明 |
| --- | --- | --- |
| `entity_kind` | `"equipment"` | 实体类型 |
| `online_status` | `EquipmentStatus` | 在线状态 |
| `capacity` | `dict[str, Any]` | 设备能力 |
| `equipment_reports` | `list[EquipmentReport]` | 上报记录 |
| `warning_status` | `str \| null` | 告警状态 |
| `mission_status` | `EquipmentMissionStatus \| null` | 任务状态 |
| `component_status` | `list[ComponentStatus]` | 部件状态列表 |
| `platforms` | `list[Platform]` | 关联平台 |
| `payloads` | `list[Payload]` | 关联载荷 |

`Platform`

| 字段 | 类型 | 说明 |
| --- | --- | --- |
| `entity_kind` | `"platform"` | 实体类型 |
| `platform_type` | `str \| null` | 平台类型 |
| `equipment_id` | `str \| null` | 所属装备 ID |
| `motion_status` | `PlatformMotionStatus \| null` | 运动状态 |
| `health_status` | `PlatformHealthStatus \| null` | 健康状态 |
| `capacity` | `dict[str, Any]` | 平台能力 |
| `system_attributes` | `dict[str, Any]` | 系统属性 |
| `components` | `list[Component]` | 子组件 |

`Payload`

| 字段 | 类型 | 说明 |
| --- | --- | --- |
| `entity_kind` | `"payload"` | 实体类型 |
| `equipment_id` | `str \| null` | 所属装备 ID |
| `capacity` | `dict[str, Any]` | 载荷能力 |
| `system_attributes` | `dict[str, Any]` | 系统属性 |
| `components` | `list[Component]` | 载荷组件 |

`Component`

| 字段 | 类型 | 说明 |
| --- | --- | --- |
| `entity_kind` | `"component"` | 实体类型 |
| `platform_id` | `str \| null` | 所属平台 ID |
| `payload_id` | `str \| null` | 所属载荷 ID |
| `capacity` | `dict[str, Any]` | 组件能力 |
| `system_attributes` | `dict[str, Any]` | 系统属性 |
| `ammos` | `list[Ammo]` | 挂载弹药 |
| `sensors` | `list[Sensor]` | 挂载传感器 |

`Ammo`

| 字段 | 类型 | 说明 |
| --- | --- | --- |
| `entity_kind` | `"ammo"` | 实体类型 |
| `component_id` | `str \| null` | 所属组件 ID |
| `capacity` | `dict[str, Any]` | 弹药属性 |
| `system_attributes` | `dict[str, Any]` | 系统属性 |
| `ammunition` | `int` | 弹药数量 |
| `online_status` | `EquipmentStatus \| null` | 在线状态 |

`Sensor`

| 字段 | 类型 | 说明 |
| --- | --- | --- |
| `entity_kind` | `"sensor"` | 实体类型 |
| `component_id` | `str \| null` | 所属组件 ID |
| `capacity` | `dict[str, Any]` | 传感器能力 |
| `system_attributes` | `dict[str, Any]` | 系统属性 |
| `online_status` | `EquipmentStatus \| null` | 在线状态 |

`SupplyResource`

| 字段 | 类型 | 说明 |
| --- | --- | --- |
| `entity_kind` | `"supply"` | 顶层补给资源 |
| `location` | `dict[str, Any]` | 位置信息 |
| `supply_level` | `str \| null` | 供应等级 |
| `supply_status` | `str \| null` | 供应状态 |
| `capacity` | `dict[str, Any]` | 补给能力 |
| `system_attributes` | `dict[str, Any]` | 系统属性 |

`TargetResource`

| 字段 | 类型 | 说明 |
| --- | --- | --- |
| `entity_kind` | `"target"` | 目标资源 |
| `threat_level` | `str \| null` | 威胁等级 |
| `target_status` | `str \| null` | 目标状态 |
| `location` | `dict[str, Any]` | 位置信息 |

`TopLevelResource`

- 当前仅包含 `EquipmentResource` 与 `SupplyResource`。

---

## 4. 态势池 API

服务目录：

- `situation_pool`

资源接口前缀：

- `/api/v1/situation_pool/resources`
- `/api/v1/situation_pool/ingestion`
- `/health`

说明：

- 当前实际挂载的态势池接口包括健康检查、资源查询、导入接口。
- `retrieval.py`、`lifecycle.py` 文件存在，但未在 `api/router.py` 中挂载，不属于当前对外接口。

### 4.1 接口列表

| 方法 | 路径 | 说明 | 请求体 | 响应体 |
| --- | --- | --- | --- | --- |
| `GET` | `/health` | 态势池健康检查 | 无 | `HealthView` |
| `GET` | `/api/v1/situation_pool/resources` | 获取态势列表 | 无 | `SituationListResponse` |
| `GET` | `/api/v1/situation_pool/resources/id_list` | 获取态势 ID 列表 | 无 | `list` |
| `GET` | `/api/v1/situation_pool/resources/{resource_id}` | 获取单个态势详情 | 无 | `SituationView` |
| `GET` | `/api/v1/situation_pool/resources/by_type/{situation_type}` | 按态势类型获取资源 | 无 | `list[SituationView]` |
| `GET` | `/api/v1/situation_pool/resources/list_by_type/{situation_type}` | 按类型获取态势 ID 列表 | 无 | `list` |
| `GET` | `/api/v1/situation_pool/resources/get_by_type/{situation_type}` | 按类型获取态势详情列表 | 无 | `SituationListResponse` |
| `POST` | `/api/v1/situation_pool/ingestion/import` | 导入态势数据 | `ImportRequest` | `ImportResult` |

### 4.2 资源查询接口说明

#### 4.2.1 `GET /api/v1/situation_pool/resources`

查询参数：

| 参数 | 类型 | 默认值 | 说明 |
| --- | --- | --- | --- |
| `include_deleted` | `bool` | `false` | 是否包含已删除态势 |
| `limit` | `int` | `100` | 返回条数上限 |
| `send_notification` | `bool` | `false` | 是否触发通知 |

响应：`SituationListResponse`

`SituationListResponse`

| 字段 | 类型 | 说明 |
| --- | --- | --- |
| `items` | `list[SituationView]` | 态势列表 |
| `total` | `int` | 总条数 |

#### 4.2.2 `GET /api/v1/situation_pool/resources/id_list`

查询参数与列表接口一致，响应为 `list`，内容为资源 ID 字符串数组。

#### 4.2.3 `GET /api/v1/situation_pool/resources/{resource_id}`

路径参数：

| 参数 | 类型 | 说明 |
| --- | --- | --- |
| `resource_id` | `str` | 态势资源唯一 ID |

响应：`SituationView`

#### 4.2.4 `GET /api/v1/situation_pool/resources/by_type/{situation_type}`

路径参数：

| 参数 | 类型 | 说明 |
| --- | --- | --- |
| `situation_type` | `str` | 态势类型 |

响应：`list[SituationView]`

#### 4.2.5 `GET /api/v1/situation_pool/resources/list_by_type/{situation_type}`

说明：按类型过滤资源 ID 列表。

查询参数：

| 参数 | 类型 | 默认值 | 说明 |
| --- | --- | --- | --- |
| `include_deleted` | `bool` | `false` | 是否包含已删除资源 |
| `limit` | `int` | `100` | 返回条数上限 |
| `send_notification` | `bool` | `false` | 是否触发通知 |

响应：`list`

#### 4.2.6 `GET /api/v1/situation_pool/resources/get_by_type/{situation_type}`

说明：按类型过滤态势详情，并返回总数。

响应：`SituationListResponse`

### 4.3 导入接口说明

#### 4.3.1 `POST /api/v1/situation_pool/ingestion/import`

请求体：`ImportRequest`

| 字段 | 类型 | 说明 |
| --- | --- | --- |
| `resources` | `list[dict[str, Any]]` | 待导入原始资源列表 |
| `return_data_type` | `str` | 返回数据形式，默认 `none` |
| `ignore_errors` | `bool` | 是否忽略错误继续导入 |

响应：`ImportResult`

| 字段 | 类型 | 说明 |
| --- | --- | --- |
| `requested_resources` | `int` | 请求导入数量 |
| `normalized_resources` | `int` | 规范化数量 |
| `upserted_resources` | `int` | 实际写入数量 |
| `failures` | `list[str]` | 失败原因列表 |
| `imported_at` | `datetime` | 导入时间 |
| `summary` | `dict[str, Any]` | 汇总信息 |
| `results` | `list[Any]` | 明细结果 |

### 4.4 态势模型定义

#### 4.4.1 基础模型 `BaseSituation`

| 字段 | 类型 | 说明 |
| --- | --- | --- |
| `resource_id` | `str` | 资源唯一标识 |
| `situation_type` | `SituationTargetType` | 态势类型 |
| `title` | `str \| null` | 标题 |
| `description` | `str` | 详细描述 |
| `attributes` | `dict` | 扩展属性 |
| `search_text` | `str` | 检索文本 |
| `source` | `dict` | 来源信息 |
| `raw_payload` | `dict \| null` | 原始载荷 |
| `relations` | `list` | 关联资源 |
| `created_at` | `datetime` | 创建时间 |
| `updated_at` | `datetime` | 更新时间 |
| `state` | `SituationStatus` | 状态 |

#### 4.4.2 `SituationView` 联合类型

当前态势资源支持以下类型：

- `FIXEDSituationTarget`
- `MOVABLESituationTarget`
- `OBSTACLETarget`
- `OPTICALTarget`
- `FUSIONEDTarget`
- `DCTarget`
- `DWComparison`
- `RegionTarget`

#### 4.4.3 各态势资源字段

`FIXEDSituationTarget`

| 字段 | 类型 | 说明 |
| --- | --- | --- |
| `object_id` | `str` | 目标 ID |
| `object_sid` | `str` | 目标 SID |
| `name` | `str` | 目标名称 |
| `type` | `str` | 目标类别 |
| `foe` | `str` | 敌我属性 |
| `center_position` | `dict[str, Any]` | 中心位置 |
| `object_level` | `str` | 目标等级 |
| `front` | `float` | 正面尺寸 |
| `depth` | `float` | 纵深尺寸 |
| `area` | `float` | 面积 |
| `height` | `float` | 高度 |
| `material` | `str` | 材质 |
| `target` | `list[dict[str, Any]]` | 瞄准点列表 |
| `object_requirement_result` | `str` | 作战要求 |

`MOVABLESituationTarget`

| 字段 | 类型 | 说明 |
| --- | --- | --- |
| `object_id` | `str` | 目标 ID |
| `object_sid` | `str` | 目标 SID |
| `name` | `str` | 目标名称 |
| `type` | `str` | 目标类型 |
| `foe` | `str` | 敌我识别 |
| `center_position` | `dict[str, Any]` | 中心位置 |
| `object_status` | `str` | 目标状态 |
| `speed` | `float` | 目标速度 |
| `heading` | `float` | 航向角 |
| `object_requirement_result` | `str` | 作战要求 |

`OBSTACLETarget`

| 字段 | 类型 | 说明 |
| --- | --- | --- |
| `vehicle_id` | `str` | 车辆 ID |
| `vmf` | `str` | 车辆域 |
| `obstacle_id` | `int` | 障碍物 ID |
| `obstacle_type` | `int \| null` | 障碍物类型 |
| `impact_level` | `int \| null` | 影响级别 |
| `longitude` | `float` | 经度 |
| `latitude` | `float` | 纬度 |
| `altitude` | `float \| null` | 海拔 |
| `timestamp` | `datetime \| null` | 发现时间 |

`OPTICALTarget`

| 字段 | 类型 | 说明 |
| --- | --- | --- |
| `vehicle_id` | `str` | 车辆 ID |
| `vmf` | `str` | 车辆域 |
| `target_id` | `int` | 目标 ID |
| `timestamp` | `datetime \| null` | 时间戳 |
| `target_name` | `str \| null` | 目标名称 |
| `target_attr` | `int \| null` | 目标属性 |
| `target_type` | `int \| null` | 目标类型 |
| `target_mark` | `int \| null` | 目标标记 |
| `longitude` | `float` | 经度 |
| `latitude` | `float` | 纬度 |
| `altitude` | `float \| null` | 海拔 |
| `discovery_time` | `str \| null` | 发现时间 |
| `speed_ms` | `int \| null` | 速度 |
| `motion_direction` | `int \| null` | 运动方向 |
| `image_url` | `str \| null` | 图片地址 |

`FUSIONEDTarget`

| 字段 | 类型 | 说明 |
| --- | --- | --- |
| `fusion_id` | `str` | 融合目标 ID |
| `time` | `str \| null` | 目标时间 |
| `target_type` | `int \| null` | 目标类型 |
| `lon` | `float` | 经度 |
| `lat` | `float` | 纬度 |
| `alt` | `float \| null` | 海拔 |
| `threat_level` | `float \| null` | 威胁度 |
| `target_attr` | `int \| null` | 目标属性 |
| `timestamp` | `str \| null` | 上报时间 |

`DCTarget`

| 字段 | 类型 | 说明 |
| --- | --- | --- |
| `vehicle_id` | `str` | 车辆 ID |
| `vmf` | `str` | 车辆域 |
| `target_id` | `str` | 目标 ID |
| `message_type` | `str` | 消息类型 |
| `target_type` | `str \| null` | 目标类型 |
| `emitter_type` | `int \| null` | 发射器类型 |
| `foe` | `str \| null` | 敌我标识 |
| `threat_level` | `str \| null` | 威胁等级 |
| `longitude` | `float` | 经度 |
| `latitude` | `float` | 纬度 |
| `altitude` | `float \| null` | 海拔 |
| `discovery_time` | `str \| null` | 发现时间 |
| `timestamp` | `str \| null` | 上报时间戳 |
| `additional_attributes` | `dict[str, Any] \| null` | 附加属性 |

`DWComparison`

| 字段 | 类型 | 说明 |
| --- | --- | --- |
| `timestamp` | `str \| null` | 时间戳 |
| `target_summary` | `dict[str, Any] \| null` | 目标摘要 |
| `enemy_capability` | `dict[str, Any] \| null` | 敌方能力 |
| `friendly_capability` | `dict[str, Any] \| null` | 我方能力 |

`RegionTarget`

| 字段 | 类型 | 说明 |
| --- | --- | --- |
| `target_id` | `str` | 目标 ID |
| `plan_id` | `str` | 计划 ID |
| `name` | `str \| null` | 目标名称 |
| `target_type` | `str` | 目标类型 |
| `foe` | `str \| null` | 敌我标识 |
| `location` | `list[dict[str, Any]] \| null` | 位置信息 |
| `target_motion` | `list[dict[str, Any]] \| null` | 目标运动信息 |

---

## 5. 任务池 API

服务目录：

- `task_pool`

资源接口前缀：

- `/api/v1/task_pool/resources`
- `/api/v1/task_pool/ingestion`
- `/health`

### 5.1 接口列表

| 方法 | 路径 | 说明 | 请求体 | 响应体 |
| --- | --- | --- | --- | --- |
| `GET` | `/health` | 任务池健康检查 | 无 | `HealthView` |
| `GET` | `/api/v1/task_pool/resources/id_list` | 获取任务 ID 列表 | 无 | `list` |
| `GET` | `/api/v1/task_pool/resources` | 获取任务列表 | 无 | `TaskListResponse` |
| `GET` | `/api/v1/task_pool/resources/{resource_id}` | 获取任务详情 | 无 | `TaskView` |
| `GET` | `/api/v1/task_pool/resources/by_type/{task_type}` | 按任务类型查询 | 无 | `list[TaskView]` |
|  `TaskPatchRequest` | `TaskView` |
| `POST` | `/api/v1/task_pool/resources/query` | 条件查询任务 | `TaskQueryRequest` | `list[TaskView]` |
| `POST` | `/api/v1/task_pool/resources/search` | 全文检索任务 | `TaskSearchRequest` | `TaskListResponse` |
| `POST` | `/api/v1/task_pool/resources/{resource_id}/lifecycle` | 更新任务生命周期 | `TaskLifecycleUpdateRequest` | `TaskView` |
| `GET` | `/api/v1/task_pool/ingestion/runtime` | 获取接入运行状态 | 无 | `RuntimeStatusView` |
| `GET` | `/api/v1/task_pool/ingestion/cache` | 获取缓存摘要 | 无 | `TaskCacheSummaryView` |
| `POST` | `/api/v1/task_pool/ingestion/subscriptions` | 订阅主题 | `TopicSubscriptionRequest` | `StatusResponse` |
| `POST` | `/api/v1/task_pool/ingestion/commit` | 手动提交缓存 | `ManualCommitRequest` | `ManualCommitResult` |
| `POST` | `/api/v1/task_pool/ingestion/replay` | 重放待提交缓存 | `ReplayRequest` | `ManualCommitResult` |
| `POST` | `/api/v1/task_pool/ingestion/import` | 导入任务资源 | `ImportRequest` | `ImportResult` |
| `POST` | `/api/v1/task_pool/ingestion/execution-feedback` | 回传执行反馈 | `ExecutionFeedbackRequest` | `TaskView` |

### 5.2 资源查询与更新接口说明

#### 5.2.1 `GET /api/v1/task_pool/resources/id_list`

查询参数：

| 参数 | 类型 | 默认值 | 说明 |
| --- | --- | --- | --- |
| `include_deleted` | `bool` | `false` | 是否包含已删除任务 |
| `limit` | `int` | `100` | 返回条数上限 |
| `send_notification` | `bool` | `false` | 是否触发通知 |

响应：`list`

#### 5.2.2 `GET /api/v1/task_pool/resources`

响应：`TaskListResponse`

`TaskListResponse`

| 字段 | 类型 | 说明 |
| --- | --- | --- |
| `items` | `list[TaskView]` | 任务列表 |
| `total` | `int` | 任务总数 |

#### 5.2.3 `GET /api/v1/task_pool/resources/{resource_id}`

路径参数：

| 参数 | 类型 | 说明 |
| --- | --- | --- |
| `resource_id` | `str` | 任务资源 ID |

响应：`TaskView`

#### 5.2.4 `GET /api/v1/task_pool/resources/by_type/{task_type}`

路径参数：

| 参数 | 类型 | 说明 |
| --- | --- | --- |
| `task_type` | `str` | 任务类型，如 `PLAN`、`STAGE`、`TEAM`、`TACTIC` |

响应：`list[TaskView]`

#### 5.2.5 `PATCH /api/v1/task_pool/resources/{resource_id}`

请求体：`TaskPatchRequest`

| 字段 | 类型 | 说明 |
| --- | --- | --- |
| `title` | `str \| null` | 任务标题 |
| `description` | `str \| null` | 任务描述 |
| `attributes` | `dict[str, Any] \| null` | 扩展属性 |
| `search_text` | `str \| null` | 检索文本 |
| `state` | `str \| null` | 新状态 |
| `payload` | `dict[str, Any] \| null` | 任务载荷补丁 |

响应：`TaskView`

#### 5.2.6 `POST /api/v1/task_pool/resources/query`

请求体：`TaskQueryRequest`

| 字段 | 类型 | 说明 |
| --- | --- | --- |
| `task_type` | `str \| null` | 任务类型 |
| `state` | `str \| null` | 状态 |
| `relation_target` | `str \| null` | 关联目标 |
| `source_topic` | `str \| null` | 来源主题 |
| `keyword` | `str \| null` | 关键字 |
| `parent_resource_id` | `str \| null` | 父资源 ID |
| `include_deleted` | `bool` | 是否包含已删除任务 |
| `mission_ids` | `list[str] \| null` | 任务所属任务集 ID 列表 |
| `limit` | `int` | 最大返回数量，范围 `1~500` |

响应：`list[TaskView]`

#### 5.2.7 `POST /api/v1/task_pool/resources/search`

请求体：`TaskSearchRequest`

| 字段 | 类型 | 说明 |
| --- | --- | --- |
| `query` | `str` | 搜索关键字，长度 `1~200` |
| `limit` | `int` | 最大返回数量，范围 `1~100` |

响应：`TaskListResponse`

#### 5.2.8 `POST /api/v1/task_pool/resources/{resource_id}/lifecycle`

请求体：`TaskLifecycleUpdateRequest`

| 字段 | 类型 | 说明 |
| --- | --- | --- |
| `state` | `str` | 目标状态 |
| `reason` | `str` | 变更原因 |

响应：`TaskView`

### 5.3 接入管理接口说明

#### 5.3.1 `GET /api/v1/task_pool/ingestion/runtime`

响应字段与资源池 `RuntimeStatusView` 基本一致：

| 字段 | 类型 | 说明 |
| --- | --- | --- |
| `zenoh_enabled` | `bool` | 是否启用 Zenoh |
| `zenoh_connected` | `bool` | Zenoh 是否已连接 |
| `worker_running` | `bool` | 接收线程是否运行 |
| `commit_worker_running` | `bool` | 提交线程是否运行 |
| `default_topics` | `list[str]` | 默认主题列表 |
| `subscribed_topics` | `list[str]` | 当前订阅主题 |
| `pending_count` | `int` | 待处理数量 |
| `pending_cache_keys` | `list[str]` | 待处理缓存键 |
| `received_messages` | `int` | 已接收消息数 |
| `normalized_messages` | `int` | 规范化消息数 |
| `failed_messages` | `int` | 失败消息数 |
| `last_message_at` | `datetime \| null` | 最近消息时间 |
| `last_commit_at` | `datetime \| null` | 最近提交时间 |
| `last_commit_summary` | `dict[str, Any]` | 提交摘要 |
| `last_error` | `str` | 最近错误 |

#### 5.3.2 `GET /api/v1/task_pool/ingestion/cache`

响应：`TaskCacheSummaryView`

| 字段 | 类型 | 说明 |
| --- | --- | --- |
| `total_cache_keys` | `int` | 缓存总数 |
| `pending_cache_keys` | `list[str]` | 待提交缓存键 |
| `items` | `list[TaskCacheSummaryItem]` | 缓存项列表 |

`TaskCacheSummaryItem`

| 字段 | 类型 | 说明 |
| --- | --- | --- |
| `cache_key` | `str` | 缓存键 |
| `aggregate_present` | `bool` | 是否存在聚合缓存 |
| `typed_tasks` | `int` | 类型化任务数量 |
| `pending` | `bool` | 是否待处理 |

#### 5.3.3 `POST /api/v1/task_pool/ingestion/subscriptions`

请求体：`TopicSubscriptionRequest`

| 字段 | 类型 | 说明 |
| --- | --- | --- |
| `topics` | `list[str]` | 订阅主题列表 |
| `ignore_errors` | `bool` | 是否忽略错误继续 |

响应：`StatusResponse`

#### 5.3.4 `POST /api/v1/task_pool/ingestion/commit`

请求体：`ManualCommitRequest`

| 字段 | 类型 | 说明 |
| --- | --- | --- |
| `cache_keys` | `list[str]` | 需要提交的缓存键列表 |
| `ignore_errors` | `bool` | 是否忽略错误 |

响应：`ManualCommitResult`

#### 5.3.5 `POST /api/v1/task_pool/ingestion/replay`

请求体：`ReplayRequest`

| 字段 | 类型 | 说明 |
| --- | --- | --- |
| `cache_keys` | `list[str]` | 需要回放的缓存键列表 |
| `commit_immediately` | `bool` | 是否立即提交 |
| `ignore_errors` | `bool` | 是否忽略错误 |

响应：`ManualCommitResult`

#### 5.3.6 `POST /api/v1/task_pool/ingestion/import`

请求体：`ImportRequest`

| 字段 | 类型 | 说明 |
| --- | --- | --- |
| `resources` | `list[dict[str, Any]]` | 待导入任务资源 |
| `return_data_type` | `str` | 返回数据形式 |
| `ignore_errors` | `bool` | 是否忽略错误 |

响应：`ImportResult`

#### 5.3.7 `POST /api/v1/task_pool/ingestion/execution-feedback`

请求体：`ExecutionFeedbackRequest`

| 字段 | 类型 | 说明 |
| --- | --- | --- |
| `resource_id` | `str` | 任务资源 ID |
| `execution_status` | `str` | 执行状态 |
| `progress` | `float \| null` | 进度，范围 `0~1` |
| `message` | `str` | 反馈说明 |
| `feedback_payload` | `dict[str, Any]` | 附加反馈数据 |

响应：`TaskView`

### 5.4 任务模型定义

#### 5.4.1 基础模型

`TaskEnvelope`

| 字段 | 类型 | 说明 |
| --- | --- | --- |
| `resource_id` | `str` | 任务资源唯一 ID |
| `task_type` | `str` | 任务类型 |
| `attributes` | `dict[str, Any]` | 扩展属性 |
| `search_text` | `str` | 检索文本 |
| `source` | `dict[str, Any]` | 来源信息 |
| `raw_payload` | `dict[str, Any] \| null` | 原始数据 |
| `relations` | `list[TaskRelation]` | 关联关系 |
| `created_at` | `datetime` | 创建时间 |
| `updated_at` | `datetime` | 更新时间 |

`TaskAggregateBase`

| 字段 | 类型 | 说明 |
| --- | --- | --- |
| `connections` | `list[Connection]` | 连接关系 |
| `dependencies` | `list[Dependency]` | 依赖关系 |

#### 5.4.2 `TaskView` 联合类型

当前任务池支持：

- `Vehicle`
- `Command`
- `Mission`
- `Plan`
- `Action`
- `Stage`
- `Team`
- `Tactic`
- `CarActions`
- `KillChain`

#### 5.4.3 主要任务资源字段

`Plan`

| 字段 | 类型 | 说明 |
| --- | --- | --- |
| `task_type` | `"PLAN"` | 任务类型 |
| `title` | `str` | 方案标题 |
| `plan_id` | `str` | 方案 ID |
| `plan_seq` | `int` | 方案序号 |
| `mission_ids` | `list[str]` | 所属任务集 ID 列表 |
| `description` | `str` | 方案描述 |
| `teams` | `list[Team]` | 编组列表 |
| `targets` | `list[Target_abstract]` | 目标列表 |
| `stages` | `list[Stage]` | 阶段列表 |
| `tactic` | `Tactic \| null` | 战术战法 |
| `state` | `PlanState` | 方案状态 |

`Stage`

| 字段 | 类型 | 说明 |
| --- | --- | --- |
| `task_type` | `"STAGE"` | 任务类型 |
| `title` | `str` | 阶段标题 |
| `stage_id` | `str` | 阶段 ID |
| `plan_id` | `str` | 所属方案 ID |
| `plan_resource_id` | `str` | 所属方案资源 ID |
| `stage_seq` | `int` | 阶段序号 |
| `description` | `str` | 阶段描述 |
| `team_actions` | `list[TeamStageActions]` | 编组阶段行动 |
| `target_ids` | `list[str]` | 目标 ID 列表 |
| `team_ids` | `list[str]` | 编组 ID 列表 |
| `state` | `BaseState` | 阶段状态 |

`Team`

| 字段 | 类型 | 说明 |
| --- | --- | --- |
| `task_type` | `"TEAM"` | 任务类型 |
| `name` | `str` | 编组名称 |
| `team_id` | `str` | 编组 ID |
| `plan_id` | `str \| null` | 所属方案 ID |
| `description` | `str` | 编组描述 |
| `equipment` | `list[str]` | 装备 ID 列表 |
| `state` | `BaseState` | 编组状态 |

`Tactic`

| 字段 | 类型 | 说明 |
| --- | --- | --- |
| `task_type` | `"TACTIC"` | 任务类型 |
| `tactic_id` | `str` | 战术 ID |
| `title` | `str` | 战术标题 |
| `main_tactic` | `str` | 主战法 |
| `sub_tactics` | `list[str]` | 子战法列表 |
| `teams` | `list[dict[str, Any]]` | 编组说明 |
| `suggest_stage` | `str` | 阶段建议描述 |
| `required_resources` | `list[str]` | 所需资源列表 |
| `plan_id` | `str \| null` | 所属方案 ID |
| `plan_resource_id` | `str \| null` | 所属方案资源 ID |

`Action`

| 字段 | 类型 | 说明 |
| --- | --- | --- |
| `task_type` | `"ACTION"` | 任务类型 |
| `action_id` | `str` | 行动 ID |
| `name` | `str` | 行动名称 |
| `vid` | `str` | 车辆 ID |
| `action_seq` | `int` | 行动序号 |
| `equipment_id` | `str \| null` | 装备 ID |
| `param` | `dict[str, Any]` | 行动参数 |
| `dependencies` | `list[str]` | 行动依赖 |
| `time_attributes` | `action_time_attributes` | 时间属性 |
| `state` | `STAGE_CA_ActionState` | 行动状态 |
| `car_actions_id` | `str` | 所属行动序列 ID |
| `car_action_resource_id` | `str \| null` | 所属行动序列资源 ID |

`CarActions`

| 字段 | 类型 | 说明 |
| --- | --- | --- |
| `task_type` | `"CAR_ACTIONS"` | 任务类型 |
| `car_actions_id` | `str` | 行动序列 ID |
| `vid` | `str` | 车辆 ID |
| `equipment_id` | `str \| null` | 装备 ID |
| `plan_id` | `str \| null` | 所属方案 ID |
| `stage_id` | `str \| null` | 所属阶段 ID |
| `stage_resource_id` | `str \| null` | 所属阶段资源 ID |
| `team_id` | `str \| null` | 所属编组 ID |
| `action_ids` | `list[str]` | 行动 ID 列表 |
| `actions` | `list[Action]` | 行动列表 |
| `state` | `STAGE_CA_ActionState` | 状态 |

`Vehicle`

| 字段 | 类型 | 说明 |
| --- | --- | --- |
| `task_type` | `"VEHICLE"` | 任务类型 |
| `title` | `str` | 名称 |
| `vehicle_id` | `str` | 车辆 ID |
| `vmf` | `str` | 车辆域 |
| `mission_id` | `str` | 所属任务集 ID |

`Mission`

| 字段 | 类型 | 说明 |
| --- | --- | --- |
| `task_type` | `"MISSION"` | 任务类型 |
| `title` | `str` | 标题 |
| `mission_id` | `str` | 任务集 ID |
| `mission_seq` | `int` | 序号 |
| `command_id` | `str \| null` | 所属指令 ID |
| `description` | `str` | 描述 |
| `target` | `str` | 目标 |
| `duration` | `int` | 时长 |
| `state` | `BaseState` | 状态 |

`Command`

| 字段 | 类型 | 说明 |
| --- | --- | --- |
| `task_type` | `"COMMAND"` | 任务类型 |
| `title` | `str` | 标题 |
| `command_id` | `str` | 指令 ID |
| `description` | `str` | 描述 |
| `state` | `BaseState` | 状态 |

`KillChain`

| 字段 | 类型 | 说明 |
| --- | --- | --- |
| `task_type` | `"KILL_CHAIN"` | 任务类型 |
| `title` | `str` | 标题 |
| `kill_chain_id` | `str` | 杀伤链 ID |
| `description` | `str` | 描述 |
| `raw_entries` | `list[KillChainEntry]` | 原始条目 |
| `assigned_entries` | `list[KillChainEntry]` | 分配后条目 |
| `resource_ids` | `list[str]` | 关联资源 ID |
| `target_ids` | `list[str]` | 关联目标 ID |
| `mapped_plan_ids` | `list[str]` | 映射方案 ID |
| `mapping_summary` | `dict[str, Any]` | 映射摘要 |
| `state` | `BaseState` | 状态 |

---

## 6. 补充说明

### 6.1 当前文档的接口边界

本文档只覆盖当前 `api/router.py` 实际注册的接口，不包含未挂载或被注释掉的实验性接口。

### 6.2 联合类型返回

以下响应类型为联合模型，实际返回结构取决于资源类型：

- `TypedResource`
- `TopLevelResource`
- `SituationView`
- `TaskView`

### 6.3 建议调用方式

- 列表查询优先使用 `GET` 列表接口。
- 复杂筛选使用 `POST /query`。
- 模糊搜索使用 `POST /search`。
- 导入、回放、手动提交等管理类操作建议通过独立管理接口执行。
