"""
内存级 Task Pool — 模拟 Redis + SQLite 存储
支持 KILL_CHAIN / PLAN / COMMAND / MISSION 等资源类型
"""

import copy
import uuid
from datetime import datetime, timezone
from typing import Dict, Any, List, Optional


class TaskPool:
    """内存存储，替代 Redis + SQLite"""

    def __init__(self):
        self._store: Dict[str, Dict[str, Any]] = {}  # resource_id -> resource
        self._index_by_type: Dict[str, List[str]] = {}  # task_type -> [resource_id]
        self._pending: set = set()

    # ---------- 基础 CRUD ----------

    def get(self, resource_id: str) -> Optional[Dict[str, Any]]:
        return copy.deepcopy(self._store.get(resource_id))

    def set(self, resource_id: str, data: Dict[str, Any]) -> None:
        """写入/更新资源"""
        self._store[resource_id] = copy.deepcopy(data)
        task_type = data.get("task_type", "UNKNOWN")
        if task_type not in self._index_by_type:
            self._index_by_type[task_type] = []
        if resource_id not in self._index_by_type[task_type]:
            self._index_by_type[task_type].append(resource_id)
        self._pending.add(resource_id)

    def patch(self, resource_id: str, payload: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        """增量更新"""
        resource = self._store.get(resource_id)
        if not resource:
            return None
        for key, value in payload.items():
            if value is not None:
                resource[key] = copy.deepcopy(value)
        resource["updated_at"] = datetime.now(timezone.utc).isoformat()
        self._pending.add(resource_id)
        return copy.deepcopy(resource)

    def delete(self, resource_id: str) -> bool:
        if resource_id in self._store:
            del self._store[resource_id]
            for ids in self._index_by_type.values():
                if resource_id in ids:
                    ids.remove(resource_id)
            self._pending.discard(resource_id)
            return True
        return False

    # ---------- 查询 ----------

    def query(self, task_type: Optional[str] = None,
              state: Optional[str] = None,
              parent_resource_id: Optional[str] = None,
              keyword: Optional[str] = None,
              include_deleted: bool = False,
              limit: int = 50) -> List[Dict[str, Any]]:
        """按条件查询"""
        results = []
        candidates = []

        if task_type:
            candidates = [self._store.get(rid) for rid in self._index_by_type.get(task_type, [])]
            candidates = [c for c in candidates if c is not None]
        else:
            candidates = list(self._store.values())

        for item in candidates:
            if state and item.get("state") != state:
                continue
            if not include_deleted and item.get("lifecycle", {}).get("state") == "DELETED":
                continue
            if parent_resource_id:
                plan_id = item.get("plan_id", "")
                if plan_id != parent_resource_id:
                    continue
            if keyword:
                search_text = item.get("search_text", "")
                title = item.get("title", "")
                if keyword.lower() not in (search_text + title).lower():
                    continue
            results.append(copy.deepcopy(item))

        return results[:limit]

    def search(self, query: str, limit: int = 10) -> List[Dict[str, Any]]:
        """全文搜索"""
        results = []
        q = query.lower()
        for item in self._store.values():
            text = f"{item.get('title', '')} {item.get('search_text', '')} {item.get('description', '')}"
            if q in text.lower():
                results.append(copy.deepcopy(item))
        return results[:limit]

    # ---------- 生命周期 ----------

    def update_lifecycle(self, resource_id: str, state: str, reason: str = "") -> Optional[Dict[str, Any]]:
        resource = self._store.get(resource_id)
        if not resource:
            return None
        if "lifecycle" not in resource:
            resource["lifecycle"] = {}
        resource["lifecycle"]["state"] = state
        resource["lifecycle"]["reason"] = reason
        resource["lifecycle"]["updated_at"] = datetime.now(timezone.utc).isoformat()
        self._pending.add(resource_id)
        return copy.deepcopy(resource)

    # ---------- 批量导入 ----------

    def import_resources(self, resources: List[Dict[str, Any]], ignore_errors: bool = False) -> Dict[str, Any]:
        """批量导入资源"""
        imported = []
        errors = []
        for res in resources:
            try:
                rid = res.get("resource_id") or f"{res.get('task_type', 'UNKNOWN').lower()}:{uuid.uuid4().hex[:8]}"
                res["resource_id"] = rid
                if "created_at" not in res:
                    res["created_at"] = datetime.now(timezone.utc).isoformat()
                if "updated_at" not in res:
                    res["updated_at"] = res["created_at"]
                self.set(rid, res)
                imported.append(rid)
            except Exception as e:
                errors.append({"resource": res, "error": str(e)})
                if not ignore_errors:
                    raise
        return {"imported": imported, "errors": errors, "count": len(imported)}

    # ---------- 辅助 ----------

    def all(self) -> Dict[str, Dict[str, Any]]:
        return copy.deepcopy(self._store)

    def commit(self, cache_keys: List[str]) -> Dict[str, Any]:
        """模拟提交到 SQLite（内存中无实际持久化）"""
        committed = []
        for key in cache_keys:
            if key in self._pending:
                self._pending.discard(key)
                committed.append(key)
        return {"committed": committed, "count": len(committed)}


# 全局单例
task_pool = TaskPool()
