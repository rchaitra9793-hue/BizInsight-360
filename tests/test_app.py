"""End-to-end tests using Flask's test client against a temporary database."""
import io
import re

import pytest

from bizinsight import create_app
from bizinsight.utils import fmt_inr, indian_grouping


@pytest.fixture(scope="session")
def app(tmp_path_factory):
    db_path = tmp_path_factory.mktemp("db") / "test.db"
    return create_app({"DATABASE": str(db_path), "TESTING": True})


def _csrf(client):
    page = client.get("/login").get_data(as_text=True)
    return re.search(r'name="_csrf" value="([^"]+)"', page).group(1)


def _login(client, email="admin@bizinsight.com", password="admin123"):
    token = _csrf(client)
    return client.post("/login", data={"email": email, "password": password, "_csrf": token})


@pytest.fixture()
def admin(app):
    client = app.test_client()
    _login(client)
    client.token = _csrf_from_session(client)
    return client


def _csrf_from_session(client):
    client.get("/account")  # any page with a form issues the token
    with client.session_transaction() as s:
        return s["_csrf"]


def db_value(app, sql, params=()):
    from bizinsight.db import connect
    conn = connect(app.config["DATABASE"])
    try:
        return conn.execute(sql, params).fetchone()[0]
    finally:
        conn.close()


# ---------------- formatting ----------------

def test_indian_formatting():
    assert indian_grouping(12345678) == "1,23,45,678"
    assert indian_grouping(999) == "999"
    assert fmt_inr(25_000_000) == "₹2.50 Cr"
    assert fmt_inr(150_000) == "₹1.50 L"
    assert fmt_inr(-1500) == "-₹1.5K"


# ---------------- auth ----------------

def test_pages_require_login(app):
    resp = app.test_client().get("/sales/")
    assert resp.status_code == 302 and "/login" in resp.headers["Location"]


def test_wrong_password(app):
    client = app.test_client()
    resp = _login(client, password="nope")
    assert "Incorrect email or password" in resp.get_data(as_text=True)


def test_post_without_csrf_is_rejected(app):
    resp = app.test_client().post("/login", data={"email": "x", "password": "y"})
    assert resp.status_code == 400


def test_register_creates_read_only_analyst(app):
    client = app.test_client()
    token = _csrf(client)
    client.post("/register", data={"name": "Test Analyst", "email": "analyst@example.com", "password": "secret1",
                                   "confirm": "secret1", "_csrf": token})
    _login(client, "analyst@example.com", "secret1")
    assert client.get("/").status_code == 200
    token = _csrf_from_session(client)
    resp = client.post("/data/reset", data={"confirm": "RESET", "_csrf": token}, follow_redirects=True)
    assert "Only administrators" in resp.get_data(as_text=True)


# ---------------- every page renders ----------------

PAGES = ["/", "/insights", "/sales/", "/sales/?g=day&period=30d", "/sales/?g=quarter", "/profit/",
         "/products/", "/products/P0001", "/inventory/", "/inventory/?status=Low+Stock",
         "/customers/", "/customers/?segment=Champions", "/reports/",
         "/reports/summary", "/data/", "/data/products", "/data/products/new", "/data/products/P0001/edit",
         "/data/orders", "/data/orders?q=ORD-1000&page=2", "/data/orders/ORD-100001", "/data/orders/new",
         "/account", "/?region=South&category=Fashion&period=90d", "/?start=2030-01-01&end=2030-02-01"]


@pytest.mark.parametrize("url", PAGES)
def test_page_renders(admin, url):
    resp = admin.get(url)
    assert resp.status_code == 200, url
    # A dict key shadowed by a dict method (e.g. "items", "values") renders like this
    assert "built-in method" not in resp.get_data(as_text=True), url


def test_customer_profile(app, admin):
    cid = db_value(app, "SELECT customer_id FROM customers ORDER BY customer_id LIMIT 1")
    assert admin.get(f"/customers/{cid}").status_code == 200
    assert admin.get("/customers/NOPE").status_code == 404


def test_unknown_product_404(admin):
    assert admin.get("/products/NOPE").status_code == 404


def test_dashboard_shows_kpis(admin):
    html = admin.get("/").get_data(as_text=True)
    assert "Net revenue" in html and "₹" in html and "Key insights" in html


# ---------------- exports ----------------

@pytest.mark.parametrize("report", ["transactions", "monthly", "category", "region", "products", "customers", "inventory"])
def test_csv_exports(admin, report):
    resp = admin.get(f"/reports/download?report={report}&format=csv&period=90d")
    assert resp.status_code == 200
    assert resp.mimetype == "text/csv"
    assert len(resp.data.splitlines()) > 1


def test_excel_workbook(admin):
    resp = admin.get("/reports/download?report=workbook")
    assert resp.status_code == 200
    assert resp.data[:2] == b"PK"  # xlsx is a zip file


# ---------------- import ----------------

def test_import_validates_rows(app, admin):
    csv = (
        "order_id,order_date,customer_id,customer_name,product_id,product_name,category,quantity,unit_price,unit_cost,discount,status\n"
        "T-1,2026-10-01,CT1,Test Buyer,PT1,Test Gadget,Electronics,2,1000,600,10,Delivered\n"
        "T-2,not-a-date,CT1,Test Buyer,PT1,Test Gadget,Electronics,1,1000,600,0,Delivered\n"
        "T-3,2026-10-02,CT1,Test Buyer,PT1,Test Gadget,Electronics,0,1000,600,0,Delivered\n"
        "T-4,2026-10-02,CT1,Test Buyer,PT1,Test Gadget,Electronics,1,1000,600,0,Lost\n"
    )
    resp = admin.post("/data/import", data={"kind": "sales", "_csrf": admin.token,
                                            "file": (io.BytesIO(csv.encode()), "test.csv")},
                      content_type="multipart/form-data")
    html = resp.get_data(as_text=True)
    assert resp.status_code == 200
    assert "Row 3: &#39;order_date&#39; is not a valid date" in html
    assert "Row 4: &#39;quantity&#39; must be &gt;= 1" in html
    assert "Row 5: &#39;status&#39;" in html
    # 15% written as "10" means 10%: 2 x 1000 x 0.9 = 1800 revenue, 1800 - 1200 = 600 profit
    assert db_value(app, "SELECT sales FROM order_items WHERE order_id = 'T-1'") == 1800
    assert db_value(app, "SELECT profit FROM order_items WHERE order_id = 'T-1'") == 600


def test_import_missing_columns(admin):
    resp = admin.post("/data/import", data={"kind": "sales", "_csrf": admin.token,
                                            "file": (io.BytesIO(b"order_id,foo\n1,2\n"), "bad.csv")},
                      content_type="multipart/form-data", follow_redirects=True)
    assert "Missing required column" in resp.get_data(as_text=True)


def test_template_download(admin):
    resp = admin.get("/data/template/sales.csv")
    assert resp.status_code == 200 and b"order_id,order_date" in resp.data


# ---------------- orders and stock ----------------

def test_order_lifecycle_moves_stock(app, admin):
    pid = "P0001"
    admin.post(f"/inventory/{pid}/adjust", data={"_csrf": admin.token, "mode": "restock", "qty": "10"})
    before = db_value(app, "SELECT stock_qty FROM products WHERE product_id = ?", (pid,))

    cid = db_value(app, "SELECT customer_id FROM customers LIMIT 1")
    resp = admin.post("/data/orders/new", data={
        "_csrf": admin.token, "customer_mode": "existing", "customer_id": cid, "order_date": "2026-10-31",
        "status": "Delivered", "payment_method": "UPI", "ship_mode": "Express",
        "product_id": [pid], "quantity": ["3"], "discount": ["10"]})
    assert resp.status_code == 302
    order_id = resp.headers["Location"].rsplit("/", 1)[-1]
    assert db_value(app, "SELECT stock_qty FROM products WHERE product_id = ?", (pid,)) == before - 3
    price = db_value(app, "SELECT unit_price FROM products WHERE product_id = ?", (pid,))
    assert db_value(app, "SELECT sales FROM order_items WHERE order_id = ?", (order_id,)) == round(3 * price * 0.9, 2)

    # Returning the order puts the stock back
    admin.post(f"/data/orders/{order_id}/status", data={"_csrf": admin.token, "status": "Returned"})
    assert db_value(app, "SELECT stock_qty FROM products WHERE product_id = ?", (pid,)) == before
    assert db_value(app, "SELECT COUNT(*) FROM stock_movements WHERE reason LIKE ?", (f"%{order_id}%",)) == 2


def test_order_rejects_more_than_stock(app, admin):
    stock = db_value(app, "SELECT stock_qty FROM products WHERE product_id = 'P0002'")
    resp = admin.post("/data/orders/new", data={
        "_csrf": admin.token, "customer_mode": "existing", "customer_id": "C00001",
        "product_id": ["P0002"], "quantity": [str(stock + 1)], "discount": ["0"]}, follow_redirects=True)
    assert "in stock" in resp.get_data(as_text=True)
    assert db_value(app, "SELECT stock_qty FROM products WHERE product_id = 'P0002'") == stock


def test_new_product_and_delete(app, admin):
    resp = admin.post("/data/products/new", data={"_csrf": admin.token, "name": "Test Lamp", "category": "Home & Kitchen",
                                                 "unit_cost": "100", "unit_price": "250", "stock_qty": "5",
                                                 "reorder_level": "2"})
    assert resp.status_code == 302
    pid = db_value(app, "SELECT product_id FROM products WHERE name = 'Test Lamp'")
    admin.post(f"/data/products/{pid}/delete", data={"_csrf": admin.token})
    assert db_value(app, "SELECT COUNT(*) FROM products WHERE product_id = ?", (pid,)) == 0
