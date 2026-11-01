"""Login, registration, logout and password change."""
import re

from flask import Blueprint, flash, g, redirect, render_template, request, session, url_for
from werkzeug.security import check_password_hash, generate_password_hash

from ..db import get_db, query
from ..utils import login_required, safe_next

bp = Blueprint("auth", __name__)

EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")


@bp.route("/login", methods=["GET", "POST"])
def login():
    if g.user:
        return redirect(url_for("dashboard.index"))
    if request.method == "POST":
        email = request.form.get("email", "").strip().lower()
        password = request.form.get("password", "")
        user = query("SELECT * FROM users WHERE email = ?", (email,), one=True)
        if user and check_password_hash(user["password_hash"], password):
            session.clear()
            session["user_id"] = user["id"]
            flash(f"Welcome back, {user['name']}!", "success")
            return redirect(safe_next(request.args.get("next")) or url_for("dashboard.index"))
        flash("Incorrect email or password.", "danger")
    return render_template("auth/login.html")


@bp.route("/register", methods=["GET", "POST"])
def register():
    if g.user:
        return redirect(url_for("dashboard.index"))
    if request.method == "POST":
        name = request.form.get("name", "").strip()
        email = request.form.get("email", "").strip().lower()
        password = request.form.get("password", "")
        confirm = request.form.get("confirm", "")
        error = None
        if len(name) < 2:
            error = "Please enter your name."
        elif not EMAIL_RE.match(email):
            error = "Please enter a valid email address."
        elif len(password) < 6:
            error = "Password must be at least 6 characters."
        elif password != confirm:
            error = "Passwords do not match."
        elif query("SELECT 1 FROM users WHERE email = ?", (email,), one=True):
            error = "An account with this email already exists."
        if error:
            flash(error, "danger")
        else:
            db = get_db()
            # Self-registered users get read-only analyst access; admins manage data
            db.execute("INSERT INTO users (name, email, password_hash, role) VALUES (?, ?, ?, 'analyst')",
                       (name, email, generate_password_hash(password)))
            db.commit()
            flash("Account created. Please sign in.", "success")
            return redirect(url_for("auth.login"))
    return render_template("auth/register.html")


@bp.route("/logout")
def logout():
    session.clear()
    flash("You have been signed out.", "info")
    return redirect(url_for("auth.login"))


@bp.route("/account", methods=["GET", "POST"])
@login_required
def account():
    if request.method == "POST":
        user = query("SELECT * FROM users WHERE id = ?", (g.user["id"],), one=True)
        current = request.form.get("current", "")
        new = request.form.get("new", "")
        if not check_password_hash(user["password_hash"], current):
            flash("Current password is incorrect.", "danger")
        elif len(new) < 6:
            flash("New password must be at least 6 characters.", "danger")
        elif new != request.form.get("confirm", ""):
            flash("New passwords do not match.", "danger")
        else:
            db = get_db()
            db.execute("UPDATE users SET password_hash = ? WHERE id = ?",
                       (generate_password_hash(new), user["id"]))
            db.commit()
            flash("Password updated.", "success")
            return redirect(url_for("auth.account"))
    users = query("SELECT id, name, email, role, created_at FROM users ORDER BY id") \
        if g.user["role"] == "admin" else []
    return render_template("auth/account.html", users=users)


@bp.route("/users/<int:user_id>/role", methods=["POST"])
@login_required
def set_role(user_id):
    if g.user["role"] != "admin":
        flash("Only administrators can change roles.", "danger")
    elif user_id == g.user["id"]:
        flash("You cannot change your own role.", "warning")
    else:
        role = request.form.get("role")
        if role in ("admin", "analyst"):
            db = get_db()
            db.execute("UPDATE users SET role = ? WHERE id = ?", (role, user_id))
            db.commit()
            flash("Role updated.", "success")
    return redirect(url_for("auth.account"))
