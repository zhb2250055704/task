#!/usr/bin/env python3
"""Protocol test planning, execution, persistence, and report generation."""

import json
import math
import os
import posixpath
import re
import threading
import time
import uuid
import zipfile
import xml.etree.ElementTree as ET
from collections import Counter


_XL_NS = "{http://schemas.openxmlformats.org/spreadsheetml/2006/main}"
_REL_NS = "{http://schemas.openxmlformats.org/officeDocument/2006/relationships}"
_RUN_ID_RE = re.compile(r"^[A-Za-z0-9_-]{8,80}$")
_PROTOCOL_RE = re.compile(r"^[A-Za-z][A-Za-z0-9_]{1,120}$")
_MAX_COUNT = 10000
_MAX_EVENTS = 2000
_FATAL_ERROR_CODES = {
    "identity_incomplete",
    "identity_changed",
    "transport_exception",
    "transport_failed",
    "rpc_failed",
    "invalid_response",
}

FISHING_TEMPLATE = {
    "id": "fishing-drop-sampling",
    "name": "钓鱼活动掉落抽样",
    "fixture": "fishing",
    "request_protocol": "CgFishStart",
    "response_protocol": "GcFishStartResult",
    "request_payload": {
        "activityMetaId": "",
        "times": 1,
        "scene": 1,
    },
    "response_match": {"activityMetaId": ""},
    "success_condition": "code == 0",
    "finish_protocol": "CgFishFinish",
    "finish_response_protocol": "GcFishFinishResult",
    "finish_payload": {"activityMetaId": ""},
    "count": 1000,
    "concurrency": 1,
    "interval_ms": 0,
    "timeout_ms": 10000,
}

PROTOCOL_FIELD_HINTS = {
    "CgFishStart": [
        {"name": "activityMetaId", "type": "string", "required": True},
        {"name": "times", "type": "number", "required": False},
        {"name": "scene", "type": "number", "required": False},
    ],
    "GcFishStartResult": [
        {"name": "activityMetaId", "type": "string", "required": True},
        {"name": "code", "type": "number", "required": False},
        {"name": "current", "type": "PsFishRecord", "required": False},
        {"name": "goldPoolNum", "type": "number", "required": False},
        {"name": "stage", "type": "number", "required": False},
    ],
    "CgFishFinish": [
        {"name": "activityMetaId", "type": "string", "required": True},
    ],
    "GcFishFinishResult": [
        {"name": "activityMetaId", "type": "string", "required": True},
        {"name": "code", "type": "number", "required": False},
    ],
}

_STATIC_PROTOCOLS = {
    "CgFishStart": {"description": "钓鱼开始", "direction": "request"},
    "GcFishStartResult": {"description": "钓鱼开始结果", "direction": "response"},
    "CgFishFinish": {"description": "钓鱼结束", "direction": "request"},
    "GcFishFinishResult": {"description": "钓鱼结束结果", "direction": "response"},
}


def _json_safe(value):
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    if isinstance(value, dict):
        return {str(key): _json_safe(item) for key, item in value.items()}
    if isinstance(value, (list, tuple, set)):
        return [_json_safe(item) for item in value]
    return str(value)


def _write_json(path, value):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    temp_path = path + ".tmp"
    with open(temp_path, "w", encoding="utf-8") as handle:
        json.dump(_json_safe(value), handle, ensure_ascii=False, indent=2)
    os.replace(temp_path, path)


def _read_json(path, default=None):
    try:
        with open(path, "r", encoding="utf-8") as handle:
            return json.load(handle)
    except (OSError, ValueError, TypeError):
        return default


def _now_ms():
    return int(time.time() * 1000)


def _protocol_name(value):
    name = str(value or "").strip()
    return name if _PROTOCOL_RE.fullmatch(name) else ""


def _as_int(value, default):
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def _path_get(value, path):
    current = value
    for part in str(path or "").split("."):
        if not part:
            continue
        if isinstance(current, dict):
            current = current.get(part)
        else:
            return None
    return current


def _same_value(actual, expected):
    if actual == expected:
        return True
    if isinstance(actual, (int, float)) and isinstance(expected, (int, float)):
        return float(actual) == float(expected)
    return str(actual) == str(expected)


def _matches(value, expected):
    if not isinstance(expected, dict):
        return _same_value(value, expected)
    if not isinstance(value, dict):
        return False
    return all(key in value and _matches(value[key], item) for key, item in expected.items())


def evaluate_condition(response, expression):
    expression = str(expression or "").strip()
    if not expression:
        return True, ""
    match = re.fullmatch(r"([A-Za-z_][A-Za-z0-9_.]*)\s*(==|!=)\s*([^\s]+)", expression)
    if not match:
        return False, f"不支持的断言表达式：{expression}"
    actual = _path_get(response, match.group(1))
    expected_raw = match.group(3).strip().strip("'\"")
    expected = expected_raw
    if expected_raw.lower() in ("true", "false"):
        expected = expected_raw.lower() == "true"
    else:
        try:
            expected = float(expected_raw) if "." in expected_raw else int(expected_raw)
        except ValueError:
            pass
    matched = _same_value(actual, expected)
    return (matched if match.group(2) == "==" else not matched), ""


def wilson_interval(successes, total, z=1.959963984540054):
    successes = max(0, int(successes or 0))
    total = max(0, int(total or 0))
    if not total:
        return {"low": 0.0, "high": 0.0, "confidence": 0.95}
    p = successes / total
    denominator = 1 + (z * z / total)
    centre = (p + z * z / (2 * total)) / denominator
    margin = z * math.sqrt((p * (1 - p) + z * z / (4 * total)) / total) / denominator
    return {
        "low": max(0.0, centre - margin),
        "high": min(1.0, centre + margin),
        "confidence": 0.95,
    }


def _col_index(reference):
    letters = "".join(char for char in str(reference or "") if char.isalpha())
    index = 0
    for char in letters:
        index = index * 26 + ord(char.upper()) - ord("A") + 1
    return index


def _row_index(reference):
    digits = "".join(char for char in str(reference or "") if char.isdigit())
    return int(digits) if digits else 0


def _shared_strings(archive):
    path = "xl/sharedStrings.xml"
    if path not in archive.namelist():
        return []
    root = ET.fromstring(archive.read(path))
    return ["".join(node.text or "" for node in item.iter(f"{_XL_NS}t"))
            for item in root.findall(f"{_XL_NS}si")]


def _sheet_paths(archive):
    names = set(archive.namelist())
    if "xl/workbook.xml" not in names or "xl/_rels/workbook.xml.rels" not in names:
        return []
    workbook = ET.fromstring(archive.read("xl/workbook.xml"))
    rels = ET.fromstring(archive.read("xl/_rels/workbook.xml.rels"))
    rel_map = {node.get("Id"): node.get("Target", "") for node in rels}
    result = []
    for sheet in workbook.iter(f"{_XL_NS}sheet"):
        title = sheet.get("name") or f"Sheet{len(result) + 1}"
        target = rel_map.get(sheet.get(f"{_REL_NS}id"), "")
        if target.startswith("/"):
            path = target.lstrip("/")
        else:
            path = posixpath.normpath(posixpath.join("xl", target))
        if path in names:
            result.append((title, path))
    return result


def _xlsx_value(cell, shared):
    cell_type = cell.get("t")
    if cell_type == "inlineStr":
        node = cell.find(f"{_XL_NS}is")
        return "".join(item.text or "" for item in node.iter(f"{_XL_NS}t")) if node is not None else ""
    node = cell.find(f"{_XL_NS}v")
    raw = node.text if node is not None and node.text is not None else ""
    if cell_type == "s":
        try:
            return shared[int(raw)]
        except (ValueError, IndexError):
            return ""
    if cell_type == "b":
        return "TRUE" if raw == "1" else "FALSE"
    return raw


def _load_xlsx_rows(path):
    if not os.path.isfile(path):
        return []
    result = []
    try:
        with zipfile.ZipFile(path) as archive:
            shared = _shared_strings(archive)
            for title, sheet_path in _sheet_paths(archive):
                root = ET.fromstring(archive.read(sheet_path))
                rows = {}
                max_col = 0
                sheet_data = root.find(f"{_XL_NS}sheetData")
                if sheet_data is not None:
                    for row in sheet_data.findall(f"{_XL_NS}row"):
                        row_number = _as_int(row.get("r"), 0)
                        row_values = rows.setdefault(row_number, {})
                        for cell in row.findall(f"{_XL_NS}c"):
                            column = _col_index(cell.get("r"))
                            row_values[column] = _xlsx_value(cell, shared)
                            max_col = max(max_col, column)
                result.append({
                    "name": title,
                    "rows": [
                        {"row": row_number, "values": [str(values.get(column, "")) for column in range(1, max_col + 1)]}
                        for row_number, values in sorted(rows.items())
                    ],
                })
    except (OSError, ValueError, zipfile.BadZipFile, ET.ParseError):
        return []
    return result


def _extract_config_fields(rows, keys):
    keys = set(keys)
    for index, row in enumerate(rows):
        values = row.get("values", [])
        positions = {str(value).strip(): column for column, value in enumerate(values) if str(value).strip() in keys}
        if len(positions) < 2:
            continue
        data_row = None
        for candidate in rows[index + 1:index + 20]:
            values = [str(value).strip() for value in candidate.get("values", []) if str(value).strip()]
            # 配置表通常会在字段名后放类型行和示例行，真实数据行不会是单一重复值。
            if values and len(set(values)) > 1 and re.fullmatch(r"-?\d+(?:\.\d+)?", values[0]):
                data_row = candidate.get("values", [])
                break
        if data_row is None:
            continue
        return {key: str(data_row[column]).strip() if column < len(data_row) else ""
                for key, column in positions.items()}
    return {}


def _extract_config_records(rows, keys):
    """Extract real config rows while skipping the workbook's type/example rows."""
    keys = set(keys)
    for index, row in enumerate(rows or []):
        values = row.get("values", [])
        positions = {
            str(value).strip(): column
            for column, value in enumerate(values)
            if str(value).strip() in keys
        }
        if "id" not in positions or "name" not in positions:
            continue

        id_position = positions["id"]
        name_position = positions["name"]
        records = []
        for candidate in rows[index + 1:]:
            candidate_values = candidate.get("values", [])
            id_value = str(candidate_values[id_position]).strip() if id_position < len(candidate_values) else ""
            name_value = str(candidate_values[name_position]).strip() if name_position < len(candidate_values) else ""
            if not re.fullmatch(r"-?\d+(?:\.\d+)?", id_value):
                continue
            # Type and example rows use numeric placeholders in the name column.
            if not name_value or re.fullmatch(r"-?\d+(?:\.\d+)?", name_value):
                continue
            record = {
                key: str(candidate_values[column]).strip() if column < len(candidate_values) else ""
                for key, column in positions.items()
            }
            # The column before the localization key is the display name in the source workbook.
            display_position = name_position - 1
            display_name = (
                str(candidate_values[display_position]).strip()
                if display_position >= 0 and display_position < len(candidate_values)
                else ""
            )
            record["name_key"] = name_value
            record["name"] = display_name or name_value
            record["display_name"] = display_name or name_value
            records.append(record)
        if records:
            return records
    return []


_FISH_QUALITY_LABELS = {
    "1": "普通",
    "2": "普通",
    "3": "稀有",
    "4": "史诗",
    "5": "传说",
}


def _fish_quality_label(value):
    raw = str(value or "").strip()
    if not raw:
        return ""
    return _FISH_QUALITY_LABELS.get(raw, "品质 " + raw)


def _fish_config_view(record):
    raw_quality = str(record.get("quality") or "").strip()
    quality = _as_int(raw_quality, None) if raw_quality else None
    return {
        "fish_id": str(record.get("id") or ""),
        "name": str(record.get("name") or record.get("name_key") or "未知鱼类"),
        "name_key": str(record.get("name_key") or ""),
        "quality": quality if quality is not None else raw_quality,
        "quality_name": _fish_quality_label(raw_quality),
        "quality_display": (
            str(quality) + "（" + _fish_quality_label(raw_quality) + "）"
            if quality is not None and _fish_quality_label(raw_quality)
            else raw_quality
        ),
        "weight_range": str(record.get("weight") or ""),
        "crown_weight": str(record.get("crownWeight") or ""),
        "reward_id": str(record.get("reward") or ""),
        "day_and_night": str(record.get("dayAndNight") or ""),
        "desc_key": str(record.get("desc") or ""),
    }


def _weighted_distribution(raw):
    values = []
    for part in str(raw or "").split(","):
        fields = [item.strip() for item in part.split("|", 1)]
        if len(fields) != 2:
            continue
        try:
            values.append((str(int(fields[0])), float(fields[1])))
        except (ValueError, TypeError):
            continue
    total = sum(weight for _, weight in values)
    if not total:
        return []
    return [{"value": value, "weight": weight, "probability": weight / total} for value, weight in values]


def load_fishing_baseline(excel_root):
    path = os.path.join(excel_root, "csv", "common", "COA_ActivityFishingEvent.xlsx")
    sheets = _load_xlsx_rows(path)
    names = [sheet["name"] for sheet in sheets]
    main = next((sheet for sheet in sheets if sheet["name"] == "FishingEventMain"), None)
    map_sheet = next((sheet for sheet in sheets if sheet["name"] == "FishingEventMap"), None)
    pool_sheet = next((sheet for sheet in sheets if sheet["name"] == "FishingEventPool"), None)
    keys = [
        "itemId", "cost", "multiplier", "fishNumProb", "mapID", "dayTime",
        "goldenFishProb", "goldenFishMercyDrop", "goldenFishMercyNum",
        "goldenFishMissNum", "wonderland", "wonderlandProb", "wonderlandMercyDrop",
        "wonderlandMercyNum", "crownMercy",
    ]
    fields = _extract_config_fields(main.get("rows", []), keys) if main else {}
    fish_number_distribution = _weighted_distribution(fields.get("fishNumProb"))
    expected_fish_per_action = sum(
        float(item["value"]) * item["probability"] for item in fish_number_distribution
    )
    map_records = _extract_config_records(
        map_sheet.get("rows", []) if map_sheet else [],
        ["id", "name", "sceneRes", "unlockSeason", "nextMap", "collectionID", "fishRequest", "fishPool1", "fishPool2"],
    )
    pool_records = _extract_config_records(
        pool_sheet.get("rows", []) if pool_sheet else [],
        ["id", "name", "crownName", "desc", "pic", "model", "quality", "weight", "crownWeight", "reward", "dayAndNight", "offset"],
    )
    fishing_grounds = {
        str(record.get("id")): {
            "fishing_ground_id": str(record.get("id") or ""),
            "name": str(record.get("name") or "未知渔场"),
            "name_key": str(record.get("name_key") or ""),
            "scene_res": str(record.get("sceneRes") or ""),
            "fish_pool_1": str(record.get("fishPool1") or ""),
            "fish_pool_2": str(record.get("fishPool2") or ""),
        }
        for record in map_records
        if str(record.get("id") or "").strip()
    }
    fish_configs = {
        config["fish_id"]: config
        for config in (_fish_config_view(record) for record in pool_records)
        if config["fish_id"]
    }
    return {
        "file": path,
        "exists": bool(sheets),
        "sheets": names,
        "main_fields": fields,
        "fish_number_distribution": fish_number_distribution,
        "expected_fish_per_action": expected_fish_per_action,
        "expected_fish_count": expected_fish_per_action * 1000,
        "fishing_grounds": fishing_grounds,
        "fish_configs": fish_configs,
    }


def discover_protocols(client_root):
    path = os.path.join(client_root, "creator", "assets", "scripts", "common", "msg_type.ts")
    found = {}
    try:
        with open(path, "r", encoding="utf-8") as handle:
            source = handle.read()
    except OSError:
        source = ""
    pattern = re.compile(r"^\s*((?:Cg|Gc)[A-Za-z0-9_]+)\s*:\s*(\d+)\s*;\s*(?://\s*(.*))?$", re.MULTILINE)
    for match in pattern.finditer(source):
        name, message_id, description = match.groups()
        direction = "request" if name.startswith("Cg") else "response"
        found[name] = {
            "name": name,
            "id": int(message_id),
            "direction": direction,
            "description": str(description or "").strip(),
            "fields": PROTOCOL_FIELD_HINTS.get(name, []),
        }
    for name, hint in _STATIC_PROTOCOLS.items():
        found.setdefault(name, {
            "name": name,
            "id": 0,
            "direction": hint["direction"],
            "description": hint["description"],
            "fields": PROTOCOL_FIELD_HINTS.get(name, []),
        })
        found[name].update({"fields": PROTOCOL_FIELD_HINTS.get(name, []), "description": hint["description"]})
    return sorted(found.values(), key=lambda item: (item["id"] == 0, item["id"], item["name"]))


def protocol_catalog(client_root, excel_root):
    return {
        "protocols": discover_protocols(client_root),
        "templates": [FISHING_TEMPLATE],
        "baselines": {"fishing": load_fishing_baseline(excel_root)},
    }


def normalize_plan(payload):
    payload = payload if isinstance(payload, dict) else {}
    request = payload.get("request") if isinstance(payload.get("request"), dict) else {}
    finish = payload.get("finish") if isinstance(payload.get("finish"), dict) else {}
    target_specs = payload.get("target_specs")
    if not isinstance(target_specs, list):
        target_specs = []
    request_payload = request.get("payload", payload.get("request_payload", {}))
    finish_payload = finish.get("payload", payload.get("finish_payload", {}))
    if not isinstance(request_payload, dict):
        request_payload = {}
    if not isinstance(finish_payload, dict):
        finish_payload = {}
    response_match = request.get("response_match", payload.get("response_match", {}))
    if not isinstance(response_match, dict):
        response_match = {}
    return {
        "title": str(payload.get("title") or "协议测试").strip()[:120],
        "fixture": str(payload.get("fixture") or "generic").strip().lower(),
        "target_specs": [item for item in target_specs if isinstance(item, dict)],
        "request_protocol": _protocol_name(request.get("protocol") or payload.get("request_protocol")),
        "request_payload": _json_safe(request_payload),
        "response_protocol": _protocol_name(request.get("response_protocol") or payload.get("response_protocol")),
        "response_match": _json_safe(response_match),
        "success_condition": str(request.get("success_condition") or payload.get("success_condition") or "").strip(),
        "finish_protocol": _protocol_name(finish.get("protocol") or payload.get("finish_protocol")),
        "finish_payload": _json_safe(finish_payload),
        "finish_response_protocol": _protocol_name(finish.get("response_protocol") or payload.get("finish_response_protocol")),
        "count": max(1, min(_MAX_COUNT, _as_int(payload.get("count"), 1000))),
        "concurrency": max(1, _as_int(payload.get("concurrency"), 1)),
        "interval_ms": max(0, min(60000, _as_int(payload.get("interval_ms"), 0))),
        "timeout_ms": max(1000, min(12000, _as_int(payload.get("timeout_ms"), 10000))),
    }


def validate_plan(plan, require_target=True):
    errors = []
    if not plan.get("request_protocol"):
        errors.append("请求协议名称不能为空")
    if not plan.get("response_protocol"):
        errors.append("响应协议名称不能为空")
    if require_target and len(plan.get("target_specs") or []) != 1:
        errors.append("协议测试首期必须选择 1 个本机 Cocos 客户端账号")
    if plan.get("concurrency") != 1:
        errors.append("首期协议测试只支持串行执行，并发数必须为 1")
    if plan.get("fixture") == "fishing":
        if plan.get("request_protocol") != "CgFishStart" or plan.get("response_protocol") != "GcFishStartResult":
            errors.append("钓鱼模板必须使用 CgFishStart / GcFishStartResult")
        if plan.get("count", 0) > 10000:
            errors.append("单次测试最多执行 10000 次")
    return errors


def preview_plan(payload, client_root, excel_root):
    plan = normalize_plan(payload)
    errors = validate_plan(plan, require_target=False)
    baseline = load_fishing_baseline(excel_root) if plan.get("fixture") == "fishing" else None
    warnings = [
        "协议测试会真实消耗账号资源并改变游戏状态，请使用隔离测试账号。",
        "超时请求不会自动重试，避免重复消耗和污染概率统计。",
    ]
    if plan.get("fixture") == "fishing":
        warnings.extend([
            "钓鱼测试会改变道具、图鉴、总重量及金鱼/传奇鱼场保底状态。",
            "times 建议保持为 1，1000 次应由测试框架拆成 1000 个独立动作。",
        ])
    return {
        "ok": not errors,
        "plan": plan,
        "errors": errors,
        "warnings": warnings,
        "baseline": baseline,
        "protocols": discover_protocols(client_root),
    }


def _extract_fish_record(response):
    current = response.get("current") if isinstance(response, dict) else None
    return current if isinstance(current, dict) else {}


def _extract_fishes(response):
    fishes = _extract_fish_record(response).get("fishes")
    return fishes if isinstance(fishes, list) else []


def _new_stats():
    return {
        "requested": 0,
        "completed": 0,
        "success": 0,
        "business_failed": 0,
        "transport_failed": 0,
        "timeout": 0,
        "finish_failures": 0,
        "error_codes": {},
        "fish_total": 0,
        "fish_by_id": {},
        "fish_weight_by_id": {},
        "item_by_id": {},
        "mask_counts": {},
        "fishing_ground_ids": {},
        "fish_scene_ids": {},
        "response_latencies_ms": [],
        "response_by_protocol": {},
        "response_code_by_protocol": {},
        "response_samples": [],
    }


def _increment(mapping, key, amount=1):
    key = str(key)
    mapping[key] = int(mapping.get(key, 0)) + amount


def _record_response(stats, response_protocol, response):
    protocol = str(response_protocol or "unknown")
    _increment(stats["response_by_protocol"], protocol)
    code = response.get("code") if isinstance(response, dict) else None
    code_key = str(code) if code is not None else "none"
    code_counts = stats["response_code_by_protocol"].setdefault(protocol, {})
    _increment(code_counts, code_key)
    if len(stats["response_samples"]) < 3:
        if isinstance(response, dict):
            sample = {
                "protocol": protocol,
                "code": code,
                "keys": list(response.keys())[:30],
            }
        else:
            sample = {
                "protocol": protocol,
                "code": code,
                "type": type(response).__name__,
            }
        stats["response_samples"].append(_json_safe(sample))


def _numeric_weights(values):
    result = []
    for value in values or []:
        try:
            number = float(value)
        except (TypeError, ValueError):
            continue
        if math.isfinite(number):
            result.append(int(number) if number.is_integer() else number)
    return result


def _weight_summary(values):
    weights = _numeric_weights(values)
    if not weights:
        return {
            "sample_count": 0,
            "min": None,
            "max": None,
            "average": None,
        }
    return {
        "sample_count": len(weights),
        "min": min(weights),
        "max": max(weights),
        "average": sum(weights) / len(weights),
    }


def _record_fishes(stats, fishes, scene_id=None):
    scene_key = str(scene_id).strip() if scene_id is not None else ""
    if scene_key:
        _increment(stats["fishing_ground_ids"], scene_key)
    for fish in fishes:
        if not isinstance(fish, dict):
            continue
        fish_id = str(fish.get("fishId", "unknown"))
        _increment(stats["fish_by_id"], fish_id)
        stats["fish_total"] += 1
        if scene_key:
            scene_ids = stats["fish_scene_ids"].setdefault(fish_id, [])
            if scene_key not in scene_ids:
                scene_ids.append(scene_key)
        weight = fish.get("weight")
        if weight is not None:
            stats["fish_weight_by_id"].setdefault(fish_id, []).append(weight)
        if fish.get("mask") is not None:
            _increment(stats["mask_counts"], fish.get("mask"))
        for item in fish.get("items") or []:
            if not isinstance(item, dict):
                continue
            item_id = item.get("itemId", item.get("id", "unknown"))
            _increment(stats["item_by_id"], item_id, _as_int(item.get("num", item.get("count", 1)), 1))


def _report_fishing_ground(baseline, stats, state):
    configured_grounds = (baseline or {}).get("fishing_grounds") or {}
    observed_ids = list((stats.get("fishing_ground_ids") or {}).keys())
    requested_scene = _path_get(state.get("plan") or {}, "request_payload.scene")
    if not observed_ids and requested_scene is not None and str(requested_scene).strip():
        observed_ids = [str(requested_scene).strip()]
    names = [_fishing_ground_name(configured_grounds, scene_id) for scene_id in observed_ids]
    return {
        "id": ", ".join(observed_ids),
        "name": " / ".join(names) if names else "未知渔场",
        "ids": observed_ids,
        "names": names,
    }


def _fishing_ground_name(configured_grounds, scene_id):
    ground = (configured_grounds or {}).get(str(scene_id)) or {}
    return str(ground.get("name") or "场景 " + str(scene_id))


def _build_report(state, stats, baseline):
    completed = max(0, int(stats.get("completed", 0)))
    fixture = state.get("fixture") or "generic"
    is_fishing = fixture == "fishing"
    fish_total = max(0, int(stats.get("fish_total", 0))) if is_fishing else 0
    fishing_ground = _report_fishing_ground(baseline, stats, state) if is_fishing else None
    fish_configs = ((baseline or {}).get("fish_configs") or {}) if is_fishing else {}
    latencies = sorted(stats.get("response_latencies_ms") or [])
    def percentile(ratio):
        if not latencies:
            return 0
        index = min(len(latencies) - 1, max(0, math.ceil(len(latencies) * ratio) - 1))
        return latencies[index]
    fish_distribution = []
    for fish_id, count in sorted(stats.get("fish_by_id", {}).items(), key=lambda item: (-item[1], item[0])) if is_fishing else []:
        interval = wilson_interval(count, fish_total)
        config = fish_configs.get(fish_id) or {}
        observed_weight = _weight_summary((stats.get("fish_weight_by_id") or {}).get(fish_id, []))
        scene_ids = list((stats.get("fish_scene_ids") or {}).get(fish_id) or fishing_ground["ids"])
        scene_names = [
            _fishing_ground_name((baseline or {}).get("fishing_grounds") or {}, scene_id)
            for scene_id in scene_ids
        ]
        fish_distribution.append({
            "fish_id": fish_id,
            "fish_name": config.get("name") or "未知鱼类",
            "fish_name_key": config.get("name_key") or "",
            "fishing_ground_id": ", ".join(scene_ids),
            "fishing_ground_name": " / ".join(scene_names) if scene_names else fishing_ground["name"],
            "config": config,
            "observed_weight": observed_weight,
            "count": count,
            "probability": count / fish_total if fish_total else 0,
            "interval": interval,
        })
    return {
        "run_id": state["id"],
        "title": state["title"],
        "fixture": fixture,
        "status": state["status"],
        "created_at_ms": state.get("created_at_ms", 0),
        "started_at_ms": state.get("started_at_ms", 0),
        "finished_at_ms": state.get("finished_at_ms", 0),
        "duration_ms": max(0, state.get("finished_at_ms", 0) - state.get("started_at_ms", 0)),
        "fishing_ground": fishing_ground,
        "actions": {
            "requested": stats["requested"],
            "completed": completed,
            "success": stats["success"],
            "business_failed": stats["business_failed"],
            "transport_failed": stats["transport_failed"],
            "timeout": stats["timeout"],
            "finish_failures": stats["finish_failures"],
            "success_rate": stats["success"] / completed if completed else 0,
            "error_codes": stats["error_codes"],
        },
        "latency_ms": {
            "count": len(latencies),
            "p50": percentile(0.50),
            "p95": percentile(0.95),
            "p99": percentile(0.99),
            "average": sum(latencies) / len(latencies) if latencies else 0,
        },
        "drops": {
            "fish_total": fish_total,
            "fish_by_id": stats["fish_by_id"] if is_fishing else {},
            "fish_distribution": fish_distribution,
            "fish_weight_by_id": stats["fish_weight_by_id"] if is_fishing else {},
            "items": stats["item_by_id"] if is_fishing else {},
            "mask_counts": stats["mask_counts"] if is_fishing else {},
            "fishing_ground_ids": stats["fishing_ground_ids"] if is_fishing else {},
        },
        "generic": {
            "response_total": sum(stats["response_by_protocol"].values()),
            "response_by_protocol": stats["response_by_protocol"],
            "response_code_by_protocol": stats["response_code_by_protocol"],
            "samples": stats["response_samples"],
        },
        "config_baseline": baseline,
    }


class ProtocolTestService:
    def __init__(self, runtime_dir, client_root, excel_root):
        self.runtime_dir = runtime_dir
        self.client_root = client_root
        self.excel_root = excel_root
        self.lock = threading.RLock()
        self.runs = {}
        self.stop_events = {}
        self.workers = {}
        os.makedirs(runtime_dir, exist_ok=True)

    def _run_dir(self, run_id):
        if not _RUN_ID_RE.fullmatch(str(run_id or "")):
            return None
        return os.path.join(self.runtime_dir, str(run_id))

    def _load_state(self, run_id):
        with self.lock:
            if run_id in self.runs:
                return dict(self.runs[run_id])
        return _read_json(os.path.join(self._run_dir(run_id) or "", "run.json"), None)

    def start(self, payload, send_request):
        plan = normalize_plan(payload)
        errors = validate_plan(plan, require_target=True)
        if errors:
            return {"ok": False, "code": "invalid_plan", "msg": "；".join(errors), "errors": errors}
        run_id = "pt-" + uuid.uuid4().hex[:16]
        state = {
            "id": run_id,
            "title": plan["title"],
            "fixture": plan["fixture"],
            "status": "queued",
            "created_at_ms": _now_ms(),
            "started_at_ms": 0,
            "finished_at_ms": 0,
            "progress": 0,
            "total": plan["count"],
            "completed": 0,
            "success": 0,
            "failed": 0,
            "timeout": 0,
            "event_count": 0,
            "message": "等待执行",
            "plan": plan,
        }
        run_dir = self._run_dir(run_id)
        os.makedirs(run_dir, exist_ok=True)
        _write_json(os.path.join(run_dir, "run.json"), state)
        _write_json(os.path.join(run_dir, "plan.json"), plan)
        stop_event = threading.Event()
        with self.lock:
            self.runs[run_id] = state
            self.stop_events[run_id] = stop_event
        worker = threading.Thread(
            target=self._run, args=(run_id, plan, stop_event, send_request),
            name=f"protocol-test-{run_id}", daemon=True,
        )
        with self.lock:
            self.workers[run_id] = worker
        worker.start()
        return {"ok": True, "run": dict(state)}

    def _save_state(self, state):
        with self.lock:
            self.runs[state["id"]] = dict(state)
        _write_json(os.path.join(self._run_dir(state["id"]), "run.json"), state)

    def _append_event(self, run_id, event):
        run_dir = self._run_dir(run_id)
        if not run_dir:
            return
        with open(os.path.join(run_dir, "events.jsonl"), "a", encoding="utf-8") as handle:
            handle.write(json.dumps(_json_safe(event), ensure_ascii=False, separators=(",", ":")) + "\n")

    def _run(self, run_id, plan, stop_event, send_request):
        state = self._load_state(run_id) or {"id": run_id, "title": plan["title"], "fixture": plan["fixture"]}
        state.update({"status": "running", "started_at_ms": _now_ms(), "message": "正在执行协议测试"})
        stats = _new_stats()
        stats["requested"] = plan["count"]
        self._save_state(state)
        baseline = load_fishing_baseline(self.excel_root) if plan["fixture"] == "fishing" else None
        try:
            for sequence in range(1, plan["count"] + 1):
                if stop_event.is_set():
                    state["status"] = "stopped"
                    state["message"] = "测试已停止"
                    break
                sent_at = _now_ms()
                request_payload = _json_safe(plan["request_payload"])
                event = {
                    "run_id": run_id,
                    "sequence": sequence,
                    "sent_at_ms": sent_at,
                    "request_protocol": plan["request_protocol"],
                    "request": request_payload,
                    "response_protocol": plan["response_protocol"],
                }
                stats["completed"] += 1
                result = None
                try:
                    result = send_request(
                        plan["request_protocol"], request_payload, plan["response_protocol"],
                        plan["timeout_ms"], plan["response_match"],
                    )
                except Exception as exc:
                    result = {"ok": False, "code": "transport_exception", "error": str(exc)}
                received_at = _now_ms()
                event["received_at_ms"] = received_at
                event["latency_ms"] = max(0, received_at - sent_at)
                event["transport"] = _json_safe(result or {})
                if result and result.get("ok"):
                    response = result.get("response")
                    event["response"] = _json_safe(response)
                    _record_response(
                        stats,
                        result.get("response_protocol") or plan["response_protocol"],
                        response,
                    )
                    if plan["response_match"] and not _matches(response, plan["response_match"]):
                        result = {"ok": False, "code": "response_mismatch", "error": "响应字段不符合预期"}
                    else:
                        condition_ok, condition_error = evaluate_condition(response, plan["success_condition"])
                        if not condition_ok:
                            result = {"ok": False, "code": "assertion_failed", "error": condition_error or "响应断言失败"}
                        else:
                            stats["success"] += 1
                            stats["response_latencies_ms"].append(event["latency_ms"])
                            if plan["fixture"] == "fishing":
                                fish_record = _extract_fish_record(response)
                                scene_id = fish_record.get("scene", request_payload.get("scene"))
                                _record_fishes(stats, _extract_fishes(response), scene_id)
                            finish_result = None
                            if plan["finish_protocol"]:
                                finish_result = send_request(
                                    plan["finish_protocol"], plan["finish_payload"],
                                    plan["finish_response_protocol"] or "", plan["timeout_ms"],
                                    {},
                                )
                                if not finish_result or not finish_result.get("ok"):
                                    stats["finish_failures"] += 1
                                event["finish"] = _json_safe(finish_result)
                if not (result and result.get("ok")):
                    code = str((result or {}).get("code") or "unknown")
                    _increment(stats["error_codes"], code)
                    if code in ("timeout", "protocol_timeout") or "超时" in str((result or {}).get("error") or ""):
                        stats["timeout"] += 1
                    elif code in ("transport_exception", "transport_failed", "rpc_failed"):
                        stats["transport_failed"] += 1
                    else:
                        stats["business_failed"] += 1
                    state["failed"] = stats["business_failed"] + stats["transport_failed"] + stats["timeout"]
                    event["error"] = _json_safe((result or {}).get("error") or "协议测试失败")
                state["completed"] = stats["completed"]
                state["success"] = stats["success"]
                state["timeout"] = stats["timeout"]
                state["progress"] = round(stats["completed"] / plan["count"] * 100, 2)
                state["event_count"] = sequence
                state["message"] = f"已完成 {sequence}/{plan['count']} 次"
                self._append_event(run_id, event)
                self._save_state(state)
                if not (result and result.get("ok")) and code in _FATAL_ERROR_CODES:
                    state["status"] = "failed"
                    state["message"] = str((result or {}).get("error") or "协议测试连接已不可用")
                    self._save_state(state)
                    break
                if plan["interval_ms"] and sequence < plan["count"]:
                    stop_event.wait(plan["interval_ms"] / 1000)
        except Exception as exc:
            state["status"] = "failed"
            state["message"] = f"测试执行异常：{exc}"
        finally:
            if state.get("status") == "running":
                state["status"] = "succeeded" if stats["completed"] == plan["count"] else "stopped"
                state["message"] = "协议测试完成" if state["status"] == "succeeded" else "测试已停止"
            state["finished_at_ms"] = _now_ms()
            report = _build_report(state, stats, baseline)
            _write_json(os.path.join(self._run_dir(run_id), "report.json"), report)
            self._save_state(state)
            with self.lock:
                self.workers.pop(run_id, None)

    def stop(self, run_id):
        with self.lock:
            event = self.stop_events.get(run_id)
            state = self.runs.get(run_id)
        if not state:
            state = self._load_state(run_id)
        if not state:
            return {"ok": False, "code": "not_found", "msg": "测试任务不存在"}
        if event:
            event.set()
        if state.get("status") in ("queued", "running"):
            state["message"] = "正在停止测试"
            self._save_state(state)
        return {"ok": True, "run": state}

    def get(self, run_id):
        return self._load_state(run_id)

    def list(self):
        records = []
        try:
            names = os.listdir(self.runtime_dir)
        except OSError:
            names = []
        for name in names:
            state = self._load_state(name)
            if state:
                records.append(state)
        records.sort(key=lambda item: item.get("created_at_ms", 0), reverse=True)
        return records[:50]

    def events(self, run_id, limit=200):
        run_dir = self._run_dir(run_id)
        if not run_dir:
            return None
        path = os.path.join(run_dir, "events.jsonl")
        if not os.path.isfile(path):
            return []
        result = []
        try:
            with open(path, "r", encoding="utf-8") as handle:
                for line in handle:
                    if line.strip():
                        result.append(json.loads(line))
        except (OSError, ValueError):
            return result
        return result[-max(1, min(_MAX_EVENTS, _as_int(limit, 200))):]

    def report(self, run_id):
        run_dir = self._run_dir(run_id)
        if not run_dir:
            return None
        return _read_json(os.path.join(run_dir, "report.json"), None)
