# -*- coding: utf-8 -*-
"""运行时配置覆盖 + 调试接口测试 — 全部用临时文件，不碰真实 runtime_config.json / zenoh.json5"""
import json
import os
import sys
import tempfile
import unittest
from unittest.mock import MagicMock, patch

from fastapi.testclient import TestClient

from app import config as app_config
from app.routers import debug as debug_api
from app.main import app


_ZENOH_JSON5_TEMPLATE = """{{
  // zenoh 客户端配置（注释必须保留）
  mode: "client",
  connect: {{
    endpoints: [
      "{endpoint}"
    ]
  }},
  listen: {{
    endpoints: [
      "tcp/0.0.0.0:0"
    ]
  }}
}}
"""


class _TempConfigBase(unittest.TestCase):
    """把 runtime_config 路径与内存覆盖表、zenoh.json5 路径隔离到临时文件"""

    def setUp(self):
        self._tmpdir = tempfile.TemporaryDirectory()
        self.runtime_path = os.path.join(self._tmpdir.name, "runtime_config.json")
        self.zenoh_path = os.path.join(self._tmpdir.name, "zenoh.json5")
        with open(self.zenoh_path, "w", encoding="utf-8") as f:
            f.write(_ZENOH_JSON5_TEMPLATE.format(endpoint="tcp/25.11.1.3:7447"))
        self._patchers = [
            patch.object(app_config, "RUNTIME_CONFIG_PATH", self.runtime_path),
            patch.object(app_config, "_RUNTIME_OVERRIDES", {}),
            patch.object(debug_api, "ZENOH_CONFIG_PATH", self.zenoh_path),
        ]
        for p in self._patchers:
            p.start()
        self.addCleanup(self._cleanup)

    def _cleanup(self):
        for p in self._patchers:
            p.stop()
        self._tmpdir.cleanup()


class TestRuntimeOverrides(_TempConfigBase):
    def test_update_and_get_roundtrip(self):
        result = app_config.update_runtime_overrides({
            "DATA_SERVER_BASE_URL": "http://10.0.0.1:28801",
        })
        self.assertEqual(result["DATA_SERVER_BASE_URL"], "http://10.0.0.1:28801")
        # 内存与文件一致
        with open(self.runtime_path, encoding="utf-8") as f:
            self.assertEqual(json.load(f), result)
        self.assertEqual(app_config.get_runtime_overrides(), result)
        # getter 读覆盖值
        self.assertEqual(app_config.get_data_server_url(), "http://10.0.0.1:28801")
        # 未覆盖键仍走默认
        self.assertEqual(app_config.get_resource_pool_url(), app_config.RESOURCE_POOL_BASE_URL)

    def test_update_merges_patch(self):
        app_config.update_runtime_overrides({"DATA_SERVER_BASE_URL": "http://10.0.0.1:28801"})
        result = app_config.update_runtime_overrides({"RESOURCE_POOL_BASE_URL": "http://10.0.0.2:28800"})
        self.assertEqual(result["DATA_SERVER_BASE_URL"], "http://10.0.0.1:28801")
        self.assertEqual(result["RESOURCE_POOL_BASE_URL"], "http://10.0.0.2:28800")

    def test_seat_target_ips_valid(self):
        seats = {"1": "10.0.0.9", "ck": "10.0.0.10"}
        app_config.update_runtime_overrides({"SEAT_TARGET_IPS": seats})
        self.assertEqual(app_config.get_seat_target_ips(), seats)

    def test_invalid_url_rejected(self):
        # 空串已改为合法的"删除覆盖、恢复默认"语义，见 test_empty_string_restores_default
        for bad in ("25.11.1.178:28801", "tcp/25.11.1.178:28801", 123, None):
            with self.assertRaises(ValueError) as ctx:
                app_config.update_runtime_overrides({"DATA_SERVER_BASE_URL": bad})
            self.assertIn("DATA_SERVER_BASE_URL", str(ctx.exception))

    def test_empty_string_restores_default(self):
        app_config.update_runtime_overrides({"DATA_SERVER_BASE_URL": "http://10.0.0.1:28801"})
        self.assertEqual(app_config.get_data_server_url(), "http://10.0.0.1:28801")
        # 空串删除覆盖键，恢复默认
        result = app_config.update_runtime_overrides({"DATA_SERVER_BASE_URL": ""})
        self.assertNotIn("DATA_SERVER_BASE_URL", result)
        self.assertEqual(app_config.get_data_server_url(), app_config.DATA_SERVER_BASE_URL)
        # 未知键的空串同样拒绝
        with self.assertRaises(ValueError):
            app_config.update_runtime_overrides({"SOME_UNKNOWN_KEY": ""})

    def test_invalid_seat_ips_rejected(self):
        for bad in ("not-a-dict", {"1": 28801}, {"1": "25.11.1.56:28801"}, {"1": "not-an-ip"}):
            with self.assertRaises(ValueError) as ctx:
                app_config.update_runtime_overrides({"SEAT_TARGET_IPS": bad})
            self.assertIn("SEAT_TARGET_IPS", str(ctx.exception))

    def test_unknown_key_rejected(self):
        with self.assertRaises(ValueError) as ctx:
            app_config.update_runtime_overrides({"SOME_UNKNOWN_KEY": "x"})
        self.assertIn("SOME_UNKNOWN_KEY", str(ctx.exception))

    def test_validation_failure_does_not_persist(self):
        with self.assertRaises(ValueError):
            app_config.update_runtime_overrides({"DATA_SERVER_BASE_URL": "bad"})
        self.assertEqual(app_config.get_runtime_overrides(), {})
        self.assertFalse(os.path.exists(self.runtime_path))

    def test_get_effective_config(self):
        app_config.update_runtime_overrides({"VEHICLE_CONTROL_BASE_URL": "https://10.0.0.3:28009"})
        items = {i["key"]: i for i in app_config.get_effective_config()}
        self.assertEqual(set(items), set(app_config._OVERRIDABLE_KEYS))
        vc = items["VEHICLE_CONTROL_BASE_URL"]
        self.assertTrue(vc["overridden"])
        self.assertEqual(vc["effective"], "https://10.0.0.3:28009")
        self.assertEqual(vc["default"], "http://25.11.1.178:28009")
        ds = items["DATA_SERVER_BASE_URL"]
        self.assertFalse(ds["overridden"])
        self.assertEqual(ds["effective"], ds["default"])
        self.assertIn("label", ds) and self.assertTrue(ds["label"])

    def test_load_overrides_from_file(self):
        with open(self.runtime_path, "w", encoding="utf-8") as f:
            json.dump({"DATA_SERVER_BASE_URL": "http://10.9.9.9:28801", "bad_key": 1}, f)
        loaded = app_config._load_runtime_overrides()
        # 未知键被过滤
        self.assertEqual(loaded, {"DATA_SERVER_BASE_URL": "http://10.9.9.9:28801"})


class TestDebugConfigRoutes(_TempConfigBase):
    def setUp(self):
        super().setUp()
        self.client = TestClient(app)

    def test_get_config(self):
        resp = self.client.get("/api/v1/debug/config")
        self.assertEqual(resp.status_code, 200)
        body = resp.json()
        self.assertEqual(body["code"], 200)
        items = {i["key"]: i for i in body["data"]["items"]}
        self.assertIn("DATA_SERVER_BASE_URL", items)
        self.assertIn("SEAT_TARGET_IPS", items)
        # zenoh 项来自 zenoh.json5 实际值
        zenoh = items["ZENOH_ROUTER_URL"]
        self.assertEqual(zenoh["effective"], "tcp/25.11.1.3:7447")
        self.assertFalse(zenoh["overridden"])
        self.assertEqual(body["data"]["restart_required"], ["ZENOH_ROUTER_URL"])

    def test_post_config_valid(self):
        resp = self.client.post(
            "/api/v1/debug/config",
            json={"DATA_SERVER_BASE_URL": "http://10.0.0.1:28801"},
        )
        self.assertEqual(resp.status_code, 200)
        body = resp.json()
        self.assertEqual(body["code"], 200)
        self.assertEqual(
            body["data"]["overrides"]["DATA_SERVER_BASE_URL"], "http://10.0.0.1:28801"
        )
        # HTTP 地址走 getter，无需重启
        self.assertEqual(body["data"]["restart_required"], [])
        self.assertEqual(app_config.get_data_server_url(), "http://10.0.0.1:28801")

    def test_post_config_invalid_returns_400(self):
        resp = self.client.post(
            "/api/v1/debug/config",
            json={"DATA_SERVER_BASE_URL": "not-a-url"},
        )
        self.assertEqual(resp.status_code, 400)
        self.assertIn("DATA_SERVER_BASE_URL", resp.json()["detail"])

    def test_post_config_zenoh_targeted_rewrite(self):
        resp = self.client.post(
            "/api/v1/debug/config",
            json={"ZENOH_ROUTER_URL": "tcp/10.1.1.1:7447"},
        )
        self.assertEqual(resp.status_code, 200)
        body = resp.json()
        self.assertEqual(body["data"]["restart_required"], ["ZENOH_ROUTER_URL"])
        with open(self.zenoh_path, encoding="utf-8") as f:
            text = f.read()
        # 定点替换：地址改了，注释和 listen 段保留
        self.assertIn('"tcp/10.1.1.1:7447"', text)
        self.assertIn("// zenoh 客户端配置", text)
        self.assertIn('"tcp/0.0.0.0:0"', text)
        # 不写进 runtime_config.json
        self.assertNotIn("ZENOH_ROUTER_URL", app_config.get_runtime_overrides())

    def test_post_config_zenoh_invalid_returns_400(self):
        resp = self.client.post(
            "/api/v1/debug/config",
            json={"ZENOH_ROUTER_URL": "http://10.1.1.1:7447"},
        )
        self.assertEqual(resp.status_code, 400)
        self.assertIn("ZENOH_ROUTER_URL", resp.json()["detail"])

    def test_post_config_mixed_zenoh_and_url(self):
        resp = self.client.post(
            "/api/v1/debug/config",
            json={
                "ZENOH_ROUTER_URL": "tcp/10.1.1.1:7447",
                "RESOURCE_POOL_BASE_URL": "http://10.0.0.2:28800",
            },
        )
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.json()["data"]["restart_required"], ["ZENOH_ROUTER_URL"])
        self.assertEqual(app_config.get_resource_pool_url(), "http://10.0.0.2:28800")


class TestRestartRoute(_TempConfigBase):
    def setUp(self):
        super().setUp()
        self.client = TestClient(app)

    def test_restart_returns_200_then_execv(self):
        with patch.object(debug_api.threading, "Timer") as mock_timer_cls, \
             patch.object(debug_api.os, "execv") as mock_execv:
            resp = self.client.post("/api/v1/debug/restart")
            # 先返回 200
            self.assertEqual(resp.status_code, 200)
            self.assertEqual(resp.json(), {"code": 200, "message": "restarting"})
            mock_timer_cls.assert_called_once()
            delay, callback = mock_timer_cls.call_args.args
            self.assertEqual(delay, 0.5)
            mock_timer_cls.return_value.start.assert_called_once()
            # 定时器回调触发 execv，测试中不真的重启
            with patch.object(sys, "argv", ["/usr/bin/python3", "app.main:app"]):
                callback()
            mock_execv.assert_called_once()
            args = mock_execv.call_args.args
            self.assertEqual(args[0], sys.executable)
            self.assertEqual(args[1][0], sys.executable)
            self.assertEqual(args[1][1:], ["/usr/bin/python3", "app.main:app"])

    def test_restart_rewrites_python_dash_m_argv(self):
        # python -m uvicorn 启动时 argv[0] 是包内 __main__.py 路径，还原为 -m 形式
        fake_argv = ["/venv/lib/python3.11/site-packages/uvicorn/__main__.py",
                     "app.main:app", "--host", "0.0.0.0", "--port", "28600"]
        with patch.object(debug_api.os, "execv") as mock_execv, \
             patch.object(sys, "argv", fake_argv):
            debug_api._restart_process()
        exec_argv = mock_execv.call_args.args[1]
        self.assertEqual(
            exec_argv[1:],
            ["-m", "uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "28600"],
        )


class TestDebugLogsRoute(_TempConfigBase):
    def setUp(self):
        super().setUp()
        self.client = TestClient(app)
        # 造一个临时日志文件
        import tempfile

        self.log_fd, self.log_path = tempfile.mkstemp(suffix=".log")
        with os.fdopen(self.log_fd, "w", encoding="utf-8") as f:
            f.write("[2026-09-15 16:00:00.000] [TEST] 日志内容\n")

    def tearDown(self):
        if os.path.exists(self.log_path):
            os.unlink(self.log_path)
        super().tearDown()

    def test_export_backend_log(self):
        with patch.object(debug_api, "BACKEND_LOG_FILE", self.log_path):
            resp = self.client.get("/api/v1/debug/logs?source=backend")
        self.assertEqual(resp.status_code, 200)
        self.assertIn("日志内容", resp.text)
        # 文件名带时间戳（北京时间），Content-Disposition 触发浏览器下载
        self.assertIn("attachment", resp.headers.get("content-disposition", ""))
        self.assertIn("backend-", resp.headers["content-disposition"])

    def test_export_log_not_found_returns_404(self):
        with patch.object(debug_api, "BACKEND_LOG_FILE", "/tmp/__no_such_log_file__.log"):
            resp = self.client.get("/api/v1/debug/logs?source=backend")
        self.assertEqual(resp.status_code, 404)

    def test_export_log_invalid_source_returns_400(self):
        resp = self.client.get("/api/v1/debug/logs?source=../../etc/passwd")
        self.assertEqual(resp.status_code, 400)


if __name__ == "__main__":
    unittest.main()
