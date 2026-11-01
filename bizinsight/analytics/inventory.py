"""Inventory health: stock value, days of cover, reorder suggestions and dead stock.

Rules (all configurable in config.py):
  avg daily demand  = units sold in the last DEMAND_WINDOW_DAYS / DEMAND_WINDOW_DAYS
  days of cover     = stock on hand / avg daily demand
  reorder point     = avg daily demand x (lead time + safety days), never below reorder_level
  suggested order   = demand for (lead time + safety + review period) - stock on hand
"""
import math
from datetime import date, timedelta

from flask import current_app

from ..db import cached_query as query
from .filters import NET_STATUS_SQL, data_bounds

STATUS_ORDER = ["Out of Stock", "Low Stock", "Dead Stock", "Overstock", "Healthy"]


def as_of_date():
    """Inventory is measured against the latest order date in the data."""
    return data_bounds()[1]


def stock_status(category=""):
    cfg = current_app.config
    window = cfg["DEMAND_WINDOW_DAYS"]
    as_of = as_of_date()
    since = (date.fromisoformat(as_of) - timedelta(days=window)).isoformat()

    params = [since, as_of]
    cat_clause = ""
    if category:
        cat_clause = "WHERE p.category = ?"
        params.append(category)
    rows = query(f"""
        WITH demand AS (
            SELECT product_id, SUM(quantity) AS units, SUM(cost) AS cogs
            FROM v_sales
            WHERE order_date > ? AND order_date <= ? AND {NET_STATUS_SQL}
            GROUP BY product_id
        ),
        last_sale AS (
            SELECT product_id, MAX(order_date) AS last_sold FROM v_sales GROUP BY product_id
        )
        SELECT p.product_id, p.name, p.category, p.sub_category, p.supplier,
               p.unit_cost, p.unit_price, p.stock_qty, p.reorder_level,
               COALESCE(d.units, 0) AS units_window,
               COALESCE(d.cogs, 0)  AS cogs_window,
               l.last_sold
        FROM products p
        LEFT JOIN demand d    ON d.product_id = p.product_id
        LEFT JOIN last_sale l ON l.product_id = p.product_id
        {cat_clause}
        ORDER BY p.category, p.name""", params)

    cover_days = cfg["LEAD_TIME_DAYS"] + cfg["SAFETY_STOCK_DAYS"]
    for r in rows:
        daily = r["units_window"] / window
        r["avg_daily"] = daily
        r["stock_value"] = r["stock_qty"] * r["unit_cost"]
        r["retail_value"] = r["stock_qty"] * r["unit_price"]
        r["days_cover"] = r["stock_qty"] / daily if daily else None
        r["reorder_point"] = max(r["reorder_level"], math.ceil(daily * cover_days))
        target = math.ceil(daily * (cover_days + cfg["REVIEW_PERIOD_DAYS"]))
        r["days_since_sale"] = ((date.fromisoformat(as_of) - date.fromisoformat(r["last_sold"])).days
                                if r["last_sold"] else None)

        if r["stock_qty"] == 0:
            r["status"] = "Out of Stock"
        elif daily == 0:
            r["status"] = "Dead Stock"
        elif r["stock_qty"] <= r["reorder_point"]:
            r["status"] = "Low Stock"
        elif r["days_cover"] > cfg["OVERSTOCK_DAYS"]:
            r["status"] = "Overstock"
        else:
            r["status"] = "Healthy"

        needs_order = r["status"] in ("Out of Stock", "Low Stock") and daily > 0
        r["suggested_order"] = max(target - r["stock_qty"], 0) if needs_order else 0
        r["order_cost"] = r["suggested_order"] * r["unit_cost"]
        # Annualised turnover: cost of goods sold per year / current stock value
        r["turnover"] = ((r["cogs_window"] * 365 / window) / r["stock_value"]
                         if r["stock_value"] else None)
    return rows


def summary(rows):
    total_value = sum(r["stock_value"] for r in rows)
    annual_cogs = sum(r["cogs_window"] for r in rows) * 365 / current_app.config["DEMAND_WINDOW_DAYS"]
    counts = {s: 0 for s in STATUS_ORDER}
    values = {s: 0.0 for s in STATUS_ORDER}
    for r in rows:
        counts[r["status"]] += 1
        values[r["status"]] += r["stock_value"]
    return {
        "products": len(rows),
        "units": sum(r["stock_qty"] for r in rows),
        "stock_value": total_value,
        "retail_value": sum(r["retail_value"] for r in rows),
        "turnover": annual_cogs / total_value if total_value else None,
        "days_of_inventory": total_value / (annual_cogs / 365) if annual_cogs else None,
        "status_counts": counts,
        "status_values": values,
        "reorder_cost": sum(r["order_cost"] for r in rows),
        "reorder_items": sum(1 for r in rows if r["suggested_order"] > 0),
        "as_of": as_of_date(),
    }


def by_category(rows):
    cats = {}
    for r in rows:
        c = cats.setdefault(r["category"], {"label": r["category"], "stock_value": 0.0,
                                            "units": 0, "cogs": 0.0, "at_risk": 0})
        c["stock_value"] += r["stock_value"]
        c["units"] += r["stock_qty"]
        c["cogs"] += r["cogs_window"]
        if r["status"] in ("Out of Stock", "Low Stock"):
            c["at_risk"] += 1
    window = current_app.config["DEMAND_WINDOW_DAYS"]
    for c in cats.values():
        c["turnover"] = (c["cogs"] * 365 / window) / c["stock_value"] if c["stock_value"] else None
    return sorted(cats.values(), key=lambda c: c["stock_value"], reverse=True)


def movements(limit=20):
    return query("""
        SELECT m.created_at, m.product_id, p.name, m.change_qty, m.reason, u.name AS user_name
        FROM stock_movements m
        JOIN products p ON p.product_id = m.product_id
        LEFT JOIN users u ON u.id = m.user_id
        ORDER BY m.id DESC LIMIT ?""", (limit,))
