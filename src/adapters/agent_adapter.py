from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Dict, List

from src.adapters.hive_parser_sdk import parse_sql


@dataclass
class AgentParseSummary:
    trace_id: str
    actual_status: str
    actual_error_type: str
    actual_error_subtype: str
    actual_error_type_raw: str
    actual_error_subtype_raw: str
    actual_error_position: str
    parser_code: int
    parser_message: str
    raw_response: str


class BasePublishAgentAdapter:
    """Preserves the agent-facing response contract for all parser backends."""

    def __init__(self, trace_prefix: str) -> None:
        self._counter = 0
        self._trace_prefix = trace_prefix

    def _next_trace_id(self) -> str:
        self._counter += 1
        return f"{self._trace_prefix}{self._counter:06d}"

    def parse_summary(self, case: Dict[str, str]) -> AgentParseSummary:
        response = self.submit_sql(case)
        trace_id = str(response["traceId"])
        code = int(response["code"])
        message = str(response["message"])
        data = response["data"]
        status = str(data["status"])
        actual_status = "pass" if status == "ok" else "fail"

        actual_error_type = ""
        actual_error_subtype = ""
        actual_error_type_raw = ""
        actual_error_subtype_raw = ""
        actual_error_position = ""
        if actual_status == "fail":
            result_text = str(data["result"])
            parsed_result = json.loads(result_text)
            actual_error_type = str(parsed_result.get("normalizedErrorType", ""))
            actual_error_subtype = str(parsed_result.get("normalizedErrorSubtype", ""))
            actual_error_type_raw = str(parsed_result.get("rawErrorType", actual_error_type))
            actual_error_subtype_raw = str(parsed_result.get("rawErrorSubtype", actual_error_subtype))
            positions: List[Dict[str, int]] = parsed_result.get("positions", [])
            if positions:
                actual_error_position = f"{positions[0]['line']}:{positions[0]['column']}"

        return AgentParseSummary(
            trace_id=trace_id,
            actual_status=actual_status,
            actual_error_type=actual_error_type,
            actual_error_subtype=actual_error_subtype,
            actual_error_type_raw=actual_error_type_raw,
            actual_error_subtype_raw=actual_error_subtype_raw,
            actual_error_position=actual_error_position,
            parser_code=code,
            parser_message=message,
            raw_response=json.dumps(response, ensure_ascii=False),
        )

    @staticmethod
    def _build_success_response(trace_id: str, source_name: str, parser_message: str) -> Dict[str, object]:
        return {
            "code": 200,
            "message": parser_message,
            "traceId": trace_id,
            "data": {
                "status": "ok",
                "hints": [
                    {
                        "source": source_name,
                        "type": "info",
                        "message": parser_message,
                    }
                ],
                "result": None,
            },
        }

    @staticmethod
    def _build_failure_response(
        trace_id: str,
        source_name: str,
        actual_error_type: str,
        actual_error_subtype: str,
        raw_error_type: str,
        raw_error_subtype: str,
        actual_error_position: str,
        parser_message: str,
    ) -> Dict[str, object]:
        line, column = BasePublishAgentAdapter._split_position(actual_error_position)
        error_message = (
            f"LogId:{trace_id}\n"
            f"{source_name}.ParseException: {actual_error_type} at line {line}, column {column}"
        )
        return {
            "code": 400,
            "message": parser_message,
            "traceId": trace_id,
            "data": {
                "status": "error",
                "hints": [
                    {
                        "source": source_name,
                        "type": "error",
                        "message": error_message,
                    }
                ],
                "result": json.dumps(
                    {
                        "passed": False,
                        "operation": "parse",
                        "positions": [
                            {
                                "line": line,
                                "column": column,
                            }
                        ],
                        "normalizedErrorType": actual_error_type,
                        "normalizedErrorSubtype": actual_error_subtype,
                        "rawErrorType": raw_error_type,
                        "rawErrorSubtype": raw_error_subtype,
                    },
                    ensure_ascii=False,
                ),
            },
        }

    @staticmethod
    def _split_position(position: str) -> tuple[int, int]:
        if ":" not in position:
            return 1, 1
        line_text, column_text = position.split(":", 1)
        return int(line_text), int(column_text)


class HiveParseSdkAdapter(BasePublishAgentAdapter):
    """Real adapter backed by Apache Hive ParseDriver."""

    def __init__(self) -> None:
        super().__init__("SDKAGENT")

    def submit_sql(self, case: Dict[str, str]) -> Dict[str, object]:
        trace_id = self._next_trace_id()
        parsed = parse_sql(case["sql_text"].strip())
        actual_status = parsed["actual_status"]
        actual_error_type = parsed.get("actual_error_type", "")
        actual_error_subtype = parsed.get("actual_error_subtype", "")
        raw_error_type = parsed.get("raw_error_type", actual_error_type)
        raw_error_subtype = parsed.get("raw_error_subtype", actual_error_subtype)
        actual_error_position = parsed.get("actual_error_position", "")
        parser_message = parsed.get("parser_message", "")

        if actual_status == "pass":
            return self._build_success_response(trace_id, "hive_parse_sdk", parser_message or "Hive Parse SDK success")
        return self._build_failure_response(
            trace_id=trace_id,
            source_name="hive_parse_sdk",
            actual_error_type=actual_error_type,
            actual_error_subtype=actual_error_subtype,
            raw_error_type=raw_error_type,
            raw_error_subtype=raw_error_subtype,
            actual_error_position=actual_error_position,
            parser_message=parser_message or "Hive Parse SDK rejected SQL",
        )


def build_publish_agent_adapter(parser_backend: str | None = None) -> BasePublishAgentAdapter:
    return HiveParseSdkAdapter()
