"""Unit tests for SD-WAN governance ingest helpers."""

from __future__ import annotations

from terra_sdwan.sdwan_governance import (
    build_governance_query_body,
    governance_source_key,
    normalize_governance_row,
    normalize_severity,
)


def test_build_governance_query_body_last_n_hours() -> None:
    body = build_governance_query_body(hours=6, size=500)
    assert body["size"] == 500
    rules = body["query"]["rules"]
    assert len(rules) == 1
    assert rules[0]["field"] == "entry_time"
    assert rules[0]["operator"] == "last_n_hours"
    assert rules[0]["value"] == ["6"]


def test_normalize_severity_maps_aliases() -> None:
    assert normalize_severity("Critical") == "critical"
    assert normalize_severity("warning") == "major"
    assert normalize_severity("information") == "info"
    assert normalize_severity(None) == "unknown"


def test_governance_source_key_stable_for_same_row() -> None:
    row = {
        "uuid": "alarm-1",
        "entry_time": 1_700_000_000_000,
        "system_ip": "10.0.0.1",
        "rule_name": "BFD",
    }
    a = governance_source_key(
        sdwan_instance_id=1,
        sdwan_tenant_id="default",
        stream_kind="alarm",
        row=row,
    )
    b = governance_source_key(
        sdwan_instance_id=1,
        sdwan_tenant_id="default",
        stream_kind="alarm",
        row=row,
    )
    assert a == b
    assert a.startswith("alarm:")


def test_normalize_governance_row_alarm_fields() -> None:
    row = {
        "severity": "Major",
        "active": True,
        "system-ip": "192.168.1.10",
        "rule_name_display": "InterfaceDown",
        "message": "ge0/0 is down",
        "entry_time": 1_700_000_000_000,
    }
    norm = normalize_governance_row(row, stream_kind="alarm")
    assert norm["severity_norm"] == "major"
    assert norm["active"] is True
    assert norm["system_ip"] == "192.168.1.10"
    assert norm["title"] == "InterfaceDown"
    assert "down" in norm["summary"]


def test_normalize_governance_row_audit_user() -> None:
    row = {
        "loguser": "admin@corp",
        "logfeature": "Policy",
        "logmsg": "Updated policy list",
        "entry_time": 1_700_000_000_000,
    }
    norm = normalize_governance_row(row, stream_kind="audit")
    assert norm["loguser"] == "admin@corp"
    assert norm["logfeature"] == "Policy"
    assert norm["title"]
