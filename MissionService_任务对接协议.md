# MissionService 任务对接协议

## 1. 文档目的

本文档用于任务类接口，明确说明：

- 任务下发使用的 topic
- 请求 payload 的统一外层格式
- 任务文件内部 JSON 结构
- 各类元任务的 JSON 格式
- 任务控制指令格式
- 当前代理会发布的反馈 topic 和反馈内容

## 2. 总体约定

### 2.1 推荐对接入口

推荐同事统一走标准命令 topic：

```text
op/t{team}/g{group}/v{vehicle}/cmd/MissionService/{action}
```

说明：

- `team`：队伍编号，例如 `0`
- `group`：分组编号，例如 `0`
- `vehicle`：车辆编号，例如 `ZD04`
- 实际 topic 中车辆段需要写成 `v{vehicle}`，例如 `vZD04`
- `action`：具体动作，例如 `send_mission`、`control_mission`

示例：

```text
op/t0/g0/vZD04/cmd/MissionService/send_mission
op/t0/g0/vZD04/cmd/MissionService/control_mission
```

### 2.2 请求 payload 外层统一格式

所有发送给 `MissionService` 的命令，统一使用如下 JSON：

```json
{
  "service": "MissionService",
  "action": "<action>",
  "args": {
  }
}
```

说明：

- `service` 固定为 `MissionService`
- `action` 与 topic 最后一段保持一致
- 业务参数全部放在 `args` 内

## 3. 任务下发协议

### 3.1 Topic

```text
op/t{team}/g{group}/v{vehicle}/cmd/MissionService/send_mission
```

### 3.2 外层 payload

```json
{
  "service": "MissionService",
  "action": "send_mission",
  "args": {
    "mission_data": {
    }
  }
}
```

### 3.3 `mission_data` 总体说明

`mission_data` 直接传任务 JSON 对象。

当前 `MissionService` 的实现约定如下：

- 上层可以直接发送完整任务 JSON
- `MissionService` 会自动选出当前代理对应的车辆
- `MissionService` 内部会按 `acts` 自动拆成多个单行动 `0x02A20901`
- 从车端协议角度，`0x02A20901` 仍然满足“单包单行动”

### 3.4 当前代码对车辆选择的规则

`MissionService` 处理完整任务时，按如下规则选择当前车：

1. 约定对接时 `task.vehicles[].vid` 传当前车辆的 `vmf` 数字编号
2. 如果没匹配到，则退回 `vehicles` 数组中的第一辆

因此建议任务软件对接时：

- `task.vehicles[].vid` 明确填写当前车辆的 `vmf`，类型为 `uint64`
- topic 里的 `v{vehicle}` 继续使用平台路由车号，例如 `vZD04`

### 3.5 `mission_data` 顶层结构

```json
{
  "task": {
    "tid": 10001,
    "type": 0,
    "cnt": "演示任务",
    "start": "2026-05-28 10:00:00",
    "end": "2026-05-28 10:30:00",
    "vehicles": [
      {
        "vid": 99076716,
        "cnt": "ZD04任务",
        "acts": [
        ]
      }
    ]
  }
}
```

### 3.6 任务 JSON 字段说明

#### `task` 级字段

| 字段 | 类型 | 必填 | 说明 |
| --- | --- | --- | --- |
| `tid` | uint64 | 是 | 任务编号 |
| `type` | uint8 | 否 | 任务类型，默认 `0` |
| `cnt` | string | 否 | 任务描述 |
| `start` | string | 否 | 任务开始时间，格式 `YYYY-MM-DD hh:mm:ss` |
| `end` | string | 否 | 任务结束时间，格式 `YYYY-MM-DD hh:mm:ss` |
| `vehicles` | array | 是 | 车辆任务列表 |

#### `task.vehicles[]` 级字段

| 字段 | 类型 | 必填 | 说明 |
| --- | --- | --- | --- |
| `vid` | uint64 | 是 | 本车车辆数字编号，按 `vmf` 传，例如 `99076716` |
| `cnt` | string | 否 | 本车任务描述 |
| `acts` | array | 是 | 本车行动列表 |

#### `task.vehicles[].acts[]` 级字段

| 字段 | 类型 | 必填 | 说明 |
| --- | --- | --- | --- |
| `aid` | uint16 | 是 | 行动编号，从 1 递增 |
| `num` | uint8 | 建议填 | 当前车行动总数，建议所有 act 中保持一致 |
| `vid` | array[uint64] | 建议填 | 协同车辆数字编号列表，按 `vmf` 传，无协同时长度为 1 |
| `vip` | array[string] | 建议填 | 协同车辆 IP 列表，无协同时长度为 1 |
| `strategy` | uint8 | 建议填 | 断连后策略，`0` 停车，`1` 返航，`2` 继续任务 |
| `start` | string | 否 | 行动开始时间 |
| `end` | string | 否 | 行动结束时间 |
| `premise` | array[uint8] | 否 | 前置行动编号列表 |
| `endwith` | int | 否 | 当前行动终止条件，默认 `-1` |
| `level` | uint8 | 否 | 重要程度，默认 `0` |
| `service` | object | 是 | 元任务服务体 |

## 4. 元任务 `service` JSON 格式

本节给出 `1.2.2` 对应的 JSON 结构。

### 4.1 自主机动 `sid = 1`

```json
{
  "sid": 1,
  "points": [
    {
      "lon": 116397128,
      "lat": 39909231,
      "alt": 435,
      "radius": -1,
      "type": 1
    },
    {
      "lon": 116397500,
      "lat": 39909500,
      "alt": 435,
      "radius": -1,
      "type": 1
    }
  ],
  "limited_speed": 20,
  "safe_mode": 0,
  "loop_mode": 0
}
```

字段说明：

- `sid`：固定 `1`
- `points`：路径点数组，至少 2 个点
- `lon`：经度，按 `1e6` 放大后的整数
- `lat`：纬度，按 `1e6` 放大后的整数
- `alt`：海拔，按 `10` 放大后的整数
- `radius`：调整半径，`-1` 表示不约束
- `type`：`1` 路网必经点，`2` 非路网必经点，`3` 禁行点
- `limited_speed`：限速，单位 `km/h`
- `safe_mode`：`0` 避障，`1` 突击，`2` 停障
- `loop_mode`：`0` 不绕圈，`-1` 一直绕圈

当前代码要求：

- `sid = 1` 时，`points` 至少 2 个
- 每个点必须有 `lon`、`lat`

### 4.2 静默值守 `sid = 4`

```json
{
  "sid": 4,
  "time": 20
}
```

字段说明：

- `sid`：固定 `4`
- `time`：静默时长，单位秒

### 4.3 设置返航点 `sid = 5`

```json
{
  "sid": 5
}
```

说明：

- 当前代码可接收该结构
- 当前 demo 不会给返航点设置专门动作效果，默认按短时驻留处理

### 4.4 开启返航 `sid = 6`

```json
{
  "sid": 6
}
```

说明：

- 当前代码可接收该结构
- 当前 demo 不会给返航专门动作效果，默认按短时驻留处理

### 4.5 跟随机动 `sid = 2`

```json
{
  "sid": 2,
  "x": 960,
  "y": 540,
  "width": 1920,
  "height": 1080,
  "limited_speed": 15,
  "safe_mode": 0,
  "strategy": 0
}
```

字段说明：

- `sid`：固定 `2`
- `x`、`y`：图像坐标
- `width`、`height`：图像尺寸
- `limited_speed`：限速，单位 `km/h`
- `safe_mode`：安全模式
- `strategy`：`0` 定位跟随，`1` 非定位跟随

说明：

- 当前 demo 可接收该结构
- 当前 demo 不会真正模拟跟随目标运动，默认按短时驻留处理

### 4.6 编队机动 `sid = 7`

```json
{
  "sid": 7,
  "points": [
    {
      "lon": 116397128,
      "lat": 39909231,
      "alt": 435,
      "offsetX": 0,
      "offsetY": 0
    },
    {
      "lon": 116397500,
      "lat": 39909500,
      "alt": 435,
      "offsetX": 0,
      "offsetY": 0
    }
  ],
  "limited_speed": 20,
  "formation_mode": 0,
  "safe_mode": 0
}
```

说明：

- 当前 demo 可接收该结构
- 当前 demo 不会给编队机动专门动作效果，默认按短时驻留处理

### 4.7 姿态调整 `sid = 9`

```json
{
  "sid": 9,
  "pose": [9000, 0, 0],
  "pose_deviation": [100, 100, 100],
  "limited_speed": 10,
  "safe_mode": 0
}
```

说明：

- `pose` / `pose_deviation` 为数组
- 当前 demo 可接收该结构
- 当前 demo 不会专门模拟姿态变化，默认按短时驻留处理

### 4.8 人工任务 `sid = 8`

```json
{
  "sid": 8,
  "type": 1
}
```

字段说明：

- `sid`：固定 `8`
- `type`：`1` 人工保障，`2` 人工打击，`3` 飞无人机

说明：

- 当前 demo 会把 `sid = 8` 当成等待型 action 处理

## 5. 任务控制协议

### 5.1 Topic

```text
op/t{team}/g{group}/v{vehicle}/cmd/MissionService/control_mission
```

### 5.2 payload

```json
{
  "service": "MissionService",
  "action": "control_mission",
  "args": {
    "taskid": 10001,
    "aid": 0,
    "task_control": 1,
    "action_control": 0
  }
}
```

### 5.3 字段说明

| 字段 | 类型 | 必填 | 说明 |
| --- | --- | --- | --- |
| `taskid` | uint64 | 是 | 任务编号 |
| `aid` | uint16 | 是 | 行动编号，整任务控制时建议填 `0` |
| `task_control` | uint8 | 建议填 | 任务控制码 |
| `action_control` | uint8 | 建议填 | 行动控制码 |

### 5.4 控制码说明

#### `task_control`

| 值 | 含义 |
| --- | --- |
| `0` | 无效 |
| `1` | 开始 |
| `2` | 暂停 |
| `3` | 继续 |
| `4` | 停止 |
| `5` | 规划 |
| `6` | 立即执行 |

#### `action_control`

| 值 | 含义 |
| --- | --- |
| `0` | 无效 |
| `1` | 开始 |
| `2` | 暂停 |
| `3` | 继续 |
| `4` | 停止 |
| `6` | 立即执行 |

### 5.5 当前 demo 行为说明

当前 `MissionService` 的 demo 行为是：

- 透传 `task_control` 和 `action_control` 到车端协议
- 本地 demo 只响应整任务控制
- 因此建议同事对 demo 发：
  - `aid = 0`
  - `action_control = 0`
  - 只通过 `task_control` 控整任务

## 6. 当前代理发布的反馈

### 6.1 命令执行 ACK

每次命令通过标准 cmd topic 进入代理后，代理会发布 ACK：

```text
mgmt/t{team}/g{group}/v{vehicle}/cmd/ack
```

ACK 典型格式：

```json
{
  "status": "ok",
  "result_code": 200,
  "message": "",
  "vehicle_id": "vZD04",
  "service": "MissionService",
  "action": "send_mission",
  "timestamp": 1780000000000,
  "cmd_seq": 12,
  "session_id": 0,
  "result": {
    "status": "success",
    "message": "Mission data split and queued for sending",
    "action_count": 3
  }
}
```

### 6.2 任务文件接收反馈

topic：

```text
op/t{team}/g{group}/v{vehicle}/mission/task_received_status
```

当前发布格式：

```json
{
  "tid": 10001,
  "recv_num": 3,
  "received_aids": [
    { "aid": 1, "status": 0 },
    { "aid": 2, "status": 0 },
    { "aid": 3, "status": 0 }
  ],
  "vehicle_id": "ZD04",
  "VMF": 99076716
}
```

字段说明：

- `tid`：任务编号
- `recv_num`：已接收行动数
- `received_aids`：行动确认列表
- `status = 0`：当前表示已接收成功

### 6.3 任务执行状态发布

topic：

```text
op/t{team}/g{group}/v{vehicle}/mission/mission_status
```

当前发布格式：

```json
{
  "vehicle_id": "ZD04",
  "VMF": 99076716,
  "mission_id": 10001,
  "action_count": 3,
  "actions": [
    { "action_id": 1, "status": 1 },
    { "action_id": 2, "status": 0 },
    { "action_id": 3, "status": 0 }
  ],
  "passability": 100,
  "phase": 1,
  "started": true,
  "paused": false,
  "finished": false,
  "low_oil_triggered": false
}
```

`actions[].status` 说明：

| 值 | 含义 |
| --- | --- |
| `0` | 未开始 |
| `1` | 执行中 |
| `2` | 暂停 |
| `3` | 已完成 |
| `4` | 停止/终止 |

### 6.4 位置发布

topic：

```text
op/t{team}/g{group}/v{vehicle}/navi/data
```

说明：

- 任务开始后，自主机动 `sid = 1` 期间位置会实时更新
- 当前自主机动速度由 `service.limited_speed` 控制
- 非机动类 action 位置不会继续运动

### 6.5 底盘资源发布

topic：

```text
op/t{team}/g{group}/v{vehicle}/resource/chassis_resource
```

当前发布格式：

```json
{
  "timestamp": "2026-04-27 14:32:19.004",
  "vehicle_id": "ZD04",
  "VMF": 99076716,
  "vehicle_type": 2,
  "fuel": 73,
  "battery": 91
}
```

说明：

- `fuel`：当前油量
- `battery`：当前电量
- 任务执行期间如触发低油，`fuel` 会变化

## 7. 协议示例

本节给出完整示例，建议直接发给同事作为联调模板。

### 7.1 完整任务示例

示例场景：

- `act1`：自主机动
- `act2`：静默值守
- `act3`：自主机动

请求 topic：

```text
op/t0/g0/vZD04/cmd/MissionService/send_mission
```

请求 payload：

```json
{
  "service": "MissionService",
  "action": "send_mission",
  "args": {
    "mission_data": {
      "task": {
        "tid": 10001,
        "type": 0,
        "cnt": "演示任务",
        "start": "2026-05-28 10:00:00",
        "end": "2026-05-28 10:30:00",
        "vehicles": [
          {
            "vid": 99076716,
            "cnt": "ZD04任务",
            "acts": [
              {
                "aid": 1,
                "num": 3,
                "vid": [99076716],
                "vip": ["192.168.1.11"],
                "strategy": 2,
                "start": "2026-05-28 10:00:00",
                "end": "2026-05-28 10:05:00",
                "premise": [],
                "endwith": -1,
                "level": 0,
                "service": {
                  "sid": 1,
                  "points": [
                    { "lon": 116397128, "lat": 39909231, "alt": 435, "radius": -1, "type": 1 },
                    { "lon": 116397500, "lat": 39909500, "alt": 435, "radius": -1, "type": 1 }
                  ],
                  "limited_speed": 20,
                  "safe_mode": 0,
                  "loop_mode": 0
                }
              },
              {
                "aid": 2,
                "num": 3,
                "vid": [99076716],
                "vip": ["192.168.1.11"],
                "strategy": 2,
                "start": "2026-05-28 10:05:00",
                "end": "2026-05-28 10:10:00",
                "premise": [1],
                "endwith": -1,
                "level": 0,
                "service": {
                  "sid": 4,
                  "time": 20
                }
              },
              {
                "aid": 3,
                "num": 3,
                "vid": [99076716],
                "vip": ["192.168.1.11"],
                "strategy": 2,
                "start": "2026-05-28 10:10:00",
                "end": "2026-05-28 10:15:00",
                "premise": [2],
                "endwith": -1,
                "level": 0,
                "service": {
                  "sid": 1,
                  "points": [
                    { "lon": 116397500, "lat": 39909500, "alt": 435, "radius": -1, "type": 1 },
                    { "lon": 116398000, "lat": 39910000, "alt": 435, "radius": -1, "type": 1 }
                  ],
                  "limited_speed": 20,
                  "safe_mode": 0,
                  "loop_mode": 0
                }
              }
            ]
          }
        ]
      }
    }
  }
}
```

### 7.2 开始任务示例

请求 topic：

```text
op/t0/g0/vZD04/cmd/MissionService/control_mission
```

请求 payload：

```json
{
  "service": "MissionService",
  "action": "control_mission",
  "args": {
    "taskid": 10001,
    "aid": 0,
    "task_control": 1,
    "action_control": 0
  }
}
```

### 7.3 暂停任务示例

```json
{
  "service": "MissionService",
  "action": "control_mission",
  "args": {
    "taskid": 10001,
    "aid": 0,
    "task_control": 2,
    "action_control": 0
  }
}
```

### 7.4 继续任务示例

```json
{
  "service": "MissionService",
  "action": "control_mission",
  "args": {
    "taskid": 10001,
    "aid": 0,
    "task_control": 3,
    "action_control": 0
  }
}
```

### 7.5 停止任务示例

```json
{
  "service": "MissionService",
  "action": "control_mission",
  "args": {
    "taskid": 10001,
    "aid": 0,
    "task_control": 4,
    "action_control": 0
  }
}
```

## 8. 对接建议

- 对 demo 联调，优先使用 `sid = 1 + sid = 4 + sid = 1`
- `send_mission` 直接发完整任务 JSON，不需要手工拆包
- `control_mission` 对 demo 建议只发整任务控制
- 先重点看以下 topic：
  - `mgmt/t{team}/g{group}/v{vehicle}/cmd/ack`
  - `op/t{team}/g{group}/v{vehicle}/mission/task_received_status`
  - `op/t{team}/g{group}/v{vehicle}/mission/mission_status`
  - `op/t{team}/g{group}/v{vehicle}/navi/data`
  - `op/t{team}/g{group}/v{vehicle}/resource/chassis_resource`
