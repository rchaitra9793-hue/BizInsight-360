"""Product performance and ABC (Pareto) classification."""
from ..db import cached_query as query

# Cumulative revenue share boundaries for ABC classes
ABC_A = 0.80
ABC_B = 0.95


def performance(f):
    """One row per product sold in the period, ranked by revenue, with its ABC class."""
    where, params = f.where()
    rows = query(f"""
        SELECT product_id, product_name, category, sub_category,
               ROUND(SUM(sales), 2)  AS revenue,
               ROUND(SUM(profit), 2) AS profit,
               SUM(quantity) AS units,
               COUNT(DISTINCT order_id) AS orders,
               AVG(discount) AS avg_discount
        FROM v_sales {where}
        GROUP BY product_id ORDER BY revenue DESC""", params)

    where_all, params_all = f.where(net=False)
    returns = {r["product_id"]: r for r in query(f"""
        SELECT product_id,
               COUNT(DISTINCT order_id) AS all_orders,
               COUNT(DISTINCT CASE WHEN status = 'Returned' THEN order_id END) AS returned
        FROM v_sales {where_all} GROUP BY product_id""", params_all)}
    stock = {r["product_id"]: r["stock_qty"] for r in query("SELECT product_id, stock_qty FROM products")}

    total = sum(r["revenue"] for r in rows) or 1
    running = 0.0
    for rank, r in enumerate(rows, start=1):
        running += r["revenue"]
        r["rank"] = rank
        r["share"] = r["revenue"] / total
        r["cum_share"] = running / total
        # A product belongs to class A if it is needed to reach the first 80% of revenue
        before = (running - r["revenue"]) / total
        r["abc"] = "A" if before < ABC_A else "B" if before < ABC_B else "C"
        r["margin"] = r["profit"] / r["revenue"] if r["revenue"] else 0
        ret = returns.get(r["product_id"])
        r["return_rate"] = ret["returned"] / ret["all_orders"] if ret and ret["all_orders"] else 0
        r["stock_qty"] = stock.get(r["product_id"], 0)
    return rows


def abc_summary(rows):
    total_rev = sum(r["revenue"] for r in rows) or 1
    out = []
    for cls, note in (("A", "Top sellers - never let these go out of stock"),
                      ("B", "Steady contributors - review regularly"),
                      ("C", "Long tail - candidates for clearance or delisting")):
        members = [r for r in rows if r["abc"] == cls]
        revenue = sum(r["revenue"] for r in members)
        out.append({"cls": cls, "products": len(members),
                    "product_share": len(members) / len(rows) if rows else 0,
                    "revenue": revenue, "revenue_share": revenue / total_rev, "note": note})
    return out


def unsold_products(f):
    """Catalogue items with no sales at all in the period."""
    where, params = f.where()
    cat_clause = "AND p.category = ?" if f.category else ""
    extra = [f.category] if f.category else []
    return query(f"""
        SELECT p.product_id, p.name, p.category, p.stock_qty, p.unit_price
        FROM products p
        WHERE p.product_id NOT IN (SELECT product_id FROM v_sales {where}) {cat_clause}
        ORDER BY p.category, p.name""", params + extra)


def product_info(product_id):
    return query("SELECT * FROM products WHERE product_id = ?", (product_id,), one=True)


def product_detail(f, product_id):
    """KPIs, trend and breakdowns for a single product."""
    where, params = f.where(extra="product_id = ?")
    params = params + [product_id]
    kpi = query(f"""
        SELECT COALESCE(SUM(sales), 0) AS revenue, COALESCE(SUM(profit), 0) AS profit,
               COALESCE(SUM(quantity), 0) AS units, COUNT(DISTINCT order_id) AS orders,
               COUNT(DISTINCT customer_id) AS customers, COALESCE(AVG(discount), 0) AS avg_discount,
               MIN(order_date) AS first_sale, MAX(order_date) AS last_sale
        FROM v_sales {where}""", params, one=True)
    kpi["margin"] = kpi["profit"] / kpi["revenue"] if kpi["revenue"] else 0
    regions = query(f"""
        SELECT region AS label, ROUND(SUM(sales), 2) AS revenue, SUM(quantity) AS units
        FROM v_sales {where} GROUP BY region ORDER BY revenue DESC""", params)
    where_all, params_all = f.where(net=False, extra="product_id = ?")
    statuses = query(f"""
        SELECT status AS label, COUNT(DISTINCT order_id) AS orders
        FROM v_sales {where_all} GROUP BY status ORDER BY orders DESC""", params_all + [product_id])
    return {"kpi": kpi, "regions": regions, "statuses": statuses,
            "trend": _product_trend(f, product_id)}


def _product_trend(f, product_id):
    where, params = f.where(extra="product_id = ?")
    return query(f"""
        SELECT strftime('%Y-%m', order_date) AS period, ROUND(SUM(sales), 2) AS revenue,
               ROUND(SUM(profit), 2) AS profit, SUM(quantity) AS units
        FROM v_sales {where} GROUP BY period ORDER BY period""", params + [product_id])
