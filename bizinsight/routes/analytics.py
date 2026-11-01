"""Read-only analytics pages: dashboard, sales, profit, products, customers, insights."""
from flask import Blueprint, abort, render_template, request

from ..analytics import customers as cust
from ..analytics import insights as ins
from ..analytics import inventory as inv
from ..analytics import products as prod
from ..analytics import profit as prof
from ..analytics import sales
from ..analytics.filters import Filters, filter_options
from ..utils import login_required

dashboard_bp = Blueprint("dashboard", __name__)
sales_bp = Blueprint("sales", __name__, url_prefix="/sales")
profit_bp = Blueprint("profit", __name__, url_prefix="/profit")
products_bp = Blueprint("products", __name__, url_prefix="/products")
customers_bp = Blueprint("customers", __name__, url_prefix="/customers")
blueprints = [dashboard_bp, sales_bp, profit_bp, products_bp, customers_bp]


def render(template, f, **context):
    return render_template(template, f=f, options=filter_options(), **context)


@dashboard_bp.route("/")
@login_required
def index():
    f = Filters.from_request(request.args)
    kpi, _ = sales.kpis_with_change(f)
    stock = inv.stock_status(f.category)
    return render("dashboard.html", f,
                  kpi=kpi,
                  trend=sales.trend(f),
                  categories=sales.by_dimension(f, "category"),
                  regions=sales.by_dimension(f, "region"),
                  top_products=prod.performance(f)[:5],
                  inventory=inv.summary(stock),
                  insights=ins.generate(f)[:6],
                  recent=sales.recent_orders(f))


@dashboard_bp.route("/insights")
@login_required
def insights():
    f = Filters.from_request(request.args)
    return render("insights.html", f, insights=ins.generate(f))


@sales_bp.route("/")
@login_required
def index():
    f = Filters.from_request(request.args)
    granularity = request.args.get("g") or sales.auto_granularity(f)
    if granularity not in ("day", "week", "month", "quarter", "year"):
        granularity = "month"
    kpi, _ = sales.kpis_with_change(f)
    return render("sales.html", f,
                  kpi=kpi, granularity=granularity,
                  trend=sales.trend(f, granularity),
                  categories=sales.by_dimension(f, "category"),
                  sub_categories=sales.by_dimension(f, "sub_category"),
                  regions=sales.by_dimension(f, "region"),
                  states=sales.by_dimension(f, "state", limit=10),
                  payments=sales.by_dimension(f, "payment_method"),
                  ship_modes=sales.by_dimension(f, "ship_mode"),
                  segments=sales.by_dimension(f, "segment"),
                  weekdays=sales.by_weekday(f),
                  returns=sales.return_rates(f, "category"),
                  statuses=sales.by_dimension(f, "status", net=False),
                  monthly=sales.monthly_summary(f),
                  order_stats=sales.order_value_stats(f))


@profit_bp.route("/")
@login_required
def index():
    f = Filters.from_request(request.args)
    kpi, _ = sales.kpis_with_change(f)
    return render("profit.html", f,
                  kpi=kpi,
                  bridge=prof.profit_bridge(f),
                  trend=sales.trend(f, "month"),
                  categories=sales.by_dimension(f, "category"),
                  sub_categories=sorted(sales.by_dimension(f, "sub_category"), key=lambda r: r["profit"]),
                  regions=sales.by_dimension(f, "region"),
                  bands=prof.discount_bands(f),
                  correlation=prof.discount_margin_correlation(f),
                  matrix=prof.category_discount_matrix(f),
                  losers=prof.loss_making_products(f),
                  loss_lines=prof.loss_lines_summary(f))


@products_bp.route("/")
@login_required
def index():
    f = Filters.from_request(request.args)
    rows = prod.performance(f)
    return render("products.html", f,
                  rows=rows,
                  abc=prod.abc_summary(rows),
                  top=rows[:10],
                  by_profit=sorted(rows, key=lambda r: r["profit"], reverse=True)[:10],
                  unsold=prod.unsold_products(f))


@products_bp.route("/<product_id>")
@login_required
def detail(product_id):
    info = prod.product_info(product_id)
    if not info:
        abort(404)
    f = Filters.from_request(request.args)
    stock = next((s for s in inv.stock_status() if s["product_id"] == product_id), None)
    return render("product_detail.html", f, info=info, stock=stock, **prod.product_detail(f, product_id))


@customers_bp.route("/")
@login_required
def index():
    f = Filters.from_request(request.args)
    rfm_df, segments = cust.rfm(f)
    selected = request.args.get("segment", "")
    listing = rfm_df
    if selected and not rfm_df.empty:
        listing = rfm_df[rfm_df["rfm_segment"] == selected]
    return render("customers.html", f,
                  summary=cust.summary(f),
                  segments=segments,
                  selected_segment=selected,
                  rfm_rows=listing.head(50).to_dict("records") if not rfm_df.empty else [],
                  new_vs_returning=cust.new_vs_returning(f),
                  cohort=cust.cohort_retention(f),
                  demo=cust.demographics(f),
                  cities=sales.by_dimension(f, "city", limit=10),
                  top=cust.top_customers(f))


@customers_bp.route("/<customer_id>")
@login_required
def detail(customer_id):
    profile = cust.customer_profile(customer_id)
    if not profile:
        abort(404)
    f = Filters.from_request(request.args)
    return render("customer_detail.html", f, p=profile)
