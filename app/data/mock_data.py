"""
预置 Mock 数据
包含杀伤链示例数据、资源池数据、态势目标数据
"""

from datetime import datetime, timezone


def preload_mock_data(task_pool):
    """启动时预置数据到内存存储"""

    # ---------- 态势目标 ----------
    targets = [
        {
            "resource_id": "target:target-1",
            "task_type": "TARGET",
            "target_id": "target-1",
            "target_name": "目标1",
            "target_type": "地面目标",
            "foe": "ENEMY",
            "threat_level": "high",
            "location": {"latitude": 39.8642, "longitude": 118.2085, "altitude": 95.0},
            "search_text": "目标1 地面目标 敌方",
        },
        {
            "resource_id": "target:target-2",
            "task_type": "TARGET",
            "target_id": "target-2",
            "target_name": "目标2",
            "target_type": "地面目标",
            "foe": "ENEMY",
            "threat_level": "medium",
            "location": {"latitude": 39.8701, "longitude": 118.2264, "altitude": 106.0},
            "search_text": "目标2 地面目标 敌方",
        },
    ]

    # ---------- 装备资源 ----------
    resources = [
        {
            "resource_id": "equipment:vehicle-A",
            "task_type": "EQUIPMENT",
            "entity_kind": "equipment",
            "resource_name": "无人车A",
            "resource_tag": "EQUIPMENT",
            "resource_type": "UGV",
            "online_status": "ONLINE",
            "capacity": {"max_range_km": 12, "max_speed_kmh": 45, "recon_range_km": 3},
            "search_text": "无人车A UGV 侦察",
        },
        {
            "resource_id": "equipment:vehicle-B",
            "task_type": "EQUIPMENT",
            "entity_kind": "equipment",
            "resource_name": "无人车B",
            "resource_tag": "EQUIPMENT",
            "resource_type": "UGV",
            "online_status": "ONLINE",
            "capacity": {"max_range_km": 12, "max_speed_kmh": 42, "strike_range_km": 4},
            "search_text": "无人车B UGV 打击",
        },
    ]

    # ---------- 杀伤链 ----------
    kill_chain = {
        "resource_id": "kill_chain:kc-ssl-demo-001",
        "task_type": "KILL_CHAIN",
        "kill_chain_id": "kc-ssl-demo-001",
        "title": "目标1/目标2-杀伤链构建示例",
        "description": "基于地图右键构建的侦察、定位、跟踪、瞄准/引导、打击、评估杀伤链示例。",
        "state": "ACTIVE",
        "resource_ids": ["equipment:vehicle-A", "equipment:vehicle-B"],
        "target_ids": ["target:target-1", "target:target-2"],
        "mapped_plan_ids": ["plan:plan-ssl-demo-001"],
        "connections": [{"connection_type": "PLAN", "connection_data": ["plan:plan-ssl-demo-001"]}],
        "dependencies": [],
        "relations": [{"type": "mapped_to", "target": "plan:plan-ssl-demo-001", "metadata": {"source": "kill_chain_plan_generation"}}],
        "attributes": {
            "cache_key": "kill_chain:kc-ssl-demo-001",
            "created_from": "map_context_menu",
            "source_doc": "SSL构建示例数据.docx",
            "resource_display": {"equipment:vehicle-A": "无人车A", "equipment:vehicle-B": "无人车B"},
            "target_display": {"target:target-1": "目标1", "target:target-2": "目标2"},
        },
        "search_text": "目标1 目标2 杀伤链 侦察 定位 跟踪 打击",
        "created_at": datetime.now(timezone.utc).isoformat(),
        "updated_at": datetime.now(timezone.utc).isoformat(),
        "raw_entries": [
            {
                "entry_id": "raw-001",
                "phase": "RAW",
                "entry_seq": 1,
                "target_ids": ["target:target-1", "target:target-2"],
                "operation": "侦察",
                "executor_options": [
                    {"executor_id": "equipment:vehicle-A", "allocation_count": 2, "locked": False, "note": "合法；可承担双目标侦察，历史分配2次"},
                    {"executor_id": "equipment:vehicle-B", "allocation_count": 1, "locked": True, "note": "合法但已锁定；排序靠后"},
                ],
                "selected_executor": None,
                "locked": False,
                "is_valid": True,
                "notes": "对应原始表：目标1、目标2执行侦察",
            },
            {
                "entry_id": "raw-002",
                "phase": "RAW",
                "entry_seq": 2,
                "target_ids": ["target:target-1", "target:target-2"],
                "operation": "定位",
                "executor_options": [
                    {"executor_id": "equipment:vehicle-A", "allocation_count": 0, "locked": False, "note": "合法；推荐定位执行装备"},
                    {"executor_id": "equipment:vehicle-B", "allocation_count": 0, "locked": False, "note": "合法；备选"},
                ],
                "selected_executor": None,
                "locked": False,
                "is_valid": True,
                "notes": "对应原始表：目标1、目标2执行定位",
            },
            {
                "entry_id": "raw-003",
                "phase": "RAW",
                "entry_seq": 3,
                "target_ids": ["target:target-1", "target:target-2"],
                "operation": "跟踪",
                "executor_options": [
                    {"executor_id": "equipment:vehicle-A", "allocation_count": 0, "locked": False, "note": "合法；推荐持续跟踪"},
                    {"executor_id": "equipment:vehicle-B", "allocation_count": 0, "locked": False, "note": "合法；备选"},
                ],
                "selected_executor": None,
                "locked": False,
                "is_valid": True,
                "notes": "对应原始表：目标1、目标2执行跟踪",
            },
            {
                "entry_id": "raw-004",
                "phase": "RAW",
                "entry_seq": 4,
                "target_ids": ["target:target-1"],
                "operation": "瞄准/引导",
                "executor_options": [
                    {"executor_id": "equipment:vehicle-B", "allocation_count": 1, "locked": False, "note": "合法；对目标1执行引导"},
                ],
                "selected_executor": None,
                "locked": False,
                "is_valid": True,
                "notes": "对应原始表：目标1执行瞄准/引导",
            },
            {
                "entry_id": "raw-005",
                "phase": "RAW",
                "entry_seq": 5,
                "target_ids": ["target:target-1"],
                "operation": "打击",
                "executor_options": [
                    {"executor_id": "equipment:vehicle-B", "allocation_count": 1, "locked": False, "note": "合法；对目标1执行打击"},
                ],
                "selected_executor": None,
                "locked": False,
                "is_valid": True,
                "notes": "对应原始表：目标1执行打击",
            },
            {
                "entry_id": "raw-006",
                "phase": "RAW",
                "entry_seq": 6,
                "target_ids": ["target:target-1"],
                "operation": "评估",
                "executor_options": [
                    {"executor_id": "equipment:vehicle-B", "allocation_count": 1, "locked": False, "note": "合法；对目标1执行毁伤评估"},
                ],
                "selected_executor": None,
                "locked": False,
                "is_valid": True,
                "notes": "对应原始表：目标1执行评估",
            },
        ],
        "assigned_entries": [
            {
                "entry_id": "assigned-001",
                "phase": "ASSIGNED",
                "entry_seq": 1,
                "target_ids": ["target:target-1"],
                "operation": "侦察",
                "executor_options": [
                    {"executor_id": "equipment:vehicle-A", "allocation_count": 3, "locked": True, "note": "已选中无人车A"},
                ],
                "selected_executor": "equipment:vehicle-A",
                "locked": True,
                "is_valid": True,
                "notes": "目标1侦察",
            },
            {
                "entry_id": "assigned-002",
                "phase": "ASSIGNED",
                "entry_seq": 2,
                "target_ids": ["target:target-1"],
                "operation": "定位",
                "executor_options": [
                    {"executor_id": "equipment:vehicle-A", "allocation_count": 3, "locked": True, "note": "已选中无人车A"},
                ],
                "selected_executor": "equipment:vehicle-A",
                "locked": True,
                "is_valid": True,
                "notes": "目标1定位",
            },
            {
                "entry_id": "assigned-003",
                "phase": "ASSIGNED",
                "entry_seq": 3,
                "target_ids": ["target:target-1"],
                "operation": "跟踪",
                "executor_options": [
                    {"executor_id": "equipment:vehicle-A", "allocation_count": 3, "locked": True, "note": "已选中无人车A"},
                ],
                "selected_executor": "equipment:vehicle-A",
                "locked": True,
                "is_valid": True,
                "notes": "目标1跟踪",
            },
            {
                "entry_id": "assigned-004",
                "phase": "ASSIGNED",
                "entry_seq": 4,
                "target_ids": ["target:target-1"],
                "operation": "瞄准/引导",
                "executor_options": [
                    {"executor_id": "equipment:vehicle-B", "allocation_count": 3, "locked": True, "note": "已选中无人车B"},
                ],
                "selected_executor": "equipment:vehicle-B",
                "locked": True,
                "is_valid": True,
                "notes": "目标1瞄准/引导",
            },
            {
                "entry_id": "assigned-005",
                "phase": "ASSIGNED",
                "entry_seq": 5,
                "target_ids": ["target:target-1"],
                "operation": "打击",
                "executor_options": [
                    {"executor_id": "equipment:vehicle-B", "allocation_count": 3, "locked": True, "note": "已选中无人车B"},
                ],
                "selected_executor": "equipment:vehicle-B",
                "locked": True,
                "is_valid": True,
                "notes": "目标1打击",
            },
            {
                "entry_id": "assigned-006",
                "phase": "ASSIGNED",
                "entry_seq": 6,
                "target_ids": ["target:target-1"],
                "operation": "评估",
                "executor_options": [
                    {"executor_id": "equipment:vehicle-B", "allocation_count": 3, "locked": True, "note": "已选中无人车B"},
                ],
                "selected_executor": "equipment:vehicle-B",
                "locked": True,
                "is_valid": True,
                "notes": "目标1评估",
            },
            {
                "entry_id": "assigned-007",
                "phase": "ASSIGNED",
                "entry_seq": 7,
                "target_ids": ["target:target-2"],
                "operation": "侦察",
                "executor_options": [
                    {"executor_id": "equipment:vehicle-A", "allocation_count": 3, "locked": True, "note": "已选中无人车A"},
                ],
                "selected_executor": "equipment:vehicle-A",
                "locked": True,
                "is_valid": True,
                "notes": "目标2侦察",
            },
            {
                "entry_id": "assigned-008",
                "phase": "ASSIGNED",
                "entry_seq": 8,
                "target_ids": ["target:target-2"],
                "operation": "定位",
                "executor_options": [
                    {"executor_id": "equipment:vehicle-A", "allocation_count": 3, "locked": True, "note": "已选中无人车A"},
                ],
                "selected_executor": "equipment:vehicle-A",
                "locked": True,
                "is_valid": True,
                "notes": "目标2定位",
            },
            {
                "entry_id": "assigned-009",
                "phase": "ASSIGNED",
                "entry_seq": 9,
                "target_ids": ["target:target-2"],
                "operation": "跟踪",
                "executor_options": [
                    {"executor_id": "equipment:vehicle-A", "allocation_count": 3, "locked": True, "note": "已选中无人车A"},
                ],
                "selected_executor": "equipment:vehicle-A",
                "locked": True,
                "is_valid": True,
                "notes": "目标2跟踪",
            },
        ],
        "mapping_summary": {
            "total_raw_entries": 6,
            "total_assigned_entries": 9,
            "target_count": 2,
            "resource_count": 2,
            "targets": {
                "target:target-1": {"display_name": "目标1", "operations": ["侦察", "定位", "跟踪", "瞄准/引导", "打击", "评估"], "executors": ["equipment:vehicle-A", "equipment:vehicle-B"]},
                "target:target-2": {"display_name": "目标2", "operations": ["侦察", "定位", "跟踪"], "executors": ["equipment:vehicle-A"]},
            },
            "operation_executor_map": {
                "侦察": ["equipment:vehicle-A"],
                "定位": ["equipment:vehicle-A"],
                "跟踪": ["equipment:vehicle-A"],
                "瞄准/引导": ["equipment:vehicle-B"],
                "打击": ["equipment:vehicle-B"],
                "评估": ["equipment:vehicle-B"],
            },
            "generated_plan_resource_id": "plan:plan-ssl-demo-001",
        },
        "network": {
            "nodes": [
                {"resource_id": "equipment:vehicle-A", "name": "无人车A", "status": "ONLINE", "status_color": "GREEN", "position": {"latitude": 39.0, "longitude": 116.0, "z": 0}, "address": "http://target01:8850"},
                {"resource_id": "equipment:vehicle-B", "name": "无人车B", "status": "ONLINE", "status_color": "GREEN", "position": {"latitude": 39.0, "longitude": 116.1, "z": 0}, "address": "http://target02:8850"},
            ],
            "edges": [
                {"edge_id": "e_kc1_001", "from_node": "equipment:vehicle-B", "to_node": "equipment:vehicle-A", "type": "spotting", "label": "目标引导", "required": True},
            ],
        },
    }

    # ---------- Plan 方案 ----------
    plan = {
        "resource_id": "plan:plan-ssl-demo-001",
        "task_type": "PLAN",
        "plan_id": "plan-ssl-demo-001",
        "title": "杀伤链映射行动方案",
        "description": "由 kill_chain:kc-ssl-demo-001 映射生成的行动方案。",
        "state": "DRAFT",
        "attributes": {"plan_type": "KILL_CHAIN_GENERATED", "source_kill_chain_id": "kill_chain:kc-ssl-demo-001"},
        "relations": [{"type": "generated_from", "target": "kill_chain:kc-ssl-demo-001", "metadata": {}}],
        "connections": [{"connection_type": "KILL_CHAIN", "connection_data": ["kill_chain:kc-ssl-demo-001"]}],
        "teams": [
            {"task_type": "TEAM", "team_id": "team-recon", "name": "侦察定位组", "plan_id": "plan-ssl-demo-001", "description": "由无人车A组成，负责目标1和目标2的侦察、定位、跟踪。", "equipment": ["equipment:vehicle-A"], "state": "READY"},
            {"task_type": "TEAM", "team_id": "team-strike", "name": "引导打击组", "plan_id": "plan-ssl-demo-001", "description": "由无人车B组成，负责目标1的瞄准/引导、打击和评估。", "equipment": ["equipment:vehicle-B"], "state": "READY"},
        ],
        "targets": [
            {"task_type": "TARGET", "target_id": "target-1", "name": "目标1", "plan_id": "plan-ssl-demo-001", "target_type": "地面目标"},
            {"task_type": "TARGET", "target_id": "target-2", "name": "目标2", "plan_id": "plan-ssl-demo-001", "target_type": "地面目标"},
        ],
        "stages": [
            {
                "task_type": "STAGE",
                "stage_id": "stage-kill-chain-execution",
                "title": "杀伤链执行阶段",
                "plan_id": "plan-ssl-demo-001",
                "stage_seq": 1,
                "target_ids": ["target:target-1", "target:target-2"],
                "team_ids": ["team-recon", "team-strike"],
                "state": "SCHEDULED",
            }
        ],
        "search_text": "杀伤链映射行动方案",
        "created_at": datetime.now(timezone.utc).isoformat(),
        "updated_at": datetime.now(timezone.utc).isoformat(),
    }

    # ---------- 更多杀伤链（Mock） ----------
    kill_chain_2 = {
        "resource_id": "kill_chain:kc-demo-002",
        "task_type": "KILL_CHAIN",
        "kill_chain_id": "kc-demo-002",
        "title": "对敌雷达站侦察杀伤链",
        "description": "针对区域C的敌方雷达站，执行侦察→定位→打击→评估的杀伤链。",
        "state": "READY",
        "resource_ids": ["equipment:vehicle-A", "equipment:vehicle-B"],
        "target_ids": ["target:target-2"],
        "mapped_plan_ids": ["plan:plan-demo-002"],
        "raw_entries": [
            {"entry_id": "raw-201", "phase": "RAW", "entry_seq": 1, "target_ids": ["target:target-2"], "operation": "侦察", "executor_options": [{"executor_id": "equipment:vehicle-A", "allocation_count": 1, "locked": False, "note": "无人车A侦察"}], "selected_executor": None, "locked": False, "is_valid": True, "notes": ""},
            {"entry_id": "raw-202", "phase": "RAW", "entry_seq": 2, "target_ids": ["target:target-2"], "operation": "定位", "executor_options": [{"executor_id": "equipment:vehicle-A", "allocation_count": 1, "locked": False, "note": "无人车A定位"}], "selected_executor": None, "locked": False, "is_valid": True, "notes": ""},
            {"entry_id": "raw-203", "phase": "RAW", "entry_seq": 3, "target_ids": ["target:target-2"], "operation": "打击", "executor_options": [{"executor_id": "equipment:vehicle-B", "allocation_count": 1, "locked": False, "note": "无人车B打击"}], "selected_executor": None, "locked": False, "is_valid": True, "notes": ""},
            {"entry_id": "raw-204", "phase": "RAW", "entry_seq": 4, "target_ids": ["target:target-2"], "operation": "评估", "executor_options": [{"executor_id": "equipment:vehicle-B", "allocation_count": 1, "locked": False, "note": "无人车B评估"}], "selected_executor": None, "locked": False, "is_valid": True, "notes": ""},
        ],
        "assigned_entries": [],
        "network": {"nodes": [], "edges": []},
        "is_mock": True,
        "created_at": datetime.now(timezone.utc).isoformat(),
        "updated_at": datetime.now(timezone.utc).isoformat(),
    }

    kill_chain_3 = {
        "resource_id": "kill_chain:kc-demo-003",
        "task_type": "KILL_CHAIN",
        "kill_chain_id": "kc-demo-003",
        "title": "对敌通信枢纽干扰杀伤链",
        "description": "针对区域D的敌方通信枢纽，执行侦察→干扰→评估的杀伤链。",
        "state": "INIT",
        "resource_ids": ["equipment:vehicle-A"],
        "target_ids": ["target:target-1"],
        "mapped_plan_ids": [],
        "raw_entries": [
            {"entry_id": "raw-301", "phase": "RAW", "entry_seq": 1, "target_ids": ["target:target-1"], "operation": "侦察", "executor_options": [{"executor_id": "equipment:vehicle-A", "allocation_count": 1, "locked": False, "note": "无人车A侦察"}], "selected_executor": None, "locked": False, "is_valid": True, "notes": ""},
            {"entry_id": "raw-302", "phase": "RAW", "entry_seq": 2, "target_ids": ["target:target-1"], "operation": "干扰", "executor_options": [{"executor_id": "equipment:vehicle-A", "allocation_count": 1, "locked": False, "note": "无人车A干扰"}], "selected_executor": None, "locked": False, "is_valid": True, "notes": ""},
            {"entry_id": "raw-303", "phase": "RAW", "entry_seq": 3, "target_ids": ["target:target-1"], "operation": "评估", "executor_options": [{"executor_id": "equipment:vehicle-A", "allocation_count": 1, "locked": False, "note": "无人车A评估"}], "selected_executor": None, "locked": False, "is_valid": True, "notes": ""},
        ],
        "assigned_entries": [],
        "network": {"nodes": [], "edges": []},
        "is_mock": True,
        "created_at": datetime.now(timezone.utc).isoformat(),
        "updated_at": datetime.now(timezone.utc).isoformat(),
    }

    # ---------- 更多 Plan 方案（Mock） ----------
    plan_2 = {
        "resource_id": "plan:plan-demo-002",
        "task_type": "PLAN",
        "plan_id": "plan-demo-002",
        "title": "雷达站侦察打击行动方案",
        "description": "由 kill_chain:kc-demo-002 映射生成的行动方案。",
        "state": "DRAFT",
        "teams": [
            {"task_type": "TEAM", "team_id": "team-recon-2", "name": "侦察打击组", "plan_id": "plan-demo-002", "description": "无人车A侦察 + 无人车B打击", "equipment": ["equipment:vehicle-A", "equipment:vehicle-B"], "state": "READY"},
        ],
        "targets": [
            {"task_type": "TARGET", "target_id": "target-2", "name": "目标2", "plan_id": "plan-demo-002", "target_type": "地面目标"},
        ],
        "stages": [
            {"task_type": "STAGE", "stage_id": "stage-001", "title": "侦察阶段", "plan_id": "plan-demo-002", "stage_seq": 1, "target_ids": ["target:target-2"], "team_ids": ["team-recon-2"], "state": "SCHEDULED"},
            {"task_type": "STAGE", "stage_id": "stage-002", "title": "打击阶段", "plan_id": "plan-demo-002", "stage_seq": 2, "target_ids": ["target:target-2"], "team_ids": ["team-recon-2"], "state": "SCHEDULED"},
        ],
        "is_mock": True,
        "created_at": datetime.now(timezone.utc).isoformat(),
        "updated_at": datetime.now(timezone.utc).isoformat(),
    }

    plan_3 = {
        "resource_id": "plan:plan-demo-003",
        "task_type": "PLAN",
        "plan_id": "plan-demo-003",
        "title": "通信枢纽干扰行动方案",
        "description": "由 kill_chain:kc-demo-003 映射生成的行动方案。",
        "state": "DRAFT",
        "teams": [
            {"task_type": "TEAM", "team_id": "team-jam-3", "name": "干扰评估组", "plan_id": "plan-demo-003", "description": "无人车A执行侦察干扰评估", "equipment": ["equipment:vehicle-A"], "state": "READY"},
        ],
        "targets": [
            {"task_type": "TARGET", "target_id": "target-1", "name": "目标1", "plan_id": "plan-demo-003", "target_type": "地面目标"},
        ],
        "stages": [
            {"task_type": "STAGE", "stage_id": "stage-003", "title": "侦察干扰阶段", "plan_id": "plan-demo-003", "stage_seq": 1, "target_ids": ["target:target-1"], "team_ids": ["team-jam-3"], "state": "SCHEDULED"},
        ],
        "is_mock": True,
        "created_at": datetime.now(timezone.utc).isoformat(),
        "updated_at": datetime.now(timezone.utc).isoformat(),
    }

    # 给原始数据也加上 mock 标记
    kill_chain["is_mock"] = True
    plan["is_mock"] = True

    # ---------- 写入存储 ----------
    for t in targets:
        task_pool.set(t["resource_id"], t)
    for r in resources:
        task_pool.set(r["resource_id"], r)
    task_pool.set(kill_chain["resource_id"], kill_chain)
    task_pool.set(kill_chain_2["resource_id"], kill_chain_2)
    task_pool.set(kill_chain_3["resource_id"], kill_chain_3)
    task_pool.set(plan["resource_id"], plan)
    task_pool.set(plan_2["resource_id"], plan_2)
    task_pool.set(plan_3["resource_id"], plan_3)

    print(f"[MockData] Loaded: {len(targets)} targets, {len(resources)} resources, 3 kill_chains, 3 plans")
