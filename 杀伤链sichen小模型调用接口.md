# 火力规划服务 (Fire Plan Service)

基于匈牙利算法的多战车多目标火力分配与行动序列校验微服务。

## 基本信息

| 项目 | 值                |
| ---- | ----------------- |
| IP   | `0.0.0.0`         |
| 端口 | `28504`           |
| 协议 | HTTP              |
| 框架 | FastAPI + Uvicorn |

## 路由

### 1. GET /health

健康检查。

**请求示例**
```bash
curl http://localhost:28504/health
```

**响应示例（200）**
```json
{"status": "ok"}
```

---

### 2. POST /plan

火力规划：根据战车、目标、装备能力和路网信息，进行多波次火力分配。

**请求方式**：POST `http://localhost:28504/plan`

**请求体**
```json
{
  "vehicles_data": {
    "vehicles": [
      {
        "vehicle_id": "V-01",
        "platform_type": "light",
        "longitude": 116.117420,
        "latitude": 39.748853,
        "ammunition": [
          {"ammo_type": "FTK", "ammo_count": 4},
          {"ammo_type": "P40", "ammo_count": 20}
        ],
        "faults": []
      }
    ]
  },
  "targets_data": {
    "fixed_targets": [
      {
        "target_id": "T-001",
        "name": "敌指挥部",
        "type": "239",
        "center_position": {"lat": 39.76, "lon": 116.128},
        "object_level": "特级",
        "threat": 100,
        "object_requirement_result": "彻底摧毁"
      }
    ],
    "moving_targets": [
      {
        "target_id": "T-002",
        "name": "发射车",
        "type": "100",
        "center_position": {"lat": 39.766, "lon": 116.145},
        "object_level": "特级",
        "threat": 95,
        "speed": 10,
        "object_requirement_result": "优先摧毁"
      }
    ]
  },
  "capability": {
    "weapons": {
      "FTK": {
        "range_max": 6000,
        "ammo_cost": 2000,
        "prep_time": 8.0,
        "fire_interval": 3.0,
        "base_prob": {"239": 0.95, "100": 0.9}
      }
    },
    "platforms": {
      "light": {"max_speed": 60, "avg_speed": 40},
      "medium": {"max_speed": 80, "avg_speed": 55}
    },
    "req_prob_map": {
      "彻底摧毁": 0.90,
      "优先摧毁": 0.85,
      "摧毁": 0.80,
      "拦截": 0.70,
      "压制": 0.50
    }
  },
  "road_network": {
    "roads": [{"road_id": 1, "node_id": [1, 2]},
              {"road_id": 2, "node_id": [2, 3]}],
    "nodes": [{"node_id": 1, "lat": 39.766, "lng": 116.131},
              {"node_id": 2, "lat": 39.765, "lng": 116.130},
              {"node_id": 3, "lat": 39.765, "lng": 116.130}]
  },
  "forbidden": [],
  "weights": [0.6, 0.2, 0.2]
}
```

**请求参数说明**

| 字段            | 类型   | 必填 | 说明                                                    |
| --------------- | ------ | ---- | ------------------------------------------------------- |
| `vehicles_data` | object | 是   | 战车数据，包含 `vehicles` 列表                          |
| `targets_data`  | object | 是   | 目标数据，包含 `fixed_targets` 和 `moving_targets` 列表 |
| `capability`    | object | 是   | 装备能力参数（武器参数、平台参数、毁伤要求映射）        |
| `road_network`  | object | 否   | 路网数据（roads + nodes），不传则火力点不受路网约束     |
| `forbidden`     | array  | 否   | 禁行区列表                                              |
| `weights`       | array  | 否   | 优化权重 (毁伤, 时间, 成本)，默认 `[0.6, 0.2, 0.2]`     |

**响应示例（200）**
```json
{
  "report": {
    "global_metrics": {
      "total_mission_time_seconds": 120.5,
      "total_economic_cost": 5400.0,
      "mission_accomplishment_rate": 1.0
    },
    "vehicle_missions": {}
  },
  "vehicle_missions": {
    "V-01": [
      {
        "target_id": "T-001",
        "target_name": "敌指挥部",
        "weapon": "FTK",
        "planned_ammo": 3,
        "fire_position_lng_lat": [116.128, 39.76],
        "time_seconds": 45.2,
        "damage_probability": 0.95,
        "cost": 6200.0
      }
    ]
  }
}
```

**响应字段说明**

| 字段                                                | 说明                                         |
| --------------------------------------------------- | -------------------------------------------- |
| `report.global_metrics.total_mission_time_seconds`  | 任务总耗时（全网最慢车辆的累积时间）         |
| `report.global_metrics.total_economic_cost`         | 总经济成本                                   |
| `report.global_metrics.mission_accomplishment_rate` | 任务完成率                                   |
| `vehicle_missions.{vid}[].attack_result`            | 每个任务包含武器、弹药、阵位、毁伤概率等详情 |

---

### 3. POST /validate

行动序列校验：对已生成的火力分配结果进行多维合法性校验，包括禁行区、弹药库存、毁伤达标、目标覆盖等。

**请求方式**：POST `http://localhost:28504/validate`

**请求体**
```json
{
  "vehicles_data": { "vehicles": [...] },
  "targets_data": { "fixed_targets": [...], "moving_targets": [...] },
  "capability": { "weapons": {...}, "platforms": {...}, "req_prob_map": {...} },
  "action_sequences": {
    "V-01": [
      {"sid": 1, "points": [{"lon": 116.128, "lat": 39.76}]},
      {"sid": 101, "points": [{"lon": 116.128, "lat": 39.76, "sug": 3}]}
    ]
  },
  "road_network": {...},
  "forbidden": [...]
}
```

**响应示例（200）**
```json
{
  "is_valid": false,
  "issues": [
    {
      "type": "目标遗漏",
      "vid": "Global",
      "desc": "存在未被分配火力覆盖的目标：T-002。"
    }
  ]
}
```

---

### 4. POST /export-sequence

行动序列导出：将 `/plan` 返回的规划报表（report）转化为标准 C2 系统所需的「机动-打击」交替式行动序列 JSON 格式。支持智能合并——连续同武器的打击任务会自动聚合为一条指令的多个 point。

**请求方式**：POST `http://localhost:28504/export-sequence`

**请求体**
```json
{
  "vehicles_data": {
    "vehicles": [
      {
        "vehicle_id": "V-01",
        "platform_type": "light",
        "longitude": 116.117420,
        "latitude": 39.748853,
        "ammunition": [
          {"ammo_type": "FTK", "ammo_count": 4},
          {"ammo_type": "P40", "ammo_count": 20}
        ],
        "faults": []
      }
    ]
  },
  "targets_data": {
    "fixed_targets": [
      {
        "target_id": "T-001",
        "name": "敌指挥部",
        "type": "239",
        "center_position": {"lat": 39.76, "lon": 116.128},
        "object_level": "特级",
        "threat": 100,
        "object_requirement_result": "彻底摧毁"
      }
    ],
    "moving_targets": []
  },
  "capability": {
    "weapons": {
      "FTK": {
        "range_max": 6000,
        "ammo_cost": 2000,
        "prep_time": 8.0,
        "fire_interval": 3.0,
        "base_prob": {"239": 0.95}
      }
    },
    "platforms": {
      "light": {"max_speed": 60, "avg_speed": 40}
    },
    "weapon_id_map": {
      "FTK": 101,
      "P40": 102
    }
  },
  "report_data": {
    "vehicle_missions": {
      "V-01": {
        "vehicle_operational_time_seconds": 120.5,
        "tasks": [
          {
            "target_id": "T-001",
            "target_name": "敌指挥部",
            "selected_weapon": "FTK",
            "planned_ammo_consumption": 3,
            "fire_position_lng_lat": [116.128, 39.76],
            "maneuver_time_seconds": 45.2,
            "damage_probability": 0.95,
            "task_cost": 6200.0
          }
        ]
      }
    }
  }
}
```

**请求参数说明**

| 字段            | 类型   | 必填 | 说明                                                  |
| --------------- | ------ | ---- | ----------------------------------------------------- |
| `vehicles_data` | object | 是   | 战车数据，与 `/plan` 请求格式一致                     |
| `targets_data`  | object | 是   | 目标数据，与 `/plan` 请求格式一致                     |
| `capability`    | object | 是   | 装备能力参数（需额外包含 `weapon_id_map` 数字映射）   |
| `report_data`   | object | 是   | `/plan` 返回的 `report` 对象（含 `vehicle_missions`） |

**响应示例（200）**
```json
{
  "action_sequences": {
    "V-01": [
      {
        "sid": 1,
        "points": [
          {
            "lon": 116.128,
            "lat": 39.76,
            "alt": 0.0,
            "radius": -1,
            "yaw": -1,
            "Speed": 48.0
          }
        ],
        "limited_speed": 48.0,
        "safe_mode": 0
      },
      {
        "sid": 101,
        "time": 45.2,
        "sort": 1,
        "num": 1,
        "points": [
          {
            "tart": 239,
            "attr": 1,
            "lon": 116.128,
            "lat": 39.76,
            "alt": 999999.0,
            "thr": 100,
            "dam": 1,
            "blk": 0,
            "figt": 2,
            "sug": 3
          }
        ]
      }
    ]
  }
}
```

**响应字段说明**

| 字段                                         | 说明                                            |
| -------------------------------------------- | ----------------------------------------------- |
| `action_sequences.{vid}`                     | 每辆战车的行动序列列表                          |
| `action_sequences.{vid}[].sid`               | 指令类型：`1` 为机动任务，其余值为武器 SID 编号 |
| `action_sequences.{vid}[].points`            | 指令路径点列表                                  |
| `action_sequences.{vid}[].points[].lon/.lat` | 目标点经纬度                                    |
| `action_sequences.{vid}[].points[].sug`      | 建议弹药消耗量（仅打击任务有）                  |
| `action_sequences.{vid}[].points[].Speed`    | 机动速度（仅机动任务有）                        |

---

## 启动方式

```bash
cd backend/services/fire_plan_service/app
python main.py
```

## 依赖

- fastapi
- uvicorn
- scipy
- numpy
