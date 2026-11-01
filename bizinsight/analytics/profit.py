"""Profitability analysis: margins, discount impact and loss makers."""
import statistics

from ..db import cached_query as query

DISCOUNT_BAND_SQL = """
    CASE WHEN discount = 0     THEN 'No discount'
         WHEN discount <= 0.10 THEN '1-10%'
         WHEN discount <= 0.20 THEN '11-20%'
         WHEN discount <= 0.30 THEN '21-30%'
         ELSE 'Above 30%' END"""


def profit_bridge(f):
    """Gross sales -> discounts -> net sales -> cost of goods -> profit."""
    where, params = f.where()
    row = query(f"""
        SELECT COALESCE(SUM(quantity * unit_price), 0) AS gross,
               COALESCE(SUM(sales), 0)  AS net,
               COALESCE(SUM(cost), 0)   AS cost,
               COALESCE(SUM(profit), 0) AS profit
        FROM v_sales {where}""", params, one=True)
    row["discounts"] = row["gross"] - row["net"]
    row["discount_pct"] = row["discounts"] / row["gross"] if row["gross"] else 0
    return row


def discount_bands(f):
    where, params = f.where()
    rows = query(f"""
        SELECT {DISCOUNT_BAND_SQL} AS band,
               MIN(discount) AS sort_key,
               COUNT(*) AS lines,
               ROUND(SUM(sales), 2)  AS revenue,
               ROUND(SUM(profit), 2) AS profit,
               SUM(quantity) AS units
        FROM v_sales {where}
        GROUP BY band ORDER BY sort_key""", params)
    for r in rows:
        r["margin"] = r["profit"] / r["revenue"] if r["revenue"] else 0
    return rows


def discount_margin_correlation(f):
    """Pearson correlation between line discount and line profit margin."""
    where, params = f.where(extra="sales > 0")
    rows = query(f"SELECT discount, profit / sales AS margin FROM v_sales {where}", params)
    if len(rows) < 3:
        return None
    discounts = [r["discount"] for r in rows]
    margins = [r["margin"] for r in rows]
    try:
        r = statistics.correlation(discounts, margins)
    except statistics.StatisticsError:
        return None
    strength = ("very strong" if abs(r) >= 0.8 else "strong" if abs(r) >= 0.6 else
                "moderate" if abs(r) >= 0.4 else "weak" if abs(r) >= 0.2 else "negligible")
    return {"r": r, "strength": strength, "direction": "negative" if r < 0 else "positive",
            "n": len(rows)}


def loss_making_products(f, limit=15):
    where, params = f.where()
    rows = query(f"""
        SELECT product_id, product_name, category,
               ROUND(SUM(sales), 2)  AS revenue,
               ROUND(SUM(profit), 2) AS profit,
               SUM(quantity) AS units,
               AVG(discount) AS avg_discount
        FROM v_sales {where}
        GROUP BY product_id HAVING SUM(profit) < 0
        ORDER BY profit ASC LIMIT ?""", params + [limit])
    for r in rows:
        r["margin"] = r["profit"] / r["revenue"] if r["revenue"] else 0
    return rows


def loss_lines_summary(f):
    """How much profit leaks through individual order lines sold at a loss."""
    where, params = f.where(extra="profit < 0")
    return query(f"""
        SELECT COUNT(*) AS lines, COALESCE(SUM(profit), 0) AS loss,
               COALESCE(AVG(discount), 0) AS avg_discount
        FROM v_sales {where}""", params, one=True)


def category_discount_matrix(f):
    """Margin for every category x discount band (heatmap)."""
    where, params = f.where()
    rows = query(f"""
        SELECT category, {DISCOUNT_BAND_SQL} AS band,
               SUM(sales) AS revenue, SUM(profit) AS profit
        FROM v_sales {where}
        GROUP BY category, band""", params)
    bands = ["No discount", "1-10%", "11-20%", "21-30%", "Above 30%"]
    categories = sorted({r["category"] for r in rows})
    cells = {(r["category"], r["band"]): (r["profit"] / r["revenue"] if r["revenue"] else None)
             for r in rows}
    return {"bands": bands, "rows": [
        {"category": c, "cells": [cells.get((c, b)) for b in bands]} for c in categories]}
