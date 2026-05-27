# SSL 数据服务器接口问题分析

> 数据服务器地址：`http://<host>:28801` | 文档：`SSL_DATA_API_README.md`  
> 实测参考：`demo/backend/test.py`（三类接口调用范例）

---

## 一、用户指定的核心接口

| 编号 | 接口 | 用途 |
|------|------|------|
| 2.3 | `GET /api/v1/task_pool/resources/{resource_id}` | 查询单个杀伤链详情 |
| 2.4 | `GET /api/v1/task_pool/resources/by_type/KILL_CHAIN` | 获取所有杀伤链列表 |
| 2.5 | `PATCH /api/v1/task_pool/resources/{resource_id}` | 更新杀伤链 |
| 5.6 | `POST /api/v1/task_pool/ingestion/import` | 插入新杀伤链数据 |

---

## 二、test.py 实测发现与问题澄清

### 2.1 查询接口（GET）— ✅ 无问题

**实测数据：** `test.py` 中调用 `GET /api/v1/task_pool/resources/kill_chain:kill_chain_001` 返回了完整的 KillChain 结构：

```json
{
  "resource_id": "kill_chain:kill_chain_001",
  "task_type": "KILL_CHAIN",
  "title": "对敌装甲目标杀伤链",
  "kill_chain_id": "kill_chain_001",
  "state": "ACTIVE",
  "resource_ids": ["eq_无人车A", "eq_巡逻无人机", "eq_无人车B", "target_001"],
  "target_ids": ["target_001"],
  "mapped_plan_ids": ["plan_001"],
  "mapping_summary": {...},
  "raw_entries": [{"entry_id": "entry_01", "phase": "RAW", ...}],
  "assigned_entries": [{"entry_id": "entry_01", "phase": "ASSIGNED", ...}]
}
```

**结论：** 数据服务器**完全支持** KillChain 特有字段的存储和查询返回，`raw_entries` / `assigned_entries` / `mapping_summary` 等字段都能正常读写。

---

### 2.2 插入接口（POST import）— ✅ 无问题

**实测 payload：** `test.py` 中展示了完整的导入请求体，直接包含 KillChain 完整字段：

```json
{
  "resources": [{
    "task_type": "KILL_CHAIN",
    "kill_chain_id": "kill_chain_001",
    "raw_entries": [...],
    "assigned_entries": [...]
  }],
  "return_data_type": "full",
  "ignore_errors": true
}
```

**注意：** `return_data_type` 用了 `"full"`，但文档中只列出 `"none"` / `"typed"` / `"raw"`。 `"full"` 可能是未文档化的有效值，或文档遗漏。

**结论：** import 接口**支持**直接导入 KillChain 完整结构，无需转换。

---

### 2.3 更新接口（PATCH）— ⚠️ 需要通过 `payload` 字段

**实测代码：** `test.py` 中 PATCH 请求体如下：

```python
patch_payload = {
    "payload": {
        "target_ids": ["target_002", "target_003"],
        "mapped_plan_ids": ["plan_003", "plan_004"],
        "mapping_summary": {...}
    }
}
```

**关键发现：** KillChain 特有字段必须放在 **`payload`** 字段内传递，不能直接作为顶层字段。

| 字段 | 是否可直接 PATCH | 传递方式 |
|------|----------------|----------|
| `title` | ✅ | 顶层字段 |
| `description` | ✅ | 顶层字段 |
| `state` | ✅ | 顶层字段 |
| `raw_entries` | ❌ | 放入 `payload` |
| `assigned_entries` | ❌ | 放入 `payload` |
| `target_ids` | ❌ | 放入 `payload` |
| `mapped_plan_ids` | ❌ | 放入 `payload` |
| `mapping_summary` | ❌ | 放入 `payload` |

**对后端的影响：** 当前后端 router 中的 `PATCH /kill-chains/{id}` 直接接收 `raw_entries` / `assigned_entries` 等字段，需要加一层转换：
- 收到前端请求 → 将特有字段打包到 `payload` → 转发给数据服务器
- 从数据服务器读取 → 从 `payload` 解析特有字段 → 返回给前端

---

### 2.4 装备-目标映射关系 — ⚠️ 需要调整前端设计

**test.py 实测数据结构中的分配表达：**

```json
{
  "entry_id": "entry_01",
  "phase": "ASSIGNED",
  "target_ids": ["target_001"],
  "operation": "侦察",
  "executor_options": [
    {"executor_id": "eq_无人车A", "allocation_count": 1, "locked": true, "note": "最终选定"}
  ],
  "selected_executor": "eq_无人车A",
  "locked": true
}
```

**关键发现：**

| 当前前端设计 | test.py 实测数据结构 |
|-------------|-------------------|
| `executor_assignments: [{executor_name, target_name}]` — 装备→目标多对多映射 | `executor_options: [{executor_id, note}]` — 只是**候选/已选装备列表** |
| 一个装备可以勾选多个目标 | `selected_executor` 只选一个装备负责该 entry 的所有 `target_ids` |

**结论：** 数据服务器的 KillChainEntry 中，`executor_options` 本身**不包含目标映射**。一个 entry 的 target→装备关系是：
- `target_ids` 在 entry 级别定义该条目涉及的所有目标
- `selected_executor` 指定**一个**装备负责执行该条目（所有目标）
- `executor_options` 只是候选装备列表（RAW 阶段）或已选装备（ASSIGNED 阶段）

**对前端的影响：**
- 如果业务需要"装备A负责目标1、装备B负责目标2"，需要拆分为**两个 entry**（每个 entry 一个 target）
- 当前弹窗中的"一个装备勾选多个目标"交互需要调整为： entry 级别选装备，而非装备→目标多对多映射

---

## 三、问题汇总与解决方案

| 问题 | 严重程度 | 原因 | 解决方案 |
|------|---------|------|----------|
| PATCH 特有字段需放入 `payload` | 中等 | 数据服务器 PATCH 只识别通用字段 | 后端加转换层：收到请求后打包到 `payload`，读取后从 `payload` 解析 |
| 装备-目标映射方式不同 | 中等 | 数据服务器用 `selected_executor` 表达一对一，前端设计为多对多 | 前端调整：entry 级别选装备，或拆分为单目标 entry |
| `return_data_type: "full"` 未文档化 | 低 | 文档遗漏 | 与数据服务器团队确认，或改用 `"typed"` |

---

## 四、后端适配层改造建议

```
前端请求 ──→ 当前后端 (FastAPI) ──→ 数据转换层 ──→ 数据服务器 (task_pool)
              │                       │
              │  raw_entries          │  打包到 payload
              │  assigned_entries     │  或 attributes
              │  network              │
              │                       │
              │  从 payload 解析      │  返回 TaskView
              │  特有字段             │
              ↓                       ↓
```

**具体改造点：**

1. **PATCH /kill-chains/{id}**
   - 接收前端的 `raw_entries` / `assigned_entries` / `network` 等字段
   - 序列化为 JSON 字符串放入 `payload` 字段
   - 调用数据服务器 `PATCH /task_pool/resources/{resource_id}`

2. **GET /kill-chains/{id}**
   - 调用数据服务器 `GET /task_pool/resources/{resource_id}`
   - 从返回的 `payload` 字段解析出 `raw_entries` / `assigned_entries` 等
   - 组装为前端熟悉的结构返回

3. **POST /kill-chains（创建）**
   - 组装完整 KillChain 对象
   - 调用数据服务器 `POST /task_pool/ingestion/import`

---

## 五、需要确认的问题

| 问题 | 影响 | 建议决策方 |
|------|------|-----------|
| `return_data_type: "full"` 是否稳定可用？ | 影响 import 接口返回值 | 数据服务器团队 |
| 前端是否接受"一个 entry 只选一个装备"？ | 影响目标分配弹窗交互 | 产品/前端 |
| `network` 节点状态图是否存数据服务器？ | 影响状态同步方案 | 架构 |
