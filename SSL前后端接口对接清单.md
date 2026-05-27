# SSL（杀伤链）前后端接口对接清单

> 后端服务：`http://localhost:28600` | 前端项目：`demo/frontend`

---

## 一、现状概述

| 层级 | 状态 |
|------|------|
| 后端 API | ✅ 已实现 20+ 个接口（Mock 数据） |
| 前端界面 | ✅ 已实现（假数据驱动） |
| 前后端联调 | ❌ 未接入，全部使用本地假数据 |

---

## 二、可对接接口一览

### 2.1 杀伤链列表与详情

| 前端位置 | 当前实现 | 可调后端接口 | 优先级 |
|----------|----------|-------------|--------|
| `TaskPlanningPanel.vue` 左侧杀伤链列表 | `planningDataModel.js` 中 `killChainList` 假数据 | `POST /api/v1/task_pool/resources/query` (task_type=KILL_CHAIN) | P0 |
| `TaskPlanningPanel.vue` 右侧杀伤链详情 | `killChainDetailMap` 假数据 | `GET /api/v1/kill-chains/{kill_chain_id}` | P0 |
| 详情面板标题/状态/描述 | 直接读假数据字段 | 同上，解析返回 JSON 的 title/state/description | P0 |

### 2.2 杀伤链条目（Entry）管理

| 前端位置 | 当前实现 | 可调后端接口 | 优先级 |
|----------|----------|-------------|--------|
| 表格显示 raw_entries | 读假数据 `entries` 数组 | `GET /api/v1/kill-chains/{id}` 返回的 `raw_entries` / `assigned_entries` | P0 |
| "新增" 按钮 | `onAddKillChainEntry` 仅 appendSystemMessage | `POST /api/v1/kill-chains/{id}/entries` | P1 |
| "删除" 按钮 | `onDeleteKillChainEntry` 仅提示 | `DELETE /api/v1/kill-chains/{id}/entries/{entry_id}` | P1 |

### 2.3 资源分配

| 前端位置 | 当前实现 | 可调后端接口 | 优先级 |
|----------|----------|-------------|--------|
| "自动分配" 按钮 | `onAutoAllocate` 仅提示 | `POST /api/v1/kill-chains/{id}/entries/{entry_id}/auto-allocate` | P1 |
| "调整分配"/"配置装备" 弹窗确定 | `onAllocConfirm` 修改本地数据 | `POST /api/v1/kill-chains/{id}/entries/{entry_id}/allocate` | P1 |
| 执行装备标签显示 | 直接渲染 `executor_assignments` | 后端返回同名字段，无需额外接口 | P0 |

### 2.4 方案生成

| 前端位置 | 当前实现 | 可调后端接口 | 优先级 |
|----------|----------|-------------|--------|
| "生成行动方案"（未来扩展） | 暂未实现按钮 | `POST /api/v1/kill-chains/{id}/generate-plan` | P2 |

### 2.5 状态管理

| 前端位置 | 当前实现 | 可调后端接口 | 优先级 |
|----------|----------|-------------|--------|
| "激活" 按钮 | 暂未实现 | `POST /api/v1/kill-chains/{id}/activate` | P2 |
| "静默" 按钮 | 暂未实现 | `POST /api/v1/kill-chains/{id}/deactivate` | P2 |

### 2.6 SSE 实时同步（高价值）

| 前端位置 | 当前实现 | 可调后端接口 | 优先级 |
|----------|----------|-------------|--------|
| 左侧列表实时刷新 | 无，需手动切换 | `GET /api/v1/planning/events/overview?client_id=xxx&scope=planning_home` | P1 |
| 右侧详情实时刷新 | 无，点击才加载 | `GET /api/v1/planning/events/detail?client_id=xxx&resource_type=kill_chain&resource_id=xxx` | P1 |

---

## 三、前端具体代码位置

### 3.1 假数据定义文件

```
demo/frontend/src/features/mission-control/modules/coordination/data/planningDataModel.js
├── killChainList        ← 替换为 API: POST /api/v1/task_pool/resources/query
├── killChainDetailMap   ← 替换为 API: GET /api/v1/kill-chains/{id}
└── killChainDetail      ← 兼容导出，同上
```

### 3.2 列表与详情展示

```
TaskPlanningPanel.vue
├── selectedKillChainId        ← 选中后触发 API 请求
├── selectedKillChain          ← 列表项，来自 killChainList
├── currentKillChainDetail     ← computed，应改为 async/await API 调用
├── 左侧 plan-list-sub-tabs    ← 切换时无需 API
├── 右侧 kill-chain-detail-pane
│   ├── 标题/状态/描述         ← 来自 currentKillChainDetail
│   ├── 信息概览卡片           ← 同上
│   └── 原始杀伤链表           ← currentKillChainDetail.entries
```

### 3.3 操作按钮

```
TaskPlanningPanel.vue
├── onAutoAllocate()           ← 调用 POST .../auto-allocate
├── onEditKillChain()          ← 调用 PATCH /api/v1/kill-chains/{id}
├── onAddKillChainEntry()      ← 调用 POST .../entries
├── onDeleteKillChainEntry()   ← 调用 DELETE .../entries/{entry_id}
├── onEntryAction()
│   ├── '调整分配'             ← 打开弹窗（纯前端）
│   ├── '配置装备'             ← 打开弹窗（纯前端）
│   └── '地图直配'             ← 调用 POST .../allocate（人工分配）
```

### 3.4 目标分配弹窗

```
KillChainAllocationDialog.vue
├── initAllocation()           ← 读取 entry.executor_assignments（前端数据）
├── onConfirm()                ←  emit confirm，由父组件处理
│                                父组件 onAllocConfirm 应调用 API
└── 复选框勾选状态              ← 纯本地状态，确定后统一提交
```

---

## 四、推荐接入顺序

```
Phase 1: 列表 + 详情（只读）
  ├─ 左侧列表调用 POST /task_pool/resources/query
  ├─ 右侧详情调用 GET /kill-chains/{id}
  └─ 删除 planningDataModel.js 中 killChainList/killChainDetailMap

Phase 2: 条目操作（增删改）
  ├─ 新增条目 → POST /kill-chains/{id}/entries
  ├─ 删除条目 → DELETE /kill-chains/{id}/entries/{entry_id}
  └─ 自动分配 → POST .../auto-allocate

Phase 3: SSE 实时同步
  ├─ 连接 overview SSE 流
  ├─ 连接 detail SSE 流
  └─ 用事件推送替代手动刷新

Phase 4: 方案生成 + 状态切换
  ├─ 生成方案 → POST .../generate-plan
  └─ 激活/静默 → POST .../activate / deactivate
```

---

## 五、前端需新增的通用模块

| 模块 | 用途 | 建议位置 |
|------|------|----------|
| `api/killChain.js` | 封装所有杀伤链 HTTP 请求 | `src/api/` 或 `src/services/` |
| `api/sse.js` | SSE 连接管理（EventSource） | 同上 |
| `stores/killChainStore.js` | Pinia/Vuex 状态管理（可选） | `src/stores/` |

---

## 六、后端 CORS 已配置

```python
# demo/backend/app/main.py
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],   ← 前端 localhost:5173 可直接访问
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)
```

前端可直接使用 `fetch` 或 `axios` 调用后端，无需额外代理配置。
