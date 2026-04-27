"""
WSGI entrypoint (production/deployment).

Example (gunicorn):
  gunicorn -w 2 -b 0.0.0.0:8050 haccp_dashboard.wsgi:server
"""

import os

from haccp_dashboard.app import server

if __name__ == "__main__":
    host = os.getenv("HOST", "127.0.0.1")
    port = int(os.getenv("PORT", "8050"))
    server.run(host=host, port=port, debug=False)
