-- BizInsight 360 database schema (SQLite)

PRAGMA foreign_keys = ON;

CREATE TABLE IF NOT EXISTS users (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    name          TEXT NOT NULL,
    email         TEXT NOT NULL UNIQUE,
    password_hash TEXT NOT NULL,
    role          TEXT NOT NULL DEFAULT 'analyst' CHECK (role IN ('admin', 'analyst')),
    created_at    TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS customers (
    customer_id TEXT PRIMARY KEY,
    name        TEXT NOT NULL,
    gender      TEXT,
    age         INTEGER,
    city        TEXT,
    state       TEXT,
    region      TEXT,
    segment     TEXT
);

CREATE TABLE IF NOT EXISTS products (
    product_id    TEXT PRIMARY KEY,
    name          TEXT NOT NULL,
    category      TEXT NOT NULL,
    sub_category  TEXT,
    unit_cost     REAL NOT NULL CHECK (unit_cost >= 0),
    unit_price    REAL NOT NULL CHECK (unit_price >= 0),
    stock_qty     INTEGER NOT NULL DEFAULT 0 CHECK (stock_qty >= 0),
    reorder_level INTEGER NOT NULL DEFAULT 10 CHECK (reorder_level >= 0),
    supplier      TEXT
);

CREATE TABLE IF NOT EXISTS orders (
    order_id       TEXT PRIMARY KEY,
    order_date     TEXT NOT NULL,            -- ISO date YYYY-MM-DD
    ship_date      TEXT,
    customer_id    TEXT NOT NULL REFERENCES customers (customer_id),
    status         TEXT NOT NULL CHECK (status IN ('Delivered', 'Shipped', 'Cancelled', 'Returned')),
    ship_mode      TEXT,
    payment_method TEXT
);

-- sales / cost / profit are stored at insert time so every report agrees
CREATE TABLE IF NOT EXISTS order_items (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    order_id   TEXT NOT NULL REFERENCES orders (order_id) ON DELETE CASCADE,
    product_id TEXT NOT NULL REFERENCES products (product_id),
    quantity   INTEGER NOT NULL CHECK (quantity > 0),
    unit_price REAL NOT NULL,
    unit_cost  REAL NOT NULL,
    discount   REAL NOT NULL DEFAULT 0 CHECK (discount >= 0 AND discount < 1),
    sales      REAL NOT NULL,                -- quantity * unit_price * (1 - discount)
    cost       REAL NOT NULL,                -- quantity * unit_cost
    profit     REAL NOT NULL,                -- sales - cost
    UNIQUE (order_id, product_id)
);

CREATE TABLE IF NOT EXISTS stock_movements (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    product_id TEXT NOT NULL REFERENCES products (product_id),
    change_qty INTEGER NOT NULL,
    reason     TEXT NOT NULL,
    user_id    INTEGER REFERENCES users (id),
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS import_log (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    filename      TEXT NOT NULL,
    import_type   TEXT NOT NULL,
    rows_total    INTEGER NOT NULL,
    rows_imported INTEGER NOT NULL,
    rows_rejected INTEGER NOT NULL,
    user_id       INTEGER REFERENCES users (id),
    imported_at   TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);

-- data_version increases on every change to business data; analytics results
-- are cached against it, so a cached answer can never be stale
CREATE TABLE IF NOT EXISTS meta (
    key   TEXT PRIMARY KEY,
    value INTEGER NOT NULL
);
INSERT OR IGNORE INTO meta (key, value) VALUES ('data_version', 0);

CREATE TRIGGER IF NOT EXISTS trg_orders_ins AFTER INSERT ON orders BEGIN UPDATE meta SET value = value + 1 WHERE key = 'data_version'; END;
CREATE TRIGGER IF NOT EXISTS trg_orders_upd AFTER UPDATE ON orders BEGIN UPDATE meta SET value = value + 1 WHERE key = 'data_version'; END;
CREATE TRIGGER IF NOT EXISTS trg_orders_del AFTER DELETE ON orders BEGIN UPDATE meta SET value = value + 1 WHERE key = 'data_version'; END;
CREATE TRIGGER IF NOT EXISTS trg_items_ins AFTER INSERT ON order_items BEGIN UPDATE meta SET value = value + 1 WHERE key = 'data_version'; END;
CREATE TRIGGER IF NOT EXISTS trg_items_upd AFTER UPDATE ON order_items BEGIN UPDATE meta SET value = value + 1 WHERE key = 'data_version'; END;
CREATE TRIGGER IF NOT EXISTS trg_items_del AFTER DELETE ON order_items BEGIN UPDATE meta SET value = value + 1 WHERE key = 'data_version'; END;
CREATE TRIGGER IF NOT EXISTS trg_products_ins AFTER INSERT ON products BEGIN UPDATE meta SET value = value + 1 WHERE key = 'data_version'; END;
CREATE TRIGGER IF NOT EXISTS trg_products_upd AFTER UPDATE ON products BEGIN UPDATE meta SET value = value + 1 WHERE key = 'data_version'; END;
CREATE TRIGGER IF NOT EXISTS trg_products_del AFTER DELETE ON products BEGIN UPDATE meta SET value = value + 1 WHERE key = 'data_version'; END;
CREATE TRIGGER IF NOT EXISTS trg_customers_ins AFTER INSERT ON customers BEGIN UPDATE meta SET value = value + 1 WHERE key = 'data_version'; END;
CREATE TRIGGER IF NOT EXISTS trg_customers_upd AFTER UPDATE ON customers BEGIN UPDATE meta SET value = value + 1 WHERE key = 'data_version'; END;
CREATE TRIGGER IF NOT EXISTS trg_customers_del AFTER DELETE ON customers BEGIN UPDATE meta SET value = value + 1 WHERE key = 'data_version'; END;
CREATE TRIGGER IF NOT EXISTS trg_moves_ins AFTER INSERT ON stock_movements BEGIN UPDATE meta SET value = value + 1 WHERE key = 'data_version'; END;

CREATE INDEX IF NOT EXISTS idx_orders_date     ON orders (order_date);
CREATE INDEX IF NOT EXISTS idx_orders_customer ON orders (customer_id);
CREATE INDEX IF NOT EXISTS idx_items_order     ON order_items (order_id);
CREATE INDEX IF NOT EXISTS idx_items_product   ON order_items (product_id);

-- One flat row per order line: the base for every analytics query
CREATE VIEW IF NOT EXISTS v_sales AS
SELECT oi.id            AS item_id,
       o.order_id,
       o.order_date,
       o.ship_date,
       o.status,
       o.ship_mode,
       o.payment_method,
       c.customer_id,
       c.name           AS customer_name,
       c.gender,
       c.age,
       c.city,
       c.state,
       c.region,
       c.segment,
       p.product_id,
       p.name           AS product_name,
       p.category,
       p.sub_category,
       oi.quantity,
       oi.unit_price,
       oi.discount,
       oi.sales,
       oi.cost,
       oi.profit
FROM order_items oi
JOIN orders o    ON o.order_id = oi.order_id
JOIN customers c ON c.customer_id = o.customer_id
JOIN products p  ON p.product_id = oi.product_id;
