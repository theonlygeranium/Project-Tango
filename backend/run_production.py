from __future__ import annotations

import os
import signal
import subprocess
import sys
import time
from collections.abc import Sequence


def _spawn(name: str, args: Sequence[str]) -> subprocess.Popen[str]:
    env = {
        **os.environ,
        "PYTHONUNBUFFERED": "1",
    }
    process = subprocess.Popen(
        args,
        env=env,
        stdin=subprocess.DEVNULL,
        text=True,
    )
    print(f"started {name} pid={process.pid}", flush=True)
    return process


def _terminate(processes: list[subprocess.Popen[str]]) -> None:
    for process in processes:
        if process.poll() is None:
            process.terminate()

    deadline = time.monotonic() + 20
    while time.monotonic() < deadline:
        if all(process.poll() is not None for process in processes):
            return
        time.sleep(0.25)

    for process in processes:
        if process.poll() is None:
            process.kill()


def main() -> int:
    python = sys.executable
    backend_port = os.getenv("BACKEND_PORT", "8030")
    log_level = os.getenv("LOG_LEVEL", "info")
    worker_log_level = os.getenv("LIVEKIT_LOG_LEVEL", log_level).upper()

    processes = [
        _spawn(
            "tango-api",
            [
                python,
                "-m",
                "uvicorn",
                "main:app",
                "--host",
                "127.0.0.1",
                "--port",
                backend_port,
                "--workers",
                "1",
                "--log-level",
                log_level.lower(),
            ],
        ),
        _spawn(
            "tango-livekit-worker",
            [
                python,
                "main.py",
                "start",
                "--log-level",
                worker_log_level,
            ],
        ),
    ]

    stopping = False

    def handle_signal(signum: int, _frame: object) -> None:
        nonlocal stopping
        if stopping:
            return
        stopping = True
        print(f"received signal {signum}; stopping Tango backend processes", flush=True)
        _terminate(processes)

    signal.signal(signal.SIGTERM, handle_signal)
    signal.signal(signal.SIGINT, handle_signal)

    try:
        while not stopping:
            for process in processes:
                return_code = process.poll()
                if return_code is not None:
                    print(
                        f"backend child pid={process.pid} exited with code {return_code}",
                        flush=True,
                    )
                    _terminate(processes)
                    return return_code or 1
            time.sleep(1)
    finally:
        _terminate(processes)

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
