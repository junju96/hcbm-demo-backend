# SSL 地图数据接口说明

> 版本: 1.0.0 | 服务端口: 28600 | 服务器地址：25.11.1.222 | 基础路径: `/api/v1/ssl`

## 概述

本组接口用于接收 Mission Control 地图右键 SSL 菜单点击"确认"后发送的数据，并提供查询能力供其它模块（如杀伤链、方案规划、行动序列）调用传递数据。

数据在服务端以内存方式存储，重启后清空。如需持久化，可后续接入数据服务器。

---

## 通用约定

| 项目 | 说明 |
|------|------|
| 基础 URL | `http://localhost:28600/api/v1/ssl` |
| 请求格式 | `Content-Type: application/json` |
| 响应格式 | 统一包装为 `{code, message, data}` |
| 存储方式 | 内存列表，按 `created_at` 倒序排列 |

### 统一响应结构

```json
{
  "code": 200,
  "message": "success",
  "data": { ... }
}
```

| 字段 | 类型 | 说明 |
|------|------|------|
| `code` | int | 200 表示成功，404 表示资源不存在 |
| `message` | string | 状态描述 |
| `data` | object / null | 业务数据 |

---

## 接口列表

### 1. 接收 SSL 地图数据

接收 Mission Control 地图右键 SSL 菜单"确认"后提交的完整数据。

- **方法**: `POST`
- **路径**: `/api/v1/ssl/map-data`

#### 请求体

| 字段 | 类型 | 必填 | 说明 |
|------|------|------|------|
| `method` | `string[]` | 是 | 已选择资源的 SSL 一级菜单动作名称列表，如 `["侦察", "打击"]` |
| `resource_list` | `string[][]` | 是 | 与 `method` 下标一一对应的资源 ID 列表 |
| `object_list` | `object[]` | 是 | 地图上右键选中的对象列表 |
| `object_list[].order` | `number` | 是 | 对象在当前选择中的顺序，从 1 开始 |
| `object_list[].object_id` | `string` | 是 | 地图对象唯一标识 |
| `object_list[].object_type` | `string` | 是 | 地图对象类型：`vehicle` / `situation` / `map-point` |
| `object_list[].name` | `string` | 是 | 地图对象显示名称 |
| `object_list[].lon` | `number` | 是 | 对象经度 |
| `object_list[].lat` | `number` | 是 | 对象纬度 |
| `object_list[].properties` | `object` | 否 | 地图对象原始属性 |

#### 请求示例

```json
{
  "method": ["侦察", "打击"],
  "resource_list": [
    ["B-1", "A-1"],
    ["B-1"]
  ],
  "object_list": [
    {
      "order": 1,
      "object_id": "vehicle:10070001",
      "object_type": "vehicle",
      "name": "UGV-1",
      "lon": 121.4373,
      "lat": 31.2304,
      "properties": {
        "id": "10070001",
        "vehicle_name": "UGV-1",
        "vmf_code": "10070001"
      }
    },
    {
      "order": 2,
      "object_id": "map-point:target-2",
      "object_type": "map-point",
      "name": "目标2",
      "lon": 121.4937,
      "lat": 31.2464,
      "properties": {
        "id": "target-2",
        "name": "目标2",
        "type": "target"
      }
    }
  ]
}
```

#### 响应示例

```json
{
  "code": 200,
  "message": "success",
  "data": {
    "record_id": "ssl:a3f7b2c8d1e4",
    "method_resources": {
      "侦察": ["B-1", "A-1"],
      "打击": ["B-1"]
    },
    "object_count": 2,
    "message": "SSL 地图数据已接收"
  }
}
```

#### cURL

```bash
curl -X POST http://localhost:28600/api/v1/ssl/map-data \
  -H "Content-Type: application/json" \
  -d '{
    "method": ["侦察", "打击"],
    "resource_list": [["B-1", "A-1"], ["B-1"]],
    "object_list": [
      {
        "order": 1,
        "object_id": "vehicle:10070001",
        "object_type": "vehicle",
        "name": "UGV-1",
        "lon": 121.4373,
        "lat": 31.2304,
        "properties": {"id": "10070001", "vehicle_name": "UGV-1", "vmf_code": "10070001"}
      },
      {
        "order": 2,
        "object_id": "map-point:target-2",
        "object_type": "map-point",
        "name": "目标2",
        "lon": 121.4937,
        "lat": 31.2464,
        "properties": {"id": "target-2", "name": "目标2", "type": "target"}
      }
    ]
  }'
```

---

### 2. 获取最新 SSL 地图数据

获取最近一次接收的 SSL 地图数据，**供其它模块调用传递数据**。

- **方法**: `GET`
- **路径**: `/api/v1/ssl/map-data/latest`
- **参数**: 无

#### 响应示例

```json
{
  "code": 200,
  "message": "success",
  "data": {
    "record": {
      "record_id": "ssl:a3f7b2c8d1e4",
      "method": ["侦察", "打击"],
      "resource_list": [["B-1", "A-1"], ["B-1"]],
      "object_list": [
        {
          "order": 1,
          "object_id": "vehicle:10070001",
          "object_type": "vehicle",
          "name": "UGV-1",
          "lon": 121.4373,
          "lat": 31.2304,
          "properties": {"id": "10070001", "vehicle_name": "UGV-1", "vmf_code": "10070001"}
        }
      ],
      "created_at": "2026-05-28T09:30:00+08:00"
    },
    "method_resources": {
      "侦察": ["B-1", "A-1"],
      "打击": ["B-1"]
    },
    "objects": [
      {
        "order": 1,
        "object_id": "vehicle:10070001",
        "object_type": "vehicle",
        "name": "UGV-1",
        "lon": 121.4373,
        "lat": 31.2304,
        "properties": {"id": "10070001", "vehicle_name": "UGV-1", "vmf_code": "10070001"}
      }
    ]
  }
}
```

#### cURL

```bash
curl -s http://localhost:28600/api/v1/ssl/map-data/latest | python3 -m json.tool
```

---

### 3. 获取 SSL 地图数据列表

获取历史接收的 SSL 地图数据列表，按时间倒序排列。

- **方法**: `GET`
- **路径**: `/api/v1/ssl/map-data`

#### 查询参数

| 参数 | 类型 | 必填 | 默认值 | 说明 |
|------|------|------|--------|------|
| `limit` | `int` | 否 | 20 | 返回条数上限 |

#### 响应示例

```json
{
  "code": 200,
  "message": "success",
  "data": {
    "items": [
      {
        "record_id": "ssl:a3f7b2c8d1e4",
        "method": ["侦察", "打击"],
        "resource_list": [["B-1", "A-1"], ["B-1"]],
        "object_list": [...],
        "created_at": "2026-05-28T09:30:00+08:00"
      }
    ],
    "total": 5
  }
}
```

#### cURL

```bash
curl -s "http://localhost:28600/api/v1/ssl/map-data?limit=10" | python3 -m json.tool
```

---

### 4. 按 ID 获取单条数据

- **方法**: `GET`
- **路径**: `/api/v1/ssl/map-data/{record_id}`

#### 路径参数

| 参数 | 类型 | 说明 |
|------|------|------|
| `record_id` | `string` | 数据记录 ID，如 `ssl:a3f7b2c8d1e4` |

#### 响应示例

```json
{
  "code": 200,
  "message": "success",
  "data": {
    "record_id": "ssl:a3f7b2c8d1e4",
    "method": ["侦察", "打击"],
    "resource_list": [["B-1", "A-1"], ["B-1"]],
    "object_list": [...],
    "created_at": "2026-05-28T09:30:00+08:00"
  }
}
```

#### cURL

```bash
curl -s http://localhost:28600/api/v1/ssl/map-data/ssl:a3f7b2c8d1e4 | python3 -m json.tool
```

---

### 5. 删除单条数据

- **方法**: `DELETE`
- **路径**: `/api/v1/ssl/map-data/{record_id}`

#### 响应示例

```json
{
  "code": 200,
  "message": "success",
  "data": {
    "deleted": 1,
    "record_id": "ssl:a3f7b2c8d1e4"
  }
}
```

#### cURL

```bash
curl -s -X DELETE http://localhost:28600/api/v1/ssl/map-data/ssl:a3f7b2c8d1e4 | python3 -m json.tool
```

---

### 6. 清空所有数据

- **方法**: `POST`
- **路径**: `/api/v1/ssl/map-data/clear`

#### 响应示例

```json
{
  "code": 200,
  "message": "success",
  "data": {
    "cleared": 5
  }
}
```

#### cURL

```bash
curl -s -X POST http://localhost:28600/api/v1/ssl/map-data/clear | python3 -m json.tool
```

---

## 下游模块调用建议

### 杀伤链模块

杀伤链模块在生成或更新方案时，可调用 `/api/v1/ssl/map-data/latest` 获取最新的地图对象和资源分配信息：

```python
import requests

resp = requests.get("http://localhost:28600/api/v1/ssl/map-data/latest")
data = resp.json()["data"]

# 提取目标对象
objects = data["objects"]           # 地图上的车辆、目标点
# 提取动作-资源映射
method_resources = data["method_resources"]  # {"侦察": ["B-1"], "打击": ["A-1"]}
```

### 方案规划模块

方案规划模块可根据 `method_resources` 中的资源分配，自动生成对应的 team / stage 结构：

```python
for method, resources in data["method_resources"].items():
    # method: "侦察" / "打击" / "定位"
    # resources: ["B-1", "A-1"]
    create_stage(method=method, assigned_resources=resources)
```

---

## 数据模型

### SSLMapDataRequest

```python
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
```

---

## 调试

启动本地后端后，可通过以下地址查看自动生成的 Swagger 文档：

- Swagger UI: `http://localhost:28600/docs`
- 直接过滤标签: `http://localhost:28600/docs#/SSL地图数据`
