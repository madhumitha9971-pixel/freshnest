import os
import re
import json
import math
import uuid
import secrets
import sqlite3

from pathlib import Path
from datetime import date, datetime
from functools import wraps
from contextlib import contextmanager

from flask import Flask, request, jsonify, session, Response
from werkzeug.security import (
    generate_password_hash,
    check_password_hash,
)


# ==========================================================
# APPLICATION CONFIGURATION
# ==========================================================

BASE = Path(__file__).resolve().parent
PRIVATE = BASE / ".instance"
PRIVATE.mkdir(exist_ok=True)


def private_value(filename, supplied=None):
    path = PRIVATE / filename

    if supplied:
        return supplied

    if path.exists():
        return path.read_text().strip()

    value = secrets.token_urlsafe(32)
    path.write_text(value)
    path.chmod(0o600)

    return value


app = Flask(__name__)

app.secret_key = private_value(
    "session_secret.txt",
    os.environ.get("FRESHNEST_SECRET"),
)

app.config.update(
    SESSION_COOKIE_HTTPONLY=True,
    SESSION_COOKIE_SAMESITE="Lax",
    SESSION_COOKIE_SECURE=(
        os.environ.get("FRESHNEST_HTTPS", "0") == "1"
    ),
    MAX_CONTENT_LENGTH=100000,
)

DATABASE = os.environ.get(
    "FRESHNEST_DATABASE",
    str(PRIVATE / "freshnest.sqlite3"),
)

Path(DATABASE).parent.mkdir(parents=True, exist_ok=True)

ADMIN_MOBILE = os.environ.get(
    "FRESHNEST_ADMIN_MOBILE",
    "9999999999",
)

ADMIN_PASSWORD = private_value(
    "admin_password.txt",
    os.environ.get("FRESHNEST_ADMIN_PASSWORD"),
)

STATUSES = [
    "Confirmed",
    "Packed",
    "Out for delivery",
    "Delivered",
]

SLOTS = [
    "8 AM - 11 AM",
    "12 PM - 3 PM",
    "5 PM - 8 PM",
]


# ==========================================================
# SAMPLE PRODUCT DATA
# Prices are rupees per kilogram.
# ==========================================================

SEED_PRODUCTS = [
    (1, "Tomato", "Everyday essentials", 40, 50, 80),
    (2, "Onion", "Everyday essentials", 35, 45, 80),
    (3, "Potato", "Everyday essentials", 30, 40, 80),
    (4, "Carrot", "Roots and greens", 55, 70, 60),
    (5, "Cabbage", "Roots and greens", 28, 38, 60),
    (6, "Cauliflower", "Seasonal picks", 45, 60, 60),
    (7, "Brinjal", "Seasonal picks", 50, 65, 60),
    (8, "Lady's finger", "Seasonal picks", 60, 75, 60),
    (9, "Cucumber", "Salad favourites", 32, 42, 60),
    (10, "Capsicum", "Salad favourites", 70, 85, 60),
    (11, "Beans", "Roots and greens", 65, 80, 60),
    (12, "Green chilli", "Everyday essentials", 80, 100, 60),
]

RECIPES = [
    {
        "name": "Vegetable kurma",
        "icon": "🍲",
        "items": {"3": 0.5, "4": 0.25, "6": 0.5, "11": 0.25},
    },
    {
        "name": "Crunchy salad",
        "icon": "🥗",
        "items": {"1": 0.5, "4": 0.25, "9": 0.5, "10": 0.25},
    },
    {
        "name": "Sambar vegetables",
        "icon": "🍛",
        "items": {"1": 0.5, "2": 0.25, "7": 0.5, "8": 0.25},
    },
]


# ==========================================================
# DATABASE
# ==========================================================

@contextmanager
def database():
    connection = sqlite3.connect(DATABASE, timeout=20)
    connection.row_factory = sqlite3.Row

    try:
        with connection:
            yield connection
    finally:
        connection.close()


def initialise_database():
    with database() as connection:
        connection.executescript("""
        CREATE TABLE IF NOT EXISTS users (
            id INTEGER PRIMARY KEY,
            name TEXT NOT NULL,
            mobile TEXT UNIQUE NOT NULL,
            password TEXT NOT NULL,
            role TEXT NOT NULL DEFAULT 'customer'
        );

        CREATE TABLE IF NOT EXISTS products (
            id INTEGER PRIMARY KEY,
            name TEXT NOT NULL,
            category TEXT NOT NULL,
            price INTEGER NOT NULL,
            mrp INTEGER NOT NULL,
            stock REAL NOT NULL
        );

        CREATE TABLE IF NOT EXISTS orders (
            id TEXT PRIMARY KEY,
            user_id INTEGER NOT NULL,
            created TEXT NOT NULL,
            items TEXT NOT NULL,
            delivery TEXT NOT NULL,
            subtotal INTEGER NOT NULL,
            fee INTEGER NOT NULL,
            total INTEGER NOT NULL,
            status TEXT NOT NULL
        );
        """)

        connection.executemany(
            "INSERT OR IGNORE INTO products VALUES(?,?,?,?,?,?)",
            SEED_PRODUCTS,
        )

        existing = connection.execute(
            "SELECT id FROM users WHERE mobile=?",
            (ADMIN_MOBILE,),
        ).fetchone()

        if not existing:
            connection.execute(
                """
                INSERT INTO users(name,mobile,password,role)
                VALUES(?,?,?,'admin')
                """,
                (
                    "FreshNest Admin",
                    ADMIN_MOBILE,
                    generate_password_hash(ADMIN_PASSWORD),
                ),
            )


initialise_database()


# ==========================================================
# AUTHENTICATION AND REQUEST PROTECTION
# ==========================================================

def current_user():
    with database() as connection:
        row = connection.execute(
            """
            SELECT id,name,mobile,role
            FROM users
            WHERE id=?
            """,
            (session.get("user_id"),),
        ).fetchone()

    return dict(row) if row else None


def require_login(admin=False):
    def decorator(function):
        @wraps(function)
        def wrapped(*args, **kwargs):
            user = current_user()

            if not user:
                return jsonify(error="Please sign in first."), 401

            if admin and user["role"] != "admin":
                return jsonify(error="Admin access required."), 403

            return function(*args, **kwargs)

        return wrapped

    return decorator


@app.before_request
def protect_requests():
    if request.method in ("POST", "PATCH", "DELETE"):
        expected = session.get("csrf")
        received = request.headers.get("X-CSRF-Token", "")

        if not expected or not secrets.compare_digest(
            expected,
            received,
        ):
            return jsonify(
                error="Session expired. Refresh the page."
            ), 403


@app.after_request
def security_headers(response):
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["X-Frame-Options"] = "DENY"

    if request.path.startswith("/api/"):
        response.headers["Cache-Control"] = "no-store"

    return response


@app.get("/")
def home():
    return Response(HTML, mimetype="text/html")


@app.get("/health")
def health():
    return jsonify(status="ok")


@app.get("/api/start")
def start():
    session.setdefault("csrf", secrets.token_urlsafe(32))

    with database() as connection:
        products = [
            dict(row)
            for row in connection.execute(
                "SELECT * FROM products ORDER BY id"
            )
        ]

    return jsonify(
        csrf=session["csrf"],
        user=current_user(),
        products=products,
        recipes=RECIPES,
        statuses=STATUSES,
        slots=SLOTS,
    )


@app.post("/api/auth")
def authenticate():
    data = request.get_json(silent=True) or {}

    mobile = str(data.get("mobile", "")).strip()
    password = str(data.get("password", ""))

    if not re.fullmatch(r"[0-9]{10}", mobile):
        return jsonify(
            error="Enter a 10-digit mobile number."
        ), 400

    if not 1 <= len(password) <= 128:
        return jsonify(error="Check your password."), 400

    with database() as connection:
        if data.get("mode") == "signup":
            name = str(data.get("name", "")).strip()

            if not 2 <= len(name) <= 70:
                return jsonify(
                    error="Enter a name of 2-70 characters."
                ), 400

            if len(password) < 8:
                return jsonify(
                    error="Use at least 8 password characters."
                ), 400

            try:
                cursor = connection.execute(
                    """
                    INSERT INTO users(name,mobile,password)
                    VALUES(?,?,?)
                    """,
                    (
                        name,
                        mobile,
                        generate_password_hash(password),
                    ),
                )

                user_id = cursor.lastrowid

            except sqlite3.IntegrityError:
                return jsonify(
                    error="This number is already registered."
                ), 400

        elif data.get("mode") == "login":
            row = connection.execute(
                "SELECT * FROM users WHERE mobile=?",
                (mobile,),
            ).fetchone()

            if not row or not check_password_hash(
                row["password"],
                password,
            ):
                return jsonify(
                    error="Incorrect mobile number or password."
                ), 401

            user_id = row["id"]

        else:
            return jsonify(error="Invalid request."), 400

    session.clear()
    session["user_id"] = user_id
    session["csrf"] = secrets.token_urlsafe(32)

    return jsonify(
        user=current_user(),
        csrf=session["csrf"],
    )


@app.post("/api/logout")
def logout():
    session.clear()
    session["csrf"] = secrets.token_urlsafe(32)

    return jsonify(csrf=session["csrf"])


# ==========================================================
# CUSTOMER ORDERS
# ==========================================================

def unpack_order(row):
    order = dict(row)
    order["items"] = json.loads(order["items"])
    order["delivery"] = json.loads(order["delivery"])
    return order


@app.get("/api/orders")
@require_login()
def customer_orders():
    with database() as connection:
        rows = connection.execute(
            """
            SELECT * FROM orders
            WHERE user_id=?
            ORDER BY created DESC
            """,
            (session["user_id"],),
        ).fetchall()

    return jsonify(
        orders=[unpack_order(row) for row in rows]
    )


@app.post("/api/orders")
@require_login()
def place_order():
    data = request.get_json(silent=True) or {}
    cart = data.get("cart")
    raw_delivery = data.get("delivery")

    if (
        not isinstance(cart, dict)
        or not cart
        or len(cart) > 20
        or not isinstance(raw_delivery, dict)
    ):
        return jsonify(error="Invalid cart or address."), 400

    fields = [
        "name", "mobile", "address", "area",
        "city", "pin", "date", "slot",
    ]

    delivery = {
        field: str(raw_delivery.get(field, "")).strip()
        for field in fields
    }

    if any(
        not value or len(value) > 300
        for value in delivery.values()
    ):
        return jsonify(
            error="Complete all delivery details."
        ), 400

    if not re.fullmatch(r"[0-9]{10}", delivery["mobile"]):
        return jsonify(
            error="Enter a valid delivery mobile number."
        ), 400

    if not re.fullmatch(r"[0-9]{6}", delivery["pin"]):
        return jsonify(
            error="Enter a valid six-digit PIN code."
        ), 400

    if delivery["slot"] not in SLOTS:
        return jsonify(error="Select a valid time slot."), 400

    try:
        if date.fromisoformat(delivery["date"]) <= date.today():
            raise ValueError()
    except ValueError:
        return jsonify(
            error="Choose a date from tomorrow onwards."
        ), 400

    with database() as connection:
        connection.execute("BEGIN IMMEDIATE")

        items = []
        subtotal = 0

        for key, raw_quantity in cart.items():
            try:
                product_id = int(key)
                quantity = float(raw_quantity)

                if (
                    not math.isfinite(quantity)
                    or not 0.25 <= quantity <= 20
                    or abs(
                        quantity * 4 - round(quantity * 4)
                    ) > 0.00001
                ):
                    raise ValueError()

            except (ValueError, TypeError, OverflowError):
                return jsonify(
                    error="Use quantities in 250 g steps, up to 20 kg."
                ), 400

            product = connection.execute(
                "SELECT * FROM products WHERE id=?",
                (product_id,),
            ).fetchone()

            if not product or quantity > product["stock"]:
                return jsonify(
                    error="An item has insufficient stock."
                ), 400

            amount = round(
                product["price"] * quantity * 100
            )

            subtotal += amount

            items.append({
                "id": product_id,
                "name": product["name"],
                "quantity": quantity,
                "amount": amount,
            })

        fee = 0 if subtotal >= 50000 else 3000
        order_id = "FN-" + uuid.uuid4().hex[:10].upper()

        for item in items:
            connection.execute(
                """
                UPDATE products
                SET stock=stock-?
                WHERE id=?
                """,
                (item["quantity"], item["id"]),
            )

        connection.execute(
            """
            INSERT INTO orders
            VALUES(?,?,?,?,?,?,?,?,?)
            """,
            (
                order_id,
                session["user_id"],
                datetime.now().isoformat(timespec="seconds"),
                json.dumps(items),
                json.dumps(delivery),
                subtotal,
                fee,
                subtotal + fee,
                "Confirmed",
            ),
        )

    return jsonify(order_id=order_id)


# ==========================================================
# ADMIN
# ==========================================================

@app.get("/api/admin")
@require_login(admin=True)
def admin_data():
    with database() as connection:
        rows = connection.execute(
            "SELECT * FROM orders ORDER BY created DESC"
        ).fetchall()

        customers = connection.execute(
            """
            SELECT COUNT(*) FROM users
            WHERE role='customer'
            """
        ).fetchone()[0]

    return jsonify(
        orders=[unpack_order(row) for row in rows],
        customers=customers,
    )


@app.patch("/api/admin/order/<order_id>")
@require_login(admin=True)
def update_order(order_id):
    status = (
        request.get_json(silent=True) or {}
    ).get("status")

    if status not in STATUSES:
        return jsonify(error="Invalid status."), 400

    with database() as connection:
        connection.execute("BEGIN IMMEDIATE")

        row = connection.execute(
            "SELECT status FROM orders WHERE id=?",
            (order_id,),
        ).fetchone()

        if not row:
            return jsonify(error="Order not found."), 404

        if STATUSES.index(status) < STATUSES.index(row["status"]):
            return jsonify(
                error="Order status cannot move backwards."
            ), 400

        connection.execute(
            "UPDATE orders SET status=? WHERE id=?",
            (status, order_id),
        )

    return jsonify(ok=True)


@app.patch("/api/admin/stock/<int:product_id>")
@require_login(admin=True)
def update_stock(product_id):
    try:
        quantity = float(
            (request.get_json(silent=True) or {})["stock"]
        )

        if not math.isfinite(quantity) or not 0 <= quantity <= 10000:
            raise ValueError()

    except (KeyError, ValueError, TypeError):
        return jsonify(error="Enter stock from 0 to 10000 kg."), 400

    with database() as connection:
        cursor = connection.execute(
            "UPDATE products SET stock=? WHERE id=?",
            (quantity, product_id),
        )

        if not cursor.rowcount:
            return jsonify(error="Product not found."), 404

    return jsonify(ok=True)


# ==========================================================
# BUILT-IN PRODUCT ILLUSTRATIONS
# No external image service is required.
# ==========================================================

ART = {
    1: """
    <circle cx="150" cy="165" r="80" fill="#e85b43"/>
    <ellipse cx="120" cy="145" rx="15" ry="27" fill="#fa8a70"/>
    <path d="M150 110l-35-25 30 4 5-29 10 30 32-7-25 22
    9 20-28-16-24 14z" fill="#507b43"/>
    """,
    2: """
    <path d="M150 65C130 100 75 130 78 182c5 73 140 78
    145-1 4-50-56-81-73-116" fill="#c691af"/>
    <path d="M150 75c-40 75-40 126 0 165M150 75c40 75
    40 126 0 165" fill="none" stroke="#ecd6e2" stroke-width="8"/>
    """,
    3: """
    <ellipse cx="150" cy="160" rx="90" ry="65"
    transform="rotate(-25 150 160)" fill="#c7a16e"/>
    <g fill="#927144">
    <circle cx="110" cy="145" r="5"/>
    <circle cx="175" cy="125" r="4"/>
    <circle cx="160" cy="190" r="5"/>
    <circle cx="205" cy="165" r="4"/>
    </g>
    """,
    4: """
    <path d="M110 115Q165 90 190 125L140 255z" fill="#ed9238"/>
    <path d="M145 115Q100 55 115 40Q150 55 150 95
    Q160 35 185 40Q185 75 160 112" fill="#628e48"/>
    <path d="M125 150l25-7m-18 40 19-6m-11 32 12-4"
    stroke="#c67127" stroke-width="5"/>
    """,
    5: """
    <circle cx="150" cy="160" r="80" fill="#95b95e"/>
    <path d="M150 237C95 200 85 140 110 95M150 237
    c55-37 65-97 40-142M150 237V82M85 145l65 45 65-45"
    fill="none" stroke="#c6dca0" stroke-width="9"/>
    """,
    6: """
    <path d="M150 245Q60 205 75 165l75 30 75-30
    q15 40-75 80" fill="#73994b"/>
    <g fill="#eee9ce" stroke="#dfd8b9" stroke-width="3">
    <circle cx="108" cy="145" r="42"/>
    <circle cx="150" cy="112" r="42"/>
    <circle cx="192" cy="145" r="42"/>
    <circle cx="150" cy="173" r="42"/>
    </g>
    """,
    7: """
    <path d="M166 105c67 8 60 110-10 132
    -85 28-98-62-36-102z" fill="#76518b"/>
    <path d="M153 110l-25 25 7-32-25-7 33-10
    9-29 12 28 25-4-13 20 18 16z" fill="#628c45"/>
    <path d="M118 165q-25 40 9 50" fill="none"
    stroke="#a77bb6" stroke-width="10"/>
    """,
    8: """
    <path d="M95 100l48 140 14-150z" fill="#6d994b"/>
    <path d="M162 100l18 140 40-125z" fill="#89b15e"/>
    <path d="M117 105l27 110m36-102 1 102"
    stroke="#bed695" stroke-width="5"/>
    """,
    9: """
    <rect x="108" y="65" width="85" height="185" rx="42"
    fill="#66935a" transform="rotate(30 150 156)"/>
    <path d="M165 85l-65 130m87-111-60 126"
    stroke="#a5bf7a" stroke-width="7"/>
    """,
    10: """
    <path d="M150 110c-70-55-100 55-65 100
    15 25 40 15 65 7 30 15 55 9 67-17
    23-55-4-119-67-90" fill="#84a84e"/>
    <path d="M148 110q-17 65 1 108m21-110q30 45 11 100"
    fill="none" stroke="#adc970" stroke-width="9"/>
    <path d="M150 110q-12-40 16-55"
    fill="none" stroke="#547b3b" stroke-width="13"/>
    """,
    11: """
    <g fill="none" stroke-width="18" stroke-linecap="round">
    <path d="M95 80q75 60 40 160" stroke="#71a051"/>
    <path d="M145 78q65 70 30 160" stroke="#8bb55e"/>
    <path d="M185 80q40 80 20 150" stroke="#5f8c47"/>
    </g>
    """,
    12: """
    <path d="M95 112q118-20 106 45-16 58-111 78
    65-40 67-80-4-27-62-27z" fill="#64964c"/>
    <path d="M95 120q-7-35 18-48"
    fill="none" stroke="#4c7339" stroke-width="13"/>
    """,
}


@app.get("/images/<int:product_id>.svg")
def product_image(product_id):
    shape = ART.get(product_id)

    if not shape:
        return Response(status=404)

    svg = f"""
    <svg xmlns="http://www.w3.org/2000/svg"
         viewBox="0 0 300 300">
      <ellipse cx="150" cy="255" rx="80" ry="11"
               fill="#244c3910"/>
      {shape}
    </svg>
    """

    return Response(svg, mimetype="image/svg+xml")


# ==========================================================
# COMPLETE FRONTEND
# ==========================================================

HTML = r"""
<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<meta name="theme-color" content="#244c39">
<title>FreshNest — Fresh starts here</title>

<style>
:root{
 --green:#244c39;--cream:#f8f9f5;--ink:#263d2e;
 --muted:#7b8678;--line:#e5eadf;
}
*{box-sizing:border-box}
body{
 margin:0;background:var(--cream);color:var(--ink);
 font:14px system-ui,-apple-system,Segoe UI,sans-serif;
}
button,input,select,textarea{font:inherit}
button{cursor:pointer;border:0}
button:disabled{opacity:.5;cursor:not-allowed}
input,textarea,select{outline-color:#88a568}
.top{
 background:var(--green);color:white;text-align:center;
 padding:9px;font-size:10px;letter-spacing:1px;
}
header{
 position:sticky;top:0;z-index:20;background:#fffffff5;
 backdrop-filter:blur(12px);border-bottom:1px solid var(--line);
}
.nav{
 max-width:1240px;margin:auto;padding:18px 24px;
 display:flex;gap:22px;align-items:center;
}
.brand{
 font-size:25px;font-weight:800;letter-spacing:-1px;
 background:none;color:var(--green);white-space:nowrap;
}
.brand span{color:#839a58}
.search{
 flex:1;background:#f1f4ec;border:1px solid var(--line);
 padding:12px 16px;border-radius:12px;display:flex;gap:10px;
}
.search input{border:0;background:none;width:100%;font-size:12px}
.primary{
 background:var(--green);color:white;border-radius:10px;
 padding:12px 19px;font-size:12px;font-weight:650;
}
.secondary{
 background:#edf2e5;color:var(--green);border-radius:9px;
 padding:10px 15px;font-size:12px;
}
.navlink{background:none;color:var(--ink);font-size:12px}
.subnav{
 display:flex;gap:23px;overflow:auto;max-width:1240px;
 margin:auto;padding:0 24px 13px;
}
.subnav button{
 background:none;color:#6c7865;font-size:11px;white-space:nowrap;
}
main{max-width:1190px;margin:25px auto;padding:0 18px;min-height:65vh}
.hero{
 display:grid;grid-template-columns:1.15fr 1fr;
 border-radius:23px;overflow:hidden;background:#eaf0e0;
}
.herotext{padding:42px}
.eyebrow{
 font-size:10px;text-transform:uppercase;letter-spacing:2px;
 color:#728451;font-weight:700;
}
h1{font-size:45px;line-height:1.12;letter-spacing:-2px;margin:18px 0}
h2{font-size:22px;letter-spacing:-.6px;margin:0}
h3{font-size:15px;margin:12px 0 5px}
.hero p{font-size:13px;line-height:1.8;color:#78816f;max-width:350px}
.heroart{
 background:linear-gradient(130deg,#d8e5c5,#bed29d);
 display:grid;grid-template-columns:1fr 1fr;align-items:center;
 padding:15px;position:relative;
}
.heroart img{width:100%;height:150px;transform:rotate(-10deg)}
.tag{
 position:absolute;bottom:15px;right:15px;background:#fffef2ec;
 padding:10px 14px;border-radius:10px;font-size:10px;
}
.benefits{
 display:grid;grid-template-columns:repeat(3,1fr);gap:15px;
 padding:24px 5px;border-bottom:1px solid var(--line);
 font-size:12px;
}
.benefits small{display:block;margin-top:5px}
small,.muted{color:var(--muted)}
.sectionhead{
 display:flex;align-items:center;justify-content:space-between;
 gap:12px;margin:26px 0 18px;
}
.chips{display:flex;gap:8px;overflow:auto;margin-bottom:20px}
.chip{
 padding:10px 16px;border-radius:25px;background:white;
 border:1px solid var(--line);font-size:11px;white-space:nowrap;
 color:#68755f;
}
.chip.active{background:var(--green);color:white}
select{border:1px solid var(--line);border-radius:8px;padding:9px;background:white}
.grid{display:grid;grid-template-columns:repeat(4,minmax(0,1fr));gap:17px}
.card{
 background:white;border:1px solid var(--line);border-radius:16px;
 padding:12px;transition:.2s;
}
.card:hover{transform:translateY(-3px);box-shadow:0 12px 25px #244c3910}
.picture{
 height:160px;border-radius:10px;position:relative;
 background:linear-gradient(135deg,#f4f6ee,#e7efdc);
}
.picture img{width:100%;height:100%;object-fit:contain;padding:10px}
.badge{
 position:absolute;top:9px;left:9px;background:#e1ecd0;
 color:#5b733b;padding:5px 7px;border-radius:5px;
 font-size:9px;font-weight:700;
}
.heart{
 position:absolute;right:8px;top:8px;background:white;
 color:#657e49;width:28px;height:28px;border-radius:50%;
 font-size:17px;
}
.pricebar{
 display:flex;align-items:center;justify-content:space-between;
 gap:5px;margin-top:16px;
}
.price{font-size:17px;font-weight:750}
del{font-size:10px;color:#a3aa9b;font-weight:400;margin-left:4px}
.add{
 background:#eff4e7;border:1px solid #d6e1c7;color:var(--green);
 border-radius:8px;padding:8px 14px;font-size:11px;font-weight:700;
}
.step{
 display:flex;align-items:center;gap:6px;background:#f0f5e8;
 border:1px solid #d6e1c7;border-radius:8px;font-size:11px;
 white-space:nowrap;
}
.step button{background:none;color:var(--green);padding:8px}
.recipebanner{
 margin-top:28px;background:#eeeada;padding:26px;border-radius:18px;
 display:flex;align-items:center;justify-content:space-between;gap:15px;
}
.panel{
 background:white;border:1px solid var(--line);padding:22px;
 border-radius:16px;margin-bottom:17px;
}
.layout{display:grid;grid-template-columns:1.6fr 1fr;gap:22px}
.row{
 display:flex;align-items:center;gap:13px;padding:15px 0;
 border-bottom:1px solid var(--line);
}
.row img{width:55px;height:55px;background:#f1f5e9;border-radius:10px}
.grow{flex:1}
.sum{display:flex;justify-content:space-between;gap:12px;margin:17px 0;font-size:12px}
.total{border-top:1px solid var(--line);padding-top:17px;font-size:18px;font-weight:750}
.full{width:100%}
.empty{text-align:center;padding:65px 15px}
.formgrid{display:grid;grid-template-columns:1fr 1fr;gap:15px}
label{display:block;font-size:11px;font-weight:600;margin-bottom:6px}
.field{
 width:100%;padding:12px;border:1px solid #dfe5d8;
 border-radius:9px;background:white;
}
.wide{grid-column:1/-1}
.overlay{
 position:fixed;inset:0;background:#172c225b;backdrop-filter:blur(5px);
 z-index:60;display:flex;align-items:center;justify-content:center;padding:18px;
}
.modal{
 position:relative;background:white;border-radius:21px;
 padding:28px;max-width:440px;width:100%;max-height:90vh;overflow:auto;
}
.close{position:absolute;right:12px;top:10px;border-radius:50%;padding:5px 10px}
.modal label{margin-top:16px}
.progress{display:flex;gap:5px;margin:22px 0}
.progress span{
 flex:1;border-top:4px solid #e6ebdf;padding-top:9px;
 text-align:center;font-size:10px;color:#97a08e;
}
.progress .done{border-color:#718e51;color:#4b6839}
.pill{background:#edf3e4;color:#628046;border-radius:20px;padding:7px 11px;font-size:10px}
.stats{display:grid;grid-template-columns:repeat(3,1fr);gap:12px}
.stat{background:white;border:1px solid var(--line);padding:20px;border-radius:13px}
.stat strong{display:block;font-size:23px;margin-top:8px}
.toast{
 position:fixed;bottom:25px;left:50%;transform:translateX(-50%);
 background:var(--green);color:white;padding:14px 22px;border-radius:11px;
 max-width:90%;z-index:100;font-size:12px;
}
footer{text-align:center;padding:35px 15px;color:#89917f;font-size:10px;line-height:1.8}
.mobilebar{display:none}
@media(max-width:850px){
 .grid{grid-template-columns:repeat(3,minmax(0,1fr))}
 .herotext{padding:28px}h1{font-size:37px}
}
@media(max-width:600px){
 .nav{flex-wrap:wrap;gap:10px;padding:14px}
 .brand{font-size:22px}.navlink{margin-left:auto}
 .search{order:5;flex-basis:100%}
 .subnav{padding-left:14px;gap:20px}
 main{padding:0 12px;margin-top:15px}
 .hero{grid-template-columns:1fr}
 .herotext{padding:25px}.heroart{height:150px}
 .heroart img{height:120px}.heroart img:nth-child(n+3){display:none}
 .benefits{gap:8px;font-size:9px}.benefits small{font-size:8px}
 .grid{grid-template-columns:repeat(2,minmax(0,1fr));gap:10px}
 .card{padding:9px}.picture{height:130px}
 .price{font-size:15px}.add{padding:7px 11px}
 .step{gap:2px}.step button{padding:7px}
 .sectionhead{align-items:flex-start}.sectionhead select{max-width:125px;font-size:10px}
 .recipebanner{align-items:flex-start;flex-direction:column}
 .layout{grid-template-columns:1fr;gap:4px}
 .panel{padding:16px}.row{gap:8px}.row img{width:38px;height:42px}
 .formgrid{grid-template-columns:1fr}.wide{grid-column:auto}
 .stats{gap:7px}.stat{padding:12px;font-size:10px}.stat strong{font-size:18px}
 .mobilebar{
  display:flex;justify-content:space-around;position:fixed;
  bottom:0;left:0;right:0;padding:10px 4px;background:#fffffff5;
  border-top:1px solid var(--line);z-index:30;
 }
 .mobilebar button{background:none;color:var(--green);font-size:10px;line-height:1.8}
 footer{padding-bottom:95px}.toast{bottom:80px}
}
</style>
</head>

<body>
<div class="top">A LITTLE FRESHER, EVERY DAY · FREE DELIVERY ON ORDERS ₹500+</div>

<header>
 <div class="nav">
  <button class="brand" onclick="home()">🌿 Fresh<span>Nest</span></button>
  <div class="search">⌕
   <input id="search" placeholder="Search tomatoes, carrots and more…"
    aria-label="Search products" oninput="query=this.value;showShop(false)">
  </div>
  <button id="account" class="navlink" onclick="account()">Sign in</button>
  <button class="primary" onclick="showCart()">Bag · <span id="count">0</span></button>
 </div>
 <nav class="subnav">
  <button onclick="home()">Shop vegetables</button>
  <button onclick="showRecipes()">Cook-to-Cart</button>
  <button onclick="showSaved()">Saved favourites</button>
  <button onclick="showOrders()">Track orders</button>
  <button id="adminButton" hidden onclick="showAdmin()">Store management</button>
 </nav>
</header>

<main id="content"><div class="empty">Preparing your fresh start…</div></main>

<footer>
 🌿 FreshNest · Thoughtfully picked. Simply delivered.<br>
 Student prototype · Sample prices · No real payment or delivery
</footer>

<nav class="mobilebar">
 <button onclick="home()">⌂<br>Home</button>
 <button onclick="showRecipes()">♧<br>Recipes</button>
 <button onclick="showSaved()">♡<br>Saved</button>
 <button onclick="showOrders()">▣<br>Orders</button>
 <button onclick="showCart()">🛍<br>Bag</button>
</nav>

<div id="modalRoot"></div>
<div id="toastRoot"></div>

<script>
const $ = s => document.querySelector(s);
const esc = s => String(s ?? '').replace(/[&<>"']/g, c =>
 ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
const money = n => '₹' + Number(n).toLocaleString('en-IN',
 {minimumFractionDigits:2,maximumFractionDigits:2});

function stored(key,fallback){
 try{return JSON.parse(localStorage.getItem(key)) ?? fallback}
 catch{return fallback}
}

let bag=stored('freshnest_bag',{}), saved=stored('freshnest_saved',[]);
let S={}, query='', category='All vegetables', sort='featured';
let savedOnly=false, mode='login', toastTimer;
const product=id=>S.products.find(p=>p.id===Number(id));

function notify(message){
 clearTimeout(toastTimer);
 $('#toastRoot').innerHTML=`<div class="toast" role="status">${esc(message)}</div>`;
 toastTimer=setTimeout(()=>$('#toastRoot').innerHTML='',4000);
}

async function api(path,method='GET',body){
 const response=await fetch('/api/'+path,{
  method,
  headers:{'Content-Type':'application/json','X-CSRF-Token':S.csrf||''},
  body:body?JSON.stringify(body):undefined
 });
 const data=await response.json();
 if(!response.ok)throw Error(data.error||'Request failed.');
 return data;
}

async function load(){
 S={...S,...await api('start')};
 updateHeader();
}

function updateHeader(){
 $('#account').textContent=S.user?S.user.name.split(' ')[0]:'Sign in';
 $('#count').textContent=Object.keys(bag).length;
 $('#adminButton').hidden=S.user?.role!=='admin';
}

function persist(){
 try{
  localStorage.setItem('freshnest_bag',JSON.stringify(bag));
  localStorage.setItem('freshnest_saved',JSON.stringify(saved));
 }catch{}
 updateHeader();
}

function closeModal(){$('#modalRoot').innerHTML=''}

function modal(content){
 $('#modalRoot').innerHTML=`<div class="overlay"
 onclick="if(event.target===this)closeModal()">
 <div class="modal" role="dialog" aria-modal="true">
 <button class="close" aria-label="Close" onclick="closeModal()">×</button>
 ${content}</div></div>`;
}

function home(){
 closeModal();query='';savedOnly=false;
 $('#search').value='';showShop(true);
 window.scrollTo({top:0,behavior:'smooth'});
}

function showSaved(){
 savedOnly=true;query='';$('#search').value='';
 category='All vegetables';showShop(false);
}

function selectedProducts(){
 let items=S.products.filter(p=>
  (!savedOnly||saved.includes(p.id))&&
  (category==='All vegetables'||p.category===category)&&
  p.name.toLowerCase().includes(query.toLowerCase())
 );
 if(sort==='low')items.sort((a,b)=>a.price-b.price);
 if(sort==='high')items.sort((a,b)=>b.price-a.price);
 return items;
}

function chooseCategory(index){
 category=['All vegetables',...new Set(S.products.map(p=>p.category))][index];
 showShop(false);
}

function toggleSaved(id){
 saved=saved.includes(id)?saved.filter(x=>x!==id):[...saved,id];
 persist();showShop(false);
}

function step(id){
 return `<div class="step">
 <button aria-label="Decrease quantity" onclick="changeQuantity(${id},-.25)">−</button>
 <span>${bag[id]} kg</span>
 <button aria-label="Increase quantity" onclick="changeQuantity(${id},.25)">+</button>
 </div>`;
}

function changeQuantity(id,delta,cartPage=false){
 const p=product(id), next=Math.round(((bag[id]||0)+delta)*4)/4;
 if(next>Math.min(20,p.stock)){notify('Available stock or 20 kg limit reached.');return}
 if(next<=0)delete bag[id];else bag[id]=next;
 persist();
 if(cartPage)showCart();else showShop(false);
}

function add(id){
 const p=product(id);
 if(p.stock<.25){notify('Currently out of stock.');return}
 changeQuantity(id,p.stock>=.5?.5:.25);
}

function card(p){
 return `<article class="card">
 <div class="picture">
 <span class="badge">${Math.round((1-p.price/p.mrp)*100)}% OFF</span>
 <button class="heart" aria-label="Save product"
 onclick="toggleSaved(${p.id})">${saved.includes(p.id)?'♥':'♡'}</button>
 <img src="/images/${p.id}.svg" alt="${esc(p.name)}" loading="lazy">
 </div>
 <h3>${esc(p.name)}</h3>
 <small>Price per kg · ${p.stock>=.25?'Available':'Out of stock'}</small>
 <div class="pricebar">
 <div class="price">₹${p.price}<del>₹${p.mrp}</del></div>
 ${bag[p.id]?step(p.id):`<button class="add"
 onclick="add(${p.id})" ${p.stock<.25?'disabled':''}>ADD +</button>`}
 </div></article>`;
}

function showShop(hero=true){
 const categories=['All vegetables',...new Set(S.products.map(p=>p.category))];
 $('#content').innerHTML=`
 ${hero?`<section class="hero">
 <div class="herotext"><div class="eyebrow">Your everyday fresh start</div>
 <h1>Good food starts<br>with fresh things.</h1>
 <p>Build a colourful basket of everyday vegetables,
 or let your next recipe do the shopping.</p>
 <button class="primary" onclick="document.getElementById('market')
 .scrollIntoView({behavior:'smooth'})">Explore the market ↗</button></div>
 <div class="heroart">
 <img src="/images/5.svg" alt="Cabbage">
 <img src="/images/4.svg" alt="Carrot">
 <img src="/images/1.svg" alt="Tomato">
 <img src="/images/7.svg" alt="Brinjal">
 <div class="tag">🌱 A better basket, one veggie at a time</div>
 </div></section>
 <div class="benefits">
 <div>🥕 Everyday essentials<small>Pick only what you need</small></div>
 <div>🚚 Free delivery ₹500+<small>Otherwise just ₹30</small></div>
 <div>🍲 Cook-to-Cart<small>Your recipe, your basket</small></div>
 </div>`:''}
 <div id="market" class="sectionhead" style="scroll-margin-top:160px">
 <div><h2>${savedOnly?'Your saved favourites':'Fresh from the market'}</h2>
 <small>${selectedProducts().length} vegetables · Sample prices</small></div>
 <select aria-label="Sort products" onchange="sort=this.value;showShop(false)">
 <option value="featured" ${sort==='featured'?'selected':''}>Featured</option>
 <option value="low" ${sort==='low'?'selected':''}>Price: low to high</option>
 <option value="high" ${sort==='high'?'selected':''}>Price: high to low</option>
 </select></div>
 <div class="chips">${categories.map((c,i)=>`
 <button class="chip ${category===c?'active':''}"
 onclick="chooseCategory(${i})">${esc(c)}</button>`).join('')}</div>
 <div class="grid">${selectedProducts().map(card).join('')}</div>
 ${!selectedProducts().length?'<div class="empty">No matching products.</div>':''}
 <div class="recipebanner"><div><div class="eyebrow">Less planning. More cooking.</div>
 <h2 style="margin-top:10px">Your next meal, in one basket.</h2>
 <p class="muted">Choose a dish and adjust the servings.</p></div>
 <button class="primary" onclick="showRecipes()">Try Cook-to-Cart →</button></div>`;
}

function totals(){
 let subtotal=0;
 Object.entries(bag).forEach(([id,q])=>{
  subtotal+=Math.round(product(id).price*q*100);
 });
 const fee=subtotal&&subtotal<50000?3000:0;
 return {subtotal,fee,total:subtotal+fee};
}

function summary(button=''){
 const t=totals();
 return `<div class="panel"><h2>Order summary</h2>
 <div class="sum"><span>Vegetables</span><span>${money(t.subtotal/100)}</span></div>
 <div class="sum"><span>Delivery</span><span>${t.fee?money(t.fee/100):'FREE'}</span></div>
 <div class="sum total"><span>Total</span><span>${money(t.total/100)}</span></div>
 <p class="muted" style="font-size:11px">Free delivery on orders ₹500+.</p>
 ${button}</div>`;
}

function showCart(){
 closeModal();
 if(!Object.keys(bag).length){
  $('#content').innerHTML=`<div class="empty">
  <div style="font-size:60px">🛍️</div><h2>Your shopping bag is empty.</h2>
  <p class="muted">A fresh start is only a few vegetables away.</p>
  <button class="primary" onclick="home()">Explore vegetables</button></div>`;
  return;
 }
 $('#content').innerHTML=`<div class="sectionhead"><h2>Your shopping bag</h2>
 <button class="secondary" onclick="bag={};persist();showCart()">Clear bag</button></div>
 <div class="layout"><div class="panel">
 ${Object.entries(bag).map(([id,q])=>{const p=product(id);return `
 <div class="row"><img src="/images/${p.id}.svg" alt="${esc(p.name)}">
 <div class="grow"><strong>${esc(p.name)}</strong><br><small>₹${p.price}/kg</small></div>
 <div class="step"><button onclick="changeQuantity(${p.id},-.25,true)">−</button>
 <span>${q} kg</span><button onclick="changeQuantity(${p.id},.25,true)">+</button></div>
 <strong style="font-size:12px">${money(p.price*q)}</strong>
 <button aria-label="Remove" class="navlink"
 onclick="delete bag[${p.id}];persist();showCart()">×</button></div>`}).join('')}
 </div>${summary('<button class="primary full" onclick="checkout()">Continue to checkout →</button>')}
 </div>`;
}

function checkout(){
 if(!S.user){auth();notify('Sign in, then continue to checkout.');return}
 if(!Object.keys(bag).length){showCart();return}
 const d=new Date();d.setDate(d.getDate()+1);
 const tomorrow=d.getFullYear()+'-'+String(d.getMonth()+1).padStart(2,'0')
 +'-'+String(d.getDate()).padStart(2,'0');
 $('#content').innerHTML=`<div class="sectionhead"><h2>Delivery and order review</h2></div>
 <div class="layout"><form class="panel" onsubmit="placeOrder(event)">
 <div class="formgrid">
 <div><label>Recipient name</label><input class="field" name="name"
 value="${esc(S.user.name)}" maxlength="100" required></div>
 <div><label>Mobile number</label><input class="field" name="mobile"
 type="tel" pattern="[0-9]{10}" value="${esc(S.user.mobile)}" required></div>
 <div class="wide"><label>House / flat / street</label>
 <textarea class="field" name="address" maxlength="300" required></textarea></div>
 <div><label>Area / locality</label><input class="field" name="area" required></div>
 <div><label>City</label><input class="field" name="city" required></div>
 <div><label>PIN code</label><input class="field" name="pin"
 pattern="[0-9]{6}" inputmode="numeric" required></div>
 <div><label>Delivery date</label><input class="field" name="date"
 type="date" min="${tomorrow}" value="${tomorrow}" required></div>
 <div class="wide"><label>Preferred slot</label><select class="field" name="slot">
 ${S.slots.map(s=>`<option>${esc(s)}</option>`).join('')}</select></div>
 </div>
 <p class="muted" style="font-size:11px">
 Demo cash on delivery. No money is collected or actual delivery booked.</p>
 <button id="placeButton" class="primary full">Confirm demo order</button>
 </form><div>${summary()}
 <div class="panel"><h2>Your vegetables</h2>
 ${Object.entries(bag).map(([id,q])=>`<div class="sum">
 <span>${esc(product(id).name)} · ${q} kg</span>
 <span>${money(product(id).price*q)}</span></div>`).join('')}</div></div></div>`;
}

async function placeOrder(event){
 event.preventDefault();
 if(!confirm('Place this demo cash-on-delivery order?'))return;
 const button=$('#placeButton');button.disabled=true;button.textContent='Saving order…';
 try{
  const result=await api('orders','POST',{
   cart:bag,delivery:Object.fromEntries(new FormData(event.target))
  });
  bag={};persist();await load();
  $('#content').innerHTML=`<div class="empty"><div style="font-size:60px">✅</div>
  <div class="eyebrow">You're all set</div><h1 style="font-size:35px">Your basket is on the list.</h1>
  <p>Order <strong>${esc(result.order_id)}</strong> saved.</p>
  <p class="muted">Demo only. No payment taken or delivery dispatched.</p>
  <button class="primary" onclick="showOrders()">View order tracking →</button></div>`;
 }catch(e){notify(e.message);button.disabled=false;button.textContent='Confirm demo order'}
}

function auth(nextMode='login'){
 mode=nextMode;
 modal(`<div class="eyebrow">Welcome to FreshNest</div>
 <h2 style="margin-top:12px">${mode==='signup'?'Make yourself at home.':'Fresh things await.'}</h2>
 <form onsubmit="submitAuth(event)">
 ${mode==='signup'?'<label>Your name</label><input class="field" name="name" minlength="2" maxlength="70" required>':''}
 <label>Mobile number</label><input class="field" name="mobile" type="tel"
 pattern="[0-9]{10}" maxlength="10" required autocomplete="tel">
 <label>Password</label><input class="field" name="password" type="password"
 ${mode==='signup'?'minlength="8"':''} maxlength="128" required
 autocomplete="${mode==='signup'?'new-password':'current-password'}">
 <p class="muted" style="font-size:10px">Use test details and a password you don't use elsewhere.</p>
 <button class="primary full">${mode==='signup'?'Create account':'Sign in'}</button>
 <p id="authError" style="font-size:12px;color:#aa5135"></p></form>
 <button class="navlink" style="margin-top:12px"
 onclick="auth('${mode==='signup'?'login':'signup'}')">
 ${mode==='signup'?'Already registered? Sign in':'New here? Create an account'}</button>`);
}

async function submitAuth(event){
 event.preventDefault();
 const button=event.target.querySelector('button');button.disabled=true;
 try{
  S={...S,...await api('auth','POST',{
   ...Object.fromEntries(new FormData(event.target)),mode
  })};
  updateHeader();closeModal();notify('Welcome, '+S.user.name);
 }catch(e){$('#authError').textContent=e.message;button.disabled=false}
}

function account(){
 if(!S.user){auth();return}
 modal(`<h2>Hello, ${esc(S.user.name)}</h2><p class="muted">${esc(S.user.mobile)}</p>
 <button class="primary full" onclick="showOrders()">My orders</button>
 ${S.user.role==='admin'?'<button class="secondary full" style="margin-top:10px" onclick="showAdmin()">Store management</button>':''}
 <button class="secondary full" style="margin-top:10px" onclick="signOut()">Sign out</button>`);
}

async function signOut(){
 try{
  const result=await api('logout','POST',{});
  S.user=null;S.csrf=result.csrf;updateHeader();home();notify('Signed out.');
 }catch(e){notify(e.message)}
}

function showRecipes(){
 closeModal();
 $('#content').innerHTML=`<div class="sectionhead"><div>
 <div class="eyebrow">The FreshNest kitchen</div>
 <h2 style="margin-top:10px">Your next meal, in one basket.</h2>
 <p class="muted">Rule-based suggestions, not AI predictions.</p></div></div>
 <div class="grid" style="grid-template-columns:repeat(auto-fit,minmax(240px,1fr))">
 ${S.recipes.map((r,i)=>`<div class="panel"><div style="font-size:50px">${r.icon}</div>
 <h2 style="margin-top:15px">${esc(r.name)}</h2>
 <p class="muted" style="font-size:12px">Untick vegetables already in your kitchen.</p>
 <label>Servings</label><select id="servings${i}" class="field" onchange="recipePreview(${i})">
 <option value="2">2 people</option><option value="4" selected>4 people</option>
 <option value="6">6 people</option><option value="8">8 people</option></select>
 <div id="recipePreview${i}" style="margin:20px 0"></div>
 <button class="primary full" onclick="addRecipe(${i})">Add selected vegetables →</button></div>`).join('')}
 </div><div class="panel"><small>Vegetables only.
 Spices, oil, rice, lentils and pantry items are not included.
 Quantities round up to 250 g shopping increments.</small></div>`;
 S.recipes.forEach((_,i)=>recipePreview(i));
}

function recipeItems(index){
 const servings=Number($('#servings'+index).value);
 return Object.entries(S.recipes[index].items).map(([id,q])=>({
  id:Number(id),quantity:Math.ceil(q*servings)/4
 }));
}

function recipePreview(index){
 $('#recipePreview'+index).innerHTML=recipeItems(index).map(x=>`
 <label class="sum" style="font-weight:400">
 <span><input id="recipe-${index}-${x.id}" type="checkbox" checked
 onchange="recipeTotal(${index})"> ${esc(product(x.id).name)}</span>
 <span>${x.quantity} kg</span></label>`).join('')
 +`<div class="sum total"><span>Vegetables</span><span id="recipeTotal${index}"></span></div>`;
 recipeTotal(index);
}

function selectedRecipe(index){
 return recipeItems(index).filter(x=>$('#recipe-'+index+'-'+x.id).checked);
}

function recipeTotal(index){
 $('#recipeTotal'+index).textContent=money(selectedRecipe(index)
 .reduce((sum,x)=>sum+product(x.id).price*x.quantity,0));
}

function addRecipe(index){
 const items=selectedRecipe(index);
 if(!items.length){notify('Select at least one vegetable.');return}
 for(const x of items){
  if((bag[x.id]||0)+x.quantity>Math.min(20,product(x.id).stock)){
   notify('Insufficient stock for '+product(x.id).name);return;
  }
 }
 items.forEach(x=>bag[x.id]=(bag[x.id]||0)+x.quantity);
 persist();showCart();notify('Recipe basket added.');
}

function orderCard(order,admin=false){
 const d=order.delivery;
 return `<div class="panel">
 <div style="display:flex;justify-content:space-between;gap:12px;flex-wrap:wrap">
 <div><strong>${esc(order.id)}</strong><br>
 <small>${esc(order.created.replace('T',' · '))}</small></div>
 <span class="pill">${esc(order.status)}</span><strong>${money(order.total/100)}</strong></div>
 <div class="progress">${S.statuses.map((s,i)=>`
 <span class="${i<=S.statuses.indexOf(order.status)?'done':''}">${esc(s)}</span>`).join('')}</div>
 <p style="font-size:12px">${order.items.map(x=>
 `${esc(x.name)} × ${x.quantity} kg`).join(' · ')}</p>
 <p class="muted" style="font-size:11px">
 ${esc(d.name)} · ${esc(d.mobile)}<br>
 ${esc(d.address)}, ${esc(d.area)}, ${esc(d.city)} - ${esc(d.pin)}<br>
 ${esc(d.date)} · ${esc(d.slot)}<br>Cash on delivery · Demo order</p>
 ${admin?`<select id="status-${esc(order.id)}">
 ${S.statuses.map(s=>`<option ${s===order.status?'selected':''}>${esc(s)}</option>`).join('')}
 </select> <button class="primary"
 onclick="saveStatus('${esc(order.id)}')">Update status</button>`:''}</div>`;
}

async function showOrders(){
 if(!S.user){auth();return}
 closeModal();
 try{
  const data=await api('orders');
  $('#content').innerHTML=`<div class="sectionhead"><h2>Your fresh deliveries</h2>
  <button class="secondary" onclick="showOrders()">Refresh status</button></div>
  ${data.orders.length?data.orders.map(o=>orderCard(o)).join(''):
  '<div class="empty">No orders yet. Your first basket is waiting.</div>'}`;
 }catch(e){notify(e.message)}
}

async function showAdmin(){
 closeModal();
 try{
  await load();
  const data=await api('admin');
  $('#content').innerHTML=`<div class="sectionhead"><h2>Store management</h2>
  <button class="secondary" onclick="showAdmin()">Refresh</button></div>
  <div class="stats">
  <div class="stat">Orders<strong>${data.orders.length}</strong></div>
  <div class="stat">Customers<strong>${data.customers}</strong></div>
  <div class="stat">Order value · not collected<strong>
  ${money(data.orders.reduce((sum,o)=>sum+o.total,0)/100)}</strong></div></div>
  <div class="sectionhead"><h2>Inventory</h2></div><div class="panel">
  ${S.products.map(p=>`<div class="sum" style="align-items:center">
  <span class="grow">${esc(p.name)}</span>
  <input class="field" style="width:80px" type="number" min="0"
  max="10000" step=".25" id="stock-${p.id}" value="${p.stock}">
  <small>kg</small><button class="secondary" onclick="saveStock(${p.id})">Save</button>
  </div>`).join('')}</div>
  <div class="sectionhead"><h2>Customer orders</h2></div>
  ${data.orders.map(o=>orderCard(o,true)).join('')||'<div class="panel">No orders yet.</div>'}`;
 }catch(e){notify(e.message)}
}

async function saveStatus(id){
 try{
  await api('admin/order/'+id,'PATCH',{status:$('#status-'+id).value});
  notify('Order updated.');await showAdmin();
 }catch(e){notify(e.message)}
}

async function saveStock(id){
 try{
  await api('admin/stock/'+id,'PATCH',{stock:Number($('#stock-'+id).value)});
  await load();notify('Stock updated.');
 }catch(e){notify(e.message)}
}

(async()=>{
 try{
  await load();
  if(!bag||typeof bag!=='object'||Array.isArray(bag))bag={};
  bag=Object.fromEntries(Object.entries(bag).filter(([id,q])=>
   product(id)&&Number.isFinite(q)&&q>=.25&&q<=20&&Number.isInteger(q*4)));
  if(!Array.isArray(saved))saved=[];
  persist();home();
 }catch(e){
  $('#content').innerHTML=`<div class="empty">${esc(e.message)}<br>
  Refresh the page to retry.</div>`;
 }
})();
</script>
</body>
</html>
"""


# ==========================================================
# START APPLICATION
# ==========================================================

if __name__ == "__main__":
    print("
FreshNest admin mobile:", ADMIN_MOBILE)
    print("FreshNest initial admin password:", ADMIN_PASSWORD)
    print("Keep these credentials private.
")

    app.run(
        host="0.0.0.0",
        port=int(os.environ.get("PORT", "8000")),
        debug=False,
        use_reloader=False,
    )