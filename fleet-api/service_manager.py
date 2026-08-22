from __future__ import annotations

import shutil
import subprocess
import time

_LAST_RESTART: dict[str, float] = {}
RESTART_COOLDOWN = 30.0


class ServiceManager:
    def __init__(self, dry_run: bool = False) -> None:
        self.dry_run = dry_run or shutil.which("systemctl") is None

    def status(self, service: str) -> str:
        if self.dry_run:
            return "online"
        try:
            result = subprocess.run(
                ["sudo", "-n", "systemctl", "is-active", service],
                capture_output=True,
                text=True,
                check=False,
                timeout=10,
            )
            raw = (result.stdout or "").strip()
            if raw == "active":
                return "online"
            if raw in {"inactive", "failed"}:
                return "offline"
            return raw or "unknown"
        except Exception:
            return "unknown"

    def restart(self, service: str) -> dict[str, str]:
        now = time.time()
        last = _LAST_RESTART.get(service, 0)
        if now - last < RESTART_COOLDOWN:
            return {
                "status": "rate_limited",
                "error": f"Restart limited to 1 per {int(RESTART_COOLDOWN)}s",
            }
        _LAST_RESTART[service] = now

        if self.dry_run:
            return {"status": "restarted", "mode": "dry_run"}

        try:
            result = subprocess.run(
                ["sudo", "-n", "systemctl", "restart", service],
                capture_output=True,
                text=True,
                check=False,
                timeout=60,
            )
            if result.returncode != 0:
                return {
                    "status": "error",
                    "error": (result.stderr or result.stdout or "restart failed").strip(),
                }
            return {"status": "restarted"}
        except Exception as exc:
            return {"status": "error", "error": str(exc)}

    def logs(self, service: str, lines: int = 100) -> str:
        if self.dry_run:
            return f"[dry-run] No journalctl output for {service}"
        try:
            result = subprocess.run(
                ["journalctl", "-u", service, "-n", str(lines), "--no-pager"],
                capture_output=True,
                text=True,
                check=False,
                timeout=30,
            )
            return result.stdout or result.stderr or ""
        except Exception as exc:
            return str(exc)
