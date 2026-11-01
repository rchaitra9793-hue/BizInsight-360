"""Dashboard filters shared by every analytics page."""
from dataclasses import dataclass, replace
from datetime import date, timedelta
from urllib.parse import urlencode

from ..db import cached_query as query

# Orders that count as revenue: cancelled and returned orders are excluded
NET_STATUS_SQL = "status NOT IN ('Cancelled', 'Returned')"


def data_bounds():
    row = query("SELECT MIN(order_date) AS first, MAX(order_date) AS last FROM orders", one=True)
    today = date.today().isoformat()
    return (row["first"] or today), (row["last"] or today)


def _valid_date(text):
    try:
        return date.fromisoformat(text).isoformat()
    except (TypeError, ValueError):
        return None


@dataclass(frozen=True)
class Filters:
    start: str
    end: str
    region: str = ""
    category: str = ""

    @classmethod
    def from_request(cls, args):
        first, last = data_bounds()
        preset = args.get("period", "")
        if not (preset or args.get("start") or args.get("end")):
            preset = "12m"   # default view: last 12 months, so KPIs have a prior year to compare with
        start = _valid_date(args.get("start")) or first
        end = _valid_date(args.get("end")) or last
        if preset:
            start, end = _preset_range(preset, first, last)
        if start > end:
            start, end = end, start
        return cls(start=start, end=end, region=args.get("region", "").strip(),
                   category=args.get("category", "").strip())

    def where(self, net=True, extra=None):
        """WHERE clause + params for queries against the v_sales view."""
        clauses = ["order_date BETWEEN ? AND ?"]
        params = [self.start, self.end]
        if self.region:
            clauses.append("region = ?")
            params.append(self.region)
        if self.category:
            clauses.append("category = ?")
            params.append(self.category)
        if net:
            clauses.append(NET_STATUS_SQL)
        if extra:
            clauses.append(extra)
        return "WHERE " + " AND ".join(clauses), params

    def previous(self):
        """The period of equal length immediately before this one."""
        start, end = date.fromisoformat(self.start), date.fromisoformat(self.end)
        length = end - start
        prev_end = start - timedelta(days=1)
        return replace(self, start=(prev_end - length).isoformat(), end=prev_end.isoformat())

    @property
    def days(self):
        return (date.fromisoformat(self.end) - date.fromisoformat(self.start)).days + 1

    @property
    def label(self):
        fmt = "%d %b %Y"
        return f"{date.fromisoformat(self.start).strftime(fmt)} - {date.fromisoformat(self.end).strftime(fmt)}"

    def args(self):
        out = {"start": self.start, "end": self.end}
        if self.region:
            out["region"] = self.region
        if self.category:
            out["category"] = self.category
        return out

    def query_string(self):
        return urlencode(self.args())


def _preset_range(preset, first, last):
    end = date.fromisoformat(last)
    if preset == "30d":
        start = end - timedelta(days=29)
    elif preset == "90d":
        start = end - timedelta(days=89)
    elif preset == "12m":
        start = end - timedelta(days=364)
    elif preset == "ytd":
        start = end.replace(month=1, day=1)
    else:
        return first, last
    return max(start.isoformat(), first), last


def filter_options():
    return {
        "regions": [r["region"] for r in query(
            "SELECT DISTINCT region FROM customers WHERE region IS NOT NULL ORDER BY region")],
        "categories": [r["category"] for r in query(
            "SELECT DISTINCT category FROM products ORDER BY category")],
    }


def period_sql(granularity, column="order_date"):
    """SQL expression that buckets a date column."""
    if granularity == "day":
        return column
    if granularity == "week":
        # Monday of the week
        return f"date({column}, '-' || ((CAST(strftime('%w', {column}) AS INTEGER) + 6) % 7) || ' days')"
    if granularity == "quarter":
        return (f"strftime('%Y', {column}) || '-Q' || "
                f"((CAST(strftime('%m', {column}) AS INTEGER) + 2) / 3)")
    if granularity == "year":
        return f"strftime('%Y', {column})"
    return f"strftime('%Y-%m', {column})"


def pct_change(current, previous):
    if not previous:
        return None
    return (current - previous) / abs(previous)
