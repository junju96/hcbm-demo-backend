# Zenoh 配置使用说明

本文说明 Zenoh 桥接服务如何通过共享 `backend/zenoh_py/zenoh_service.py` 加载配置。

## 1. 默认配置文件

- 文件路径：`backend/services/zenoh_bridge_service/config/zenoh.json5`
- 当前默认内容用于连接本机路由器 `tcp/127.0.0.1:7447`
- 服务级默认订阅配置文件：`backend/services/zenoh_bridge_service/config/zenoh_service.json`

## 2. 配置加载优先级

服务启动时按以下顺序取配置：

1. `ZENOH_CONFIG_JSON5`（直接传 JSON5 文本）
2. `ZENOH_CONFIG_PATH`（传文件路径）
3. `backend/services/zenoh_bridge_service/config/zenoh.json5`（默认文件）
4. 若以上都没有，则尝试 `zenoh.Config()` 默认配置

默认订阅主题按以下顺序加载：

1. `ZENOH_SERVICE_CONFIG_JSON`（直接传 JSON 文本）
2. `ZENOH_SERVICE_CONFIG_PATH`（传服务配置文件路径）
3. `backend/services/zenoh_bridge_service/config/zenoh_service.json`（默认服务配置文件）

服务启动时会自动读取 `default_subscriptions`，并立即建立订阅。

## 2.1 默认订阅主题配置格式

```json
{
  "local_peer_fallback": true,
  "default_subscriptions": [
    "demo/topic",
    {
      "topic": "demo/telemetry",
      "buffer_size": 1000
    }
  ]
}
```

## 3. 使用方式

### 3.1 使用默认配置

```bash
conda activate fastapi
python -m uvicorn backend.services.zenoh_bridge_service.app.main:app --host 0.0.0.0 --port 28003
```

### 3.2 使用自定义配置文件

```bash
conda activate fastapi
set ZENOH_CONFIG_PATH=D:\1206_project\backend\config\zenoh.json5
python -m uvicorn backend.services.zenoh_bridge_service.app.main:app --host 0.0.0.0 --port 28003
```

### 3.3 使用环境变量直接注入配置

```bash
conda activate fastapi
set ZENOH_CONFIG_JSON5={mode:"client",connect:{endpoints:["tcp/192.168.1.10:7447"]}}
python -m uvicorn backend.services.zenoh_bridge_service.app.main:app --host 0.0.0.0 --port 28003
```

### 3.4 使用服务配置文件自动订阅默认主题

```bash
conda activate fastapi
python -m uvicorn backend.services.zenoh_bridge_service.app.main:app --host 0.0.0.0 --port 28003
```

启动后会自动读取 `backend/services/zenoh_bridge_service/config/zenoh_service.json` 中的 `default_subscriptions` 并订阅。

说明：

- 桥接服务已不再维护自己的 `app/zenoh_service.py` 副本。
- 服务启动时会先给共享 Zenoh 模块注入本服务默认配置路径，再按上面的优先级解析配置。
- `local_peer_fallback` 现在只从 `zenoh_service.json` 配置中读取，不再单独读取 `ZENOH_LOCAL_PEER_FALLBACK` 系统变量。
- 当 `local_peer_fallback` 为 `true` 时，如果 router 不可用，会退回到当前进程内的本地 peer 测试模式；为 `false` 时则直接返回连接失败。

