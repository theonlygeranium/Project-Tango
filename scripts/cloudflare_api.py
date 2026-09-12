#!/usr/bin/env python3
"""
CloudflareAPI — Shared Cloudflare API client for both bots.

Provides async methods for DNS management, tunnel configuration, zone settings,
cache purging, and general API requests. Reads credentials from environment
variables set in /opt/Project-Tango/.env.

Used by:
  - The Architect (architect-bot.py) — as a dev tool
  - Admiral Schubert (schubert-bot-v2.py) — as an MCP-style tool

Author: Jeff Geronimo / WRITER Agent
"""

from __future__ import annotations

import json
import os
from typing import Any, Optional

import aiohttp

# ---------------------------------------------------------------------------
# Configuration — read from environment
# ---------------------------------------------------------------------------

CF_API_TOKEN = os.environ.get("CLOUDFLARE_API_TOKEN", "")
CF_ACCOUNT_ID = os.environ.get("CLOUDFLARE_ACCOUNT_ID", "")

# Zone IDs (pre-mapped for convenience)
CF_ZONES = {
    "edstratumlabs.ai": os.environ.get("CLOUDFLARE_ZONE_EDSTRATUMLABS", ""),
    "jgeronimo.com": os.environ.get("CLOUDFLARE_ZONE_JGERONIMO", ""),
    "schubert.life": os.environ.get("CLOUDFLARE_ZONE_SCHUBERT_LIFE", ""),
}

# Tunnel IDs
CF_TUNNELS = {
    "schubert-foxtrot": os.environ.get("CLOUDFLARE_TUNNEL_SCHUBERT_FOXTROT", ""),
}

CF_API_BASE = "https://api.cloudflare.com/client/v4"
CF_TUNNEL_ENDPOINT = "cd4474e7-d944-424f-ae41-1ccc4fee1a7e.cfargotunnel.com"


def _resolve_zone(zone: str) -> str:
    """Resolve a zone name to its zone ID. Accepts zone names or raw zone IDs."""
    if zone in CF_ZONES.values():
        return zone
    if zone in CF_ZONES:
        return CF_ZONES[zone]
    return zone


def _resolve_tunnel(tunnel: str) -> str:
    """Resolve a tunnel name to its tunnel ID."""
    if tunnel in CF_TUNNELS.values():
        return tunnel
    if tunnel in CF_TUNNELS:
        return CF_TUNNELS[tunnel]
    return tunnel


def _headers() -> dict:
    return {
        "Authorization": f"Bearer {CF_API_TOKEN}",
        "Content-Type": "application/json",
    }


# ---------------------------------------------------------------------------
# Core API request method
# ---------------------------------------------------------------------------

async def cf_request(
    method: str,
    path: str,
    body: dict | None = None,
    params: dict | None = None,
) -> dict:
    """
    Make a raw Cloudflare API request.
    """
    if not CF_API_TOKEN:
        return {"success": False, "status": 0, "result": None,
                "errors": [{"message": "CLOUDFLARE_API_TOKEN not set in environment"}],
                "messages": []}

    url = f"{CF_API_BASE}{path}"
    try:
        async with aiohttp.ClientSession() as session:
            async with session.request(
                method,
                url,
                headers=_headers(),
                json=body if body else None,
                params=params if params else None,
                timeout=aiohttp.ClientTimeout(total=30),
            ) as resp:
                data = await resp.json()
                return {
                    "success": data.get("success", False),
                    "status": resp.status,
                    "result": data.get("result"),
                    "errors": data.get("errors", []),
                    "messages": data.get("messages", []),
                    "result_info": data.get("result_info"),
                }
    except aiohttp.ClientError as e:
        return {"success": False, "status": 0, "result": None,
                "errors": [{"message": f"Network error: {e}"}], "messages": []}
    except Exception as e:
        return {"success": False, "status": 0, "result": None,
                "errors": [{"message": f"Request failed: {e}"}], "messages": []}


# ---------------------------------------------------------------------------
# DNS Record Management
# ---------------------------------------------------------------------------

async def list_dns_records(zone: str, record_type: str = "") -> str:
    zone_id = _resolve_zone(zone)
    params = {}
    if record_type:
        params["type"] = record_type
    resp = await cf_request("GET", f"/zones/{zone_id}/dns_records", params=params or None)
    if not resp["success"]:
        return f"Error: {resp['errors']}"
    records = resp["result"] or []
    if not records:
        return f"No DNS records found for {zone}."
    lines = [f"DNS Records for {zone} ({len(records)} total):"]
    for r in records:
        proxied = "🟠" if r.get("proxied") else "⚪"
        lines.append(
            f"  {proxied} {r.get('type',''):5s} {r.get('name',''):40s} → {r.get('content','')}"
            f"  [TTL: {r.get('ttl','')}]"
        )
    return "\n".join(lines)


async def create_dns_record(
    zone: str, record_type: str, name: str, content: str,
    proxied: bool = True, ttl: int = 1, priority: int | None = None,
) -> str:
    zone_id = _resolve_zone(zone)
    body = {"type": record_type, "name": name, "content": content, "proxied": proxied, "ttl": ttl}
    if priority is not None:
        body["priority"] = priority
    resp = await cf_request("POST", f"/zones/{zone_id}/dns_records", body=body)
    if not resp["success"]:
        return f"Error creating DNS record: {resp['errors']}"
    r = resp["result"]
    return f"✅ Created {r.get('type')} record: {r.get('name')} → {r.get('content')} (proxied: {r.get('proxied')})"


async def update_dns_record(
    zone: str, record_id: str, record_type: str = "", name: str = "",
    content: str = "", proxied: bool | None = None, ttl: int | None = None,
) -> str:
    zone_id = _resolve_zone(zone)
    body = {}
    if record_type: body["type"] = record_type
    if name: body["name"] = name
    if content: body["content"] = content
    if proxied is not None: body["proxied"] = proxied
    if ttl is not None: body["ttl"] = ttl
    resp = await cf_request("PATCH", f"/zones/{zone_id}/dns_records/{record_id}", body=body)
    if not resp["success"]:
        return f"Error updating DNS record: {resp['errors']}"
    r = resp["result"]
    return f"✅ Updated DNS record: {r.get('name')} → {r.get('content')} (proxied: {r.get('proxied')})"


async def delete_dns_record(zone: str, record_id: str) -> str:
    zone_id = _resolve_zone(zone)
    resp = await cf_request("DELETE", f"/zones/{zone_id}/dns_records/{record_id}")
    if not resp["success"]:
        return f"Error deleting DNS record: {resp['errors']}"
    return f"✅ Deleted DNS record {record_id}"


# ---------------------------------------------------------------------------
# Zone Management
# ---------------------------------------------------------------------------

async def list_zones() -> str:
    resp = await cf_request("GET", "/zones")
    if not resp["success"]:
        return f"Error: {resp['errors']}"
    zones = resp["result"] or []
    lines = [f"Cloudflare Zones ({len(zones)} total):"]
    for z in zones:
        lines.append(f"  {z.get('status',''):8s} {z.get('name',''):25s} ID: {z.get('id','')}  Plan: {z.get('plan',{}).get('name','')}")
    return "\n".join(lines)


async def get_zone_settings(zone: str) -> str:
    zone_id = _resolve_zone(zone)
    settings_to_check = ["ssl", "always_use_https", "browser_cache_ttl", "cache_level"]
    lines = [f"Zone Settings for {zone}:"]
    for setting in settings_to_check:
        resp = await cf_request("GET", f"/zones/{zone_id}/settings/{setting}")
        if resp["success"] and resp["result"]:
            val = resp["result"].get("value", "unknown")
            lines.append(f"  {setting}: {val}")
        else:
            lines.append(f"  {setting}: (unavailable)")
    return "\n".join(lines)


async def set_ssl_mode(zone: str, mode: str) -> str:
    zone_id = _resolve_zone(zone)
    resp = await cf_request("PATCH", f"/zones/{zone_id}/settings/ssl", body={"value": mode})
    if not resp["success"]:
        return f"Error setting SSL mode: {resp['errors']}"
    return f"✅ SSL mode for {zone} set to '{mode}'"


async def set_always_https(zone: str, enabled: bool) -> str:
    zone_id = _resolve_zone(zone)
    resp = await cf_request("PATCH", f"/zones/{zone_id}/settings/always_use_https", body={"value": "on" if enabled else "off"})
    if not resp["success"]:
        return f"Error setting Always Use HTTPS: {resp['errors']}"
    return f"✅ Always Use HTTPS for {zone} set to {'on' if enabled else 'off'}"


# ---------------------------------------------------------------------------
# Tunnel Management
# ---------------------------------------------------------------------------

async def list_tunnels() -> str:
    resp = await cf_request("GET", f"/accounts/{CF_ACCOUNT_ID}/cfd_tunnel")
    if not resp["success"]:
        return f"Error: {resp['errors']}"
    tunnels = resp["result"] or []
    lines = [f"Cloudflare Tunnels ({len(tunnels)} total):"]
    for t in tunnels:
        conns = t.get("connections", [])
        conn_info = f"{len(conns)} connections" if conns else "no connections"
        lines.append(f"  {t.get('status',''):8s} {t.get('name',''):30s} ID: {t.get('id','')}  [{conn_info}]")
    return "\n".join(lines)


async def get_tunnel_config(tunnel: str = "schubert-foxtrot") -> str:
    tunnel_id = _resolve_tunnel(tunnel)
    resp = await cf_request("GET", f"/accounts/{CF_ACCOUNT_ID}/cfd_tunnel/{tunnel_id}/configurations")
    if not resp["success"]:
        return f"Error getting tunnel config: {resp['errors']}"
    config = resp["result"]
    if not config:
        return f"No configuration found for tunnel {tunnel}."
    ingress = config.get("config", {}).get("ingress", [])
    lines = [f"Tunnel '{tunnel}' Ingress Rules ({len(ingress)} rules):"]
    for i, rule in enumerate(ingress):
        hostname = rule.get("hostname", "(catch-all)")
        service = rule.get("service", "")
        origin_req = rule.get("originRequest", {})
        tls = origin_req.get("noTLSVerify", False)
        lines.append(f"  {i+1}. {hostname:45s} → {service}" + (" [noTLSVerify]" if tls else ""))
    return "\n".join(lines)


async def get_tunnel_details(tunnel: str = "schubert-foxtrot") -> str:
    tunnel_id = _resolve_tunnel(tunnel)
    resp = await cf_request("GET", f"/accounts/{CF_ACCOUNT_ID}/cfd_tunnel/{tunnel_id}")
    if not resp["success"]:
        return f"Error: {resp['errors']}"
    t = resp["result"]
    if not t:
        return f"Tunnel '{tunnel}' not found."
    lines = [
        f"Tunnel: {t.get('name')}",
        f"  ID: {t.get('id')}",
        f"  Status: {t.get('status')}",
        f"  Config source: {t.get('config_src')}",
        f"  Remote config: {t.get('remote_config')}",
        f"  Created: {t.get('created_at')}",
        f"  Active connections: {len(t.get('connections', []))}",
    ]
    for conn in t.get("connections", []):
        lines.append(f"    - {conn.get('colo_name','')} (v{conn.get('client_version','')}) opened {conn.get('opened_at','')}")
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Cache Management
# ---------------------------------------------------------------------------

async def purge_cache(zone: str, urls: list[str] | None = None) -> str:
    zone_id = _resolve_zone(zone)
    body = {}
    if urls:
        body["files"] = urls
    else:
        body["purge_everything"] = True
    resp = await cf_request("POST", f"/zones/{zone_id}/purge_cache", body=body)
    if not resp["success"]:
        return f"Error purging cache: {resp['errors']}"
    if urls:
        return f"✅ Purged cache for {len(urls)} URL(s) in {zone}"
    return f"✅ Purged ALL cache for {zone}"


# ---------------------------------------------------------------------------
# High-level convenience: Add a new public service
# ---------------------------------------------------------------------------

async def add_public_service(
    hostname: str, service_url: str, zone: str = "", tunnel: str = "schubert-foxtrot",
) -> str:
    if not zone:
        for zname in CF_ZONES:
            if hostname.endswith(zname):
                zone = zname
                break
    if not zone:
        return f"Error: Could not auto-detect zone for hostname '{hostname}'. Please specify zone explicitly."
    dns_result = await create_dns_record(zone=zone, record_type="CNAME", name=hostname, content=CF_TUNNEL_ENDPOINT, proxied=True)
    if "Error" in dns_result:
        return dns_result
    tunnel_id = _resolve_tunnel(tunnel)
    config_resp = await cf_request("GET", f"/accounts/{CF_ACCOUNT_ID}/cfd_tunnel/{tunnel_id}/configurations")
    if not config_resp["success"]:
        return f"DNS record created but failed to get tunnel config: {config_resp['errors']}"
    config = config_resp["result"].get("config", {})
    ingress = config.get("ingress", [])
    new_rule = {"hostname": hostname, "service": service_url, "originRequest": {"noTLSVerify": True}}
    catch_all_idx = None
    for i, rule in enumerate(ingress):
        if "hostname" not in rule:
            catch_all_idx = i
            break
    if catch_all_idx is not None:
        ingress.insert(catch_all_idx, new_rule)
    else:
        ingress.append(new_rule)
    if not any("hostname" not in r for r in ingress):
        ingress.append({"service": "http_status:404"})
    config["ingress"] = ingress
    update_resp = await cf_request("PUT", f"/accounts/{CF_ACCOUNT_ID}/cfd_tunnel/{tunnel_id}/configurations", body={"config": config})
    if not update_resp["success"]:
        return f"DNS record created but failed to update tunnel config: {update_resp['errors']}"
    return f"✅ Added public service '{hostname}' → {service_url}\n  - DNS CNAME created in {zone}\n  - Tunnel ingress rule added to {tunnel}"


# ---------------------------------------------------------------------------
# Main dispatch function — called by execute_dev_tool() in both bots
# ---------------------------------------------------------------------------

async def execute_cloudflare_tool(action: str, args: dict) -> str:
    try:
        if action == "list_dns":
            return await list_dns_records(zone=args.get("zone", "schubert.life"), record_type=args.get("record_type", ""))
        elif action == "create_dns":
            return await create_dns_record(zone=args.get("zone", "schubert.life"), record_type=args.get("record_type", "CNAME"), name=args.get("name", ""), content=args.get("content", ""), proxied=args.get("proxied", True), ttl=args.get("ttl", 1), priority=args.get("priority"))
        elif action == "update_dns":
            return await update_dns_record(zone=args.get("zone", "schubert.life"), record_id=args.get("record_id", ""), record_type=args.get("record_type", ""), name=args.get("name", ""), content=args.get("content", ""), proxied=args.get("proxied"), ttl=args.get("ttl"))
        elif action == "delete_dns":
            return await delete_dns_record(zone=args.get("zone", "schubert.life"), record_id=args.get("record_id", ""))
        elif action == "list_zones":
            return await list_zones()
        elif action == "zone_settings":
            return await get_zone_settings(args.get("zone", "schubert.life"))
        elif action == "set_ssl":
            return await set_ssl_mode(zone=args.get("zone", "schubert.life"), mode=args.get("mode", "flexible"))
        elif action == "set_https":
            return await set_always_https(zone=args.get("zone", "schubert.life"), enabled=args.get("enabled", True))
        elif action == "list_tunnels":
            return await list_tunnels()
        elif action == "tunnel_config":
            return await get_tunnel_config(args.get("tunnel", "schubert-foxtrot"))
        elif action == "tunnel_details":
            return await get_tunnel_details(args.get("tunnel", "schubert-foxtrot"))
        elif action == "purge_cache":
            return await purge_cache(zone=args.get("zone", "schubert.life"), urls=args.get("urls"))
        elif action == "add_service":
            return await add_public_service(hostname=args.get("hostname", ""), service_url=args.get("service_url", ""), zone=args.get("zone", ""), tunnel=args.get("tunnel", "schubert-foxtrot"))
        elif action == "raw_request":
            resp = await cf_request(method=args.get("method", "GET"), path=args.get("path", "/"), body=args.get("body"), params=args.get("params"))
            return json.dumps(resp, indent=2)[:3000]
        else:
            return f"Unknown Cloudflare action: {action}. Available: list_dns, create_dns, update_dns, delete_dns, list_zones, zone_settings, set_ssl, set_https, list_tunnels, tunnel_config, tunnel_details, purge_cache, add_service, raw_request"
    except Exception as e:
        return f"Cloudflare API error: {e}"


# ---------------------------------------------------------------------------
# Tool definitions for LLM function calling
# ---------------------------------------------------------------------------

def get_cloudflare_tool_definition() -> dict:
    return {
        "type": "function",
        "function": {
            "name": "cloudflare",
            "description": (
                "Manage Cloudflare DNS, tunnels, zones, and cache. "
                "Can list/create/update/delete DNS records, manage tunnel ingress rules, "
                "view zone settings, purge cache, and add new public services. "
                "Actions: list_dns, create_dns, update_dns, delete_dns, list_zones, "
                "zone_settings, set_ssl, set_https, list_tunnels, tunnel_config, "
                "tunnel_details, purge_cache, add_service, raw_request."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "action": {"type": "string", "description": "The Cloudflare action to perform. One of: list_dns, create_dns, update_dns, delete_dns, list_zones, zone_settings, set_ssl, set_https, list_tunnels, tunnel_config, tunnel_details, purge_cache, add_service, raw_request"},
                    "zone": {"type": "string", "description": "Zone name (edstratumlabs.ai, jgeronimo.com, schubert.life) or zone ID. Default: schubert.life"},
                    "record_type": {"type": "string", "description": "DNS record type (A, CNAME, MX, TXT, etc.)"},
                    "name": {"type": "string", "description": "DNS record name (hostname)"},
                    "content": {"type": "string", "description": "DNS record content/value"},
                    "record_id": {"type": "string", "description": "DNS record ID (for update/delete)"},
                    "proxied": {"type": "boolean", "description": "Whether to proxy through Cloudflare (default true)"},
                    "ttl": {"type": "integer", "description": "TTL in seconds (1 = automatic)"},
                    "tunnel": {"type": "string", "description": "Tunnel name (default: schubert-foxtrot)"},
                    "mode": {"type": "string", "description": "SSL mode: off, flexible, full, full_strict"},
                    "enabled": {"type": "boolean", "description": "Enable or disable (for set_https)"},
                    "hostname": {"type": "string", "description": "Full hostname for add_service (e.g., newservice.schubert.life)"},
                    "service_url": {"type": "string", "description": "Origin service URL for add_service (e.g., http://localhost:3000)"},
                    "urls": {"type": "array", "items": {"type": "string"}, "description": "Specific URLs to purge (for purge_cache). Omit to purge everything."},
                    "method": {"type": "string", "description": "HTTP method for raw_request (GET, POST, PUT, PATCH, DELETE)"},
                    "path": {"type": "string", "description": "API path for raw_request (e.g., /zones)"},
                    "body": {"type": "object", "description": "Request body for raw_request"},
                },
                "required": ["action"],
            },
        },
    }