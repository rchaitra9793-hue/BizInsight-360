"""
Convert the Kaggle "Superstore" dataset into BizInsight 360's import format.

Download the CSV from Kaggle (e.g. "Sample - Superstore.csv"), then run:

    python scripts/convert_superstore.py "path/to/Sample - Superstore.csv"

It writes two files next to the input:
    superstore_sales.csv     -> Data import > "Sales transactions"
    superstore_products.csv  -> Data import > "Product catalogue & stock"

How the columns are derived (Superstore has no price or cost column):
    unit_price = Sales / (Quantity x (1 - Discount))   list price before discount
    unit_cost  = (Sales - Profit) / Quantity           so profit matches the dataset exactly
Superstore has no order status, gender, age or stock levels: every order is
imported as Delivered and products start with zero stock (edit stock in the
Product catalogue or upload a products file with real stock figures).
"""
import os
import sys

import pandas as pd

COLUMNS = {
    "order id": "order_id", "order date": "order_date", "ship date": "ship_date",
    "ship mode": "ship_mode", "customer id": "customer_id", "customer name": "customer_name",
    "segment": "segment", "city": "city", "state": "state", "region": "region",
    "product id": "product_id", "category": "category", "sub-category": "sub_category",
    "product name": "product_name", "sales": "sales", "quantity": "quantity",
    "discount": "discount", "profit": "profit",
}
DATE_FORMATS = ["%m/%d/%Y", "%d/%m/%Y", "%d-%m-%Y", "%Y-%m-%d", "%m-%d-%Y"]


def read_csv(path):
    for encoding in ("utf-8-sig", "cp1252"):
        try:
            return pd.read_csv(path, encoding=encoding, dtype=str)
        except UnicodeDecodeError:
            continue
    raise SystemExit("Could not read the file - is it a CSV?")


def parse_dates(series):
    """Pick the one date format that parses every row (Superstore copies differ)."""
    for fmt in DATE_FORMATS:
        parsed = pd.to_datetime(series, format=fmt, errors="coerce")
        if parsed.notna().all():
            return parsed.dt.strftime("%Y-%m-%d")
    raise SystemExit(f"Unrecognised date format, e.g. '{series.iloc[0]}'")


def main(path):
    df = read_csv(path)
    df.columns = [c.strip().lower() for c in df.columns]
    missing = [c for c in COLUMNS if c not in df.columns]
    if missing:
        raise SystemExit("This doesn't look like the Superstore file. Missing: " + ", ".join(missing))
    df = df[list(COLUMNS)].rename(columns=COLUMNS)

    for col in ("sales", "quantity", "discount", "profit"):
        df[col] = pd.to_numeric(df[col], errors="coerce")
    before = len(df)
    df = df.dropna(subset=["sales", "quantity", "discount", "profit"])
    df = df[df["quantity"] > 0]
    df["order_date"] = parse_dates(df["order_date"])
    df["ship_date"] = parse_dates(df["ship_date"])

    # Superstore sometimes lists the same product twice in one order: merge those lines
    df = (df.groupby(["order_id", "product_id"], as_index=False)
            .agg({"order_date": "first", "ship_date": "first", "ship_mode": "first",
                  "customer_id": "first", "customer_name": "first", "segment": "first",
                  "city": "first", "state": "first", "region": "first", "category": "first",
                  "sub_category": "first", "product_name": "first", "sales": "sum",
                  "quantity": "sum", "discount": "mean", "profit": "sum"}))

    df["discount"] = df["discount"].clip(0, 0.95).round(4)
    df["unit_price"] = (df["sales"] / (df["quantity"] * (1 - df["discount"]))).round(2)
    df["unit_cost"] = ((df["sales"] - df["profit"]) / df["quantity"]).clip(lower=0).round(2)
    df["status"] = "Delivered"
    df["payment_method"] = ""

    out_dir = os.path.dirname(os.path.abspath(path))
    sales_cols = ["order_id", "order_date", "ship_date", "status", "ship_mode", "payment_method",
                  "customer_id", "customer_name", "city", "state", "region", "segment",
                  "product_id", "product_name", "category", "sub_category", "quantity",
                  "unit_price", "unit_cost", "discount"]
    sales_path = os.path.join(out_dir, "superstore_sales.csv")
    df[sales_cols].to_csv(sales_path, index=False)

    # Catalogue: latest list price and cost per product, zero stock
    products = (df.sort_values("order_date").groupby("product_id", as_index=False)
                  .agg(name=("product_name", "last"), category=("category", "last"),
                       sub_category=("sub_category", "last"), unit_cost=("unit_cost", "median"),
                       unit_price=("unit_price", "median")))
    products["stock_qty"] = 0
    products["reorder_level"] = 5
    products["supplier"] = ""
    products_path = os.path.join(out_dir, "superstore_products.csv")
    products.to_csv(products_path, index=False)

    print(f"Read {before:,} rows -> {len(df):,} order lines, {df['order_id'].nunique():,} orders, "
          f"{len(products):,} products ({df['order_date'].min()} to {df['order_date'].max()})")
    print(f"Sales file:    {sales_path}")
    print(f"Products file: {products_path}")
    print(f"Check: total sales {df['sales'].sum():,.2f}, total profit {df['profit'].sum():,.2f}")


if __name__ == "__main__":
    if len(sys.argv) != 2:
        raise SystemExit('Usage: python scripts/convert_superstore.py "Sample - Superstore.csv"')
    main(sys.argv[1])
