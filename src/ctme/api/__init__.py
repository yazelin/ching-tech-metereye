"""REST API module for MeterEye."""

try:
    from ctme.api.server import create_app, run_server

    __all__ = ["create_app", "run_server"]
except ImportError:
    # FastAPI not installed
    __all__ = []
