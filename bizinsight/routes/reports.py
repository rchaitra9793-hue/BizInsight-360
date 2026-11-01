"""Downloadable reports (CSV / Excel) and the printable executive summary."""
import io
from datetime import datetime

import pandas as pd
from flask import Blueprint, Response, abort, render_template, request

from ..analytics import customers as cust
from ..analytics import insights as ins
from ..analytics import inventory as inv
from ..analytics import products as prod
from ..analytics import profit as prof
from ..analytics import sales
from ..analytics.filters import Filters, filter_options
from ..db import query
from ..utils import login_required

bp = Blueprint("reports", __name__, url_prefix="/reports")

REPORTS = {
    "transactions": "Sales transactions (every order line)",
    "monthly": "Monthly sales summary with MoM / YoY growth",
    "category": "Category & sub-category performance",
    "region": "Region & state performance",
    "products": "Product performance with ABC class",
    "customers": "Customer RFM segmentation",
    "inventory": "Inventory status & reorder suggestions",
}


def _frame(kind, f):
    if kind == "transactions":
        where, params = f.where(net=False)
        return pd.DataFrame(query(f"""
            SELECT order_id, order_date, status, customer_id, customer_name, city, state, region, segment,
                   product_id, product_name, category, sub_category, quantity, unit_price, discount,
                   sales, cost, profit, payment_method, ship_mode
            FROM v_sales {where} ORDER BY order_date, order_id""", params))
    if kind == "monthly":
        df = pd.DataFrame(sales.monthly_summary(f))
        return df.rename(columns={"mom": "mom_growth", "yoy": "yoy_growth"})
    if kind == "category":
        cat = pd.DataFrame(sales.by_dimension(f, "category")).assign(level="Category")
        sub = pd.DataFrame(sales.by_dimension(f, "sub_category")).assign(level="Sub-category")
        return pd.concat([cat, sub], ignore_index=True)
    if kind == "region":
        reg = pd.DataFrame(sales.by_dimension(f, "region")).assign(level="Region")
        st = pd.DataFrame(sales.by_dimension(f, "state")).assign(level="State")
        return pd.concat([reg, st], ignore_index=True)
    if kind == "products":
        return pd.DataFrame(prod.performance(f))
    if kind == "customers":
        df, _ = cust.rfm(f)
        return df
    if kind == "inventory":
        df = pd.DataFrame(inv.stock_status(f.category))
        return df.drop(columns=["cogs_window"], errors="ignore")
    abort(404)


@bp.route("/")
@login_required
def index():
    f = Filters.from_request(request.args)
    return render_template("reports.html", f=f, options=filter_options(), reports=REPORTS)


@bp.route("/download")
@login_required
def download():
    f = Filters.from_request(request.args)
    kind = request.args.get("report", "transactions")
    fmt = request.args.get("format", "csv")
    stamp = datetime.now().strftime("%Y%m%d")

    if kind == "workbook":
        buf = io.BytesIO()
        with pd.ExcelWriter(buf, engine="openpyxl") as writer:
            for key in REPORTS:
                if key == "transactions":
                    continue
                _round(_frame(key, f)).to_excel(writer, sheet_name=key.title(), index=False)
        return _send(buf.getvalue(), f"bizinsight_workbook_{stamp}.xlsx", "xlsx")

    if kind not in REPORTS:
        abort(404)
    df = _round(_frame(kind, f))
    if fmt == "xlsx":
        buf = io.BytesIO()
        df.to_excel(buf, index=False, sheet_name=kind.title(), engine="openpyxl")
        return _send(buf.getvalue(), f"bizinsight_{kind}_{stamp}.xlsx", "xlsx")
    return _send(df.to_csv(index=False).encode("utf-8-sig"), f"bizinsight_{kind}_{stamp}.csv", "csv")


def _round(df):
    return df.round(4) if not df.empty else df


def _send(data, filename, fmt):
    mime = ("application/vnd.openxmlformats-officedocument.spreadsheetml.sheet" if fmt == "xlsx"
            else "text/csv")
    return Response(data, mimetype=mime, headers={"Content-Disposition": f"attachment; filename={filename}"})


@bp.route("/summary")
@login_required
def summary():
    f = Filters.from_request(request.args)
    kpi, prev = sales.kpis_with_change(f)
    rows = prod.performance(f)
    stock = inv.stock_status(f.category)
    _, segments = cust.rfm(f)
    return render_template("report_summary.html", f=f, kpi=kpi, prev=prev,
                           generated=datetime.now().strftime("%d %b %Y, %I:%M %p"),
                           categories=sales.by_dimension(f, "category"),
                           regions=sales.by_dimension(f, "region"),
                           monthly=sales.monthly_summary(f)[-12:],
                           top=rows[:10], abc=prod.abc_summary(rows),
                           bridge=prof.profit_bridge(f), losers=prof.loss_making_products(f, 5),
                           inventory=inv.summary(stock), segments=segments,
                           customers=cust.summary(f), insights=ins.generate(f))
