"""
Generate the BizInsight 360 sample dataset.

Produces two CSV files in ../data:
  - products.csv      : product catalogue with current stock levels
  - sample_sales.csv  : 24 months of order-line transactions

The data is synthetic but follows realistic business patterns:
festive-season peaks (Oct/Nov), weekend uplift, year-on-year growth,
loyal vs one-time customers, category-specific return rates, and
heavy discounts that turn some sales into losses.

Uses only the Python standard library and a fixed random seed, so the
output is identical on every run.
"""
import bisect
import csv
import math
import os
import random
from datetime import date, timedelta

SEED = 360
START_DATE = date(2024, 11, 1)
END_DATE = date(2026, 10, 31)
NUM_CUSTOMERS = 1500
BASE_DAILY_ORDERS = 10

OUT_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "data")

# (category, sub_category, item name, base selling price, cost ratio)
CATALOG = [
    ("Electronics", "Mobiles", "5G Smartphone", 18999, 0.82),
    ("Electronics", "Mobiles", "Smartphone Lite", 9999, 0.80),
    ("Electronics", "Audio", "Wireless Earbuds", 1999, 0.55),
    ("Electronics", "Audio", "Bluetooth Speaker", 2499, 0.58),
    ("Electronics", "Audio", "Over-Ear Headphones", 3999, 0.60),
    ("Electronics", "Accessories", "Power Bank 20000mAh", 1499, 0.55),
    ("Electronics", "Accessories", "65W Fast Charger", 1199, 0.50),
    ("Electronics", "Accessories", "USB-C Cable", 299, 0.40),
    ("Electronics", "Wearables", "Smartwatch", 3499, 0.62),
    ("Electronics", "Wearables", "Fitness Band", 1799, 0.58),
    ("Electronics", "Computers", "Wireless Mouse", 699, 0.52),
    ("Electronics", "Computers", "Mechanical Keyboard", 3299, 0.64),
    ("Fashion", "Men's Clothing", "Cotton T-Shirt", 499, 0.45),
    ("Fashion", "Men's Clothing", "Slim Fit Jeans", 1499, 0.50),
    ("Fashion", "Men's Clothing", "Formal Shirt", 1199, 0.48),
    ("Fashion", "Women's Clothing", "Printed Kurta", 999, 0.46),
    ("Fashion", "Women's Clothing", "Saree", 2499, 0.52),
    ("Fashion", "Women's Clothing", "Western Dress", 1799, 0.50),
    ("Fashion", "Footwear", "Running Shoes", 2999, 0.55),
    ("Fashion", "Footwear", "Casual Sneakers", 1999, 0.52),
    ("Fashion", "Footwear", "Sandals", 799, 0.47),
    ("Fashion", "Accessories", "Leather Wallet", 699, 0.42),
    ("Fashion", "Accessories", "Analog Watch", 1999, 0.50),
    ("Home & Kitchen", "Cookware", "Non-Stick Pan Set", 1899, 0.60),
    ("Home & Kitchen", "Cookware", "Pressure Cooker 5L", 2199, 0.65),
    ("Home & Kitchen", "Appliances", "Mixer Grinder", 3499, 0.70),
    ("Home & Kitchen", "Appliances", "Air Fryer", 5999, 0.72),
    ("Home & Kitchen", "Appliances", "Electric Kettle", 999, 0.62),
    ("Home & Kitchen", "Decor", "Wall Clock", 699, 0.45),
    ("Home & Kitchen", "Decor", "Table Lamp", 1299, 0.50),
    ("Home & Kitchen", "Furnishing", "Bedsheet Set", 1099, 0.48),
    ("Home & Kitchen", "Furnishing", "Curtains (Pair)", 899, 0.47),
    ("Beauty & Personal Care", "Skincare", "Face Wash", 249, 0.40),
    ("Beauty & Personal Care", "Skincare", "Sunscreen SPF 50", 449, 0.42),
    ("Beauty & Personal Care", "Skincare", "Moisturiser", 399, 0.40),
    ("Beauty & Personal Care", "Haircare", "Shampoo", 349, 0.45),
    ("Beauty & Personal Care", "Haircare", "Hair Dryer", 1499, 0.60),
    ("Beauty & Personal Care", "Grooming", "Beard Trimmer", 1299, 0.58),
    ("Beauty & Personal Care", "Fragrance", "Perfume 100ml", 1199, 0.45),
    ("Sports & Fitness", "Fitness Equipment", "Yoga Mat", 799, 0.48),
    ("Sports & Fitness", "Fitness Equipment", "Dumbbell Set", 2499, 0.66),
    ("Sports & Fitness", "Fitness Equipment", "Resistance Bands", 599, 0.42),
    ("Sports & Fitness", "Sports Gear", "Cricket Bat", 1999, 0.58),
    ("Sports & Fitness", "Sports Gear", "Football", 799, 0.52),
    ("Sports & Fitness", "Sports Gear", "Badminton Racket", 1299, 0.55),
    ("Sports & Fitness", "Nutrition", "Whey Protein 1kg", 2299, 0.68),
    ("Books & Stationery", "Books", "Fiction Novel", 399, 0.60),
    ("Books & Stationery", "Books", "Competitive Exam Guide", 549, 0.62),
    ("Books & Stationery", "Books", "Self-Help Book", 349, 0.58),
    ("Books & Stationery", "Stationery", "Notebook Pack (5)", 249, 0.45),
    ("Books & Stationery", "Stationery", "Gel Pen Set", 149, 0.40),
    ("Books & Stationery", "Stationery", "Art & Craft Kit", 699, 0.50),
]

BRANDS = {
    "Electronics": ["Volt", "Nexa"],
    "Fashion": ["Urbane", "Desi Threads"],
    "Home & Kitchen": ["HomeNest", "ChefPro"],
    "Beauty & Personal Care": ["Glow", "PureVeda"],
    "Sports & Fitness": ["FitCore", "ProPlay"],
    "Books & Stationery": ["PageTurn", "InkWell"],
}

SUPPLIERS = {
    "Electronics": ["Shenzhen Tech Traders", "Bharat Electronics Distributors"],
    "Fashion": ["Tiruppur Textiles", "Mumbai Fashion House"],
    "Home & Kitchen": ["Delhi Home Supplies", "Rajkot Appliances Co."],
    "Beauty & Personal Care": ["Herbal Care India", "Glow Cosmetics Pvt Ltd"],
    "Sports & Fitness": ["Jalandhar Sports Works", "Meerut Sports Industries"],
    "Books & Stationery": ["National Book Depot", "Sivakasi Paper Mart"],
}

# Share of order lines that end up returned, by category
RETURN_RATE = {
    "Electronics": 0.06,
    "Fashion": 0.13,
    "Home & Kitchen": 0.04,
    "Beauty & Personal Care": 0.03,
    "Sports & Fitness": 0.05,
    "Books & Stationery": 0.02,
}

# (city, state, region, weight)
CITIES = [
    ("Delhi", "Delhi", "North", 10), ("Gurugram", "Haryana", "North", 4),
    ("Noida", "Uttar Pradesh", "North", 3), ("Lucknow", "Uttar Pradesh", "North", 3),
    ("Jaipur", "Rajasthan", "North", 3), ("Chandigarh", "Chandigarh", "North", 2),
    ("Amritsar", "Punjab", "North", 1),
    ("Bengaluru", "Karnataka", "South", 11), ("Chennai", "Tamil Nadu", "South", 6),
    ("Hyderabad", "Telangana", "South", 7), ("Kochi", "Kerala", "South", 3),
    ("Coimbatore", "Tamil Nadu", "South", 2), ("Mysuru", "Karnataka", "South", 1),
    ("Visakhapatnam", "Andhra Pradesh", "South", 2),
    ("Mumbai", "Maharashtra", "West", 11), ("Pune", "Maharashtra", "West", 6),
    ("Ahmedabad", "Gujarat", "West", 4), ("Surat", "Gujarat", "West", 2),
    ("Nagpur", "Maharashtra", "West", 2), ("Panaji", "Goa", "West", 1),
    ("Kolkata", "West Bengal", "East", 6), ("Bhubaneswar", "Odisha", "East", 2),
    ("Patna", "Bihar", "East", 2), ("Guwahati", "Assam", "East", 2),
    ("Ranchi", "Jharkhand", "East", 1),
    ("Bhopal", "Madhya Pradesh", "Central", 2), ("Indore", "Madhya Pradesh", "Central", 3),
    ("Raipur", "Chhattisgarh", "Central", 1),
]

FIRST_NAMES_M = ["Aarav", "Vivaan", "Aditya", "Arjun", "Rohan", "Karthik", "Rahul", "Siddharth",
                 "Vikram", "Amit", "Rajesh", "Suresh", "Nikhil", "Pranav", "Harsh", "Manish",
                 "Deepak", "Imran", "Farhan", "Gurpreet", "Joseph", "Abhishek", "Varun", "Kunal"]
FIRST_NAMES_F = ["Ananya", "Diya", "Priya", "Sneha", "Kavya", "Pooja", "Neha", "Aishwarya",
                 "Meera", "Riya", "Shruti", "Divya", "Lakshmi", "Fatima", "Simran", "Anjali",
                 "Nisha", "Swati", "Tanvi", "Isha", "Sana", "Mary", "Bhavna", "Kritika"]
LAST_NAMES = ["Sharma", "Verma", "Patel", "Reddy", "Nair", "Iyer", "Gupta", "Singh", "Khan",
              "Das", "Mehta", "Joshi", "Rao", "Kumar", "Chatterjee", "Banerjee", "Menon",
              "Pillai", "Shah", "Agarwal", "Mishra", "Yadav", "D'Souza", "Kulkarni", "Bose"]

SEGMENTS = [("Consumer", 75), ("Corporate", 15), ("Home Office", 10)]
SHIP_MODES = [("Standard", 60, 4), ("Express", 25, 2), ("Same Day", 5, 0), ("Economy", 10, 7)]
PAYMENTS = [("UPI", 40), ("Cash on Delivery", 22), ("Credit/Debit Card", 20),
            ("Wallet", 10), ("Net Banking", 8)]
DISCOUNTS = [0, 0, 0, 0, 0.05, 0.05, 0.10, 0.10, 0.10, 0.15, 0.15, 0.20, 0.25, 0.30, 0.40, 0.50]
FESTIVE_DISCOUNTS = [0, 0, 0.05, 0.10, 0.10, 0.15, 0.20, 0.20, 0.25, 0.30, 0.30, 0.40, 0.50]

# Multiplier on order volume by calendar month (Diwali / festive peak in Oct-Nov)
MONTH_FACTOR = {1: 0.85, 2: 0.85, 3: 0.95, 4: 0.9, 5: 0.95, 6: 0.9,
                7: 1.0, 8: 1.1, 9: 1.05, 10: 1.55, 11: 1.45, 12: 1.2}
# Single-day sale events (month, day): multiplier
SALE_DAYS = {(1, 26): 1.8, (8, 15): 1.9, (10, 2): 1.6, (12, 25): 1.5, (3, 8): 1.4}


def weighted(rng, pairs):
    items = [p[0] for p in pairs]
    weights = [p[1] for p in pairs]
    return rng.choices(items, weights=weights, k=1)[0]


def poisson(rng, lam):
    """Knuth's algorithm; fine for the small lambdas used here."""
    limit, k, p = math.exp(-lam), 0, 1.0
    while True:
        p *= rng.random()
        if p <= limit:
            return k
        k += 1


def build_products(rng):
    products = []
    total_days = (END_DATE - START_DATE).days
    pid = 1
    for category, sub, item, price, cost_ratio in CATALOG:
        for b_idx, brand in enumerate(BRANDS[category]):
            # The second brand is a budget variant
            sell = round(price * (1.0 if b_idx == 0 else rng.uniform(0.75, 0.9)), -1) - 1
            cost = round(sell * cost_ratio * rng.uniform(0.95, 1.05), 2)
            launch = START_DATE
            discontinue = END_DATE
            roll = rng.random()
            if roll < 0.08:
                # Launched part-way through the period
                launch = START_DATE + timedelta(days=rng.randint(120, 450))
            elif roll < 0.15:
                # Stopped selling - these become dead stock
                discontinue = START_DATE + timedelta(days=rng.randint(200, total_days - 150))
            products.append({
                "product_id": f"P{pid:04d}",
                "name": f"{brand} {item}",
                "category": category,
                "sub_category": sub,
                "unit_cost": cost,
                "unit_price": sell,
                "supplier": SUPPLIERS[category][b_idx],
                "popularity": rng.paretovariate(1.6),
                "launch": launch,
                "discontinue": discontinue,
            })
            pid += 1
    return products


def build_customers(rng):
    customers = []
    total_days = (END_DATE - START_DATE).days
    city_pairs = [((c, s, r), w) for c, s, r, w in CITIES]
    for i in range(1, NUM_CUSTOMERS + 1):
        gender = "Female" if rng.random() < 0.46 else "Male"
        first = rng.choice(FIRST_NAMES_F if gender == "Female" else FIRST_NAMES_M)
        city, state, region = weighted(rng, city_pairs)
        age = max(18, min(70, int(rng.gauss(32, 9))))
        # 30% of customers existed before the period; the rest join gradually
        if rng.random() < 0.30:
            active_from = START_DATE
        else:
            active_from = START_DATE + timedelta(days=int(rng.random() ** 0.9 * (total_days - 20)))
        customers.append({
            "customer_id": f"C{i:05d}",
            "customer_name": f"{first} {rng.choice(LAST_NAMES)}",
            "gender": gender,
            "age": age,
            "city": city,
            "state": state,
            "region": region,
            "segment": weighted(rng, SEGMENTS),
            "active_from": active_from,
            "loyalty": rng.paretovariate(1.3),
        })
    customers.sort(key=lambda c: c["active_from"])
    return customers


def main():
    rng = random.Random(SEED)
    products = build_products(rng)
    customers = build_customers(rng)

    activation_days = [c["active_from"] for c in customers]
    cum_loyalty = []
    running = 0.0
    for c in customers:
        running += c["loyalty"]
        cum_loyalty.append(running)

    rows = []
    order_no = 100000
    total_days = (END_DATE - START_DATE).days
    day = START_DATE
    while day <= END_DATE:
        progress = (day - START_DATE).days / total_days
        lam = BASE_DAILY_ORDERS * (1 + 0.30 * progress) * MONTH_FACTOR[day.month]
        if day.weekday() >= 5:
            lam *= 1.2
        lam *= SALE_DAYS.get((day.month, day.day), 1.0)
        festive = day.month in (10, 11) or (day.month, day.day) in SALE_DAYS

        available = [p for p in products if p["launch"] <= day <= p["discontinue"]]
        avail_weights = [p["popularity"] for p in available]
        n_active = bisect.bisect_right(activation_days, day)

        for _ in range(poisson(rng, lam)):
            if n_active == 0:
                break
            # Pick a customer, favouring loyal ones
            idx = bisect.bisect_left(cum_loyalty, rng.random() * cum_loyalty[n_active - 1])
            cust = customers[min(idx, n_active - 1)]

            order_no += 1
            ship_mode, _, ship_days = rng.choices(SHIP_MODES, weights=[m[1] for m in SHIP_MODES])[0]
            ship_date = day + timedelta(days=ship_days + rng.randint(0, 1))
            payment = weighted(rng, PAYMENTS)

            n_items = rng.choices([1, 2, 3, 4], weights=[60, 25, 10, 5])[0]
            chosen = {}
            for _ in range(n_items):
                p = rng.choices(available, weights=avail_weights)[0]
                chosen[p["product_id"]] = p
            lines = list(chosen.values())

            if (END_DATE - day).days < 5:
                status = "Shipped"
            elif rng.random() < 0.035:
                status = "Cancelled"
            elif rng.random() < max(RETURN_RATE[p["category"]] for p in lines):
                status = "Returned"
            else:
                status = "Delivered"

            for p in lines:
                qty = rng.choices([1, 2, 3, 4, 5], weights=[70, 18, 7, 3, 2])[0]
                if p["category"] == "Books & Stationery" or p["unit_price"] < 500:
                    qty = rng.choices([1, 2, 3, 5, 10], weights=[45, 25, 15, 10, 5])[0]
                discount = rng.choice(FESTIVE_DISCOUNTS if festive else DISCOUNTS)
                rows.append({
                    "order_id": f"ORD-{order_no}",
                    "order_date": day.isoformat(),
                    "ship_date": ship_date.isoformat(),
                    "status": status,
                    "ship_mode": ship_mode,
                    "payment_method": payment,
                    "customer_id": cust["customer_id"],
                    "customer_name": cust["customer_name"],
                    "gender": cust["gender"],
                    "age": cust["age"],
                    "city": cust["city"],
                    "state": cust["state"],
                    "region": cust["region"],
                    "segment": cust["segment"],
                    "product_id": p["product_id"],
                    "product_name": p["name"],
                    "category": p["category"],
                    "sub_category": p["sub_category"],
                    "quantity": qty,
                    "unit_price": p["unit_price"],
                    "unit_cost": p["unit_cost"],
                    "discount": discount,
                })
        day += timedelta(days=1)

    # Set current stock from the last 90 days of demand so the inventory
    # module shows a realistic mix of healthy, low, out-of-stock and overstock items.
    recent_cutoff = (END_DATE - timedelta(days=90)).isoformat()
    recent_units = {}
    for r in rows:
        if r["order_date"] > recent_cutoff and r["status"] not in ("Cancelled", "Returned"):
            recent_units[r["product_id"]] = recent_units.get(r["product_id"], 0) + r["quantity"]

    for p in products:
        daily = recent_units.get(p["product_id"], 0) / 90
        roll = rng.random()
        if daily == 0:
            p["stock_qty"] = rng.randint(15, 120)          # dead stock
        elif roll < 0.07:
            p["stock_qty"] = 0                              # out of stock
        elif roll < 0.22:
            p["stock_qty"] = int(daily * rng.uniform(2, 9))  # running low
        elif roll < 0.32:
            p["stock_qty"] = int(daily * rng.uniform(200, 320))  # overstocked
        else:
            p["stock_qty"] = int(daily * rng.uniform(25, 110))
        p["reorder_level"] = max(5, int(math.ceil(daily * 10)))

    os.makedirs(OUT_DIR, exist_ok=True)
    product_fields = ["product_id", "name", "category", "sub_category", "unit_cost",
                      "unit_price", "stock_qty", "reorder_level", "supplier"]
    with open(os.path.join(OUT_DIR, "products.csv"), "w", newline="", encoding="utf-8") as fh:
        writer = csv.DictWriter(fh, fieldnames=product_fields, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(products)

    with open(os.path.join(OUT_DIR, "sample_sales.csv"), "w", newline="", encoding="utf-8") as fh:
        writer = csv.DictWriter(fh, fieldnames=list(rows[0].keys()))
        writer.writeheader()
        writer.writerows(rows)

    orders = len({r["order_id"] for r in rows})
    print(f"Generated {len(products)} products, {orders} orders, {len(rows)} order lines "
          f"({START_DATE} to {END_DATE}) in {os.path.normpath(OUT_DIR)}")


if __name__ == "__main__":
    main()
