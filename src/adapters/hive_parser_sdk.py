"""本地 Hive Parse Java SDK 调用封装。"""

from __future__ import annotations

import json
import os
import subprocess
import tempfile
from pathlib import Path
from typing import Dict, Iterable, List

from src.core.progress import print_kv, print_stage
from src.core.project_config import SDK_CLASS_DIR, SDK_LIB_DIR, SDK_MAIN_CLASS, SDK_SOURCE_FILE


JAVA_OPEN_MODULE_ARGS = [
    "--add-opens",
    "java.base/java.net=ALL-UNNAMED",
]


def _list_sdk_jars() -> List[Path]:
    return sorted(SDK_LIB_DIR.glob("*.jar"))


def _build_classpath(include_classes: bool = True) -> str:
    paths = []
    if include_classes:
        paths.append(str(SDK_CLASS_DIR))
    paths.extend(str(path) for path in _list_sdk_jars())
    return os.pathsep.join(paths)


def is_sdk_ready() -> bool:
    return SDK_SOURCE_FILE.exists() and SDK_LIB_DIR.exists() and bool(_list_sdk_jars())


def ensure_sdk_compiled(force: bool = False) -> None:
    if not is_sdk_ready():
        raise FileNotFoundError(
            "Hive Parse SDK assets are incomplete. Please make sure the Java source and lib jars exist."
        )

    class_file = SDK_CLASS_DIR / "com" / "trainingcamp" / "hive" / "HiveParseSdkCli.class"
    if not force and class_file.exists() and class_file.stat().st_mtime >= SDK_SOURCE_FILE.stat().st_mtime:
        return

    SDK_CLASS_DIR.mkdir(parents=True, exist_ok=True)
    print_stage("编译 Java Hive Parse SDK")
    print_kv("Java 源文件", SDK_SOURCE_FILE)
    command = [
        "javac",
        "-encoding",
        "UTF-8",
        "-cp",
        _build_classpath(include_classes=False),
        "-d",
        str(SDK_CLASS_DIR),
        str(SDK_SOURCE_FILE),
    ]
    completed = subprocess.run(
        command,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="ignore",
        check=False,
    )
    if completed.returncode != 0:
        raise RuntimeError(
            "Failed to compile Hive Parse SDK CLI.\n"
            f"STDOUT:\n{completed.stdout}\nSTDERR:\n{completed.stderr}"
        )
    print_kv("Java SDK 编译结果", "success")


def _run_sdk_command(args: List[str], *, stdin_text: str | None = None) -> str:
    ensure_sdk_compiled()
    command = [
        "java",
        *JAVA_OPEN_MODULE_ARGS,
        "-cp",
        _build_classpath(include_classes=True),
        SDK_MAIN_CLASS,
        *args,
    ]
    completed = subprocess.run(
        command,
        input=stdin_text,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="ignore",
        check=False,
    )
    if completed.returncode != 0:
        raise RuntimeError(
            "Hive Parse SDK execution failed.\n"
            f"STDOUT:\n{completed.stdout}\nSTDERR:\n{completed.stderr}"
        )
    return completed.stdout


def parse_sql(sql_text: str) -> Dict[str, str]:
    output = _run_sdk_command([], stdin_text=sql_text)
    return json.loads(output)


def parse_sql_rows(rows: Iterable[Dict[str, str]]) -> List[Dict[str, str]]:
    payload_rows = list(rows)
    if not payload_rows:
        return []

    print_stage("批量调用 Hive Parse SDK")
    print_kv("待解析 SQL 数量", len(payload_rows))
    with tempfile.TemporaryDirectory(prefix="hive_parse_sdk_") as temp_dir:
        temp_path = Path(temp_dir)
        input_path = temp_path / "input.jsonl"
        output_path = temp_path / "output.jsonl"

        with input_path.open("w", encoding="utf-8") as handle:
            for row in payload_rows:
                handle.write(json.dumps(row, ensure_ascii=False) + "\n")

        _run_sdk_command(["--input-jsonl", str(input_path), "--output-jsonl", str(output_path)])

        results: List[Dict[str, str]] = []
        with output_path.open("r", encoding="utf-8") as handle:
            for line in handle:
                if not line.strip():
                    continue
                results.append(json.loads(line))
        print_kv("已返回解析结果数", len(results))
        return results
