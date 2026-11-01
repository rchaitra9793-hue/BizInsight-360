"""BizInsight 360 - E-Commerce Sales, Profit & Inventory Analytics Platform."""
from flask import Flask, g, render_template, session

from config import Config

from . import db
from .utils import init_csrf, register_filters


def create_app(overrides=None):
    app = Flask(__name__, instance_relative_config=False)
    app.config.from_object(Config)
    if overrides:
        app.config.update(overrides)

    register_filters(app)
    init_csrf(app)
    db.init_app(app)

    @app.before_request
    def load_user():
        uid = session.get("user_id")
        g.user = db.query("SELECT id, name, email, role FROM users WHERE id = ?", (uid,), one=True) if uid else None

    from .routes import analytics, auth, data, inventory, reports
    app.register_blueprint(auth.bp)
    for bp in analytics.blueprints:
        app.register_blueprint(bp)
    app.register_blueprint(inventory.bp)
    app.register_blueprint(data.bp)
    app.register_blueprint(reports.bp)

    @app.errorhandler(400)
    @app.errorhandler(404)
    @app.errorhandler(413)
    def handle_error(err):
        return render_template("error.html", error=err), err.code

    return app
