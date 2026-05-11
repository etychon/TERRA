"""Normalize Cisco SD-WAN Manager `dataservice` JSON shapes (shared by client probe and device sync)."""

from __future__ import annotations

from typing import Any


def _fields_from_dataservice_header(header: Any) -> list[str] | None:
    if not isinstance(header, dict):
        return None
    fields = header.get("fields")
    if not isinstance(fields, list) or not fields:
        return None
    keys: list[str] = []
    for f in fields:
        if isinstance(f, dict):
            name = f.get("property") or f.get("name") or f.get("title") or f.get("field")
            if isinstance(name, str) and name.strip():
                keys.append(name.strip())
        elif isinstance(f, str) and f.strip():
            keys.append(f.strip())
    return keys or None


def rows_from_dataservice_body(body: Any) -> list[dict[str, Any]]:
    """Normalize vManage dataservice JSON into a list of row dicts (object rows or tabular header+data)."""
    if isinstance(body, list):
        return [x for x in body if isinstance(x, dict)]
    if not isinstance(body, dict):
        return []
    data = body.get("data")
    if not isinstance(data, list):
        return []
    if not data:
        return []
    if all(isinstance(x, dict) for x in data):
        return list(data)
    if all(isinstance(x, list) for x in data):
        keys = _fields_from_dataservice_header(body.get("header"))
        if not keys:
            return []
        out: list[dict[str, Any]] = []
        for row in data:
            if not isinstance(row, list):
                continue
            n = min(len(row), len(keys))
            if n:
                out.append(dict(zip(keys[:n], row[:n], strict=False)))
        return out
    return [x for x in data if isinstance(x, dict)]
