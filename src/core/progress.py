from __future__ import annotations


def print_stage(title: str) -> None:
    print(f"[stage] {title}", flush=True)


def print_kv(label: str, value: object) -> None:
    print(f"[info] {label}: {value}", flush=True)


def print_progress(prefix: str, current: int, total: int, *, item: str = "") -> None:
    safe_total = total if total > 0 else 1
    width = 24
    filled = int(width * min(current, safe_total) / safe_total)
    bar = "#" * filled + "-" * (width - filled)
    suffix = f" | {item}" if item else ""
    print(f"[progress] {prefix} [{bar}] {current}/{total}{suffix}", flush=True)
