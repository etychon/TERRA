"""Classify SD-WAN Manager API credentials against multitenant vs single-tenant behavior."""

from __future__ import annotations

from dataclasses import dataclass

import httpx

from terra_sdwan.sdwan_http import refresh_sdwan_dataservice_csrf_header
from terra_sdwan.sdwan_sync import (
    _tenant_switch_id,
    fetch_device_inventory,
    fetch_tenant_list,
    switch_tenant,
)

# Max tenant switch probes per verify (latency bound).
_MAX_TENANT_SWITCH_SAMPLES = 6


@dataclass(frozen=True)
class CredentialScopeDetection:
    """Result of ``detect_credential_scope`` (persisted on ``SdWanManagerInstance``)."""

    code: str
    detail: str
    tenant_rows: int
    switchable_count: int
    switch_ok_distinct: int


def credential_scope_public_label(code: str | None) -> str:
    """Short label for Administration table (no PII)."""
    if not code:
        return "— (run Verify)"
    return {
        "non_multitenant": "Non-multitenant cluster",
        "multitenant_provider": "Multitenant · provider / all tenants",
        "multitenant_tenant_token": "Multitenant · single-tenant token",
        "multitenant_ambiguous": "Multitenant · one tenant visible",
        "unknown": "Unknown",
    }.get(code, code)


def detect_credential_scope(client: httpx.Client, base_url: str) -> CredentialScopeDetection:
    """
    Infer how stored credentials relate to multitenant Manager APIs.

    - **non_multitenant:** ``GET /dataservice/tenant`` is empty / not applicable (see ``fetch_tenant_list``).
    - **multitenant_provider:** successful switches for **two or more** distinct tenants, **or** tenant list
      suggests MT but switches fail while provider-level ``GET /dataservice/device`` still works.
    - **multitenant_tenant_token:** two or more tenants are listed but only **one** distinct tenant switch works.
    - **multitenant_ambiguous:** exactly one switchable tenant row and that switch succeeds (provider with one
      customer vs tenant token cannot be distinguished without policy context).
    - **unknown:** inconsistent state, transport errors, or rows without switch ids.
    """
    try:
        tenants = fetch_tenant_list(client, base_url)
    except RuntimeError as exc:
        return CredentialScopeDetection(
            code="unknown",
            detail=f"tenant list error: {exc}",
            tenant_rows=0,
            switchable_count=0,
            switch_ok_distinct=0,
        )

    n_rows = len(tenants)
    if not tenants:
        return CredentialScopeDetection(
            code="non_multitenant",
            detail="No multitenant tenant registry (empty list or tenant API not used).",
            tenant_rows=0,
            switchable_count=0,
            switch_ok_distinct=0,
        )

    switchable = [t for t in tenants if isinstance(t, dict) and _tenant_switch_id(t)]
    n_sw = len(switchable)
    if not switchable:
        return CredentialScopeDetection(
            code="unknown",
            detail="Tenant payload returned rows but none had a resolvable id for POST …/tenant/{id}/switch.",
            tenant_rows=n_rows,
            switchable_count=0,
            switch_ok_distinct=0,
        )

    refresh_sdwan_dataservice_csrf_header(client, base_url)

    ok_tids: set[str] = set()
    for row in switchable[:_MAX_TENANT_SWITCH_SAMPLES]:
        tid = _tenant_switch_id(row)
        try:
            switch_tenant(client, base_url, tid)
            ok_tids.add(tid)
        except (RuntimeError, ValueError):
            continue

    n_ok = len(ok_tids)

    if n_ok >= 2:
        return CredentialScopeDetection(
            code="multitenant_provider",
            detail=f"Successful tenant context switches for {n_ok} distinct tenant(s) "
            f"(sampled up to {_MAX_TENANT_SWITCH_SAMPLES} of {n_sw} listed).",
            tenant_rows=n_rows,
            switchable_count=n_sw,
            switch_ok_distinct=n_ok,
        )

    if n_sw >= 2 and n_ok == 1:
        return CredentialScopeDetection(
            code="multitenant_tenant_token",
            detail=f"Listed {n_sw} tenants but only one distinct tenant switch succeeded; "
            "token is likely scoped to that tenant.",
            tenant_rows=n_rows,
            switchable_count=n_sw,
            switch_ok_distinct=n_ok,
        )

    if n_sw >= 2 and n_ok == 0:
        try:
            fetch_device_inventory(client, base_url)
        except RuntimeError as exc:
            return CredentialScopeDetection(
                code="unknown",
                detail=(
                    f"Multitenant list ({n_sw} tenants) but all switches failed "
                    f"and device inventory failed: {exc}"
                ),
                tenant_rows=n_rows,
                switchable_count=n_sw,
                switch_ok_distinct=0,
            )
        return CredentialScopeDetection(
            code="multitenant_provider",
            detail=(
                f"{n_sw} tenant row(s) listed; tenant switches failed but "
                "provider-level device inventory succeeded."
            ),
            tenant_rows=n_rows,
            switchable_count=n_sw,
            switch_ok_distinct=0,
        )

    # n_sw == 1
    if n_ok == 1:
        return CredentialScopeDetection(
            code="multitenant_ambiguous",
            detail="One tenant row and switch succeeded; cannot tell provider-with-one-tenant vs tenant token.",
            tenant_rows=n_rows,
            switchable_count=n_sw,
            switch_ok_distinct=1,
        )

    try:
        fetch_device_inventory(client, base_url)
    except RuntimeError as exc:
        return CredentialScopeDetection(
            code="unknown",
            detail=f"Single listed tenant but switch failed and device inventory failed: {exc}",
            tenant_rows=n_rows,
            switchable_count=n_sw,
            switch_ok_distinct=0,
        )
    return CredentialScopeDetection(
        code="multitenant_ambiguous",
        detail="One tenant row; switch failed; root device inventory still succeeded (scope unclear).",
        tenant_rows=n_rows,
        switchable_count=n_sw,
        switch_ok_distinct=0,
    )
