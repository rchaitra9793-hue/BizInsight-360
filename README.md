# BizInsight 360 – E-Commerce Sales, Profit & Inventory Analytics Platform

A web-based Business Intelligence platform that helps an e-commerce business understand its
**sales, revenue, profit, inventory, products and customers** through interactive dashboards,
rule-based insights and downloadable reports.

All analysis uses **SQL queries, descriptive statistics and business rules**. No AI or machine
learning models are trained or used.

---

## Features

| Module | What it does |
|---|---|
| **Overview dashboard** | 9 KPIs with % change vs the previous period, revenue/profit trend, category & region split, top products, inventory health, key insights, recent orders |
| **Sales analysis** | Day/week/month/quarter trends with 3-period moving average, MoM & YoY growth table, category, sub-category, region, state, payment method, shipping mode, segment, day-of-week, return rates, order-value statistics (mean, median, std dev, percentiles, histogram) |
| **Profit analysis** | Profit bridge (gross sales → discounts → net → COGS → profit), margin trend, margin by discount band, Pearson correlation of discount vs margin, category × discount heatmap, loss-making products |
| **Product analysis** | ABC / Pareto classification, Pareto curve, top 10 by revenue or profit, full product table with search, unsold products, per-product detail page |
| **Inventory analytics** | Stock value, turnover, days of inventory, status per product (Out of Stock / Low / Dead / Overstock / Healthy), days of cover, reorder suggestions with cost, dead stock, stock movement log, one-click restock |
| **Customer analysis** | RFM segmentation (7 segments with recommended actions), new vs returning customers, cohort retention heatmap, age groups, gender & category preference, top cities, top customers, customer profile pages |
| **Insights** | 15+ rule-based findings with recommended actions (e.g. "Discounts above 30% lose money") |
| **Reports** | CSV / Excel export of 7 reports, a complete multi-sheet Excel workbook, and a printable executive summary (Save as PDF) |
| **Data management** | CSV import with row-level validation & error report, downloadable templates, product catalogue CRUD, order entry (reduces stock), order status changes (returns restock items), database reset |
| **Users** | Login / registration, hashed passwords, Admin and Analyst (read-only) roles, CSRF protection |
| **UI** | Responsive layout, light & dark mode, colour-blind-safe chart palette |

Every analytics page shares one filter bar: **date range** (with 30D / 90D / YTD / 12M / All presets), **region** and **category**.

---

## Technology stack (all free)

| Layer | Technology |
|---|---|
| Backend | Python 3.10+ · Flask |
| Database | SQLite (built into Python, no server needed) |
| Data processing | SQL (aggregations, CTEs, CASE, views), pandas (CSV import, RFM quintiles, cohorts, Excel export), Python `statistics` |
| Frontend | Jinja2 templates · Bootstrap 5 · Bootstrap Icons · Chart.js 4 |
| Testing | pytest (47 automated tests) |

---

## Getting started

```bash
# 1. Create a virtual environment and install dependencies
python -m venv .venv
.venv\Scripts\activate            # Windows
# source .venv/bin/activate       # macOS / Linux
pip install -r requirements.txt

# 2. Run the app
python app.py
```

Open **http://127.0.0.1:5000** and sign in with the demo administrator:

- Email: `admin@bizinsight.com`
- Password: `admin123`

On first run the database (`instance/bizinsight.db`) is created and the sample dataset is
loaded automatically (takes a few seconds). Change the admin password from the **Account** page.

Useful commands:

```bash
flask --app app init-db           # recreate tables and reload the sample data
flask --app app init-db --empty   # start with an empty database
python scripts/generate_data.py   # regenerate the sample CSV files
python -m pytest tests            # run the test suite
```

> The UI loads Bootstrap and Chart.js from a CDN, so the browser needs an internet connection.

---

## Sample dataset

`scripts/generate_data.py` creates a realistic, reproducible dataset (fixed random seed) for an
Indian e-commerce store, so there are no licensing issues:

- **24 months** of data (Nov 2024 – Oct 2026), **~9,500 orders**, **~15,000 order lines**
- **104 products** in 6 categories, 28 cities across 5 regions, 1,500 customers
- Built-in business patterns: Diwali/festive peaks in Oct–Nov, weekend uplift, sale days,
  year-on-year growth, loyal vs one-time customers, higher return rates in Fashion, deep
  discounts that cause losses, discontinued products (dead stock) and stock-outs

### Using your own or a public dataset

Download `sales_template.csv` from **Data import** and fill it in, or map a public dataset
(for example the Kaggle *Superstore* or *Brazilian E-Commerce* datasets) to these columns:

| Required | Optional |
|---|---|
| order_id, order_date, customer_id, customer_name, product_id, product_name, category, quantity, unit_price, unit_cost | ship_date, status, ship_mode, payment_method, gender, age, city, state, region, segment, sub_category, discount |

Each row is validated (dates, numbers, ranges, status values). Valid rows are imported, invalid
rows are listed with their row number and reason, and re-importing a file updates existing rows
instead of duplicating them.

---

## Project structure

```
BizInsight 360/
├── app.py                     # entry point: python app.py
├── config.py                  # settings and business-rule thresholds
├── requirements.txt
├── data/                      # sample CSV files (generated)
├── scripts/generate_data.py   # sample data generator
├── tests/test_app.py          # automated tests
└── bizinsight/
    ├── __init__.py            # Flask application factory
    ├── schema.sql             # tables, indexes, triggers, v_sales view
    ├── db.py                  # connection, query helpers, result cache, seeding
    ├── importer.py            # CSV validation & import
    ├── utils.py               # ₹ formatting, auth decorators, CSRF
    ├── analytics/             # all business logic (SQL + statistics)
    │   ├── filters.py         #   shared date/region/category filters
    │   ├── sales.py           #   KPIs, trends, breakdowns, growth, statistics
    │   ├── profit.py          #   profit bridge, discount analysis, loss makers
    │   ├── products.py        #   product performance, ABC classification
    │   ├── inventory.py       #   stock status, days of cover, reorder rules
    │   ├── customers.py       #   RFM, cohorts, demographics
    │   └── insights.py        #   rule-based insight generator
    ├── routes/                # Flask blueprints (pages and actions)
    ├── templates/             # Jinja2 HTML templates
    └── static/                # CSS and chart helpers
```

---

## Database design

```
customers (customer_id PK, name, gender, age, city, state, region, segment)
products  (product_id PK, name, category, sub_category, unit_cost, unit_price, stock_qty, reorder_level, supplier)
orders    (order_id PK, order_date, ship_date, customer_id FK, status, ship_mode, payment_method)
order_items (id PK, order_id FK, product_id FK, quantity, unit_price, unit_cost, discount, sales, cost, profit)
stock_movements (id PK, product_id FK, change_qty, reason, user_id FK, created_at)
users (id PK, name, email UNIQUE, password_hash, role)
import_log (id PK, filename, import_type, rows_total, rows_imported, rows_rejected, user_id, imported_at)
v_sales  -- VIEW joining order_items + orders + customers + products: one row per order line
```

`sales`, `cost` and `profit` are stored per order line at the moment of sale, so historical
reports stay correct even if a product's price changes later.

---

## Business definitions & formulas

| Measure | Definition |
|---|---|
| Net revenue | Σ quantity × unit_price × (1 − discount), **excluding Cancelled and Returned orders** |
| Gross profit | Net revenue − Σ quantity × unit_cost |
| Profit margin | Gross profit ÷ net revenue |
| Average order value (AOV) | Net revenue ÷ number of orders |
| Return rate | Returned orders ÷ all orders |
| Previous period | The same number of days immediately before the selected range |
| MoM / YoY growth | (this month − previous month) ÷ previous month; same month last year for YoY |
| ABC class | Products ranked by revenue: A = first 80% of cumulative revenue, B = next 15%, C = last 5% |
| RFM | Recency, Frequency, Monetary each split into quintiles (score 1–5), mapped to segments by fixed rules |
| Cohort retention | % of customers whose first order was in month M who ordered again in month M + n |
| Avg daily demand | Units sold in the last 90 days ÷ 90 |
| Days of cover | Stock on hand ÷ avg daily demand |
| Reorder point | max(reorder level, avg daily demand × (lead time 7 d + safety stock 7 d)) |
| Suggested order qty | avg daily demand × (lead time + safety + 30-day review period) − stock on hand |
| Inventory turnover | Annualised cost of goods sold ÷ current stock value (at cost) |
| Dead stock | Stock on hand but no sales in the last 90 days |
| Overstock | More than 180 days of cover |

All thresholds can be changed in `config.py`.

---

## User roles

| Role | Can do |
|---|---|
| **Admin** | Everything: view analytics, import data, edit products, record orders, change order status, adjust stock, reset the database, manage user roles |
| **Analyst** | View all dashboards, insights and reports, download exports (read-only) |

New registrations are Analysts; an Admin can promote them from **Account → Users**.

---

## Possible future enhancements

- Scheduled email of the executive summary
- Supplier and purchase-order module
- Multi-store / multi-currency support
- Moving the database to PostgreSQL or MySQL for multi-user deployment
