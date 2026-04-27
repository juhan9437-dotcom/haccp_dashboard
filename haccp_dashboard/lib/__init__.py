"""
Internal helpers used by Dash pages.

Dash `use_pages=True` auto-imports every module under `haccp_dashboard/pages`.
We keep heavy helpers (pandas/model loading/HTTP/OpenAI utilities) outside that folder
to reduce server startup and initial page-load time.
"""

