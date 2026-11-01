"""Rule-based business insights.

Each rule looks at an aggregate, compares it to a fixed business threshold and,
if it fires, produces a short finding with a recommended action. No models are
trained; every statement can be traced back to a SQL query on the page.
"""
from flask import current_app

from ..utils import fmt_inr, fmt_pct
from . import customers, inventory, products, profit, sales


def _insight(level, area, title, text, action=None, link=None):
    # level: positive | negative | warning | info
    return {"level": level, "area": area, "title": title, "text": text, "action": action, "link": link}


def generate(f):
    out = []
    kpi, prev = sales.kpis_with_change(f)
    if not kpi["orders"]:
        return [_insight("info", "Data", "No sales in this period",
                         "Widen the date range or clear the filters to see insights.")]

    # --- Revenue and profit momentum
    rev_change = kpi["change"]["revenue"]
    if rev_change is not None:
        if rev_change >= 0.05:
            out.append(_insight("positive", "Sales", f"Revenue up {fmt_pct(rev_change)}",
                                f"Revenue reached {fmt_inr(kpi['revenue'])} versus {fmt_inr(prev['revenue'])} "
                                f"in the previous {f.days} days.", link="sales.index"))
        elif rev_change <= -0.05:
            out.append(_insight("negative", "Sales", f"Revenue down {fmt_pct(abs(rev_change))}",
                                f"Revenue fell to {fmt_inr(kpi['revenue'])} from {fmt_inr(prev['revenue'])} "
                                f"in the previous {f.days} days.",
                                "Check which categories and regions drove the decline.", link="sales.index"))
    margin_change = kpi["change"]["margin"]
    if margin_change is not None and abs(margin_change) >= 0.01:
        direction = "improved" if margin_change > 0 else "slipped"
        out.append(_insight("positive" if margin_change > 0 else "warning", "Profit",
                            f"Profit margin {direction} {abs(margin_change) * 100:.1f} pts",
                            f"Margin is {fmt_pct(kpi['margin'])} now against {fmt_pct(prev['margin'])} before.",
                            None if margin_change > 0 else "Review discount levels and loss-making items.",
                            link="profit.index"))

    # --- Category concentration
    cats = sales.by_dimension(f, "category")
    if cats:
        top = cats[0]
        out.append(_insight("info", "Sales", f"{top['label']} leads with {fmt_pct(top['share'])} of revenue",
                            f"{top['label']} earned {fmt_inr(top['revenue'])} at a {fmt_pct(top['margin'])} margin.",
                            link="sales.index"))
        best_margin = max(cats, key=lambda c: c["margin"])
        if best_margin["label"] != top["label"] and best_margin["share"] < 0.25:
            out.append(_insight("positive", "Profit", f"{best_margin['label']} has the best margin",
                                f"{best_margin['label']} returns {fmt_pct(best_margin['margin'])} profit "
                                f"but only {fmt_pct(best_margin['share'])} of sales.",
                                "Promote it more: each extra sale here is worth more profit.",
                                link="profit.index"))

    # --- Regions
    regions = sales.by_dimension(f, "region")
    if len(regions) > 1 and not f.region:
        best, worst = regions[0], regions[-1]
        out.append(_insight("info", "Sales", f"{best['label']} is the strongest region",
                            f"{best['label']} brings {fmt_pct(best['share'])} of revenue; "
                            f"{worst['label']} is smallest at {fmt_pct(worst['share'])}.",
                            f"Test targeted campaigns in {worst['label']}.", link="sales.index"))

    # --- Discounts eating profit
    bands = profit.discount_bands(f)
    deep = next((b for b in bands if b["band"] == "Above 30%"), None)
    if deep and deep["margin"] < 0:
        out.append(_insight("negative", "Profit", "Discounts above 30% lose money",
                            f"Lines discounted above 30% sold {fmt_inr(deep['revenue'])} "
                            f"but lost {fmt_inr(abs(deep['profit']))} ({fmt_pct(deep['margin'])} margin).",
                            "Cap discounts at 30% or limit deep discounts to high-margin items.",
                            link="profit.index"))
    corr = profit.discount_margin_correlation(f)
    if corr and corr["r"] <= -0.4:
        out.append(_insight("warning", "Profit", "Higher discounts mean lower margins",
                            f"Discount and margin have a {corr['strength']} negative correlation "
                            f"(r = {corr['r']:.2f}) across {corr['n']:,} order lines.",
                            link="profit.index"))

    losers = profit.loss_making_products(f, limit=100)
    if losers:
        total_loss = sum(p["profit"] for p in losers)
        title = "1 product is sold at a loss" if len(losers) == 1 else f"{len(losers)} products are sold at a loss"
        out.append(_insight("negative", "Products", title,
                            f"Together they lost {fmt_inr(abs(total_loss))}. Worst: {losers[0]['product_name']} "
                            f"({fmt_inr(losers[0]['profit'])}).",
                            "Reprice, renegotiate supplier cost or stop discounting these items.",
                            link="profit.index"))

    # --- Pareto
    perf = products.performance(f)
    if perf:
        abc = products.abc_summary(perf)[0]
        out.append(_insight("info", "Products",
                            f"{fmt_pct(abc['product_share'])} of products make {fmt_pct(abc['revenue_share'])} of revenue",
                            f"{abc['products']} class-A products drive most sales (Pareto principle).",
                            "Prioritise stock availability and visibility for class-A items.",
                            link="products.index"))

    # --- Returns
    if kpi["return_rate"] >= current_app.config["HIGH_RETURN_RATE"]:
        worst = sales.return_rates(f, "category")[0]
        out.append(_insight("warning", "Sales", f"Return rate is high at {fmt_pct(kpi['return_rate'])}",
                            f"Returned orders were worth {fmt_inr(kpi['returned_value'])}. "
                            f"{worst['label']} has the highest return rate ({fmt_pct(worst['rate'])}).",
                            f"Improve size guides, photos and descriptions in {worst['label']}.",
                            link="sales.index"))

    # --- Inventory (snapshot, not date-filtered)
    stock = inventory.stock_status(f.category)
    inv = inventory.summary(stock)
    counts = inv["status_counts"]
    at_risk = counts["Out of Stock"] + counts["Low Stock"]
    if at_risk:
        a_items = {p["product_id"] for p in perf if p["abc"] == "A"}
        a_at_risk = sum(1 for s in stock if s["status"] in ("Out of Stock", "Low Stock")
                        and s["product_id"] in a_items)
        extra = f" {a_at_risk} of them are class-A best-sellers." if a_at_risk else ""
        out.append(_insight("negative" if a_at_risk else "warning", "Inventory",
                            f"{at_risk} products need restocking",
                            f"{counts['Out of Stock']} out of stock and {counts['Low Stock']} below the "
                            f"reorder point.{extra}",
                            f"Suggested purchase order: {fmt_inr(inv['reorder_cost'])}.",
                            link="inventory.index"))
    if counts["Dead Stock"]:
        out.append(_insight("warning", "Inventory", f"{fmt_inr(inv['status_values']['Dead Stock'])} tied up in dead stock",
                            f"{counts['Dead Stock']} products have stock but no sales in the last "
                            f"{current_app.config['DEMAND_WINDOW_DAYS']} days.",
                            "Clear with bundles or markdowns, then stop reordering.", link="inventory.index"))
    if counts["Overstock"]:
        out.append(_insight("info", "Inventory", f"{counts['Overstock']} products are overstocked",
                            f"{fmt_inr(inv['status_values']['Overstock'])} of stock covers more than "
                            f"{current_app.config['OVERSTOCK_DAYS']} days of demand.",
                            "Pause purchase orders for these items.", link="inventory.index"))

    # --- Customers
    cs = customers.summary(f)
    if cs["customers"]:
        level = "positive" if cs["repeat_rate"] >= 0.4 else "warning"
        out.append(_insight(level, "Customers", f"{fmt_pct(cs['repeat_rate'])} of customers are repeat buyers",
                            f"{cs['repeat_customers']:,} of {cs['customers']:,} customers ordered more than once; "
                            f"{cs['new_customers']:,} were new.",
                            None if level == "positive" else "Introduce a loyalty programme or second-order coupon.",
                            link="customers.index"))
    _, segments = customers.rfm(f)
    risk = next((s for s in segments if s["segment"] == "At Risk"), None)
    if risk:
        out.append(_insight("warning", "Customers", f"{risk['customers']} valuable customers are at risk",
                            f"They spent {fmt_inr(risk['revenue'])} but haven't ordered for "
                            f"{risk['avg_recency']:.0f} days on average.",
                            risk["action"] + ".", link="customers.index"))

    # --- Timing
    weekdays = sales.by_weekday(f)
    if weekdays:
        best_day = max(weekdays, key=lambda d: d["avg_daily_revenue"])
        out.append(_insight("info", "Sales", f"{best_day['label']} is the best sales day",
                            f"Average revenue on a {best_day['label']} is {fmt_inr(best_day['avg_daily_revenue'])}.",
                            "Schedule campaigns and flash sales to land on peak days.", link="sales.index"))
    payments = sales.by_dimension(f, "payment_method")
    if payments:
        p = payments[0]
        out.append(_insight("info", "Sales", f"{p['label']} is the top payment method",
                            f"{fmt_pct(p['share'])} of revenue is paid via {p['label']}.", link="sales.index"))
    return out
