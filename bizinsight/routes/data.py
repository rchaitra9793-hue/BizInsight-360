"""Data management: CSV import, product catalogue, orders and database reset."""
import math
from datetime import date

from flask import (Blueprint, Response, current_app, flash, g, redirect, render_template, request,
                   url_for)

from ..db import get_db, query, reset_business_data, sample_available, scalar
from ..importer import ImportFailed, import_products, import_sales, template_csv
from ..utils import admin_required, login_required

bp = Blueprint("data", __name__, url_prefix="/data")

STATUSES = ["Delivered", "Shipped", "Cancelled", "Returned"]
NET = {"Delivered", "Shipped"}
SHIP_MODES = ["Standard", "Express", "Same Day", "Economy"]
PAYMENTS = ["UPI", "Cash on Delivery", "Credit/Debit Card", "Wallet", "Net Banking"]
REGIONS = ["North", "South", "East", "West", "Central"]
SEGMENTS = ["Consumer", "Corporate", "Home Office"]


def _next_id(table, column, prefix, width):
    """Next sequential id such as P0105 or C01501."""
    start = len(prefix) + 1
    last = scalar(f"SELECT MAX(CAST(SUBSTR({column}, {start}) AS INTEGER)) FROM {table} "
                  f"WHERE {column} LIKE ?", (prefix + "%",))
    return f"{prefix}{(last or 0) + 1:0{width}d}"


# ---------------- overview & import ----------------

@bp.route("/")
@login_required
def index():
    counts = query("""
        SELECT (SELECT COUNT(*) FROM orders) AS orders,
               (SELECT COUNT(*) FROM order_items) AS lines,
               (SELECT COUNT(*) FROM customers) AS customers,
               (SELECT COUNT(*) FROM products) AS products,
               (SELECT MIN(order_date) FROM orders) AS first,
               (SELECT MAX(order_date) FROM orders) AS last""", one=True)
    history = query("""
        SELECT l.*, u.name AS user_name FROM import_log l
        LEFT JOIN users u ON u.id = l.user_id ORDER BY l.id DESC LIMIT 15""")
    return render_template("data/index.html", counts=counts, history=history)


@bp.route("/import", methods=["POST"])
@admin_required
def upload():
    kind = request.form.get("kind")
    file = request.files.get("file")
    if kind not in ("sales", "products"):
        flash("Choose what you are importing.", "danger")
        return redirect(url_for("data.index"))
    if not file or not file.filename:
        flash("Choose a CSV file to upload.", "danger")
        return redirect(url_for("data.index"))
    if not file.filename.lower().endswith(".csv"):
        flash("Only .csv files are supported.", "danger")
        return redirect(url_for("data.index"))
    importer = import_sales if kind == "sales" else import_products
    try:
        result = importer(get_db(), file.stream, file.filename, g.user["id"])
    except ImportFailed as exc:
        flash(f"Import failed: {exc}", "danger")
        return redirect(url_for("data.index"))
    return render_template("data/import_result.html", result=result, kind=kind, filename=file.filename)


@bp.route("/template/<kind>.csv")
@login_required
def template(kind):
    if kind not in ("sales", "products"):
        return redirect(url_for("data.index"))
    return Response(template_csv(kind), mimetype="text/csv",
                    headers={"Content-Disposition": f"attachment; filename={kind}_template.csv"})


@bp.route("/reset", methods=["POST"])
@admin_required
def reset():
    if request.form.get("confirm") != "RESET":
        flash("Type RESET to confirm.", "warning")
        return redirect(url_for("data.index"))
    with_sample = request.form.get("mode") != "empty"
    if with_sample and not sample_available():
        flash("Sample CSV files are not in the data/ folder. Choose 'Start empty' or run "
              "python scripts/generate_data.py to recreate them.", "warning")
        return redirect(url_for("data.index"))
    reset_business_data(get_db(), with_sample=with_sample, user_id=g.user["id"])
    flash("Database reset" + (" and sample data loaded." if with_sample else " - all business data removed."),
          "success")
    return redirect(url_for("data.index"))


# ---------------- products ----------------

@bp.route("/products")
@login_required
def products():
    q = request.args.get("q", "").strip()
    category = request.args.get("category", "")
    clauses, params = [], []
    if q:
        clauses.append("(p.name LIKE ? OR p.product_id LIKE ?)")
        params += [f"%{q}%", f"%{q}%"]
    if category:
        clauses.append("p.category = ?")
        params.append(category)
    where = ("WHERE " + " AND ".join(clauses)) if clauses else ""
    rows = query(f"""
        SELECT p.*, (SELECT COUNT(*) FROM order_items oi WHERE oi.product_id = p.product_id) AS lines
        FROM products p {where} ORDER BY p.product_id""", params)
    categories = [r["category"] for r in query("SELECT DISTINCT category FROM products ORDER BY category")]
    return render_template("data/products.html", rows=rows, q=q, category=category, categories=categories)


def _product_form_values(form):
    errors = []
    values = {k: form.get(k, "").strip() for k in
              ("name", "category", "sub_category", "supplier", "unit_cost", "unit_price",
               "stock_qty", "reorder_level")}
    if not values["name"]:
        errors.append("Name is required.")
    if not values["category"]:
        errors.append("Category is required.")
    for key, cast in (("unit_cost", float), ("unit_price", float), ("stock_qty", int), ("reorder_level", int)):
        try:
            values[key] = cast(values[key] or 0)
            if values[key] < 0:
                errors.append(f"{key.replace('_', ' ').title()} cannot be negative.")
        except ValueError:
            errors.append(f"{key.replace('_', ' ').title()} must be a number.")
    if not errors and values["unit_price"] < values["unit_cost"]:
        flash("Note: selling price is below cost, so every sale will make a loss.", "warning")
    return values, errors


@bp.route("/products/new", methods=["GET", "POST"])
@bp.route("/products/<product_id>/edit", methods=["GET", "POST"])
@admin_required
def product_form(product_id=None):
    product = None
    if product_id:
        product = query("SELECT * FROM products WHERE product_id = ?", (product_id,), one=True)
        if not product:
            flash("Product not found.", "danger")
            return redirect(url_for("data.products"))
    if request.method == "POST":
        values, errors = _product_form_values(request.form)
        if errors:
            for e in errors:
                flash(e, "danger")
            product = {**(product or {}), **values}
        else:
            db = get_db()
            with db:
                if product_id:
                    db.execute("""UPDATE products SET name=?, category=?, sub_category=?, supplier=?,
                                  unit_cost=?, unit_price=?, stock_qty=?, reorder_level=?
                                  WHERE product_id=?""",
                               (values["name"], values["category"], values["sub_category"] or None,
                                values["supplier"] or None, values["unit_cost"], values["unit_price"],
                                values["stock_qty"], values["reorder_level"], product_id))
                    if values["stock_qty"] != product["stock_qty"]:
                        db.execute("INSERT INTO stock_movements (product_id, change_qty, reason, user_id) "
                                   "VALUES (?, ?, 'Manual stock correction', ?)",
                                   (product_id, values["stock_qty"] - product["stock_qty"], g.user["id"]))
                else:
                    product_id = _next_id("products", "product_id", "P", 4)
                    db.execute("""INSERT INTO products (product_id, name, category, sub_category, supplier,
                                  unit_cost, unit_price, stock_qty, reorder_level)
                                  VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                               (product_id, values["name"], values["category"], values["sub_category"] or None,
                                values["supplier"] or None, values["unit_cost"], values["unit_price"],
                                values["stock_qty"], values["reorder_level"]))
            flash(f"Product {product_id} saved.", "success")
            return redirect(url_for("data.products"))
    categories = [r["category"] for r in query("SELECT DISTINCT category FROM products ORDER BY category")]
    return render_template("data/product_form.html", product=product, categories=categories)


@bp.route("/products/<product_id>/delete", methods=["POST"])
@admin_required
def product_delete(product_id):
    if scalar("SELECT COUNT(*) FROM order_items WHERE product_id = ?", (product_id,)):
        flash("This product has sales history and cannot be deleted. Set its stock to 0 instead.", "warning")
    else:
        db = get_db()
        with db:
            db.execute("DELETE FROM stock_movements WHERE product_id = ?", (product_id,))
            db.execute("DELETE FROM products WHERE product_id = ?", (product_id,))
        flash(f"Product {product_id} deleted.", "success")
    return redirect(url_for("data.products"))


# ---------------- orders ----------------

@bp.route("/orders")
@login_required
def orders():
    q = request.args.get("q", "").strip()
    status = request.args.get("status", "")
    page = max(request.args.get("page", 1, type=int), 1)
    per_page = current_app.config["ROWS_PER_PAGE"]
    clauses, params = [], []
    if q:
        clauses.append("(o.order_id LIKE ? OR c.name LIKE ? OR c.customer_id LIKE ?)")
        params += [f"%{q}%"] * 3
    if status in STATUSES:
        clauses.append("o.status = ?")
        params.append(status)
    where = ("WHERE " + " AND ".join(clauses)) if clauses else ""
    total = scalar(f"SELECT COUNT(*) FROM orders o JOIN customers c ON c.customer_id = o.customer_id {where}",
                   params)
    rows = query(f"""
        SELECT o.order_id, o.order_date, o.status, o.payment_method, o.ship_mode,
               c.customer_id, c.name AS customer_name, c.city,
               (SELECT COUNT(*) FROM order_items oi WHERE oi.order_id = o.order_id) AS item_count,
               (SELECT ROUND(SUM(sales), 2) FROM order_items oi WHERE oi.order_id = o.order_id) AS value
        FROM orders o JOIN customers c ON c.customer_id = o.customer_id
        {where}
        ORDER BY o.order_date DESC, o.order_id DESC LIMIT ? OFFSET ?""",
                 params + [per_page, (page - 1) * per_page])
    pages = max(math.ceil(total / per_page), 1)
    return render_template("data/orders.html", rows=rows, q=q, status=status, statuses=STATUSES,
                           page=page, pages=pages, total=total)


@bp.route("/orders/<order_id>")
@login_required
def order_detail(order_id):
    order = query("""SELECT o.*, c.name AS customer_name, c.city, c.state, c.region
                     FROM orders o JOIN customers c ON c.customer_id = o.customer_id
                     WHERE o.order_id = ?""", (order_id,), one=True)
    if not order:
        flash("Order not found.", "danger")
        return redirect(url_for("data.orders"))
    items = query("""SELECT oi.*, p.name, p.category FROM order_items oi
                     JOIN products p ON p.product_id = oi.product_id WHERE oi.order_id = ?""", (order_id,))
    return render_template("data/order_detail.html", order=order, items=items, statuses=STATUSES)


@bp.route("/orders/<order_id>/status", methods=["POST"])
@admin_required
def order_status(order_id):
    new = request.form.get("status")
    order = query("SELECT * FROM orders WHERE order_id = ?", (order_id,), one=True)
    if not order or new not in STATUSES:
        flash("Invalid order or status.", "danger")
        return redirect(url_for("data.orders"))
    old = order["status"]
    if old == new:
        return redirect(url_for("data.order_detail", order_id=order_id))

    # Moving in or out of a "sold" state puts stock back or takes it out
    direction = 0
    if old in NET and new not in NET:
        direction = 1
    elif old not in NET and new in NET:
        direction = -1
    items = query("SELECT oi.product_id, oi.quantity, p.stock_qty, p.name FROM order_items oi "
                  "JOIN products p ON p.product_id = oi.product_id WHERE oi.order_id = ?", (order_id,))
    if direction == -1:
        short = [i["name"] for i in items if i["stock_qty"] < i["quantity"]]
        if short:
            flash("Not enough stock to reinstate this order: " + ", ".join(short), "danger")
            return redirect(url_for("data.order_detail", order_id=order_id))
    db = get_db()
    with db:
        db.execute("UPDATE orders SET status = ? WHERE order_id = ?", (new, order_id))
        if direction:
            for i in items:
                db.execute("UPDATE products SET stock_qty = stock_qty + ? WHERE product_id = ?",
                           (direction * i["quantity"], i["product_id"]))
                db.execute("INSERT INTO stock_movements (product_id, change_qty, reason, user_id) VALUES (?, ?, ?, ?)",
                           (i["product_id"], direction * i["quantity"], f"Order {order_id}: {old} -> {new}",
                            g.user["id"]))
    flash(f"Order {order_id} marked as {new}.", "success")
    return redirect(url_for("data.order_detail", order_id=order_id))


@bp.route("/orders/new", methods=["GET", "POST"])
@admin_required
def order_new():
    products = query("SELECT product_id, name, unit_price, unit_cost, stock_qty FROM products ORDER BY name")
    customers = query("SELECT customer_id, name, city FROM customers ORDER BY name")
    if request.method == "POST":
        form = request.form
        errors = []
        by_id = {p["product_id"]: p for p in products}

        lines = {}
        for pid, qty, disc in zip(form.getlist("product_id"), form.getlist("quantity"), form.getlist("discount")):
            if not pid:
                continue
            try:
                qty = int(qty)
                disc = float(disc or 0) / 100
            except ValueError:
                errors.append("Quantity and discount must be numbers.")
                continue
            p = by_id.get(pid)
            if not p:
                errors.append(f"Unknown product {pid}.")
            elif qty <= 0:
                errors.append(f"Quantity for {p['name']} must be at least 1.")
            elif not 0 <= disc < 1:
                errors.append(f"Discount for {p['name']} must be between 0 and 99%.")
            else:
                prev = lines.get(pid)
                lines[pid] = (qty + (prev[0] if prev else 0), disc)
        if not lines and not errors:
            errors.append("Add at least one product.")
        for pid, (qty, _) in lines.items():
            if by_id[pid]["stock_qty"] < qty:
                errors.append(f"Only {by_id[pid]['stock_qty']} units of {by_id[pid]['name']} in stock.")

        customer_id = form.get("customer_id", "").strip()
        new_customer = form.get("customer_mode") == "new"
        if new_customer:
            if not form.get("c_name", "").strip():
                errors.append("New customer name is required.")
        elif not any(c["customer_id"] == customer_id for c in customers):
            errors.append("Select an existing customer.")

        order_date = form.get("order_date") or date.today().isoformat()
        try:
            date.fromisoformat(order_date)
        except ValueError:
            errors.append("Order date is invalid.")

        if errors:
            for e in errors:
                flash(e, "danger")
        else:
            db = get_db()
            order_id = _next_id("orders", "order_id", "ORD-", 6)
            with db:
                if new_customer:
                    customer_id = _next_id("customers", "customer_id", "C", 5)
                    age = form.get("c_age", "").strip()
                    db.execute("""INSERT INTO customers (customer_id, name, gender, age, city, state, region, segment)
                                  VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
                               (customer_id, form["c_name"].strip(), form.get("c_gender") or None,
                                int(age) if age.isdigit() else None, form.get("c_city", "").strip() or None,
                                form.get("c_state", "").strip() or None, form.get("c_region") or None,
                                form.get("c_segment") or "Consumer"))
                db.execute("""INSERT INTO orders (order_id, order_date, ship_date, customer_id, status,
                              ship_mode, payment_method) VALUES (?, ?, NULL, ?, ?, ?, ?)""",
                           (order_id, order_date, customer_id,
                            form.get("status") if form.get("status") in NET else "Shipped",
                            form.get("ship_mode") or "Standard", form.get("payment_method") or "UPI"))
                for pid, (qty, disc) in lines.items():
                    p = by_id[pid]
                    sales = round(qty * p["unit_price"] * (1 - disc), 2)
                    cost = round(qty * p["unit_cost"], 2)
                    db.execute("""INSERT INTO order_items (order_id, product_id, quantity, unit_price, unit_cost,
                                  discount, sales, cost, profit) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                               (order_id, pid, qty, p["unit_price"], p["unit_cost"], disc, sales, cost,
                                round(sales - cost, 2)))
                    db.execute("UPDATE products SET stock_qty = stock_qty - ? WHERE product_id = ?", (qty, pid))
                    db.execute("INSERT INTO stock_movements (product_id, change_qty, reason, user_id) "
                               "VALUES (?, ?, ?, ?)", (pid, -qty, f"Sale {order_id}", g.user["id"]))
            flash(f"Order {order_id} created.", "success")
            return redirect(url_for("data.order_detail", order_id=order_id))
    return render_template("data/order_form.html", products=products, customers=customers,
                           ship_modes=SHIP_MODES, payments=PAYMENTS, regions=REGIONS, segments=SEGMENTS,
                           today=date.today().isoformat())
