"""Tạo database SQLite giả lập một cửa hàng.

- products + reviews : dùng cho Demo 3 (benchmark)
- users + orders     : dùng cho Demo 1 (caching hồ sơ người dùng)

Chạy: python bench/seed_db.py   (~30-60 giây)
"""
import random
import os
import sqlite3
import sys
from datetime import date, timedelta
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8")  # in tiếng Việt được trên mọi terminal Windows

DB_PATH = Path(os.getenv("SHOP_DB", Path(__file__).with_name("shop.db")))  # Docker: SHOP_DB=/data/shop.db
N_PRODUCTS = 1000
N_CATEGORIES = 20
N_REVIEWS = 300_000
N_USERS = 200_000
N_ORDERS = 1_000_000

HO = ["Nguyen", "Tran", "Le", "Pham", "Hoang", "Huynh", "Phan", "Vu", "Vo", "Dang", "Bui", "Do", "Ho", "Ngo", "Duong"]
DEM = ["Van", "Thi", "Minh", "Ngoc", "Thanh", "Quoc", "Gia", "Bao", "Duc", "Hoai"]
TEN = ["An", "Binh", "Chau", "Dung", "Giang", "Hai", "Khanh", "Linh", "Mai", "Nam", "Phuc", "Quan", "Son", "Trang", "Vy"]
CITIES = ["Ho Chi Minh", "Ha Noi", "Da Nang", "Can Tho", "Hai Phong", "Hue", "Nha Trang", "Vung Tau"]
STREETS = ["Le Loi", "Tran Hung Dao", "Nguyen Hue", "Hai Ba Trung", "Ly Thuong Kiet", "Vo Van Tan", "Pasteur"]
# 3 người đầu trùng với USERS trong source_api.py để phần đăng nhập (Demo 1 -> Demo 2) liền mạch
FIXED_USERS = {1: ("Nguyen Van A", "Ho Chi Minh"), 2: ("Tran Thi B", "Ha Noi"), 3: ("Le Van C", "Da Nang")}

random.seed(42)  # cố định để lần nào tạo cũng ra cùng dữ liệu


def make_user(i: int):
    name, city = FIXED_USERS.get(i) or (f"{random.choice(HO)} {random.choice(DEM)} {random.choice(TEN)}",
                                        random.choice(CITIES))
    joined = date(2020, 1, 1) + timedelta(days=random.randint(0, 2000))
    return (i, name, f"user{i}@example.com", f"09{random.randint(10_000_000, 99_999_999)}", city,
            f"{random.randint(1, 500)} {random.choice(STREETS)}, {city}", joined.isoformat())


def make_order(_):
    day = date(2024, 1, 1) + timedelta(days=random.randint(0, 1000))
    return (random.randint(1, N_USERS), random.randint(1, N_PRODUCTS),
            random.randint(1, 200) * 5000, day.isoformat())


def main():
    # ghi ra file tạm, xong hết mới đổi tên => không bao giờ để lại shop.db dở dang
    tmp = DB_PATH.with_name(DB_PATH.name + ".tmp")
    tmp.unlink(missing_ok=True)
    db = sqlite3.connect(tmp)
    db.executescript("""
        CREATE TABLE products (
            id       INTEGER PRIMARY KEY,
            name     TEXT NOT NULL,
            category TEXT NOT NULL,
            price    INTEGER NOT NULL
        );
        CREATE TABLE reviews (
            id         INTEGER PRIMARY KEY,
            product_id INTEGER NOT NULL,
            rating     INTEGER NOT NULL,
            comment    TEXT NOT NULL
        );
        CREATE TABLE users (
            id         INTEGER PRIMARY KEY,
            name       TEXT NOT NULL,
            email      TEXT NOT NULL,
            phone      TEXT NOT NULL,
            city       TEXT NOT NULL,
            address    TEXT NOT NULL,
            created_at TEXT NOT NULL
        );
        -- cố ý KHÔNG đánh index user_id: mỗi lần xem hồ sơ phải quét 1 triệu đơn => truy vấn tốn kém thật
        CREATE TABLE orders (
            id         INTEGER PRIMARY KEY,
            user_id    INTEGER NOT NULL,
            product_id INTEGER NOT NULL,
            amount     INTEGER NOT NULL,
            created_at TEXT NOT NULL
        );
    """)

    db.executemany(
        "INSERT INTO products VALUES (?, ?, ?, ?)",
        [(i, f"Sản phẩm {i}", f"Danh mục {i % N_CATEGORIES + 1}", random.randint(10, 500) * 1000)
         for i in range(1, N_PRODUCTS + 1)],
    )
    db.executemany(
        "INSERT INTO reviews (product_id, rating, comment) VALUES (?, ?, ?)",
        [(random.randint(1, N_PRODUCTS), random.randint(1, 5), f"Nhận xét số {i}")
         for i in range(N_REVIEWS)],
    )
    print(f"  {N_PRODUCTS:,} sản phẩm, {N_REVIEWS:,} đánh giá")

    db.executemany("INSERT INTO users VALUES (?, ?, ?, ?, ?, ?, ?)", map(make_user, range(1, N_USERS + 1)))
    print(f"  {N_USERS:,} người dùng")
    db.executemany("INSERT INTO orders (user_id, product_id, amount, created_at) VALUES (?, ?, ?, ?)",
                   map(make_order, range(N_ORDERS)))
    print(f"  {N_ORDERS:,} đơn hàng")

    db.commit()
    db.close()
    tmp.replace(DB_PATH)
    print(f"Đã tạo {DB_PATH.name} ({DB_PATH.stat().st_size / 1_000_000:.0f} MB)")


if __name__ == "__main__":
    main()
