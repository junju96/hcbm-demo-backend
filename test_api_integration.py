#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
================================================================================
数据服务器 & 本地后端 接口联调测试脚本
================================================================================
测试三个核心接口：
  1. POST /api/v1/task_pool/resources/query  — 查询杀伤链列表
  2. GET  /api/v1/task_pool/resources/{id}   — 查询杀伤链详情
  3. PATCH /api/v1/task_pool/resources/{id}  — 更新杀伤链

运行方式:
  cd demo/backend && python3 test_api_integration.py

输出说明:
  ✅ 通过    ❌ 失败    ⚠️  警告/需关注
================================================================================
"""

from __future__ import annotations

import json
import sys
import time
import uuid
from typing import Any

import requests

# ---------- 配置 ----------
DATA_SERVER_URL = "http://25.11.1.178:28801"
LOCAL_BACKEND_URL = "http://localhost:28600"
TIMEOUT_SECONDS = 10
TEST_RESOURCE_ID = "kill_chain:kill_chain_001"

# 颜色代码
C_GREEN = "\033[32m"
C_RED = "\033[31m"
C_YELLOW = "\033[33m"
C_CYAN = "\033[36m"
C_RESET = "\033[0m"
C_BOLD = "\033[1m"


def _ok(msg: str) -> str:
    return f"{C_GREEN}✅ {msg}{C_RESET}"


def _fail(msg: str) -> str:
    return f"{C_RED}❌ {msg}{C_RESET}"


def _warn(msg: str) -> str:
    return f"{C_YELLOW}⚠️  {msg}{C_RESET}"


def _info(msg: str) -> str:
    return f"{C_CYAN}ℹ️  {msg}{C_RESET}"


def _title(msg: str) -> None:
    print(f"\n{C_BOLD}{'=' * 80}{C_RESET}")
    print(f"{C_BOLD}{msg}{C_RESET}")
    print(f"{C_BOLD}{'=' * 80}{C_RESET}")


def _section(msg: str) -> None:
    print(f"\n{C_BOLD}▶ {msg}{C_RESET}")
    print("-" * 60)


def print_json(data: Any, indent: int = 2) -> None:
    print(json.dumps(data, ensure_ascii=False, indent=indent))


def pretty_curl(method: str, url: str, payload: dict | None = None) -> str:
    """生成等价的 curl 命令，方便手动复现"""
    cmd = f"curl -s -X {method} '{url}'"
    if payload is not None:
        cmd += f" -H 'Content-Type: application/json' -d '{json.dumps(payload, ensure_ascii=False)}'"
    return cmd


class ApiTester:
    def __init__(self, base_url: str, name: str) -> None:
        self.base_url = base_url.rstrip("/")
        self.name = name
        self.passed = 0
        self.failed = 0
        self.warnings = 0

    def _full_url(self, path: str) -> str:
        return f"{self.base_url}{path}"

    def _record(self, ok: bool, warn: bool = False) -> None:
        if ok:
            self.passed += 1
            if warn:
                self.warnings += 1
        else:
            self.failed += 1

    def request(
        self,
        method: str,
        path: str,
        payload: dict | None = None,
        params: dict | None = None,
        expect_status: int = 200,
    ) -> dict[str, Any] | None:
        url = self._full_url(path)
        start = time.time()
        try:
            if method.upper() == "GET":
                resp = requests.get(url, params=params, timeout=TIMEOUT_SECONDS)
            elif method.upper() == "POST":
                resp = requests.post(url, json=payload, timeout=TIMEOUT_SECONDS)
            elif method.upper() == "PATCH":
                resp = requests.patch(url, json=payload, timeout=TIMEOUT_SECONDS)
            elif method.upper() == "DELETE":
                resp = requests.delete(url, timeout=TIMEOUT_SECONDS)
            else:
                print(_fail(f"不支持的 HTTP 方法: {method}"))
                return None
            elapsed = (time.time() - start) * 1000
        except requests.exceptions.ConnectTimeout:
            print(_fail(f"连接超时 ({TIMEOUT_SECONDS}s): {url}"))
            print(f"   等效命令: {pretty_curl(method, url, payload)}")
            self._record(False)
            return None
        except requests.exceptions.ConnectionError as e:
            print(_fail(f"连接失败: {url}"))
            print(f"   错误: {e}")
            print(f"   等效命令: {pretty_curl(method, url, payload)}")
            self._record(False)
            return None
        except Exception as e:
            print(_fail(f"请求异常: {url}"))
            print(f"   错误: {e}")
            self._record(False)
            return None

        print(f"   请求: {method} {url}")
        if payload:
            print(f"   Body:")
            print_json(payload)
        if params:
            print(f"   Params: {params}")
        print(f"   状态码: {resp.status_code} | 耗时: {elapsed:.1f}ms")

        if resp.status_code != expect_status:
            print(_fail(f"状态码不匹配! 期望 {expect_status}, 实际 {resp.status_code}"))
            try:
                print(f"   响应: {resp.text[:500]}")
            except Exception:
                pass
            self._record(False)
            return None

        try:
            data = resp.json()
        except Exception:
            data = {"_raw_text": resp.text}

        print(f"   响应体 (前 30 行):")
        # 截断打印，避免刷屏
        resp_str = json.dumps(data, ensure_ascii=False, indent=2)
        lines = resp_str.splitlines()
        for line in lines[:30]:
            print(f"      {line}")
        if len(lines) > 30:
            print(f"      ... ({len(lines) - 30} 行省略)")

        self._record(True)
        return data

    # ==================== 测试用例 ====================

    def test_query_list(self) -> None:
        _section(f"[{self.name}] 接口 1/3: POST /task_pool/resources/query (查询列表)")

        payload = {"task_type": "KILL_CHAIN", "limit": 10}
        data = self.request("POST", "/api/v1/task_pool/resources/query", payload=payload)

        if data is None:
            return

        # 数据服务器直接返回列表；本地后端返回 ApiResponse {data: {...}}
        items = data if isinstance(data, list) else data.get("data", {}).get("items", [])

        if not items:
            print(_warn("返回列表为空，请确认数据服务器是否有 KILL_CHAIN 数据"))
            self.warnings += 1
            return

        print(_ok(f"返回 {len(items)} 条记录"))

        first = items[0]
        required_keys = {"resource_id", "task_type", "title"}
        missing = required_keys - set(first.keys())
        if missing:
            print(_warn(f"列表项缺少字段: {missing}"))
            self.warnings += 1
        else:
            print(_ok(f"列表项字段完整: {required_keys}"))

        # 校验 task_type 必须是 KILL_CHAIN
        wrong_types = [i for i in items if i.get("task_type") != "KILL_CHAIN"]
        if wrong_types:
            print(_warn(f"发现 {len(wrong_types)} 条非 KILL_CHAIN 记录混入"))
            self.warnings += 1
        else:
            print(_ok("所有记录 task_type 均为 KILL_CHAIN"))

        # 打印第一条摘要
        print(_info("第一条记录摘要:"))
        summary = {k: first.get(k) for k in ["resource_id", "title", "state", "task_type"]}
        print_json(summary)

    def test_get_detail(self) -> None:
        _section(f"[{self.name}] 接口 2/3: GET /task_pool/resources/{{id}} (查询详情)")

        data = self.request("GET", f"/api/v1/task_pool/resources/{TEST_RESOURCE_ID}")

        if data is None:
            return

        # 本地后端包在 ApiResponse.data 里
        record = data.get("data", data)

        # 关键字段校验
        key_fields = [
            "resource_id",
            "task_type",
            "title",
            "state",
            "raw_entries",
            "assigned_entries",
        ]
        missing = [k for k in key_fields if k not in record]
        if missing:
            print(_warn(f"详情缺少关键字段: {missing}"))
            self.warnings += 1
        else:
            print(_ok(f"详情关键字段完整 ({len(key_fields)} 项)"))

        # 校验 resource_id 匹配
        rid = record.get("resource_id", "")
        if rid != TEST_RESOURCE_ID:
            print(_warn(f"resource_id 不匹配! 请求 {TEST_RESOURCE_ID}, 返回 {rid}"))
            self.warnings += 1
        else:
            print(_ok(f"resource_id 匹配: {rid}"))

        # raw_entries / assigned_entries 结构校验
        raw = record.get("raw_entries", [])
        assigned = record.get("assigned_entries", [])
        print(_info(f"raw_entries: {len(raw)} 条, assigned_entries: {len(assigned)} 条"))

        if raw:
            first = raw[0]
            entry_keys = {"entry_id", "phase", "operation", "executor_options"}
            missing_entry = entry_keys - set(first.keys())
            if missing_entry:
                print(_warn(f"entry 缺少字段: {missing_entry}"))
                self.warnings += 1
            else:
                print(_ok("entry 结构正确"))

        # 检查数据服务器是否把 KillChain 字段放在 raw_payload / payload 里
        if "raw_payload" in record and record["raw_payload"]:
            rp = record["raw_payload"]
            print(_info(f"raw_payload 存在，包含字段: {list(rp.keys())}"))
            # 如果 raw_entries 在顶层没有但 raw_payload 里有，需要后端做解析
            if "raw_entries" not in record and "raw_entries" in rp:
                print(_warn("raw_entries 只在 raw_payload 中，顶层缺失 — 后端需做字段提升!"))
                self.warnings += 1

    def test_patch(self) -> None:
        _section(f"[{self.name}] 接口 3/3: PATCH /task_pool/resources/{{id}} (更新)")

        # ---------- 3.1 先 GET 当前值作为基准 ----------
        print("   [Step 1] 获取当前值...")
        before = self.request("GET", f"/api/v1/task_pool/resources/{TEST_RESOURCE_ID}")
        if before is None:
            print(_fail("无法获取当前值，跳过 PATCH 测试"))
            self._record(False)
            return

        before_record = before.get("data", before)
        original_title = before_record.get("title", "")
        original_state = before_record.get("state", "ACTIVE")
        print(f"   当前 title: {original_title}, state: {original_state}")

        # ---------- 3.2 PATCH 通用字段 (title / state) ----------
        new_title = f"{original_title}_PATCH_TEST_{uuid.uuid4().hex[:4]}"
        patch_body = {
            "title": new_title,
            "state": "READY",
        }

        print(f"   [Step 2] PATCH 通用字段: title + state")
        patch_resp = self.request(
            "PATCH",
            f"/api/v1/task_pool/resources/{TEST_RESOURCE_ID}",
            payload=patch_body,
        )
        if patch_resp is None:
            print(_fail("PATCH 通用字段失败"))
            self._record(False)
            return

        patch_record = patch_resp.get("data", patch_resp)
        patched_title = patch_record.get("title", "")
        patched_state = patch_record.get("state", "")

        if patched_title == new_title:
            print(_ok(f"title 更新成功: '{original_title}' → '{patched_title}'"))
        else:
            print(_warn(f"title 未更新! 期望 '{new_title}', 实际 '{patched_title}'"))
            self.warnings += 1

        if patched_state == "READY":
            print(_ok(f"state 更新成功: '{original_state}' → '{patched_state}'"))
        else:
            print(_warn(f"state 未更新! 期望 'PENDING', 实际 '{patched_state}'"))
            self.warnings += 1

        # ---------- 3.3 PATCH KillChain 特有字段 ----------
        # 对于直连数据服务器，特有字段需要放在 payload 字段内
        # 对于本地后端，传平铺字段即可（后端会自动打包）
        print(f"   [Step 3] PATCH KillChain 特有字段 (target_ids / mapping_summary)")

        if self.name == "数据服务器(直连)":
            # 直连数据服务器：特有字段放 payload
            special_patch = {
                "payload": {
                    "target_ids": ["target_001", "target_PATCH_TEST"],
                    "mapping_summary": {
                        "plan_title": "PATCH测试方案",
                        "match_score": 0.88,
                        "remarks": "由 test_api_integration.py 写入",
                    },
                }
            }
        else:
            # 本地后端：平铺字段，后端自动转换
            special_patch = {
                "target_ids": ["target_001", "target_PATCH_TEST"],
                "mapping_summary": {
                    "plan_title": "PATCH测试方案",
                    "match_score": 0.88,
                    "remarks": "由 test_api_integration.py 写入",
                },
            }

        special_resp = self.request(
            "PATCH",
            f"/api/v1/task_pool/resources/{TEST_RESOURCE_ID}",
            payload=special_patch,
        )
        if special_resp is None:
            print(_warn("PATCH 特有字段失败"))
            self.warnings += 1
        else:
            sp_record = special_resp.get("data", special_resp)
            # 校验 target_ids
            tids = sp_record.get("target_ids", [])
            if "target_PATCH_TEST" in tids:
                print(_ok("target_ids 更新成功"))
            else:
                print(_warn(f"target_ids 未更新! 实际: {tids}"))
                self.warnings += 1

            # 校验 mapping_summary
            ms = sp_record.get("mapping_summary", {})
            if ms.get("plan_title") == "PATCH测试方案":
                print(_ok("mapping_summary 更新成功"))
            else:
                print(_warn(f"mapping_summary 未更新! 实际: {ms}"))
                self.warnings += 1

        # ---------- 3.4 恢复原始值 ----------
        print(f"   [Step 4] 恢复原始值...")
        restore_body = {
            "title": original_title,
            "state": original_state,
        }
        if self.name == "数据服务器(直连)":
            restore_body["payload"] = {
                "target_ids": before_record.get("target_ids", ["target_001"]),
                "mapping_summary": before_record.get("mapping_summary", {}),
            }
        else:
            restore_body["target_ids"] = before_record.get("target_ids", ["target_001"])
            restore_body["mapping_summary"] = before_record.get("mapping_summary", {})

        restore_resp = self.request(
            "PATCH",
            f"/api/v1/task_pool/resources/{TEST_RESOURCE_ID}",
            payload=restore_body,
        )
        if restore_resp is None:
            print(_warn("恢复原始值失败，请手动检查数据!"))
            self.warnings += 1
        else:
            rr = restore_resp.get("data", restore_resp)
            if rr.get("title") == original_title and rr.get("state") == original_state:
                print(_ok("原始值已恢复"))
            else:
                print(_warn("恢复后值与原始值不一致，请手动检查!"))
                self.warnings += 1

    def summary(self) -> None:
        print(f"\n{'=' * 60}")
        print(f"{C_BOLD}[{self.name}] 测试汇总{C_RESET}")
        print(f"{'=' * 60}")
        print(f"  通过: {C_GREEN}{self.passed}{C_RESET}")
        print(f"  失败: {C_RED}{self.failed}{C_RESET}")
        print(f"  警告: {C_YELLOW}{self.warnings}{C_RESET}")
        if self.failed == 0:
            print(f"  结果: {C_GREEN}{C_BOLD}全部通过{C_RESET}")
        else:
            print(f"  结果: {C_RED}{C_BOLD}存在失败项，请检查!{C_RESET}")


def main() -> int:
    print(f"{C_BOLD}{'=' * 80}{C_RESET}")
    print(f"{C_BOLD}  接口联调自动化测试脚本{C_RESET}")
    print(f"{C_BOLD}  数据服务器: {DATA_SERVER_URL}{C_RESET}")
    print(f"{C_BOLD}  本地后端:   {LOCAL_BACKEND_URL}{C_RESET}")
    print(f"{C_BOLD}{'=' * 80}{C_RESET}")

    # 检查本地后端是否存活
    try:
        r = requests.get(f"{LOCAL_BACKEND_URL}/health", timeout=3)
        if r.status_code == 200:
            print(_ok("本地后端已启动"))
        else:
            print(_warn(f"本地后端 /health 返回 {r.status_code}"))
    except Exception as e:
        print(_fail(f"本地后端无法连接: {e}"))
        print("请先启动本地后端: cd demo/backend && python3 -m uvicorn app.main:app --host 0.0.0.0 --port 28600")
        return 1

    # 检查数据服务器是否存活
    try:
        r = requests.get(f"{DATA_SERVER_URL}/api/v1/task_pool/resources/{TEST_RESOURCE_ID}", timeout=5)
        if r.status_code == 200:
            print(_ok("数据服务器已连通"))
        else:
            print(_warn(f"数据服务器返回 {r.status_code}"))
    except Exception as e:
        print(_fail(f"数据服务器无法连接: {e}"))
        return 1

    # ==================== 第一轮：直连数据服务器 ====================
    _title("第一轮：直连数据服务器 (验证数据服务器原生行为)")
    ds_tester = ApiTester(DATA_SERVER_URL, "数据服务器(直连)")
    ds_tester.test_query_list()
    ds_tester.test_get_detail()
    ds_tester.test_patch()
    ds_tester.summary()

    # ==================== 第二轮：走本地后端代理 ====================
    _title("第二轮：走本地后端代理 (验证后端适配层转换逻辑)")
    local_tester = ApiTester(LOCAL_BACKEND_URL, "本地后端(代理)")
    local_tester.test_query_list()
    local_tester.test_get_detail()
    local_tester.test_patch()
    local_tester.summary()

    # ==================== 总汇总 ====================
    total_passed = ds_tester.passed + local_tester.passed
    total_failed = ds_tester.failed + local_tester.failed
    total_warnings = ds_tester.warnings + local_tester.warnings

    print(f"\n{C_BOLD}{'=' * 80}{C_RESET}")
    print(f"{C_BOLD}  总汇总{C_RESET}")
    print(f"{C_BOLD}{'=' * 80}{C_RESET}")
    print(f"  通过:   {C_GREEN}{total_passed}{C_RESET}")
    print(f"  失败:   {C_RED}{total_failed}{C_RESET}")
    print(f"  警告:   {C_YELLOW}{total_warnings}{C_RESET}")

    if total_failed == 0:
        print(f"\n  {C_GREEN}{C_BOLD}🎉 全部测试通过，接口联调就绪!{C_RESET}")
        return 0
    else:
        print(f"\n  {C_RED}{C_BOLD}💥 存在 {total_failed} 项失败，请根据上方日志定位问题。{C_RESET}")
        return 1


if __name__ == "__main__":
    sys.exit(main())
