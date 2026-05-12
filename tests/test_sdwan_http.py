"""SD-WAN Manager HTTP helpers (CSRF for multitenant JWT)."""

from __future__ import annotations

import httpx

from terra.sdwan_http import refresh_sdwan_dataservice_csrf_header


def test_refresh_sdwan_dataservice_csrf_parses_dict_data() -> None:
    def dispatch(request: httpx.Request) -> httpx.Response:
        u = str(request.url)
        if "/dataservice/client/server" in u:
            return httpx.Response(200, json={"data": {"CSRFToken": "tok-dict-9", "platformVersion": "20.16"}})
        return httpx.Response(404)

    transport = httpx.MockTransport(dispatch)
    with httpx.Client(transport=transport, headers={"Authorization": "Bearer test.jwt"}) as client:
        assert refresh_sdwan_dataservice_csrf_header(client, "https://vm.example.invalid") is True
        assert client.headers.get("X-XSRF-TOKEN") == "tok-dict-9"


def test_refresh_sdwan_dataservice_csrf_parses_list_data() -> None:
    def dispatch(request: httpx.Request) -> httpx.Response:
        if "/dataservice/client/server" in str(request.url):
            return httpx.Response(200, json={"data": [{"CSRFToken": "tok-list-1"}]})
        return httpx.Response(404)

    transport = httpx.MockTransport(dispatch)
    with httpx.Client(transport=transport, headers={"Authorization": "Bearer x"}) as client:
        assert refresh_sdwan_dataservice_csrf_header(client, "https://vm2.example.invalid") is True
        assert client.headers.get("X-XSRF-TOKEN") == "tok-list-1"


def test_refresh_sdwan_dataservice_csrf_skips_without_bearer() -> None:
    transport = httpx.MockTransport(lambda _r: httpx.Response(500))
    with httpx.Client(transport=transport) as client:
        assert refresh_sdwan_dataservice_csrf_header(client, "https://vm3.example.invalid") is False
