import os

BASE_DIR = os.path.abspath(os.path.dirname(__file__))


class Config:
    # Signs login sessions. If unset, a random key is generated once and kept in instance/
    SECRET_KEY = os.environ.get("BIZ_SECRET_KEY")
    DATABASE = os.environ.get("BIZ_DATABASE", os.path.join(BASE_DIR, "instance", "bizinsight.db"))
    SESSION_COOKIE_HTTPONLY = True
    SESSION_COOKIE_SAMESITE = "Lax"
    SESSION_COOKIE_SECURE = os.environ.get("BIZ_HTTPS") == "1"   # set to 1 when served over HTTPS
    SAMPLE_DATA_DIR = os.path.join(BASE_DIR, "data")
    MAX_CONTENT_LENGTH = 20 * 1024 * 1024  # 20 MB upload limit

    # Default administrator created on first run
    ADMIN_EMAIL = os.environ.get("BIZ_ADMIN_EMAIL", "admin@bizinsight.com")
    ADMIN_PASSWORD = os.environ.get("BIZ_ADMIN_PASSWORD", "admin123")

    # Inventory business rules
    DEMAND_WINDOW_DAYS = 90     # sales history used to measure demand
    LEAD_TIME_DAYS = 7          # supplier delivery time
    SAFETY_STOCK_DAYS = 7       # buffer against demand spikes
    REVIEW_PERIOD_DAYS = 30     # stock to cover after a reorder arrives
    OVERSTOCK_DAYS = 180        # more cover than this is overstock

    # Analytics thresholds
    HIGH_RETURN_RATE = 0.08
    ROWS_PER_PAGE = 50
