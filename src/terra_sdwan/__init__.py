"""Shared Cisco Catalyst SD-WAN Manager client, inventory sync, and live dataservice reads.

Used by the ``terra`` FastAPI app (``core``) and the ``terra-collector`` worker. HTTP route
handlers stay in ``terra.routers``; low-level SD-WAN integration lives in this package.
"""
