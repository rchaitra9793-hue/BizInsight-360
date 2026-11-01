"""Sales KPIs, trends and breakdowns."""
import statistics
from dataclasses import replace

from ..db import cached_query as query
from .filters import data_bounds, pct_change, period_sql

# Columns of v_sales that may be used in GROUP BY (never interpolate user input)
DIMENSIONS = {"region", "state", "city", "category", "sub_category", "payment_method",
              "ship_mode", "segment", "gender", "status"}
WEEKDAYS = ["Sunday", "Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday"]


def kpis(f):
    where, params = f.where()
    row = query(f"""
        SELECT COALESCE(SUM(sales), 0)  AS revenue,
               COALESCE(SUM(profit), 0) AS profit,
               COALESCE(SUM(cost), 0)   AS cost,
               COUNT(DISTINCT order_id)    AS orders,
               COUNT(DISTINCT customer_id) AS customers,
               COALESCE(SUM(quantity), 0)  AS units,
               COALESCE(AVG(discount), 0)  AS avg_discount
        FROM v_sales {where}""", params, one=True)
    row["margin"] = row["profit"] / row["revenue"] if row["revenue"] else 0
    row["aov"] = row["revenue"] / row["orders"] if row["orders"] else 0

    where_all, params_all = f.where(net=False)
    status = query(f"""
        SELECT COUNT(DISTINCT order_id) AS total,
               COUNT(DISTINCT CASE WHEN status = 'Returned'  THEN order_id END) AS returned,
               COUNT(DISTINCT CASE WHEN status = 'Cancelled' THEN order_id END) AS cancelled,
               COALESCE(SUM(CASE WHEN status = 'Returned' THEN sales END), 0) AS returned_value
        FROM v_sales {where_all}""", params_all, one=True)
    total = status["total"] or 0
    row["all_orders"] = total
    row["return_rate"] = status["returned"] / total if total else 0
    row["cancel_rate"] = status["cancelled"] / total if total else 0
    row["returned_value"] = status["returned_value"]
    return row


def kpis_with_change(f):
    """Current KPIs plus change versus the previous equal-length period."""
    current = kpis(f)
    previous = kpis(f.previous())
    change = {k: pct_change(current[k], previous[k])
              for k in ("revenue", "profit", "orders", "customers", "units", "aov")}
    # Rates compare as percentage-point differences
    change["margin"] = current["margin"] - previous["margin"] if previous["revenue"] else None
    change["return_rate"] = (current["return_rate"] - previous["return_rate"]
                             if previous["all_orders"] else None)
    current["change"] = change
    return current, previous


def auto_granularity(f):
    if f.days <= 62:
        return "day"
    if f.days <= 200:
        return "week"
    return "month"


def trend(f, granularity=None):
    granularity = granularity or auto_granularity(f)
    where, params = f.where()
    rows = query(f"""
        SELECT {period_sql(granularity)} AS period,
               ROUND(SUM(sales), 2)  AS revenue,
               ROUND(SUM(profit), 2) AS profit,
               COUNT(DISTINCT order_id) AS orders,
               SUM(quantity) AS units
        FROM v_sales {where}
        GROUP BY period ORDER BY period""", params)
    for i, r in enumerate(rows):
        r["margin"] = r["profit"] / r["revenue"] if r["revenue"] else 0
        r["aov"] = r["revenue"] / r["orders"] if r["orders"] else 0
        window = [x["revenue"] for x in rows[max(0, i - 2): i + 1]]
        r["moving_avg"] = round(sum(window) / len(window), 2)
        r["growth"] = pct_change(r["revenue"], rows[i - 1]["revenue"]) if i else None
    return rows


def by_dimension(f, column, limit=None, net=True):
    if column not in DIMENSIONS:
        raise ValueError(f"Unsupported dimension: {column}")
    where, params = f.where(net=net)
    sql = f"""
        SELECT COALESCE({column}, 'Unknown') AS label,
               ROUND(SUM(sales), 2)  AS revenue,
               ROUND(SUM(profit), 2) AS profit,
               COUNT(DISTINCT order_id)    AS orders,
               COUNT(DISTINCT customer_id) AS customers,
               SUM(quantity)  AS units,
               AVG(discount)  AS avg_discount
        FROM v_sales {where}
        GROUP BY label ORDER BY revenue DESC"""
    if limit:
        sql += f" LIMIT {int(limit)}"
    rows = query(sql, params)
    total = sum(r["revenue"] for r in rows) or 1
    for r in rows:
        r["margin"] = r["profit"] / r["revenue"] if r["revenue"] else 0
        r["share"] = r["revenue"] / total
        r["aov"] = r["revenue"] / r["orders"] if r["orders"] else 0
    return rows


def return_rates(f, column="category"):
    """Share of orders returned, per dimension value, highest first."""
    if column not in DIMENSIONS:
        raise ValueError(f"Unsupported dimension: {column}")
    where, params = f.where(net=False)
    rows = query(f"""
        SELECT COALESCE({column}, 'Unknown') AS label,
               COUNT(DISTINCT order_id) AS orders,
               COUNT(DISTINCT CASE WHEN status = 'Returned' THEN order_id END) AS returned,
               ROUND(SUM(CASE WHEN status = 'Returned' THEN sales ELSE 0 END), 2) AS returned_value
        FROM v_sales {where} GROUP BY label""", params)
    for r in rows:
        r["rate"] = r["returned"] / r["orders"] if r["orders"] else 0
    return sorted(rows, key=lambda r: r["rate"], reverse=True)


def by_weekday(f):
    where, params = f.where()
    rows = query(f"""
        SELECT CAST(strftime('%w', order_date) AS INTEGER) AS dow,
               ROUND(SUM(sales), 2) AS revenue,
               COUNT(DISTINCT order_id) AS orders,
               COUNT(DISTINCT order_date) AS days
        FROM v_sales {where}
        GROUP BY dow ORDER BY dow""", params)
    by_dow = {r["dow"]: r for r in rows}
    # Monday-first ordering reads more naturally in a business week
    out = []
    for dow in [1, 2, 3, 4, 5, 6, 0]:
        r = by_dow.get(dow, {"revenue": 0, "orders": 0, "days": 0})
        out.append({"label": WEEKDAYS[dow], "revenue": r["revenue"], "orders": r["orders"],
                    "avg_daily_revenue": r["revenue"] / r["days"] if r["days"] else 0})
    return out


def monthly_summary(f):
    """Month-by-month table with month-on-month and year-on-year growth."""
    first, _ = data_bounds()
    history = replace(f, start=first)          # full history so YoY works at the window start
    where, params = history.where()
    rows = query(f"""
        SELECT strftime('%Y-%m', order_date) AS month,
               ROUND(SUM(sales), 2)  AS revenue,
               ROUND(SUM(profit), 2) AS profit,
               COUNT(DISTINCT order_id)    AS orders,
               COUNT(DISTINCT customer_id) AS customers
        FROM v_sales {where}
        GROUP BY month ORDER BY month""", params)
    by_month = {r["month"]: r for r in rows}
    out = []
    prev = None
    for r in rows:
        year, month = r["month"].split("-")
        last_year = by_month.get(f"{int(year) - 1}-{month}")
        r["margin"] = r["profit"] / r["revenue"] if r["revenue"] else 0
        r["aov"] = r["revenue"] / r["orders"] if r["orders"] else 0
        r["mom"] = pct_change(r["revenue"], prev["revenue"]) if prev else None
        r["yoy"] = pct_change(r["revenue"], last_year["revenue"]) if last_year else None
        prev = r
        if r["month"] >= f.start[:7]:
            out.append(r)
    return out


def order_value_stats(f, bins=12):
    """Descriptive statistics and a histogram of order values."""
    where, params = f.where()
    values = [r["value"] for r in query(
        f"SELECT SUM(sales) AS value FROM v_sales {where} GROUP BY order_id", params)]
    if len(values) < 2:
        return None
    values.sort()
    q = statistics.quantiles(values, n=100)
    stats = {
        "count": len(values),
        "mean": statistics.fmean(values),
        "median": statistics.median(values),
        "stdev": statistics.stdev(values),
        "min": values[0],
        "max": values[-1],
        "p25": q[24],
        "p75": q[74],
        "p90": q[89],
    }
    # Histogram up to the 95th percentile so a few huge orders don't flatten it
    upper = q[94]
    width = upper / bins if upper else 1
    counts = [0] * (bins + 1)
    for v in values:
        counts[min(int(v // width), bins)] += 1
    labels = [f"{int(i * width):,}-{int((i + 1) * width):,}" for i in range(bins)] + [f"{int(upper):,}+"]
    stats["histogram"] = {"labels": labels, "counts": counts}
    return stats


def recent_orders(f, limit=8):
    where, params = f.where(net=False)
    return query(f"""
        SELECT order_id, order_date, customer_name, status, ROUND(SUM(sales), 2) AS value,
               COUNT(*) AS item_count
        FROM v_sales {where}
        GROUP BY order_id ORDER BY order_date DESC, order_id DESC LIMIT ?""", params + [limit])
