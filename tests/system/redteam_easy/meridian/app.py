"""Meridian Systems — Internal Config Portal.

Intentionally vulnerable Flask application for red team demo.
CVE-2017-18342: yaml.load() called without Loader on user-supplied input.
"""

from importlib.metadata import distributions

import yaml
from flask import Flask, jsonify, request

app = Flask(__name__)


@app.route("/")
def index():
    return (
        "<html><body>"
        "<h1>Meridian Systems — Config Portal</h1>"
        "<p>Internal configuration management service. "
        "Submit YAML config files via POST to /api/parse-config.</p>"
        "<p>Contact the platform team for access issues.</p>"
        "</body></html>"
    )


@app.route("/api/parse-config", methods=["POST"])
def parse_config():
    data = request.get_data(as_text=True)
    if not data:
        return jsonify({"error": "No configuration data provided"}), 400
    try:
        # BUG: yaml.load without Loader — CVE-2017-18342
        parsed = yaml.load(data)  # noqa: S506
        return jsonify({"status": "ok", "config": str(parsed)})
    except Exception as exc:
        return jsonify({"status": "error", "message": str(exc)}), 400


@app.route("/debug")
def debug():
    """Developer debug endpoint — left enabled in production by mistake."""
    pkgs = {d.metadata["Name"]: d.metadata["Version"] for d in distributions()}
    return jsonify({"python": "3.10", "environment": "production", "packages": pkgs})


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000, debug=False)
