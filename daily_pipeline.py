"""Daily public-information pipeline for SCU Radar.

One command performs an incremental collection, rebuilds radar-data.js, writes
the secretary brief, and records a machine-readable run log.  The existing
collector keeps the last successful snapshot when an upstream site fails.

Usage:
    py daily_pipeline.py
    py daily_pipeline.py --full
    py daily_pipeline.py --dry-run
"""
from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path


ROOT = Path(__file__).resolve().parent
LOG_DIR = ROOT / "logs"
LOCK_FILE = ROOT / ".pipeline.lock"
STATE_FILE = ROOT / "automation-state.json"
DATA_FILE = ROOT / "radar-data.js"
TZ = timezone(timedelta(hours=8))
CORE_SOURCES = {"sis", "jwc", "jwc-contests", "campus-events"}


def now() -> str:
    return datetime.now(TZ).isoformat()


def append_log(event: dict) -> None:
    LOG_DIR.mkdir(exist_ok=True)
    with (LOG_DIR / "pipeline.jsonl").open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(event, ensure_ascii=False, separators=(",", ":")) + "\n")


def read_json(path: Path, default):
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (FileNotFoundError, json.JSONDecodeError):
        return default


def acquire_lock() -> None:
    if LOCK_FILE.exists():
        age = time.time() - LOCK_FILE.stat().st_mtime
        if age < 90 * 60:
            raise RuntimeError(f"已有采集任务运行中：{LOCK_FILE}")
        LOCK_FILE.unlink(missing_ok=True)
    descriptor = os.open(LOCK_FILE, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
    with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
        json.dump({"pid": os.getpid(), "startedAt": now()}, handle)


def source_health() -> tuple[str, list[dict]]:
    health = []
    for source_id in sorted(CORE_SOURCES):
        if source_id == "sis":
            run = read_json(ROOT.parent / "scu-sis-public-data" / "data" / "sis_run.json", {})
            # The actual sibling folder name is discovered by update_radar.py.
            if not run:
                candidates = list(ROOT.parent.glob("*/data/sis_run.json"))
                run = read_json(candidates[0], {}) if candidates else {}
            status = "warning" if run.get("errors") else ("ok" if run else "missing")
            health.append({"id": source_id, "status": status, "count": run.get("unique_articles", 0)})
            continue
        run = read_json(ROOT / "external-data" / source_id / "run.json", {})
        health.append({"id": source_id, "status": run.get("status", "missing"), "count": run.get("count", 0)})
    available = [item for item in health if item["status"] in {"ok", "warning"} and item["count"] > 0]
    return ("ok" if len(available) == len(CORE_SOURCES) else "degraded"), health


def main() -> int:
    parser = argparse.ArgumentParser(description="Run the SCU Radar daily collection pipeline")
    parser.add_argument("--full", action="store_true", help="force the weekly full scan now")
    parser.add_argument("--dry-run", action="store_true", help="show the command without collecting")
    args = parser.parse_args()
    command = [sys.executable, str(ROOT / "update_radar.py")]
    if args.full:
        command.append("--full")
    if args.dry_run:
        print(json.dumps({"command": command, "cwd": str(ROOT), "coreSources": sorted(CORE_SOURCES)}, ensure_ascii=False))
        return 0

    started = now()
    event = {"startedAt": started, "command": command, "status": "running"}
    acquire_lock()
    try:
        discovery = subprocess.run([sys.executable, str(ROOT / "discover_scu_channels.py")], cwd=ROOT, text=True, capture_output=True, timeout=2 * 60)
        result = subprocess.run(command, cwd=ROOT, text=True, capture_output=True, timeout=45 * 60)
        pipeline_status, core = source_health()
        state = read_json(STATE_FILE, {})
        event.update({
            "finishedAt": now(),
            "status": "failed" if result.returncode else pipeline_status,
            "exitCode": result.returncode,
            "coreSources": core,
            "dataBytes": DATA_FILE.stat().st_size if DATA_FILE.exists() else 0,
            "lastBuild": state.get("last_build"),
            "stdout": result.stdout[-2000:],
            "stderr": result.stderr[-2000:],
            "channelDiscovery": {"exitCode": discovery.returncode, "stdout": discovery.stdout[-1000:], "stderr": discovery.stderr[-1000:]},
        })
        append_log(event)
        if result.stdout:
            print(result.stdout, end="")
        if result.stderr:
            print(result.stderr, file=sys.stderr, end="")
        print(json.dumps({"pipeline": event["status"], "coreSources": core, "log": str(LOG_DIR / "pipeline.jsonl")}, ensure_ascii=False))
        return result.returncode
    except Exception as exc:
        event.update({"finishedAt": now(), "status": "failed", "error": str(exc)})
        append_log(event)
        raise
    finally:
        LOCK_FILE.unlink(missing_ok=True)


if __name__ == "__main__":
    raise SystemExit(main())
