"""CSV import with row-level validation for sales transactions and the product catalogue."""
import io
from dataclasses import dataclass, field

import pandas as pd

SALES_REQUIRED = ["order_id", "order_date", "customer_id", "customer_name", "product_id",
                  "product_name", "category", "quantity", "unit_price", "unit_cost"]
SALES_OPTIONAL = ["ship_date", "status", "ship_mode", "payment_method", "gender", "age", "city",
                  "state", "region", "segment", "sub_category", "discount"]

PRODUCT_REQUIRED = ["product_id", "name", "category", "unit_cost", "unit_price"]
PRODUCT_OPTIONAL = ["sub_category", "stock_qty", "reorder_level", "supplier"]

VALID_STATUS = {"Delivered", "Shipped", "Cancelled", "Returned"}
STATUS_ALIASES = {"Canceled": "Cancelled", "Complete": "Delivered", "Completed": "Delivered",
                  "Return": "Returned", "In Transit": "Shipped"}

SALES_EXAMPLE = [
    ["ORD-900001", "2026-01-15", "2026-01-19", "Delivered", "Standard", "UPI", "C90001",
     "Asha Kumar", "Female", "29", "Pune", "Maharashtra", "West", "Consumer", "P9001",
     "Sample Wireless Earbuds", "Electronics", "Audio", "2", "1999", "1100", "0.10"],
    ["ORD-900001", "2026-01-15", "2026-01-19", "Delivered", "Standard", "UPI", "C90001",
     "Asha Kumar", "Female", "29", "Pune", "Maharashtra", "West", "Consumer", "P9002",
     "Sample USB-C Cable", "Electronics", "Accessories", "1", "299", "120", "0"],
]
PRODUCT_EXAMPLE = [
    ["P9001", "Sample Wireless Earbuds", "Electronics", "Audio", "1100", "1999", "40", "10",
     "Sample Supplier Pvt Ltd"],
]


class ImportFailed(Exception):
    """The file cannot be imported at all (unreadable, wrong columns, empty)."""


@dataclass
class ImportResult:
    total: int = 0
    imported: int = 0
    rejected: int = 0
    errors: list = field(default_factory=list)   # first N "Row x: reason" messages


SALES_TEMPLATE_COLUMNS = [
    "order_id", "order_date", "ship_date", "status", "ship_mode", "payment_method",
    "customer_id", "customer_name", "gender", "age", "city", "state", "region", "segment",
    "product_id", "product_name", "category", "sub_category", "quantity", "unit_price",
    "unit_cost", "discount"]
PRODUCT_TEMPLATE_COLUMNS = [
    "product_id", "name", "category", "sub_category", "unit_cost", "unit_price",
    "stock_qty", "reorder_level", "supplier"]


def template_csv(kind):
    if kind == "sales":
        header, rows = SALES_TEMPLATE_COLUMNS, SALES_EXAMPLE
    else:
        header, rows = PRODUCT_TEMPLATE_COLUMNS, PRODUCT_EXAMPLE
    out = io.StringIO()
    pd.DataFrame(rows, columns=header).to_csv(out, index=False)
    return out.getvalue()


def _read_csv(fileobj, required, optional):
    raw = fileobj.read()
    if not raw:
        raise ImportFailed("The file is empty.")
    df = None
    for encoding in ("utf-8-sig", "latin-1"):
        try:
            df = pd.read_csv(io.BytesIO(raw), dtype=str, keep_default_na=False, encoding=encoding)
            break
        except UnicodeDecodeError:
            continue
        except pd.errors.ParserError as exc:
            raise ImportFailed(f"Could not parse CSV: {exc}") from exc
    if df is None:
        raise ImportFailed("Could not decode the file. Save it as UTF-8 CSV.")

    df.columns = [str(c).strip().lower().replace(" ", "_").replace("-", "_") for c in df.columns]
    missing = [c for c in required if c not in df.columns]
    if missing:
        raise ImportFailed("Missing required column(s): " + ", ".join(missing))
    if df.empty:
        raise ImportFailed("The file has a header but no data rows.")
    for col in optional:
        if col not in df.columns:
            df[col] = ""
    df = df[required + optional].copy()
    for col in df.columns:
        df[col] = df[col].astype(str).str.strip()
    return df


class _Validator:
    """Collects the first error found on each row."""

    def __init__(self, df):
        self.df = df
        self.errors = pd.Series("", index=df.index, dtype=object)

    def flag(self, mask, message):
        mask = mask & (self.errors == "")
        self.errors[mask] = message

    def required(self, columns):
        for col in columns:
            self.flag(self.df[col] == "", f"'{col}' is empty")

    def number(self, col, minimum=None, integer=False, default=None):
        """Parse a numeric column. Empty cells become `default` (or stay NaN if None)."""
        text = self.df[col]
        if default is not None:
            text = text.mask(text == "", str(default))
        values = pd.to_numeric(text, errors="coerce")
        present = values.notna()
        self.flag(~present & (text != ""), f"'{col}' is not a number")
        if integer:
            self.flag(present & (values % 1 != 0), f"'{col}' must be a whole number")
        if minimum is not None:
            self.flag(present & (values < minimum), f"'{col}' must be >= {minimum}")
        return values

    def messages(self, limit=25):
        bad = self.errors[self.errors != ""]
        # +2: header row and 1-based numbering, so numbers match the spreadsheet
        return [f"Row {i + 2}: {msg}" for i, msg in bad.head(limit).items()]


def _parse_dates(series):
    parsed = pd.to_datetime(series, errors="coerce", format="%Y-%m-%d")
    retry = parsed.isna() & (series != "")
    if retry.any():
        parsed[retry] = pd.to_datetime(series[retry], errors="coerce", dayfirst=True, format="mixed")
    return parsed


def _log(db, filename, kind, result, user_id):
    db.execute(
        "INSERT INTO import_log (filename, import_type, rows_total, rows_imported, rows_rejected, user_id)"
        " VALUES (?, ?, ?, ?, ?, ?)",
        (filename, kind, result.total, result.imported, result.rejected, user_id),
    )


def import_sales(db, fileobj, filename, user_id=None):
    df = _read_csv(fileobj, SALES_REQUIRED, SALES_OPTIONAL)
    v = _Validator(df)
    v.required(SALES_REQUIRED)

    order_date = _parse_dates(df["order_date"])
    v.flag(order_date.isna() & (df["order_date"] != ""), "'order_date' is not a valid date")
    ship_date = _parse_dates(df["ship_date"])
    v.flag(ship_date.isna() & (df["ship_date"] != ""), "'ship_date' is not a valid date")
    v.flag(ship_date.notna() & order_date.notna() & (ship_date < order_date),
           "'ship_date' is before 'order_date'")

    quantity = v.number("quantity", minimum=1, integer=True)
    unit_price = v.number("unit_price", minimum=0)
    unit_cost = v.number("unit_cost", minimum=0)
    age = v.number("age", minimum=0, integer=True)

    discount = v.number("discount", minimum=0, default=0)
    discount = discount.where(discount < 1, discount / 100)   # accept "15" as 15%
    v.flag(discount.notna() & (discount >= 1), "'discount' must be below 100%")

    status = df["status"].replace("", "Delivered").str.title().replace(STATUS_ALIASES)
    v.flag(~status.isin(VALID_STATUS), "'status' must be Delivered, Shipped, Cancelled or Returned")

    result = ImportResult(total=len(df))
    ok = v.errors == ""
    result.rejected = int((~ok).sum())
    result.errors = v.messages()

    clean = df[ok].copy()
    clean["order_date"] = order_date[ok].dt.strftime("%Y-%m-%d")
    clean["ship_date"] = ship_date[ok].dt.strftime("%Y-%m-%d").where(ship_date[ok].notna(), None)
    clean["quantity"] = quantity[ok].astype(int)
    clean["unit_price"] = unit_price[ok].round(2)
    clean["unit_cost"] = unit_cost[ok].round(2)
    clean["discount"] = discount[ok].round(4)
    clean["status"] = status[ok]
    clean["age"] = age[ok].astype("Int64")
    clean = clean.drop_duplicates(subset=["order_id", "product_id"], keep="last")

    clean["sales"] = (clean["quantity"] * clean["unit_price"] * (1 - clean["discount"])).round(2)
    clean["cost"] = (clean["quantity"] * clean["unit_cost"]).round(2)
    clean["profit"] = (clean["sales"] - clean["cost"]).round(2)

    def blank_to_none(value):
        return None if value == "" or pd.isna(value) else value

    customers = clean.drop_duplicates("customer_id", keep="last")
    products = clean.drop_duplicates("product_id", keep="last")
    orders = clean.drop_duplicates("order_id", keep="first")

    with db:
        db.executemany(
            """INSERT INTO customers (customer_id, name, gender, age, city, state, region, segment)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?)
               ON CONFLICT (customer_id) DO UPDATE SET
                 name = excluded.name, gender = excluded.gender, age = excluded.age,
                 city = excluded.city, state = excluded.state, region = excluded.region,
                 segment = excluded.segment""",
            [(r.customer_id, r.customer_name, blank_to_none(r.gender),
              None if pd.isna(r.age) else int(r.age), blank_to_none(r.city), blank_to_none(r.state),
              blank_to_none(r.region), blank_to_none(r.segment))
             for r in customers.itertuples()],
        )
        # New products are added with zero stock; existing catalogue entries are not overwritten
        db.executemany(
            """INSERT INTO products (product_id, name, category, sub_category, unit_cost, unit_price)
               VALUES (?, ?, ?, ?, ?, ?) ON CONFLICT (product_id) DO NOTHING""",
            [(r.product_id, r.product_name, r.category, blank_to_none(r.sub_category),
              r.unit_cost, r.unit_price) for r in products.itertuples()],
        )
        db.executemany(
            """INSERT INTO orders (order_id, order_date, ship_date, customer_id, status, ship_mode, payment_method)
               VALUES (?, ?, ?, ?, ?, ?, ?)
               ON CONFLICT (order_id) DO UPDATE SET
                 order_date = excluded.order_date, ship_date = excluded.ship_date,
                 customer_id = excluded.customer_id, status = excluded.status,
                 ship_mode = excluded.ship_mode, payment_method = excluded.payment_method""",
            [(r.order_id, r.order_date, r.ship_date, r.customer_id, r.status,
              blank_to_none(r.ship_mode), blank_to_none(r.payment_method))
             for r in orders.itertuples()],
        )
        db.executemany(
            """INSERT INTO order_items (order_id, product_id, quantity, unit_price, unit_cost,
                                        discount, sales, cost, profit)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
               ON CONFLICT (order_id, product_id) DO UPDATE SET
                 quantity = excluded.quantity, unit_price = excluded.unit_price,
                 unit_cost = excluded.unit_cost, discount = excluded.discount,
                 sales = excluded.sales, cost = excluded.cost, profit = excluded.profit""",
            [(r.order_id, r.product_id, int(r.quantity), float(r.unit_price), float(r.unit_cost),
              float(r.discount), float(r.sales), float(r.cost), float(r.profit))
             for r in clean.itertuples()],
        )
        result.imported = len(clean)
        _log(db, filename, "sales", result, user_id)
    return result


def import_products(db, fileobj, filename, user_id=None):
    df = _read_csv(fileobj, PRODUCT_REQUIRED, PRODUCT_OPTIONAL)
    v = _Validator(df)
    v.required(PRODUCT_REQUIRED)
    unit_cost = v.number("unit_cost", minimum=0)
    unit_price = v.number("unit_price", minimum=0)
    stock = v.number("stock_qty", minimum=0, integer=True, default=0)
    reorder = v.number("reorder_level", minimum=0, integer=True, default=10)

    result = ImportResult(total=len(df))
    ok = v.errors == ""
    result.rejected = int((~ok).sum())
    result.errors = v.messages()
    clean = df[ok].drop_duplicates("product_id", keep="last")

    rows = [(r.product_id, r.name, r.category, r.sub_category or None, float(unit_cost[i]),
             float(unit_price[i]), int(stock[i]), int(reorder[i]), r.supplier or None)
            for i, r in zip(clean.index, clean.itertuples())]
    with db:
        db.executemany(
            """INSERT INTO products (product_id, name, category, sub_category, unit_cost, unit_price,
                                     stock_qty, reorder_level, supplier)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
               ON CONFLICT (product_id) DO UPDATE SET
                 name = excluded.name, category = excluded.category,
                 sub_category = excluded.sub_category, unit_cost = excluded.unit_cost,
                 unit_price = excluded.unit_price, stock_qty = excluded.stock_qty,
                 reorder_level = excluded.reorder_level, supplier = excluded.supplier""",
            rows,
        )
        result.imported = len(rows)
        _log(db, filename, "products", result, user_id)
    return result
