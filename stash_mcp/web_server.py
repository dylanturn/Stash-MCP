"""Web server with REST API and UI.

This module is kept for backward compatibility.
The primary entrypoint is now stash_mcp.main.
"""

from .main import main as run_web_server

if __name__ == "__main__":
    run_web_server()
