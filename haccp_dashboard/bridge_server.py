from flask import Flask, jsonify

from haccp_dashboard.api_routes import bp as external_api_bp

try:
    from flask_socketio import SocketIO  # type: ignore
except Exception:
    SocketIO = None

from haccp_dashboard.lib.main_helpers import get_runtime_env_value


def create_bridge_app() -> Flask:
    app = Flask(__name__)
    app.config["JSON_AS_ASCII"] = False
    app.register_blueprint(external_api_bp)

    @app.get("/")
    def root():
        return jsonify(
            {
                "service": "haccp-flask-bridge",
                "status": "ok",
                "api_prefix": "/api",
                "realtime": "sse",
            }
        )

    @app.get("/healthz")
    def healthz():
        return jsonify({"status": "ok"})

    return app


def _create_socketio(app: Flask):
    if SocketIO is None:
        return None

    socketio = SocketIO(
        app,
        cors_allowed_origins="*",
        async_mode=(get_runtime_env_value("HACCP_SOCKETIO_ASYNC_MODE", "threading") or "threading"),
    )
    app.extensions["socketio"] = socketio
    return socketio


if __name__ == "__main__":
    host = get_runtime_env_value("HACCP_BRIDGE_HOST", "127.0.0.1") or "127.0.0.1"
    port = int(str(get_runtime_env_value("HACCP_BRIDGE_PORT", "5000")).strip() or "5000")
    app = create_bridge_app()
    socketio = _create_socketio(app)
    enable_socketio = str(get_runtime_env_value("HACCP_ENABLE_SOCKETIO", "0")).strip().lower() in {"1", "true", "yes", "on"}

    if enable_socketio and socketio is not None:
        socketio.run(app, host=host, port=port, debug=True, allow_unsafe_werkzeug=True)
    else:
        app.run(host=host, port=port, debug=True)
