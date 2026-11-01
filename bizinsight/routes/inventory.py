"""Inventory monitoring and stock adjustments."""
from flask import Blueprint, flash, g, redirect, render_template, request, url_for

from ..analytics import inventory as inv
from ..analytics.filters import filter_options
from ..db import get_db, query
from ..utils import admin_required, login_required

bp = Blueprint("inventory", __name__, url_prefix="/inventory")


@bp.route("/")
@login_required
def index():
    category = request.args.get("category", "")
    status = request.args.get("status", "")
    search = request.args.get("q", "").strip().lower()
    rows = inv.stock_status(category)
    summary = inv.summary(rows)
    listing = rows
    if status:
        listing = [r for r in listing if r["status"] == status]
    if search:
        listing = [r for r in listing if search in r["name"].lower() or search in r["product_id"].lower()]
    order = {s: i for i, s in enumerate(inv.STATUS_ORDER)}
    listing = sorted(listing, key=lambda r: (order[r["status"]], -(r["avg_daily"] or 0)))
    reorder = sorted((r for r in rows if r["suggested_order"] > 0), key=lambda r: -r["order_cost"])
    dead = sorted((r for r in rows if r["status"] == "Dead Stock"), key=lambda r: -r["stock_value"])
    return render_template("inventory.html", rows=listing, summary=summary, reorder=reorder, dead=dead,
                           categories=inv.by_category(rows), statuses=inv.STATUS_ORDER,
                           options=filter_options(), category=category, status=status,
                           q=request.args.get("q", ""), movements=inv.movements())


@bp.route("/<product_id>/adjust", methods=["POST"])
@admin_required
def adjust(product_id):
    product = query("SELECT * FROM products WHERE product_id = ?", (product_id,), one=True)
    if not product:
        flash("Product not found.", "danger")
        return redirect(url_for("inventory.index"))
    try:
        qty = int(request.form.get("qty", "0"))
    except ValueError:
        qty = 0
    mode = request.form.get("mode", "restock")
    reason = request.form.get("reason", "").strip()
    db = get_db()

    if mode == "reorder_level":
        if qty < 0:
            flash("Reorder level cannot be negative.", "danger")
        else:
            db.execute("UPDATE products SET reorder_level = ? WHERE product_id = ?", (qty, product_id))
            db.commit()
            flash(f"Reorder level for {product['name']} set to {qty}.", "success")
        return redirect(request.referrer or url_for("inventory.index"))

    change = qty if mode == "restock" else -qty
    if qty <= 0:
        flash("Enter a quantity greater than zero.", "danger")
    elif product["stock_qty"] + change < 0:
        flash(f"Only {product['stock_qty']} units in stock.", "danger")
    else:
        with db:
            db.execute("UPDATE products SET stock_qty = stock_qty + ? WHERE product_id = ?", (change, product_id))
            db.execute("INSERT INTO stock_movements (product_id, change_qty, reason, user_id) VALUES (?, ?, ?, ?)",
                       (product_id, change, reason or ("Restock" if change > 0 else "Write-off"), g.user["id"]))
        flash(f"{product['name']}: stock {'increased' if change > 0 else 'reduced'} by {qty}.", "success")
    return redirect(request.referrer or url_for("inventory.index"))
