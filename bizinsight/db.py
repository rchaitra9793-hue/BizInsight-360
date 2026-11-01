"""SQLite connection handling, schema setup and first-run seeding."""
import os
import sqlite3
import threading
from collections import OrderedDict

import click
from flask import current_app, g
from werkzeug.security import generate_password_hash


def get_db():
    if "db" not in g:
        g.db = connect(current_app.config["DATABASE"])
    return g.db


def connect(path):
    conn = sqlite3.connect(path, detect_types=sqlite3.PARSE_DECLTYPES)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def close_db(_exc=None):
    db = g.pop("db", None)
    if db is not None:
        db.close()


def query(sql, params=(), one=False):
    """Run a SELECT and return dicts (or a single dict / None when one=True)."""
    cur = get_db().execute(sql, params)
    rows = [dict(r) for r in cur.fetchall()]
    return (rows[0] if rows else None) if one else rows


_cache = OrderedDict()
_cache_lock = threading.Lock()
CACHE_SIZE = 1000


def cached_query(sql, params=(), one=False):
    """query() for analytics: results are reused until business data changes."""
    version = get_db().execute("SELECT value FROM meta WHERE key = 'data_version'").fetchone()[0]
    key = (current_app.config["DATABASE"], version, sql, tuple(params))
    with _cache_lock:
        rows = _cache.get(key)
        if rows is not None:
            _cache.move_to_end(key)
    if rows is None:
        rows = query(sql, params)
        with _cache_lock:
            _cache[key] = rows
            while len(_cache) > CACHE_SIZE:
                _cache.popitem(last=False)
    # Callers add computed fields to the dicts, so hand out copies
    rows = [dict(r) for r in rows]
    return (rows[0] if rows else None) if one else rows


def bump_version(db):
    db.execute("UPDATE meta SET value = value + 1 WHERE key = 'data_version'")
    db.commit()


def scalar(sql, params=()):
    row = get_db().execute(sql, params).fetchone()
    return row[0] if row else None


def create_schema(db):
    with current_app.open_resource("schema.sql") as fh:
        db.executescript(fh.read().decode("utf-8"))


def drop_all(db):
    db.executescript("""
        DROP VIEW IF EXISTS v_sales;
        DROP TABLE IF EXISTS order_items;
        DROP TABLE IF EXISTS orders;
        DROP TABLE IF EXISTS stock_movements;
        DROP TABLE IF EXISTS import_log;
        DROP TABLE IF EXISTS products;
        DROP TABLE IF EXISTS customers;
    """)


def ensure_admin(db):
    cfg = current_app.config
    exists = db.execute("SELECT 1 FROM users WHERE role = 'admin'").fetchone()
    if not exists:
        db.execute(
            "INSERT INTO users (name, email, password_hash, role) VALUES (?, ?, ?, 'admin')",
            ("Administrator", cfg["ADMIN_EMAIL"], generate_password_hash(cfg["ADMIN_PASSWORD"])),
        )
        db.commit()


def _sample_files():
    data_dir = current_app.config["SAMPLE_DATA_DIR"]
    return os.path.join(data_dir, "products.csv"), os.path.join(data_dir, "sample_sales.csv")


def sample_available():
    return all(os.path.exists(p) for p in _sample_files())


def load_sample_data(db, user_id=None):
    """Load the bundled CSV files through the same importer users upload with."""
    from .importer import import_products, import_sales

    products_csv, sales_csv = _sample_files()
    if not sample_available():
        raise FileNotFoundError("Sample data missing - run: python scripts/generate_data.py")
    with open(products_csv, "rb") as fh:
        import_products(db, fh, "products.csv", user_id)
    with open(sales_csv, "rb") as fh:
        import_sales(db, fh, "sample_sales.csv", user_id)


def reset_business_data(db, with_sample=True, user_id=None):
    """Wipe all business data (users are kept) and optionally reload the sample."""
    drop_all(db)
    create_schema(db)
    bump_version(db)   # dropping tables fires no triggers
    if with_sample:
        load_sample_data(db, user_id)


def init_app(app):
    app.teardown_appcontext(close_db)
    app.cli.add_command(init_db_command)

    os.makedirs(os.path.dirname(app.config["DATABASE"]), exist_ok=True)
    with app.app_context():
        db = get_db()
        fresh = db.execute(
            "SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = 'orders'"
        ).fetchone() is None
        create_schema(db)
        ensure_admin(db)
        if fresh and app.config.get("AUTO_LOAD_SAMPLE", True):
            if sample_available():
                app.logger.info("New database - loading sample data")
                load_sample_data(db)
            else:
                app.logger.info("New database - no sample CSVs in data/, starting empty")


@click.command("init-db")
@click.option("--empty", is_flag=True, help="Create empty tables without sample data.")
def init_db_command(empty):
    """Recreate business tables and load the sample dataset."""
    db = get_db()
    reset_business_data(db, with_sample=not empty)
    ensure_admin(db)
    click.echo("Database initialised" + ("" if empty else " with sample data") + ".")
