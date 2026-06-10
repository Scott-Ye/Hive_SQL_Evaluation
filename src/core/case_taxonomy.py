from __future__ import annotations

from typing import Dict


TARGET_BUCKETS = {
    "QUERY_50": 50,
    "DDL_CREATE_ALTER_20": 20,
    "DML_WRITE_UPDATE_20": 20,
    "UTILITY_OTHER_10": 10,
}


def build_distribution_bucket(row: Dict[str, str]) -> str:
    level1 = row["level1_category"]

    if level1 == "QUERY":
        return "QUERY_50"
    if level1 == "DDL":
        return "DDL_CREATE_ALTER_20"
    if level1 == "DML":
        return "DML_WRITE_UPDATE_20"
    return "UTILITY_OTHER_10"
