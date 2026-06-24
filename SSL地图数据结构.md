# SSL 地图数据结构

本文档说明 Mission Control 地图右键 SSL 菜单点击“确认”后发送的数据结构。

## 发送方式

- 方法：`POST`
- 地址：系统设置中的 `SSL模块 / SSL发送地址`
- 请求头：`Content-Type: application/json`
- 资源列表来源：系统设置中的 `SSL资源池地址` + `资源列表接口`

## 请求示例

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

## 字段说明

| 字段 | 类型 | 说明 |
| --- | --- | --- |
| `method` | string[] | 已选择资源的 SSL 一级菜单动作名称列表，例如 `["侦察", "打击"]`。只提交有资源选择的动作。 |
| `resource_list` | string[][] | 与 `method` 下标一一对应的资源 ID 列表。`resource_list[0]` 是 `method[0]` 对应的资源列表，只包含资源 ID，不包含资源名称和描述。 |
| `object_list` | object[] | 地图上右键选中的对象列表，例如车辆、态势目标、坐标点等。 |
| `object_list[].order` | number | 对象在当前选择中的顺序，从 1 开始。 |
| `object_list[].object_id` | string | 地图对象唯一标识。 |
| `object_list[].object_type` | string | 地图对象类型，例如 `vehicle`、`situation`、`map-point`。 |
| `object_list[].name` | string | 地图对象显示名称。 |
| `object_list[].lon` | number | 对象经度。 |
| `object_list[].lat` | number | 对象纬度。 |
| `object_list[].properties` | object | 地图对象原始属性。 |

## 动作与资源对应关系

SSL 菜单左侧每个动作都有独立的资源选择状态。用户可以先点击 `侦察` 选择一组资源，再点击 `打击` 选择另一组资源；同一个资源 ID 可以出现在多个动作的资源列表中。

提交时前端只发送至少选择了一个资源的动作，并保持 `method` 与 `resource_list` 数组顺序一致：

```json
{
  "method": ["侦察", "定位", "打击"],
  "resource_list": [
    ["resource-A", "resource-B"],
    ["resource-C"],
    ["resource-A"]
  ],
  "object_list": []
}
```

上例含义为：

| 动作 | 资源 |
| --- | --- |
| `侦察` | `resource-A`、`resource-B` |
| `定位` | `resource-C` |
| `打击` | `resource-A` |

## 资源池返回值

SSL 菜单每次打开时会请求资源池接口，默认路径为：

```text
/api/v1/resource_pool/resources/get_pick
```

前端会从资源项中读取以下字段：

| 字段 | 说明 |
| --- | --- |
| `resource_id` | 资源 ID，提交时进入 `resource_list`。 |
| `resource_name` | 资源显示名称，仅用于菜单展示。 |
| `model_type` | 资源型号或类型信息，仅用于菜单展示。 |
