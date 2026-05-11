"""CLI entry: `terra-serve` → uvicorn."""

from __future__ import annotations


def main() -> None:
    import uvicorn

    uvicorn.run(
        "terra.main:app",
        host="127.0.0.1",
        port=8000,
        reload=True,
        factory=False,
    )
