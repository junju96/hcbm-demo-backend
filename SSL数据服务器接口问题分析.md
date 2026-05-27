# SSL 数据服务器接口问题分析

> 数据服务器地址：`http://<host>:28801` | 文档：`SSL_DATA_API_README.md`

---

## 一、用户指定的核心接口

| 编号 | 接口 | 用途 |
|------|------|------|
| 2.3 | `GET /api/v1/task_pool/resources/{resource_id}` | 查询单个杀伤链详情 |
| 2.4 | `GET /api/v1/task_pool/resources/by_type/KILL_CHAIN` | 获取所有杀伤链列表 |
| 2.5 | `PATCH /api/v1/task_pool/resources/{resource_id}` | 更新杀伤链 |
| 5.6 | `POST /api/v1/task_pool/ingestion/import` | 插入新杀伤链数据 |

---

## 二、发现的问题

### 问题 1：PATCH 接口不支持杀伤链特有字段（⚠️ 严重）

**数据服务器的 PATCH 请求体（TaskPatchRequest）：**
> 定义位置：`SSL_DATA_API_README.md` → 2.5 PATCH /api/v1/task_pool/resources/{resource_id}
```
title | description | attributes | search_text | state | payload
```

**当前后端设计直接支持的字段：**
> 定义来源：`SSL_DATA_API_README.md` → KillChain（文档末尾核心数据结构说明章节）
```
title | description | raw_entries | assigned_entries | resource_ids | target_ids | mapped_plan_ids | mapping_summary | state
```

**矛盾点：**
- 数据服务器的 PATCH **没有** `raw_entries`、`assigned_entries`、`network` 等杀伤链特有字段
- 这些字段只能通过 `payload` 或 `attributes` 打包传递
- 这意味着当前后端 router 中 `PATCH /kill-chains/{id}` 直接透传 `raw_entries` 的逻辑**无法直接对接数据服务器**

**解决方向：**
- 后端收到 PATCH 请求后，将杀伤链特有字段序列化到 `payload` 字段中，再转发给数据服务器
- 或者通过 `attributes` 字典存储（但 `attributes` 通常用于元数据，不太适合存大量结构化数据）

---

### 问题 2：KillChainEntry 中的目标-装备映射缺失（⚠️ 严重）

**当前前后端设计（前端表格 + 后端模型）：**
> 前端假数据位置：`demo/frontend/src/.../data/planningDataModel.js` → killChainDetailMap.entries.executor_assignments
```js
// 前端假数据
executor_assignments: [
  { executor_name: '装备A', target_name: '目标1', locked: false },
  { executor_name: '装备A', target_name: '目标2', locked: false },
]
```
含义：装备A 分配到 目标1 和 目标2。

**数据服务器 KillChainEntry 结构：**
> 定义位置：`SSL_DATA_API_README.md` → KillChainEntry（文档末尾核心数据结构说明章节）
```
entry_id, phase, entry_seq, target_ids, operation,
executor_options, selected_executor, locked, is_valid, notes
```

**数据服务器 KillChainExecutorOption：**
> 定义位置：`SSL_DATA_API_README.md` → KillChainExecutorOption（文档末尾核心数据结构说明章节）
```
executor_id, allocation_count, locked, note
```

**矛盾点：**
- 数据服务器的 `executor_options` **没有目标映射字段**（没有 `target_name` 或类似字段）
- 一个装备可以同时分配到多个目标（如装备A→目标1、装备A→目标2），这个关系在数据服务器结构中没有地方存储
- `target_ids` 在 entry 级别，表示该条目涉及的所有目标，但不表达"哪个装备负责哪个目标"

**解决方向（需要产品/架构确认）：**
- 方案A：将 `executor_options` 扩展，增加 `target_ids` 字段表示该装备负责的目标列表
- 方案B：把装备-目标映射放到 `attributes` 或 `notes` 中作为扩展数据
- 方案C：修改前端交互，改为"一个 entry 只对应一个目标"，这样 `selected_executor` 就自然绑定到 entry 的 `target_ids`

---

### 问题 3：前端数据结构不一致（⚠️ 中等）

| 前端当前字段 | 数据服务器字段 | 差异 |
|-------------|---------------|------|
| `kill_chain_id` | `kill_chain_id` + `resource_id` | 缺少 `resource_id`（如 `kill_chain:kc-demo-001`） |
| `entries`（混合数组） | `raw_entries` + `assigned_entries`（分开） | 需要拆分 |
| `targets`（对象数组 `{target_id, name, source}`） | `target_ids`（字符串数组） | 目标名称需要另存或查询 |
| `executor_assignments` | `executor_options` | 字段名不同，结构不同 |
| `network` | ❌ 无此字段 | 需要放到 `payload`/`attributes` 中 |
| `target_names` | ❌ 无此字段 | 前端为了方便显示额外加的，需通过 target_ids 关联查询或缓存 |

---

### 问题 4：导入接口格式差异（⚠️ 中等）

**数据服务器 5.6 import 请求体：**
> 定义位置：`SSL_DATA_API_README.md` → 5.6 POST /api/v1/task_pool/ingestion/import（ImportRequest / ImportResult）
```json
{
  "resources": [
    {
      "resource_id": "kill_chain:kc-xxx",
      "task_type": "KILL_CHAIN",
      "title": "...",
      "kill_chain_id": "kc-xxx",
      "raw_entries": [...],
      "assigned_entries": [...],
      ...
    }
  ],
  "return_data_type": "typed",
  "ignore_errors": true
}
```

**当前后端 import 请求体：**
> 定义位置：`demo/backend/app/routers/kill_chain.py` → task_pool_import / `demo/backend/app/services/task_pool.py` → import_resources
```json
{
  "resources": [...],
  "ignore_errors": false
}
```

**差异：**
- 数据服务器要求每个 resource 必须包含 `resource_id` 和 `task_type`
- 数据服务器有 `return_data_type` 参数控制返回格式
- 数据服务器返回 `normalized_resources`、`upserted_resources` 等统计信息

---

### 问题 5：查询 2.4 返回格式（⚠️ 低）

`GET /api/v1/task_pool/resources/by_type/KILL_CHAIN` 返回 `list[TaskView]`。
> TaskView 定义位置：`SSL_DATA_API_README.md` → 3.1 核心数据结构说明 → TaskView（资源视图联合类型）

当前后端代理接口 `POST /api/v1/task_pool/resources/query` 返回 `{ items, total }`。
> 定义位置：`demo/backend/app/routers/kill_chain.py` → task_pool_query / `demo/backend/app/services/task_pool.py` → query

差异不大，只需调整响应包装格式。

---

## 三、对接建议

### 后端适配层改造点

```
当前后端 (FastAPI)          数据服务器 (Task Pool)
       │                           │
       ├─ PATCH /kill-chains/{id}  ├─ PATCH /task_pool/resources/{id}
       │   (接收 raw_entries 等)   │   (只接收 title/desc/state/payload)
       │         ↓                 │
       │   需要转换层：把特有字段   │
       │   打包到 payload 中       │
       │                           │
       ├─ GET /kill-chains/{id}    ├─ GET /task_pool/resources/{id}
       │         ↓                 │
       │   需要转换层：从 payload   │
       │   解析出 raw_entries 等   │
       │   返回给前端              │
```

### 前端适配点

```
1. 拆分 entries → raw_entries + assigned_entries
2. executor_assignments → executor_options（字段名映射）
3. 移除 target_names，通过 target_ids 查询目标名称
4. 增加 resource_id 字段（kill_chain:xxx）
5. network 数据放到 attributes 或单独处理
```

---

## 四、需要确认的问题

| 问题 | 影响 | 建议决策方 |
|------|------|-----------|
| KillChainExecutorOption 是否增加 target_ids？ | 决定装备-目标多对多关系能否表达 | 架构/产品 |
| PATCH 的杀伤链特有字段走 payload 还是 attributes？ | 决定后端转换层实现方式 | 后端开发 |
| 前端是否需要保留 target_names 缓存？ | 决定前端数据流设计 | 前端开发 |
| network 节点状态图是否存数据服务器？ | 决定状态同步方案 | 架构 |
