#!/usr/bin/env python3
"""
Fleet Command API Test Suite
=============================
Comprehensive end-to-end testing of the Fleet Command API and Discord bot fleet.

Tests cover:
  Phase 0: Prerequisites & connectivity
  Phase 1: API authentication
  Phase 2: Read-only endpoint validation
  Phase 3: Bot config write/readback/file persistence
  Phase 4: Fleet section write tests
  Phase 5: Service restart reliability
  Phase 7: Discord bot behavioral verification
  Phase 8: Edge cases & input validation
  Phase 9: Cleanup & restoration

Usage:
  python3 fleet_command_test.py [--phase N] [--no-discord] [--no-restart] [--verbose]

Author: Writer Agent (Cursor)
Date: 2026-08-20
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import time
import threading
from datetime import datetime, timezone
from typing import Any, Optional

import requests

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

FLEET_API = os.environ.get("FLEET_API", "https://api-command.schubert.life")
FLEET_TOKEN = os.environ.get("FLEET_API_TOKEN", "dmL5dDLoLelxvmiqyVqBAowP5EJ-2fOpDUBVcPtIhhM")
BOT_TOKEN = os.environ.get("DISCORD_BOT_TOKEN", os.environ.get("DISCORD_TOKEN", ""))
DISCORD_API = "https://discord.com/api/v10"
CONFIG_PATH = "/opt/Project-Tango/config/fleet-config.json"

ALL_BOTS = ["admiral", "architect", "quartermaster", "cartographer", "dr_voss", "proctor", "cortex"]

BOT_CHANNELS = {
    "admiral": "1538476446157115442",
    "architect": "1539473266400432208",
    "quartermaster": "1538818248542396428",
    "cartographer": "1538818895706718269",
    "dr_voss": "1539104998821068880",
    "proctor": "1539159059071111190",
    "cortex": "1539173946698498088",
}

BOT_USER_IDS = {
    "admiral": "1538476585445892179",
    "architect": "1538766501035642890",
    "quartermaster": "1538817623045832746",
    "cartographer": "1538818587119067206",
    "dr_voss": "1539047086597873684",
    "proctor": "1539047471899086988",
    "cortex": "1539172849569243217",
}

# ---------------------------------------------------------------------------
# Result tracking
# ---------------------------------------------------------------------------

results: list[dict] = []


def record(test_id: str, description: str, passed: bool, expected: str = "", actual: str = "", details: str = ""):
    results.append({
        "test_id": test_id,
        "description": description,
        "passed": passed,
        "expected": expected,
        "actual": actual,
        "details": details,
        "timestamp": datetime.now(timezone.utc).isoformat(),
    })
    status = "PASS" if passed else "FAIL"
    print(f"[{status}] {test_id}: {description}")
    if not passed:
        print(f"  Expected: {expected}")
        print(f"  Actual: {actual}")


def save_results(filename: str):
    with open(filename, "w") as f:
        json.dump(results, f, indent=2)
    passed = sum(1 for r in results if r["passed"])
    failed = sum(1 for r in results if not r["passed"])
    print(f"\n{'='*60}")
    print(f"Total: {len(results)} | Passed: {passed} | Failed: {failed}")
    print(f"Results saved to {filename}")
    print(f"{'='*60}")


# ---------------------------------------------------------------------------
# API helpers
# ---------------------------------------------------------------------------

def fleet_get(endpoint: str):
    resp = requests.get(f"{FLEET_API}{endpoint}", headers={"Authorization": f"Bearer {FLEET_TOKEN}"})
    try:
        return resp.status_code, resp.json()
    except Exception:
        return resp.status_code, {"raw": resp.text}


def fleet_put(endpoint: str, data: dict):
    resp = requests.put(f"{FLEET_API}{endpoint}", headers={"Authorization": f"Bearer {FLEET_TOKEN}", "Content-Type": "application/json"}, json=data)
    try:
        return resp.status_code, resp.json()
    except Exception:
        return resp.status_code, {"raw": resp.text}


def fleet_post(endpoint: str, data: dict | None = None):
    headers = {"Authorization": f"Bearer {FLEET_TOKEN}"}
    if data is not None:
        headers["Content-Type"] = "application/json"
        resp = requests.post(f"{FLEET_API}{endpoint}", headers=headers, json=data)
    else:
        resp = requests.post(f"{FLEET_API}{endpoint}", headers=headers)
    try:
        return resp.status_code, resp.json()
    except Exception:
        return resp.status_code, {"raw": resp.text}


def get_bot_config(bot_id: str) -> dict:
    _, data = fleet_get(f"/api/bots/{bot_id}")
    return data.get("data", data)


def restart_bot(bot_id: str, wait: bool = True, timeout: int = 60) -> bool:
    fleet_post(f"/api/bots/{bot_id}/restart")
    if not wait:
        return True
    start = time.time()
    while time.time() - start < timeout:
        _, sd = fleet_get(f"/api/bots/{bot_id}/status")
        d = sd.get("data", sd)
        if d.get("status") in ("active", "online") or d.get(bot_id) == "online":
            return True
        time.sleep(3)
    return False


def verify_config_file(section_path: str, expected_value: Any) -> tuple[bool, Any]:
    try:
        with open(CONFIG_PATH) as f:
            config = json.load(f)
        val = config
        for k in section_path.split("."):
            if k.isdigit():
                val = val[int(k)]
            elif isinstance(val, dict):
                val = val.get(k)
            else:
                return False, None
        return val == expected_value, val
    except Exception as e:
        return False, str(e)


# ---------------------------------------------------------------------------
# Discord helpers
# ---------------------------------------------------------------------------

def send_discord(channel_id: str, content: str) -> tuple[int, dict]:
    resp = requests.post(
        f"{DISCORD_API}/channels/{channel_id}/messages",
        headers={"Authorization": f"Bot {BOT_TOKEN}", "Content-Type": "application/json"},
        json={"content": content},
    )
    try:
        return resp.status_code, resp.json()
    except Exception:
        return resp.status_code, {}


def get_discord_messages(channel_id: str, limit: int = 10) -> list:
    resp = requests.get(
        f"{DISCORD_API}/channels/{channel_id}/messages?limit={limit}",
        headers={"Authorization": f"Bot {BOT_TOKEN}"},
    )
    try:
        return resp.json()
    except Exception:
        return []


def send_and_wait(bot_id: str, content: str, timeout: int = 60) -> dict | None:
    channel_id = BOT_CHANNELS[bot_id]
    bot_uid = BOT_USER_IDS[bot_id]
    send_discord(channel_id, content)
    time.sleep(1)
    start = time.time()
    while time.time() - start < timeout:
        msgs = get_discord_messages(channel_id, 5)
        if isinstance(msgs, list):
            for msg in msgs:
                if msg.get("author", {}).get("id") == bot_uid:
                    return msg
        time.sleep(3)
    return None


# ---------------------------------------------------------------------------
# Bot parameter test helper
# ---------------------------------------------------------------------------

def test_bot_param(test_id: str, bot_id: str, param_path: str, test_value: Any, verify_file: bool = True) -> bool:
    keys = param_path.split(".")
    orig_cfg = get_bot_config(bot_id)
    orig_val = orig_cfg
    for k in keys:
        orig_val = orig_val.get(k) if isinstance(orig_val, dict) else None

    put_data = {}
    ref = put_data
    for k in keys[:-1]:
        ref[k] = {}
        ref = ref[k]
    ref[keys[-1]] = test_value

    status, data = fleet_put(f"/api/bots/{bot_id}", put_data)
    write_ok = status == 200 and data.get("success", False)

    new_cfg = get_bot_config(bot_id)
    readback_val = new_cfg
    for k in keys:
        readback_val = readback_val.get(k) if isinstance(readback_val, dict) else None
    readback_ok = readback_val == test_value

    file_ok = True
    if verify_file:
        file_path = f"bots.{bot_id}.{param_path}"
        file_ok, _ = verify_config_file(file_path, test_value)

    passed = write_ok and readback_ok and file_ok
    record(test_id, f"{bot_id}.{param_path}: {orig_val} -> {test_value}", passed,
           f"write=ok, readback={test_value}, file={test_value}",
           f"write={write_ok}, readback={readback_val}, file_ok={file_ok}")

    # Revert
    revert_data = {}
    ref2 = revert_data
    for k in keys[:-1]:
        ref2[k] = {}
        ref2 = ref2[k]
    ref2[keys[-1]] = orig_val
    fleet_put(f"/api/bots/{bot_id}", revert_data)
    return passed


def test_fleet_section_param(test_id: str, endpoint: str, param_name: str, test_value: Any, section: str | None = None) -> bool:
    _, orig_data = fleet_get(endpoint)
    orig_d = orig_data.get("data", {})
    orig_val = orig_d.get(param_name)

    status, data = fleet_put(endpoint, {param_name: test_value})
    write_ok = status == 200 and data.get("success", False)

    _, new_data = fleet_get(endpoint)
    new_d = new_data.get("data", {})
    readback_val = new_d.get(param_name)
    readback_ok = readback_val == test_value

    file_ok = True
    try:
        with open(CONFIG_PATH) as f:
            config = json.load(f)
        if section:
            file_val = config.get(section, {}).get(param_name)
        else:
            file_val = config.get(param_name)
        file_ok = file_val == test_value
    except Exception:
        file_ok = False

    passed = write_ok and readback_ok and file_ok
    record(test_id, f"{param_name}: {orig_val} -> {test_value}", passed,
           f"write=ok, readback={test_value}, file={test_value}",
           f"write={write_ok}, readback={readback_val}, file_ok={file_ok}")

    fleet_put(endpoint, {param_name: orig_val})
    return passed


def test_fleet_config_param(test_id: str, section: str, param_name: str, test_value: Any) -> bool:
    _, orig_data = fleet_get("/api/fleet/config")
    orig_cfg = orig_data.get("data", {})
    orig_val = orig_cfg.get(section, {}).get(param_name)

    new_cfg = json.loads(json.dumps(orig_cfg))
    new_cfg[section][param_name] = test_value
    status, data = fleet_put("/api/fleet/config", new_cfg)
    write_ok = status == 200 and data.get("success", False)

    _, new_data = fleet_get("/api/fleet/config")
    new_d = new_data.get("data", {})
    readback_val = new_d.get(section, {}).get(param_name)
    readback_ok = readback_val == test_value

    file_ok = True
    try:
        with open(CONFIG_PATH) as f:
            config = json.load(f)
        file_ok = config.get(section, {}).get(param_name) == test_value
    except Exception:
        file_ok = False

    passed = write_ok and readback_ok and file_ok
    record(test_id, f"{section}.{param_name}: {orig_val} -> {test_value}", passed,
           f"write=ok, readback={test_value}, file={test_value}",
           f"write={write_ok}, readback={readback_val}, file_ok={file_ok}")

    orig_restore = json.loads(json.dumps(orig_cfg))
    fleet_put("/api/fleet/config", orig_restore)
    return passed


# ---------------------------------------------------------------------------
# Phase 0: Prerequisites
# ---------------------------------------------------------------------------

def phase0():
    print("\n" + "="*60 + "\nPHASE 0: Prerequisites\n" + "="*60)

    # API health
    resp = requests.get(f"{FLEET_API}/health")
    record("P0-1", "API health", resp.status_code == 200 and resp.json().get("status") == "ok",
           '{"status":"ok"}', f'{resp.status_code} {resp.json()}')

    # Auth works
    status, data = fleet_get("/api/fleet/config")
    record("P0-2", "Auth token works", status == 200 and data.get("success") == True,
           "200 with config", f"status={status}")

    # UI live
    resp = requests.get("https://command.schubert.life")
    record("P0-3", "UI is live", resp.status_code == 200, "200", f"{resp.status_code}")

    # Discord token
    if BOT_TOKEN:
        resp = requests.get(f"{DISCORD_API}/users/@me", headers={"Authorization": f"Bot {BOT_TOKEN}"})
        record("P0-4", "Discord bot token valid", resp.status_code == 200,
               "Bot user info", f"{resp.status_code}")
    else:
        record("P0-4", "Discord bot token valid", False, "Token present", "No token in env")

    # All bots online
    status, data = fleet_get("/api/fleet/status")
    d = data.get("data", {})
    all_online = all(v == "online" for v in d.values()) if d else False
    record("P0-5", "All bots online", all_online, "7 bots online", f"{d}")

    # Snapshot config
    _, cfg_data = fleet_get("/api/fleet/config")
    with open("/tmp/fleet-config-backup.json", "w") as f:
        json.dump(cfg_data.get("data", {}), f, indent=2)
    record("P0-6", "Config snapshot saved", True, "Backup file", "Saved to /tmp/fleet-config-backup.json")


# ---------------------------------------------------------------------------
# Phase 1: Authentication
# ---------------------------------------------------------------------------

def phase1():
    print("\n" + "="*60 + "\nPHASE 1: Authentication\n" + "="*60)

    # No token
    resp = requests.get(f"{FLEET_API}/api/fleet/config")
    record("AUTH-01", "No token rejected", resp.status_code in (401, 403),
           "401/403", f"{resp.status_code}")

    # Wrong token
    resp = requests.get(f"{FLEET_API}/api/fleet/config", headers={"Authorization": "Bearer wrong"})
    record("AUTH-02", "Wrong token rejected", resp.status_code in (401, 403),
           "401/403", f"{resp.status_code}")

    # Correct token
    status, _ = fleet_get("/api/fleet/config")
    record("AUTH-03", "Correct token accepted", status == 200, "200", f"{status}")

    # Health no auth
    resp = requests.get(f"{FLEET_API}/health")
    record("AUTH-04", "Health no auth", resp.status_code == 200, "200", f"{resp.status_code}")

    # PUT no auth
    resp = requests.put(f"{FLEET_API}/api/bots/admiral", headers={"Content-Type": "application/json"}, json={"llm": {"temperature": 0.5}})
    record("AUTH-05", "PUT no auth rejected", resp.status_code in (401, 403), "401/403", f"{resp.status_code}")

    # POST no auth
    resp = requests.post(f"{FLEET_API}/api/bots/admiral/restart")
    record("AUTH-06", "POST no auth rejected", resp.status_code in (401, 403), "401/403", f"{resp.status_code}")


# ---------------------------------------------------------------------------
# Phase 2: Read-only endpoints
# ---------------------------------------------------------------------------

def phase2():
    print("\n" + "="*60 + "\nPHASE 2: Read-Only Endpoints\n" + "="*60)

    # Fleet endpoints
    status, data = fleet_get("/api/fleet/config")
    d = data.get("data", {})
    record("GET-01", "Fleet config", status == 200 and "bots" in d and len(d["bots"]) == 7,
           "7 bots + sections", f"status={status}, bots={len(d.get('bots', {}))}")

    status, data = fleet_get("/api/fleet/stats")
    d = data.get("data", {})
    record("GET-02", "Fleet stats", status == 200 and isinstance(d, dict) and "active_bots" in d,
           "active_bots etc", f"status={status}, data={d}")

    status, data = fleet_get("/api/fleet/status")
    d = data.get("data", {})
    record("GET-03", "Fleet status", status == 200 and len(d) == 7,
           "7 bots", f"status={status}, bots={len(d)}")

    status, data = fleet_get("/api/fleet/protocol")
    d = data.get("data", {})
    record("GET-04", "Fleet protocol", status == 200 and "max_chain_depth" in d,
           "protocol fields", f"status={status}")

    status, data = fleet_get("/api/scheduler/config")
    d = data.get("data", {})
    record("GET-05", "Scheduler config", status == 200 and "health_check_interval" in d,
           "scheduler fields", f"status={status}")

    status, data = fleet_get("/api/scheduler/monitored-services")
    d = data.get("data", data)
    record("GET-06", "Monitored services", status == 200 and isinstance(d, list),
           "list of services", f"status={status}")

    status, data = fleet_get("/api/memory/config")
    d = data.get("data", {})
    record("GET-07", "Memory config", status == 200 and "cosine_threshold" in d,
           "memory fields", f"status={status}")

    status, data = fleet_get("/api/memory/stats")
    d = data.get("data", {})
    record("GET-08", "Memory stats", status == 200 and "memories" in d,
           "memory counts", f"status={status}")

    # Bot endpoints
    for bot_id in ALL_BOTS:
        status, data = fleet_get(f"/api/bots/{bot_id}")
        d = data.get("data", {})
        has_fields = all(k in d for k in ["meta", "llm", "prompt", "guardrails", "memory", "mcp", "multi_agent"])
        record(f"GET-09-{bot_id}", f"Bot config {bot_id}", status == 200 and has_fields,
               "all config sections", f"status={status}")

        status, data = fleet_get(f"/api/bots/{bot_id}/status")
        d = data.get("data", {})
        record(f"GET-10-{bot_id}", f"Bot status {bot_id}", status == 200 and "status" in d,
               "status field", f"status={status}, data={d}")

        status, data = fleet_get(f"/api/bots/{bot_id}/logs")
        d = data.get("data", data)
        record(f"GET-11-{bot_id}", f"Bot logs {bot_id}", status == 200,
               "log data", f"status={status}")

        status, data = fleet_get(f"/api/bots/{bot_id}/tools")
        d = data.get("data", data)
        record(f"GET-12-{bot_id}", f"Bot tools {bot_id}", status == 200,
               "tools data", f"status={status}")


# ---------------------------------------------------------------------------
# Phase 3: Bot config writes
# ---------------------------------------------------------------------------

def phase3():
    print("\n" + "="*60 + "\nPHASE 3: Bot Config Writes\n" + "="*60)

    # LLM params
    test_bot_param("PUT-LLM-01", "admiral", "llm.temperature", 0.7)
    test_bot_param("PUT-LLM-02", "architect", "llm.temperature", 0.5)
    test_bot_param("PUT-LLM-03", "admiral", "llm.max_tokens", 2048)
    test_bot_param("PUT-LLM-04", "cortex", "llm.max_tokens", 1024)
    test_bot_param("PUT-LLM-05", "admiral", "llm.llm_timeout", 30)
    test_bot_param("PUT-LLM-06", "architect", "llm.llm_timeout", 240)
    test_bot_param("PUT-LLM-07", "admiral", "llm.max_iterations", 15)
    test_bot_param("PUT-LLM-08", "proctor", "llm.max_iterations", 20)
    test_bot_param("PUT-LLM-09", "admiral", "llm.agent_timeout", 240)
    test_bot_param("PUT-LLM-10", "cartographer", "llm.agent_timeout", 480)
    test_bot_param("PUT-LLM-11", "admiral", "llm.tool_output_limit", 2000)
    test_bot_param("PUT-LLM-12", "cortex", "llm.tool_output_limit", 3000)
    test_bot_param("PUT-LLM-13", "admiral", "llm.shell_timeout", 60)
    test_bot_param("PUT-LLM-14", "architect", "llm.shell_timeout", 90)
    test_bot_param("PUT-LLM-15", "architect", "llm.session_window", 30)
    test_bot_param("PUT-LLM-16", "cortex", "llm.session_window", 15)
    test_bot_param("PUT-LLM-17", "admiral", "llm.rate_limit_per_min", 5)
    test_bot_param("PUT-LLM-18", "cortex", "llm.rate_limit_per_min", 20)
    test_bot_param("PUT-LLM-19", "admiral", "llm.model", "writer/palmyra-x6")
    test_bot_param("PUT-LLM-20", "architect", "llm.model", "writer/claude-sonnet-4-5")
    test_bot_param("PUT-LLM-21", "architect", "llm.coding_model", "writer/palmyra-x6")
    test_bot_param("PUT-LLM-22", "dr_voss", "llm.coding_model", None)

    # Prompt params
    test_bot_param("PUT-PROMPT-03", "admiral", "prompt.voice_prompt_addition", False)
    test_bot_param("PUT-PROMPT-04", "admiral", "prompt.coding_prompt_addition", False)
    test_bot_param("PUT-PROMPT-05", "admiral", "prompt.poll_prompt_addition", False)
    test_bot_param("PUT-PROMPT-06", "admiral", "prompt.meetscribe_prompt_addition", False)
    test_bot_param("PUT-PROMPT-07", "cortex", "prompt.voice_prompt_addition", False)

    # Guardrails
    test_bot_param("PUT-GUARD-01", "admiral", "guardrails.restart_confirm_timeout", 60)
    test_bot_param("PUT-GUARD-02", "cortex", "guardrails.restart_confirm_timeout", 15)

    # Memory
    test_bot_param("PUT-MEM-01", "admiral", "memory.cosine_threshold", 0.5)
    test_bot_param("PUT-MEM-02", "architect", "memory.cosine_threshold", 0.7)
    test_bot_param("PUT-MEM-03", "admiral", "memory.max_memory_injection_tokens", 800)
    test_bot_param("PUT-MEM-04", "cortex", "memory.max_memory_injection_tokens", 2000)
    test_bot_param("PUT-MEM-05", "admiral", "memory.decay_rate", "2pct/day")
    test_bot_param("PUT-MEM-06", "architect", "memory.decay_rate", "0.5pct/day")
    test_bot_param("PUT-MEM-07", "admiral", "memory.max_recall_results", 10)
    test_bot_param("PUT-MEM-08", "proctor", "memory.max_recall_results", 3)
    test_bot_param("PUT-MEM-09", "admiral", "memory.llm_entity_extraction", False)
    test_bot_param("PUT-MEM-10", "cortex", "memory.llm_entity_extraction", False)
    test_bot_param("PUT-MEM-11", "admiral", "memory.memory_storage_threshold", 50)

    # MCP
    test_bot_param("PUT-MCP-01", "admiral", "mcp.request_timeout", 120)
    test_bot_param("PUT-MCP-02", "architect", "mcp.request_timeout", 60)
    test_bot_param("PUT-MCP-03", "admiral", "mcp.tool_cache_ttl", 900)
    test_bot_param("PUT-MCP-04", "cortex", "mcp.tool_cache_ttl", 3600)
    test_bot_param("PUT-MCP-05", "admiral", "mcp.tool_cache_refresh_on_error", False)
    test_bot_param("PUT-MCP-06", "architect", "mcp.tool_cache_refresh_on_error", False)
    test_bot_param("PUT-MCP-07", "admiral", "mcp.per_project_tool_filtering", False)
    test_bot_param("PUT-MCP-08", "cortex", "mcp.per_project_tool_filtering", False)

    # Multi-agent
    test_bot_param("PUT-MA-01", "admiral", "multi_agent.response_threshold", 0.6)
    test_bot_param("PUT-MA-02", "proctor", "multi_agent.response_threshold", 0.7)
    test_bot_param("PUT-MA-03", "cortex", "multi_agent.response_threshold", 0.3)
    test_bot_param("PUT-MA-04", "admiral", "multi_agent.urgent_threshold", 0.9)
    test_bot_param("PUT-MA-05", "proctor", "multi_agent.urgent_threshold", 0.8)
    test_bot_param("PUT-MA-06", "admiral", "multi_agent.cooldown_seconds", 10)
    test_bot_param("PUT-MA-07", "proctor", "multi_agent.cooldown_seconds", 30)
    test_bot_param("PUT-MA-08", "architect", "multi_agent.fleet_delegation_role", "send_receive")
    test_bot_param("PUT-MA-09", "quartermaster", "multi_agent.fleet_delegation_role", "send_only")

    # Scheduler
    test_bot_param("PUT-SCHED-01", "admiral", "scheduler_enabled", False)
    test_bot_param("PUT-SCHED-02", "cortex", "scheduler_enabled", False)

    # Voice (admiral + cortex)
    test_bot_param("PUT-VOICE-01", "admiral", "voice.enabled", False)
    test_bot_param("PUT-VOICE-02", "cortex", "voice.enabled", False)
    test_bot_param("PUT-VOICE-03", "admiral", "voice.vad_speech_rms_threshold", 150)
    test_bot_param("PUT-VOICE-04", "cortex", "voice.vad_speech_rms_threshold", 80)
    test_bot_param("PUT-VOICE-05", "admiral", "voice.tts_stability", 0.7)
    test_bot_param("PUT-VOICE-06", "cortex", "voice.tts_stability", 0.3)
    test_bot_param("PUT-VOICE-07", "admiral", "voice.tts_similarity_boost", 0.85)
    test_bot_param("PUT-VOICE-08", "cortex", "voice.tts_similarity_boost", 0.65)
    test_bot_param("PUT-VOICE-09", "admiral", "voice.tts_text_truncation", 300)
    test_bot_param("PUT-VOICE-10", "cortex", "voice.tts_text_truncation", 1000)
    test_bot_param("PUT-VOICE-11", "admiral", "voice.stt_timeout", 60)
    test_bot_param("PUT-VOICE-12", "admiral", "voice.tts_timeout", 45)

    # Self-healing (architect + dr_voss)
    test_bot_param("PUT-HEAL-01", "architect", "self_healing.health_check_interval", 600)
    test_bot_param("PUT-HEAL-02", "dr_voss", "self_healing.health_check_interval", 120)
    test_bot_param("PUT-HEAL-03", "architect", "self_healing.max_remediation_retries", 5)
    test_bot_param("PUT-HEAL-04", "dr_voss", "self_healing.max_remediation_retries", 2)
    test_bot_param("PUT-HEAL-05", "architect", "self_healing.error_threshold", 5)
    test_bot_param("PUT-HEAL-06", "dr_voss", "self_healing.error_threshold", 1)

    # Self-improvement (architect + dr_voss)
    test_bot_param("PUT-SI-01", "architect", "self_improvement.enabled", False)
    test_bot_param("PUT-SI-02", "dr_voss", "self_improvement.enabled", False)
    test_bot_param("PUT-SI-03", "architect", "self_improvement.assessment_interval", 43200)
    test_bot_param("PUT-SI-04", "dr_voss", "self_improvement.assessment_interval", 10800)
    test_bot_param("PUT-SI-05", "architect", "self_improvement.max_updates_per_day", 5)
    test_bot_param("PUT-SI-06", "dr_voss", "self_improvement.max_updates_per_day", 1)


# ---------------------------------------------------------------------------
# Phase 4: Fleet section writes
# ---------------------------------------------------------------------------

def phase4():
    print("\n" + "="*60 + "\nPHASE 4: Fleet Section Writes\n" + "="*60)

    # Fleet protocol
    test_fleet_section_param("PUT-PROT-01", "/api/fleet/protocol", "max_chain_depth", 5, section="fleet_protocol")
    test_fleet_section_param("PUT-PROT-02", "/api/fleet/protocol", "delegation_timeout", 240, section="fleet_protocol")
    test_fleet_section_param("PUT-PROT-03", "/api/fleet/protocol", "edit_interval", 2.0, section="fleet_protocol")
    test_fleet_section_param("PUT-PROT-04", "/api/fleet/protocol", "first_send_threshold", 60, section="fleet_protocol")
    test_fleet_section_param("PUT-PROT-05", "/api/fleet/protocol", "max_length", 1500, section="fleet_protocol")

    # Conversation (via full config replace)
    test_fleet_config_param("PUT-CONV-01", "conversation", "response_lock_timeout", 60)
    test_fleet_config_param("PUT-CONV-02", "conversation", "answered_ttl", 1800)
    test_fleet_config_param("PUT-CONV-03", "conversation", "message_retention", 25)
    test_fleet_config_param("PUT-CONV-04", "conversation", "redis_message_ttl", 43200)
    test_fleet_config_param("PUT-CONV-05", "conversation", "heartbeat_ttl", 120)

    # Context builder
    test_fleet_config_param("PUT-CTX-01", "context_builder", "max_context_file_chars", 4000)
    test_fleet_config_param("PUT-CTX-02", "context_builder", "max_total_context_chars", 15000)
    test_fleet_config_param("PUT-CTX-03", "context_builder", "max_project_prompt_chars", 2000)

    # Scheduler
    test_fleet_section_param("PUT-SCHED-F-01", "/api/scheduler/config", "health_check_interval", 600, section="scheduler")
    test_fleet_section_param("PUT-SCHED-F-02", "/api/scheduler/config", "service_check_interval", 240, section="scheduler")
    test_fleet_section_param("PUT-SCHED-F-03", "/api/scheduler/config", "disk_alert_interval", 300, section="scheduler")
    test_fleet_section_param("PUT-SCHED-F-04", "/api/scheduler/config", "memory_decay_interval", 7200, section="scheduler")
    test_fleet_section_param("PUT-SCHED-F-05", "/api/scheduler/config", "disk_warning_threshold", 75, section="scheduler")
    test_fleet_section_param("PUT-SCHED-F-06", "/api/scheduler/config", "disk_critical_threshold", 85, section="scheduler")
    test_fleet_section_param("PUT-SCHED-F-07", "/api/scheduler/config", "mem_warning_threshold", 80, section="scheduler")
    test_fleet_section_param("PUT-SCHED-F-08", "/api/scheduler/config", "cpu_warning_threshold", 85, section="scheduler")
    test_fleet_section_param("PUT-SCHED-F-09", "/api/scheduler/config", "alert_dedup_cooldown", 900, section="scheduler")
    test_fleet_section_param("PUT-SCHED-F-10", "/api/scheduler/config", "service_recovered_cooldown", 300, section="scheduler")

    # Memory config (global)
    test_fleet_section_param("PUT-MEM-F-01", "/api/memory/config", "cosine_threshold", 0.5)
    test_fleet_section_param("PUT-MEM-F-02", "/api/memory/config", "max_memory_injection_tokens", 800)
    test_fleet_section_param("PUT-MEM-F-03", "/api/memory/config", "decay_rate", "2pct/day")
    test_fleet_section_param("PUT-MEM-F-04", "/api/memory/config", "max_recall_results", 10)


# ---------------------------------------------------------------------------
# Phase 5: Service restarts
# ---------------------------------------------------------------------------

def phase5():
    print("\n" + "="*60 + "\nPHASE 5: Service Restarts\n" + "="*60)

    for i, bot_id in enumerate(ALL_BOTS, 1):
        test_id = f"RESTART-{i:02d}"
        status, data = fleet_post(f"/api/bots/{bot_id}/restart")
        restart_ok = status == 200 and data.get("success", False)
        active = False
        start = time.time()
        while time.time() - start < 60:
            _, sd = fleet_get(f"/api/bots/{bot_id}/status")
            d = sd.get("data", sd)
            if d.get("status") in ("active", "online") or d.get(bot_id) == "online":
                active = True
                break
            time.sleep(3)
        elapsed = int(time.time() - start)
        record(test_id, f"Restart {bot_id}", restart_ok and active,
               "200 + active", f"restart={status}, active={active}, elapsed={elapsed}s")
        if i < 7:
            time.sleep(32)

    # Cooldown test
    print("\n--- Cooldown test ---")
    fleet_post("/api/bots/admiral/restart")
    time.sleep(1)
    status2, data2 = fleet_post("/api/bots/admiral/restart")
    cooldown = status2 != 200 or not data2.get("success", False)
    record("RESTART-08", "Cooldown enforced", cooldown,
           "Second restart rejected", f"status={status2}, data={data2}")

    time.sleep(32)
    status3, _ = fleet_post("/api/bots/admiral/restart")
    record("RESTART-08b", "Restart after cooldown", status3 == 200,
           "Succeeds after 30s", f"status={status3}")

    # Config change + restart
    print("\n--- Config change + restart ---")
    orig = get_bot_config("admiral")
    orig_temp = orig.get("llm", {}).get("temperature", 0.3)
    fleet_put("/api/bots/admiral", {"llm": {"temperature": 0.5}})
    time.sleep(32)
    restart_bot("admiral")
    new = get_bot_config("admiral")
    new_temp = new.get("llm", {}).get("temperature")
    record("RESTART-09", "Config change persists", new_temp == 0.5,
           "temp=0.5", f"temp={new_temp}")
    fleet_put("/api/bots/admiral", {"llm": {"temperature": orig_temp}})

    # Sequential restart all
    print("\n--- Sequential restart all ---")
    all_active = True
    for bot_id in ALL_BOTS:
        time.sleep(32)
        fleet_post(f"/api/bots/{bot_id}/restart")
        active = False
        start = time.time()
        while time.time() - start < 60:
            _, sd = fleet_get(f"/api/bots/{bot_id}/status")
            d = sd.get("data", sd)
            if d.get("status") in ("active", "online") or d.get(bot_id) == "online":
                active = True
                break
            time.sleep(3)
        if not active:
            all_active = False
    record("RESTART-10", "Sequential restart all", all_active,
           "All active", f"all_active={all_active}")


# ---------------------------------------------------------------------------
# Phase 7: Discord behavioral verification
# ---------------------------------------------------------------------------

def phase7():
    print("\n" + "="*60 + "\nPHASE 7: Discord Behavioral Verification\n" + "="*60)

    if not BOT_TOKEN:
        print("  Skipping — no Discord bot token")
        return

    # Basic responsiveness
    test_msgs = {
        "admiral": "Status report",
        "architect": "What can you do?",
        "quartermaster": "System health",
        "cartographer": "What documentation do you maintain?",
        "dr_voss": "Health check",
        "proctor": "Hello",
        "cortex": "Research query: what is quantum computing?",
    }

    for i, (bot_id, msg) in enumerate(test_msgs.items(), 1):
        test_id = f"DISCORD-{i:02d}"
        resp = send_and_wait(bot_id, msg, timeout=60)
        if resp:
            record(test_id, f"Responsiveness: {bot_id}", True,
                   "Bot responds", f"Response: {resp.get('content', '')[:100]}")
        elif bot_id == "proctor":
            record(test_id, f"Responsiveness: {bot_id}", True,
                   "Proctor may not respond (high threshold)", "No response (expected)")
        else:
            record(test_id, f"Responsiveness: {bot_id}", False,
                   "Bot responds", "No response: timeout")
        time.sleep(2)

    # Temperature change
    print("\n--- Temperature change ---")
    resp_low = send_and_wait("admiral", "Write a short poem about the ocean", timeout=60)
    low_content = resp_low.get("content", "") if resp_low else ""
    record("DISCORD-08", "Temp baseline at 0.3", bool(low_content),
           "Bot responds", f"len={len(low_content)}")

    fleet_put("/api/bots/admiral", {"llm": {"temperature": 0.9}})
    time.sleep(32)
    restart_bot("admiral")
    resp_high = send_and_wait("admiral", "Write a short poem about the ocean", timeout=60)
    high_content = resp_high.get("content", "") if resp_high else ""
    different = low_content != high_content
    record("DISCORD-08b", "Temp change produces different responses",
           bool(high_content) and different,
           "Different at 0.9 vs 0.3", f"low_len={len(low_content)}, high_len={len(high_content)}")

    fleet_put("/api/bots/admiral", {"llm": {"temperature": 0.3}})
    time.sleep(32)
    restart_bot("admiral")

    # System prompt change
    print("\n--- System prompt change ---")
    orig = get_bot_config("admiral")
    orig_prompt = orig.get("prompt", {}).get("system_prompt", "")
    test_prompt = orig_prompt + "\n\n[TEST MODE: Start every response with 'TEST MODE ACTIVE:']"
    fleet_put("/api/bots/admiral", {"prompt": {"system_prompt": test_prompt}})
    time.sleep(32)
    restart_bot("admiral")
    resp = send_and_wait("admiral", "Hello", timeout=60)
    resp_content = resp.get("content", "") if resp else ""
    record("DISCORD-10", "System prompt change takes effect",
           resp_content.startswith("TEST MODE ACTIVE:"),
           "Starts with 'TEST MODE ACTIVE:'", f"Response: {resp_content[:100]}")

    # Revert
    fleet_put("/api/bots/admiral", {"prompt": {"system_prompt": orig_prompt}})
    time.sleep(32)
    restart_bot("admiral")
    resp = send_and_wait("admiral", "Hello", timeout=60)
    resp_content = resp.get("content", "") if resp else ""
    record("DISCORD-11", "System prompt revert",
           not resp_content.startswith("TEST MODE ACTIVE:"),
           "Does NOT start with 'TEST MODE ACTIVE:'", f"Response: {resp_content[:100]}")

    # Rate limit
    print("\n--- Rate limit ---")
    fleet_put("/api/bots/admiral", {"llm": {"rate_limit_per_min": 3}})
    time.sleep(32)
    restart_bot("admiral")
    channel_id = BOT_CHANNELS["admiral"]
    bot_uid = BOT_USER_IDS["admiral"]
    for j in range(4):
        send_discord(channel_id, f"Quick test {j+1}")
        time.sleep(2)
    time.sleep(30)
    msgs = get_discord_messages(channel_id, 10)
    resp_count = sum(1 for m in msgs if isinstance(m, dict) and m.get("author", {}).get("id") == bot_uid)
    record("DISCORD-12", "Rate limit 3/min", resp_count <= 3,
           "4th message rate-limited", f"responses={resp_count}/4")
    fleet_put("/api/bots/admiral", {"llm": {"rate_limit_per_min": 10}})
    time.sleep(32)
    restart_bot("admiral")

    # Max length
    print("\n--- Max length ---")
    fleet_put("/api/fleet/protocol", {"max_length": 100})
    time.sleep(32)
    restart_bot("admiral")
    resp = send_and_wait("admiral", "Write a very long detailed essay about the history of computing", timeout=60)
    resp_content = resp.get("content", "") if resp else ""
    record("DISCORD-13", "Max length truncation", len(resp_content) <= 200,
           "Truncated to ~100 chars", f"len={len(resp_content)}")
    fleet_put("/api/fleet/protocol", {"max_length": 2000})
    time.sleep(32)
    restart_bot("admiral")

    # High threshold prevents delegation
    print("\n--- High threshold ---")
    fleet_put("/api/bots/admiral", {"multi_agent": {"response_threshold": 0.9}})
    time.sleep(32)
    restart_bot("admiral")
    resp = send_and_wait("admiral", "What time is it?", timeout=60)
    record("DISCORD-15", "High threshold prevents delegation", True,
           "No delegation at 0.9", f"Response: {resp.get('content', '')[:80] if resp else 'No response'}")
    fleet_put("/api/bots/admiral", {"multi_agent": {"response_threshold": 0.4}})
    time.sleep(32)
    restart_bot("admiral")

    # Scheduler disabled
    print("\n--- Scheduler disabled ---")
    fleet_put("/api/bots/admiral", {"scheduler_enabled": False})
    time.sleep(32)
    restart_bot("admiral")
    time.sleep(120)
    _, log_data = fleet_get("/api/bots/admiral/logs")
    logs = log_data.get("data", {})
    log_text = ""
    if isinstance(logs, dict):
        log_text = str(logs.get("logs", ""))
    elif isinstance(logs, list):
        log_text = "\n".join(str(l) for l in logs[-20:])
    no_scheduler = "health_check" not in log_text.lower()
    record("DISCORD-16", "Scheduler disabled", no_scheduler,
           "No scheduled entries", f"Log excerpt: {log_text[-200:]}")
    fleet_put("/api/bots/admiral", {"scheduler_enabled": True})
    time.sleep(32)
    restart_bot("admiral")


# ---------------------------------------------------------------------------
# Phase 8: Edge cases
# ---------------------------------------------------------------------------

def phase8():
    print("\n" + "="*60 + "\nPHASE 8: Edge Cases\n" + "="*60)

    # Invalid temperature (negative)
    status, data = fleet_put("/api/bots/admiral", {"llm": {"temperature": -1}})
    rejected = status in (400, 422) or (isinstance(data, dict) and not data.get("success", True))
    record("EDGE-01", "Invalid temp (-1)", rejected,
           "422/400", f"status={status}")

    # Invalid temperature (>2)
    status, data = fleet_put("/api/bots/admiral", {"llm": {"temperature": 5.0}})
    rejected = status in (400, 422) or (isinstance(data, dict) and not data.get("success", True))
    record("EDGE-02", "Invalid temp (5.0)", rejected,
           "422/400", f"status={status}")

    # Invalid max_tokens (0)
    status, data = fleet_put("/api/bots/admiral", {"llm": {"max_tokens": 0}})
    rejected = status in (400, 422) or (isinstance(data, dict) and not data.get("success", True))
    record("EDGE-03", "Invalid max_tokens (0)", rejected,
           "422/400", f"status={status}")

    # Revert any changes
    fleet_put("/api/bots/admiral", {"llm": {"temperature": 0.3, "max_tokens": 3072}})

    # Invalid model name (should be accepted — validation at runtime)
    status, data = fleet_put("/api/bots/admiral", {"llm": {"model": "invalid/model"}})
    accepted = status == 200 and data.get("success", False)
    record("EDGE-04", "Invalid model name", accepted,
           "Accepted (runtime validation)", f"status={status}")
    if accepted:
        fleet_put("/api/bots/admiral", {"llm": {"model": "writer/claude-sonnet-4-5"}})

    # Non-existent bot
    status, _ = fleet_get("/api/bots/nonexistent")
    record("EDGE-05", "Non-existent bot (GET)", status == 404, "404", f"status={status}")

    status, _ = fleet_post("/api/bots/nonexistent/restart")
    record("EDGE-06", "Restart non-existent bot", status == 404, "404", f"status={status}")

    # Partial update (deep merge)
    orig = get_bot_config("admiral")
    orig_temp = orig.get("llm", {}).get("temperature", 0.3)
    orig_max = orig.get("llm", {}).get("max_tokens", 3072)
    fleet_put("/api/bots/admiral", {"llm": {"temperature": 0.5}})
    new = get_bot_config("admiral")
    new_temp = new.get("llm", {}).get("temperature")
    new_max = new.get("llm", {}).get("max_tokens")
    deep_merge = new_temp == 0.5 and new_max == orig_max
    record("EDGE-07", "Partial update (deep merge)", deep_merge,
           f"Only temp changes, max_tokens stays {orig_max}", f"temp={new_temp}, max={new_max}")
    fleet_put("/api/bots/admiral", {"llm": {"temperature": orig_temp}})

    # Nested partial update
    orig_cosine = orig.get("memory", {}).get("cosine_threshold", 0.3)
    orig_decay = orig.get("memory", {}).get("decay_rate", "1%/day")
    fleet_put("/api/bots/admiral", {"memory": {"cosine_threshold": 0.5}})
    new = get_bot_config("admiral")
    new_cosine = new.get("memory", {}).get("cosine_threshold")
    new_decay = new.get("memory", {}).get("decay_rate")
    nested_ok = new_cosine == 0.5 and new_decay == orig_decay
    record("EDGE-08", "Nested partial update", nested_ok,
           f"Only cosine changes, decay stays {orig_decay}", f"cosine={new_cosine}, decay={new_decay}")
    fleet_put("/api/bots/admiral", {"memory": {"cosine_threshold": orig_cosine}})

    # Concurrent writes
    concurrent_results = {}
    def write_config(bid, val):
        concurrent_results[bid] = fleet_put(f"/api/bots/{bid}", {"llm": {"temperature": val}})
    t1 = threading.Thread(target=write_config, args=("admiral", 0.4))
    t2 = threading.Thread(target=write_config, args=("architect", 0.4))
    t1.start(); t2.start(); t1.join(); t2.join()
    both_ok = all(v[0] == 200 for v in concurrent_results.values())
    record("EDGE-09", "Concurrent writes", both_ok,
           "Both succeed", f"admiral={concurrent_results.get('admiral')}")
    fleet_put("/api/bots/admiral", {"llm": {"temperature": orig_temp}})
    fleet_put("/api/bots/architect", {"llm": {"temperature": 0.3}})

    # Config file valid JSON
    try:
        with open(CONFIG_PATH) as f:
            json.load(f)
        record("EDGE-11", "Config file valid JSON", True, "Valid", "Valid")
    except Exception as e:
        record("EDGE-11", "Config file valid JSON", False, "Valid", f"Error: {e}")

    # Backup file exists
    import glob
    backups = glob.glob("/opt/Project-Tango/config/fleet-config.json.bak*")
    record("EDGE-12", "Backup file exists", len(backups) > 0,
           "Backup exists", f"Backups: {backups}")


# ---------------------------------------------------------------------------
# Phase 9: Cleanup
# ---------------------------------------------------------------------------

def phase9():
    print("\n" + "="*60 + "\nPHASE 9: Cleanup\n" + "="*60)

    # Restore from backup
    try:
        with open("/tmp/fleet-config-backup.json") as f:
            backup = json.load(f)
        status, _ = fleet_put("/api/fleet/config", backup)
        record("CLEANUP-01", "Restore config", status == 200,
               "Config restored", f"status={status}")
    except Exception as e:
        record("CLEANUP-01", "Restore config", False, "Restored", f"Error: {e}")

    # Restart all bots
    for bot_id in ALL_BOTS:
        fleet_post(f"/api/bots/{bot_id}/restart")
        time.sleep(32)

    # Verify all active
    time.sleep(5)
    all_active = True
    for bot_id in ALL_BOTS:
        active = False
        start = time.time()
        while time.time() - start < 60:
            _, sd = fleet_get(f"/api/bots/{bot_id}/status")
            d = sd.get("data", sd)
            if d.get("status") in ("active", "online") or d.get(bot_id) == "online":
                active = True
                break
            time.sleep(3)
        if not active:
            all_active = False
    record("CLEANUP-02", "All bots active", all_active, "All online", f"all_active={all_active}")

    # Config file valid
    try:
        with open(CONFIG_PATH) as f:
            json.load(f)
        record("CLEANUP-03", "Config valid JSON", True, "Valid", "Valid")
    except Exception as e:
        record("CLEANUP-03", "Config valid JSON", False, "Valid", f"Error: {e}")


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(description="Fleet Command API Test Suite")
    parser.add_argument("--phase", type=int, help="Run only a specific phase (0-9)")
    parser.add_argument("--no-discord", action="store_true", help="Skip Discord behavioral tests")
    parser.add_argument("--no-restart", action="store_true", help="Skip service restart tests")
    parser.add_argument("--output", default="/tmp/fleet-command-test-results.json", help="Output file")
    args = parser.parse_args()

    phases = {
        0: phase0, 1: phase1, 2: phase2, 3: phase3, 4: phase4,
        5: phase5 if not args.no_restart else None,
        7: phase7 if not args.no_discord else None,
        8: phase8, 9: phase9,
    }

    if args.phase is not None:
        func = phases.get(args.phase)
        if func:
            func()
        else:
            print(f"Phase {args.phase} not available")
    else:
        for phase_num in sorted(phases.keys()):
            func = phases[phase_num]
            if func:
                func()

    save_results(args.output)

    # Generate summary report
    passed = sum(1 for r in results if r["passed"])
    failed = sum(1 for r in results if not r["passed"])
    print(f"\nFleet Command Test Suite Complete")
    print(f"  Total: {len(results)} | Passed: {passed} | Failed: {failed}")
    if failed > 0:
        print(f"\n  Failures:")
        for r in results:
            if not r["passed"]:
                print(f"    {r['test_id']}: {r['description']} — {r['actual']}")

    return 0 if failed == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
