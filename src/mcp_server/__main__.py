"""Entry point: python -m src.mcp_server"""

import os

import uvicorn

from src.mcp_server.server import build_app


def main() -> None:
    uvicorn.run(
        build_app(),
        host=os.environ.get("MCP_HOST", "127.0.0.1"),
        port=int(os.environ.get("MCP_PORT", "18081")),
        log_level="info",
    )


if __name__ == "__main__":
    main()
