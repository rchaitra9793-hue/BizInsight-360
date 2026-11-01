"""Customer analytics: RFM segmentation, cohorts, retention and demographics.

RFM is rule-based scoring, not machine learning: each customer is ranked on
Recency, Frequency and Monetary value, split into quintiles (scores 1-5),
and mapped to a named segment with fixed business rules.
"""
from dataclasses import replace
from datetime import date

import pandas as pd

from ..db import cached_query as query
from .filters import NET_STATUS_SQL, data_bounds

SEGMENT_INFO = {
    "Champions": ("Bought recently, buy often and spend the most", "Reward them; early access, loyalty perks"),
    "Loyal Customers": ("Buy regularly and respond well", "Upsell higher-value products"),
    "Potential Loyalists": ("Recent customers with more than one order", "Offer membership or a bundle deal"),
    "New Customers": ("First purchase was recent", "Onboarding emails, second-order coupon"),
    "Need Attention": ("Average recency, frequency and spend", "Limited-time personalised offers"),
    "At Risk": ("Used to buy often but not recently", "Win-back campaign before they churn"),
    "Hibernating": ("Low spend, long time since last order", "Re-engage with best-sellers or let go"),
}
SEGMENT_ORDER = list(SEGMENT_INFO)


def summary(f):
    where, params = f.where()
    row = query(f"""
        SELECT COUNT(DISTINCT customer_id) AS customers,
               COALESCE(SUM(sales), 0) AS revenue,
               COUNT(DISTINCT order_id) AS orders
        FROM v_sales {where}""", params, one=True)
    per_customer = query(f"""
        SELECT customer_id, COUNT(DISTINCT order_id) AS orders
        FROM v_sales {where} GROUP BY customer_id""", params)
    repeat = sum(1 for r in per_customer if r["orders"] > 1)
    new = query(f"""
        SELECT COUNT(*) AS n FROM (
            SELECT customer_id, MIN(order_date) AS first_order
            FROM orders WHERE {NET_STATUS_SQL} GROUP BY customer_id)
        WHERE first_order BETWEEN ? AND ?""", (f.start, f.end), one=True)["n"]
    customers = row["customers"] or 0
    return {
        "customers": customers,
        "new_customers": new,
        "repeat_customers": repeat,
        "repeat_rate": repeat / customers if customers else 0,
        "revenue_per_customer": row["revenue"] / customers if customers else 0,
        "orders_per_customer": row["orders"] / customers if customers else 0,
    }


def rfm(f):
    """Return (per-customer DataFrame, segment summary list)."""
    where, params = f.where()
    rows = query(f"""
        SELECT customer_id, customer_name, city, region, segment AS customer_type,
               MAX(order_date) AS last_order,
               COUNT(DISTINCT order_id) AS frequency,
               SUM(sales) AS monetary
        FROM v_sales {where}
        GROUP BY customer_id""", params)
    if len(rows) < 5:
        return pd.DataFrame(), []

    df = pd.DataFrame(rows)
    ref = pd.Timestamp(f.end)
    df["recency"] = (ref - pd.to_datetime(df["last_order"])).dt.days
    # rank(method="first") breaks ties so qcut always gets 5 distinct bins
    df["r"] = pd.qcut(df["recency"].rank(method="first"), 5, labels=[5, 4, 3, 2, 1]).astype(int)
    df["f"] = pd.qcut(df["frequency"].rank(method="first"), 5, labels=[1, 2, 3, 4, 5]).astype(int)
    df["m"] = pd.qcut(df["monetary"].rank(method="first"), 5, labels=[1, 2, 3, 4, 5]).astype(int)
    df["rfm_score"] = df["r"].astype(str) + df["f"].astype(str) + df["m"].astype(str)
    df["rfm_segment"] = df.apply(_segment, axis=1)
    df = df.sort_values("monetary", ascending=False)

    total_rev = df["monetary"].sum() or 1
    grouped = df.groupby("rfm_segment").agg(
        customers=("customer_id", "count"), revenue=("monetary", "sum"),
        avg_recency=("recency", "mean"), avg_frequency=("frequency", "mean"),
        avg_monetary=("monetary", "mean"))
    segments = []
    for name in SEGMENT_ORDER:
        if name not in grouped.index:
            continue
        g = grouped.loc[name]
        segments.append({
            "segment": name, "description": SEGMENT_INFO[name][0], "action": SEGMENT_INFO[name][1],
            "customers": int(g["customers"]), "customer_share": g["customers"] / len(df),
            "revenue": float(g["revenue"]), "revenue_share": g["revenue"] / total_rev,
            "avg_recency": float(g["avg_recency"]), "avg_frequency": float(g["avg_frequency"]),
            "avg_monetary": float(g["avg_monetary"]),
        })
    return df, segments


def _segment(row):
    r, f, m = row["r"], row["f"], row["m"]
    if r >= 4 and f >= 4 and m >= 4:
        return "Champions"
    if r >= 3 and f >= 4:
        return "Loyal Customers"
    if r >= 4 and f >= 2:
        return "Potential Loyalists"
    if r >= 4:
        return "New Customers"
    if r <= 2 and f >= 3:
        return "At Risk"
    if r <= 2:
        return "Hibernating"
    return "Need Attention"


def new_vs_returning(f):
    """Per month: customers placing their first-ever order vs returning customers."""
    where, params = f.where()
    return query(f"""
        WITH firsts AS (
            SELECT customer_id, strftime('%Y-%m', MIN(order_date)) AS first_month
            FROM orders WHERE {NET_STATUS_SQL} GROUP BY customer_id
        ),
        active AS (
            SELECT DISTINCT strftime('%Y-%m', order_date) AS month, customer_id
            FROM v_sales {where}
        )
        SELECT a.month,
               SUM(CASE WHEN a.month = fi.first_month THEN 1 ELSE 0 END) AS new_customers,
               SUM(CASE WHEN a.month > fi.first_month THEN 1 ELSE 0 END) AS returning_customers
        FROM active a JOIN firsts fi ON fi.customer_id = a.customer_id
        GROUP BY a.month ORDER BY a.month""", params)


def cohort_retention(f, cohorts=12, months=12):
    """Share of each monthly acquisition cohort still buying N months later."""
    first, _ = data_bounds()
    history = replace(f, start=first)
    where, params = history.where()
    rows = query(f"""
        SELECT customer_id, strftime('%Y-%m', order_date) AS month
        FROM v_sales {where} GROUP BY customer_id, month""", params)
    if not rows:
        return {"months": [], "rows": []}
    df = pd.DataFrame(rows)
    df["first"] = df.groupby("customer_id")["month"].transform("min")

    def month_index(ym):
        y, m = ym.str.slice(0, 4).astype(int), ym.str.slice(5, 7).astype(int)
        return y * 12 + m

    df["offset"] = month_index(df["month"]) - month_index(df["first"])
    sizes = df[df["offset"] == 0].groupby("first")["customer_id"].nunique()
    active = df[df["offset"] < months].groupby(["first", "offset"])["customer_id"].nunique()

    last_month = month_index(pd.Series([f.end[:7]])).iloc[0]
    out = []
    for cohort in sorted(sizes.index)[-cohorts:]:
        start_idx = month_index(pd.Series([cohort])).iloc[0]
        values = []
        for k in range(months):
            if start_idx + k > last_month:
                values.append(None)       # future month: not observable yet
            else:
                values.append(int(active.get((cohort, k), 0)) / int(sizes[cohort]))
        out.append({"cohort": cohort, "size": int(sizes[cohort]), "cells": values})
    return {"months": list(range(months)), "rows": out}


def demographics(f):
    where, params = f.where()
    age_groups = query(f"""
        SELECT CASE WHEN age IS NULL THEN 'Unknown'
                    WHEN age < 25 THEN '18-24' WHEN age < 35 THEN '25-34'
                    WHEN age < 45 THEN '35-44' WHEN age < 55 THEN '45-54'
                    ELSE '55+' END AS label,
               COUNT(DISTINCT customer_id) AS customers,
               ROUND(SUM(sales), 2) AS revenue,
               COUNT(DISTINCT order_id) AS orders
        FROM v_sales {where}
        GROUP BY label ORDER BY label""", params)
    for r in age_groups:
        r["aov"] = r["revenue"] / r["orders"] if r["orders"] else 0
    gender = query(f"""
        SELECT COALESCE(gender, 'Unknown') AS label, COUNT(DISTINCT customer_id) AS customers,
               ROUND(SUM(sales), 2) AS revenue
        FROM v_sales {where} GROUP BY label ORDER BY revenue DESC""", params)
    gender_category = query(f"""
        SELECT COALESCE(gender, 'Unknown') AS gender, category, ROUND(SUM(sales), 2) AS revenue
        FROM v_sales {where} GROUP BY gender, category""", params)
    return {"age_groups": age_groups, "gender": gender, "gender_category": gender_category}


def top_customers(f, limit=15):
    where, params = f.where()
    return query(f"""
        SELECT customer_id, customer_name, city, segment,
               COUNT(DISTINCT order_id) AS orders,
               ROUND(SUM(sales), 2) AS revenue,
               ROUND(SUM(profit), 2) AS profit,
               MAX(order_date) AS last_order
        FROM v_sales {where}
        GROUP BY customer_id ORDER BY revenue DESC LIMIT ?""", params + [limit])


def customer_profile(customer_id):
    info = query("SELECT * FROM customers WHERE customer_id = ?", (customer_id,), one=True)
    if not info:
        return None
    orders = query("""
        SELECT o.order_id, o.order_date, o.status, o.payment_method,
               COUNT(oi.id) AS item_count, ROUND(SUM(oi.sales), 2) AS value
        FROM orders o JOIN order_items oi ON oi.order_id = o.order_id
        WHERE o.customer_id = ?
        GROUP BY o.order_id ORDER BY o.order_date DESC""", (customer_id,))
    net = [o for o in orders if o["status"] not in ("Cancelled", "Returned")]
    lifetime = sum(o["value"] for o in net)
    favourite = query(f"""
        SELECT category, ROUND(SUM(sales), 2) AS revenue FROM v_sales
        WHERE customer_id = ? AND {NET_STATUS_SQL}
        GROUP BY category ORDER BY revenue DESC LIMIT 1""", (customer_id,), one=True)
    first = min((o["order_date"] for o in net), default=None)
    last = max((o["order_date"] for o in net), default=None)
    tenure = (date.fromisoformat(last) - date.fromisoformat(first)).days if first else 0
    return {"info": info, "orders": orders, "lifetime_value": lifetime,
            "net_orders": len(net), "aov": lifetime / len(net) if net else 0,
            "first_order": first, "last_order": last, "tenure_days": tenure,
            "favourite_category": favourite["category"] if favourite else None}
