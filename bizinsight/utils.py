"""Formatting helpers, auth decorators and CSRF protection."""
import secrets
from functools import wraps

from flask import abort, flash, g, redirect, request, session, url_for


# ---------- number formatting (Indian conventions) ----------

def fmt_inr(value, compact=True):
    """Rs. amount: compact uses Crore/Lakh/K, otherwise Indian digit grouping."""
    if value is None:
        return "-"
    sign = "-" if value < 0 else ""
    v = abs(value)
    if compact:
        if v >= 1e7:
            return f"{sign}₹{v / 1e7:.2f} Cr"
        if v >= 1e5:
            return f"{sign}₹{v / 1e5:.2f} L"
        if v >= 1e3:
            return f"{sign}₹{v / 1e3:.1f}K"
        return f"{sign}₹{v:,.0f}"
    return f"{sign}₹{indian_grouping(v)}"


def indian_grouping(value, decimals=0):
    """12345678 -> 1,23,45,678"""
    text = f"{value:.{decimals}f}"
    whole, _, frac = text.partition(".")
    if len(whole) > 3:
        head, tail = whole[:-3], whole[-3:]
        groups = []
        while len(head) > 2:
            groups.insert(0, head[-2:])
            head = head[:-2]
        if head:
            groups.insert(0, head)
        whole = ",".join(groups + [tail])
    return whole + ("." + frac if frac else "")


def fmt_pct(value, decimals=1):
    if value is None:
        return "-"
    return f"{value * 100:.{decimals}f}%"


def fmt_num(value):
    if value is None:
        return "-"
    return indian_grouping(value)


def register_filters(app):
    app.jinja_env.filters["inr"] = fmt_inr
    app.jinja_env.filters["inr_full"] = lambda v: fmt_inr(v, compact=False)
    app.jinja_env.filters["pct"] = fmt_pct
    app.jinja_env.filters["num"] = fmt_num


# ---------- authentication ----------

def login_required(view):
    @wraps(view)
    def wrapped(*args, **kwargs):
        if g.get("user") is None:
            return redirect(url_for("auth.login", next=request.full_path))
        return view(*args, **kwargs)
    return wrapped


def admin_required(view):
    @wraps(view)
    @login_required
    def wrapped(*args, **kwargs):
        if g.user["role"] != "admin":
            flash("Only administrators can do that.", "danger")
            return redirect(url_for("dashboard.index"))
        return view(*args, **kwargs)
    return wrapped


# ---------- CSRF ----------

def csrf_token():
    if "_csrf" not in session:
        session["_csrf"] = secrets.token_urlsafe(32)
    return session["_csrf"]


def init_csrf(app):
    app.jinja_env.globals["csrf_token"] = csrf_token

    @app.before_request
    def check_csrf():
        if request.method == "POST":
            sent = request.form.get("_csrf") or request.headers.get("X-CSRF-Token")
            if not sent or not secrets.compare_digest(sent, session.get("_csrf", "")):
                abort(400, description="Form expired or invalid. Please go back, refresh and try again.")


def safe_next(target):
    """Only allow redirects to local paths."""
    if target and target.startswith("/") and not target.startswith("//"):
        return target
    return None
