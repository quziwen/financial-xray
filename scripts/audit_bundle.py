"""Deterministic core audit for financial-xray analysis_bundle.json files."""

from __future__ import annotations

import argparse
import json
import math
from pathlib import Path
import re
import sys
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_SCHEMA = ROOT / "references" / "analysis_bundle.schema.json"
EXPECTED_SKILL_VERSION = "2.1.2"
TOP_LEVEL = ("run", "disclosures", "metrics", "calculations", "claims", "issues", "scenarios", "actions", "quality")
DATE_PATTERN = re.compile(r"^\d{4}-\d{2}-\d{2}$")


def _nonempty(value: Any) -> bool:
    return isinstance(value, str) and bool(value.strip())


def _record(value: Any, label: str, errors: list[str]) -> dict[str, Any] | None:
    if not isinstance(value, dict):
        errors.append(f"{label} must be an object")
        return None
    return value


def _array(value: Any, label: str, errors: list[str], *, nonempty: bool = False) -> list[Any]:
    if not isinstance(value, list):
        errors.append(f"{label} must be an array")
        return []
    if nonempty and not value:
        errors.append(f"{label} must not be empty")
    return value


def _required(record: dict[str, Any], fields: tuple[str, ...], label: str, errors: list[str]) -> None:
    for field in fields:
        if field not in record:
            errors.append(f"{label}.{field} is required")


def _check_text_fields(record: dict[str, Any], fields: tuple[str, ...], label: str, errors: list[str]) -> None:
    for field in fields:
        if field in record and not _nonempty(record[field]):
            errors.append(f"{label}.{field} must be a non-empty string")


def _unique_text_array(value: Any, label: str, errors: list[str], *, nonempty: bool = False) -> list[str]:
    items = _array(value, label, errors, nonempty=nonempty)
    if any(not _nonempty(item) for item in items):
        errors.append(f"{label} must contain only non-empty strings")
        return []
    if len(set(items)) != len(items):
        errors.append(f"{label} contains duplicate values")
    return items


def _collect_ids(records: list[Any], field: str, label: str, errors: list[str]) -> tuple[set[str], list[dict[str, Any]]]:
    identifiers: set[str] = set()
    normalized: list[dict[str, Any]] = []
    for index, value in enumerate(records):
        item_label = f"{label}[{index}]"
        record = _record(value, item_label, errors)
        if record is None:
            continue
        normalized.append(record)
        identifier = record.get(field)
        if not _nonempty(identifier):
            errors.append(f"{item_label}.{field} must be a non-empty string")
        elif identifier in identifiers:
            errors.append(f"duplicate {field}: {identifier}")
        else:
            identifiers.add(identifier)
    return identifiers, normalized


def audit_bundle(bundle: Any) -> list[str]:
    errors: list[str] = []
    root = _record(bundle, "bundle", errors)
    if root is None:
        return errors
    _required(root, TOP_LEVEL, "bundle", errors)
    extras = sorted(set(root) - set(TOP_LEVEL))
    if extras:
        errors.append(f"bundle has unsupported top-level fields: {', '.join(extras)}")

    run = _record(root.get("run"), "run", errors)
    if run is not None:
        run_fields = ("company_name", "mode", "disclosure_regime", "accounting_basis", "report_cutoff_date", "main_analysis_period", "skill_version")
        _required(run, run_fields, "run", errors)
        _check_text_fields(run, run_fields, "run", errors)
        if run.get("mode") not in {"prospectus", "financial_report"}:
            errors.append("run.mode must be prospectus or financial_report")
        if run.get("skill_version") != EXPECTED_SKILL_VERSION:
            errors.append(f"run.skill_version must be {EXPECTED_SKILL_VERSION}")
        if _nonempty(run.get("report_cutoff_date")) and not DATE_PATTERN.match(run["report_cutoff_date"]):
            errors.append("run.report_cutoff_date must use YYYY-MM-DD")

    disclosure_values = _array(root.get("disclosures"), "disclosures", errors, nonempty=True)
    metric_values = _array(root.get("metrics"), "metrics", errors, nonempty=True)
    calculation_values = _array(root.get("calculations"), "calculations", errors)
    claim_values = _array(root.get("claims"), "claims", errors, nonempty=True)
    issue_values = _array(root.get("issues"), "issues", errors)
    scenario_values = _array(root.get("scenarios"), "scenarios", errors)
    action_values = _array(root.get("actions"), "actions", errors)

    source_ids, disclosures = _collect_ids(disclosure_values, "source_id", "disclosures", errors)
    metric_ids, metrics = _collect_ids(metric_values, "metric_id", "metrics", errors)
    calculation_ids, calculations = _collect_ids(calculation_values, "calculation_id", "calculations", errors)
    claim_ids, claims = _collect_ids(claim_values, "claim_id", "claims", errors)
    _collect_ids(issue_values, "issue_id", "issues", errors)
    _collect_ids(scenario_values, "scenario_id", "scenarios", errors)
    _collect_ids(action_values, "action_id", "actions", errors)

    evidence_ids = source_ids | metric_ids | calculation_ids
    if len(evidence_ids) != len(source_ids) + len(metric_ids) + len(calculation_ids):
        errors.append("source_id, metric_id and calculation_id must be globally unique")
    if claim_ids & evidence_ids:
        errors.append("claim_id must not collide with an evidence ID")

    disclosure_fields = ("source_id", "file_or_url", "disclosure_type", "publication_date", "reporting_period", "location", "currency", "unit", "extraction_method")
    for index, item in enumerate(disclosures):
        label = f"disclosures[{index}]"
        _required(item, disclosure_fields, label, errors)
        _check_text_fields(item, disclosure_fields, label, errors)
        if _nonempty(item.get("publication_date")) and not DATE_PATTERN.match(item["publication_date"]):
            errors.append(f"{label}.publication_date must use YYYY-MM-DD")

    metric_fields = ("metric_id", "name", "value", "classification", "formula", "scope", "period", "currency", "unit", "source_chain")
    allowed_classifications = {"statutory", "non_gaap", "calculated", "proxy"}
    for index, item in enumerate(metrics):
        label = f"metrics[{index}]"
        _required(item, metric_fields, label, errors)
        _check_text_fields(item, ("metric_id", "name", "scope", "period", "currency", "unit"), label, errors)
        if not isinstance(item.get("formula"), str):
            errors.append(f"{label}.formula must be a string")
        if item.get("classification") not in allowed_classifications:
            errors.append(f"{label}.classification is invalid")
        sources = _unique_text_array(item.get("source_chain"), f"{label}.source_chain", errors, nonempty=True)
        for source in sources:
            if source not in source_ids:
                errors.append(f"{label}.source_chain references unknown source: {source}")

    calculation_fields = ("calculation_id", "input_metric_ids", "formula", "output_metric_id", "tolerance", "residual_difference")
    for index, item in enumerate(calculations):
        label = f"calculations[{index}]"
        _required(item, calculation_fields, label, errors)
        _check_text_fields(item, ("calculation_id", "formula", "output_metric_id"), label, errors)
        inputs = _unique_text_array(item.get("input_metric_ids"), f"{label}.input_metric_ids", errors, nonempty=True)
        for metric in inputs:
            if metric not in metric_ids:
                errors.append(f"{label}.input_metric_ids references unknown metric: {metric}")
        if item.get("output_metric_id") not in metric_ids:
            errors.append(f"{label}.output_metric_id references unknown metric")
        tolerance = item.get("tolerance")
        residual = item.get("residual_difference")
        if type(tolerance) not in (int, float) or not math.isfinite(tolerance) or tolerance < 0:
            errors.append(f"{label}.tolerance must be a finite non-negative number")
        if type(residual) not in (int, float) or not math.isfinite(residual):
            errors.append(f"{label}.residual_difference must be a finite number")
        elif type(tolerance) in (int, float) and math.isfinite(tolerance) and tolerance >= 0 and abs(residual) > tolerance:
            errors.append(f"{label} residual exceeds tolerance")

    claim_fields = ("claim_id", "text", "level", "placement", "evidence_ids", "dependent_metric_ids", "allowed_wording_strength")
    levels = {"disclosed_fact", "calculation", "supported_inference", "hypothesis"}
    placements = {"summary", "core", "body", "issue"}
    for index, item in enumerate(claims):
        label = f"claims[{index}]"
        _required(item, claim_fields, label, errors)
        _check_text_fields(item, ("claim_id", "text", "allowed_wording_strength"), label, errors)
        if item.get("level") not in levels:
            errors.append(f"{label}.level is invalid")
        if item.get("placement") not in placements:
            errors.append(f"{label}.placement is invalid")
        if item.get("level") == "hypothesis" and item.get("placement") in {"summary", "core"}:
            errors.append(f"{label}: hypothesis cannot appear in summary or core")
        for evidence in _unique_text_array(item.get("evidence_ids"), f"{label}.evidence_ids", errors, nonempty=True):
            if evidence not in evidence_ids:
                errors.append(f"{label}.evidence_ids references unknown ID: {evidence}")
        for metric in _unique_text_array(item.get("dependent_metric_ids"), f"{label}.dependent_metric_ids", errors):
            if metric not in metric_ids:
                errors.append(f"{label}.dependent_metric_ids references unknown metric: {metric}")

    for index, item in enumerate(issue_values):
        record = item if isinstance(item, dict) else {}
        label = f"issues[{index}]"
        _required(record, ("issue_id", "management_question", "decision_chain"), label, errors)
        _check_text_fields(record, ("issue_id", "management_question"), label, errors)
        _unique_text_array(record.get("decision_chain"), f"{label}.decision_chain", errors, nonempty=True)

    for index, item in enumerate(scenario_values):
        record = item if isinstance(item, dict) else {}
        label = f"scenarios[{index}]"
        _required(record, ("scenario_id", "name", "assumptions", "decision_effect"), label, errors)
        _check_text_fields(record, ("scenario_id", "name", "decision_effect"), label, errors)
        _unique_text_array(record.get("assumptions"), f"{label}.assumptions", errors, nonempty=True)

    for index, item in enumerate(action_values):
        record = item if isinstance(item, dict) else {}
        label = f"actions[{index}]"
        _required(record, ("action_id", "priority", "owner_role", "action", "completion_evidence"), label, errors)
        _check_text_fields(record, ("action_id", "owner_role", "action", "completion_evidence"), label, errors)
        if record.get("priority") not in {"P0", "P1", "P2"}:
            errors.append(f"{label}.priority must be P0, P1 or P2")

    quality = _record(root.get("quality"), "quality", errors)
    if quality is not None:
        _required(quality, ("audit_status", "checks", "data_gaps", "red_flags"), "quality", errors)
        if quality.get("audit_status") not in {"pending", "pass", "fail"}:
            errors.append("quality.audit_status is invalid")
        for field in ("checks", "data_gaps", "red_flags"):
            _unique_text_array(quality.get(field), f"quality.{field}", errors)
    return errors


def load_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8-sig"))


def main() -> int:
    parser = argparse.ArgumentParser(description="Audit a financial-xray analysis bundle")
    parser.add_argument("bundle", type=Path)
    parser.add_argument("--schema", type=Path, default=DEFAULT_SCHEMA)
    args = parser.parse_args()
    try:
        schema = load_json(args.schema)
        schema_version = schema["properties"]["run"]["properties"]["skill_version"]["const"]
        if schema_version != EXPECTED_SKILL_VERSION:
            raise ValueError("schema version does not match audit script")
        bundle = load_json(args.bundle)
        errors = audit_bundle(bundle)
    except (OSError, UnicodeError, json.JSONDecodeError, KeyError, TypeError, ValueError) as exc:
        print(json.dumps({"status": "FAIL", "errors": [str(exc)]}, ensure_ascii=True))
        return 1
    result = {"status": "PASS" if not errors else "FAIL", "error_count": len(errors), "errors": errors}
    print(json.dumps(result, ensure_ascii=True, indent=2))
    return 0 if not errors else 1


if __name__ == "__main__":
    sys.exit(main())
