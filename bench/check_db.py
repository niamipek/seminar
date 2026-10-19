"""Kiểm tra database bench/shop.db đã được tạo đúng chưa.

Chạy: python bench/check_db.py
"""
import os
import sqlite3
import sys
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8")

DB_PATH = Path(os.getenv("SHOP_DB", Path(__file__).with_name("shop.db")))  # Docker: SHOP_DB=/data/shop.db

if not DB_PATH.exists():
    sys.exit(f"❌ Chưa có {DB_PATH.name}. Chạy:  python bench/seed_db.py")

db = sqlite3.connect(DB_PATH)
print(f"✅ File: {DB_PATH}  ({DB_PATH.stat().st_size / 1_000_000:.1f} MB)")

tables = [t for (t,) in db.execute("SELECT name FROM sqlite_master WHERE type='table' ORDER BY name")]
print(f"✅ Các bảng: {', '.join(tables)}")

ok = True
for table, expected in (("products", 1000), ("reviews", 300_000), ("users", 200_000), ("orders", 1_000_000)):
    if table not in tables:
        print(f"❌ Thiếu bảng {table}")
        ok = False
        continue
    n = db.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
    mark = "✅" if n == expected else "❌"
    ok &= n == expected
    print(f"{mark} Bảng {table}: {n:,} dòng (mong đợi {expected:,})")

if ok:
    print("\nVài dòng mẫu trong bảng products:")
    for row in db.execute("SELECT id, name, category, price FROM products LIMIT 3"):
        print("  ", row)
    print("Vài dòng mẫu trong bảng reviews:")
    for row in db.execute("SELECT id, product_id, rating, comment FROM reviews LIMIT 3"):
        print("  ", row)
    cnt, avg = db.execute(
        "SELECT COUNT(*), ROUND(AVG(rating), 2) FROM reviews WHERE product_id = 42").fetchone()
    print(f"Sản phẩm 42 có {cnt} đánh giá, điểm trung bình {avg}")
    print("Người dùng 1 (Demo 1):", db.execute("SELECT id, name, city FROM users WHERE id = 1").fetchone(),
          "- số đơn hàng:", db.execute("SELECT COUNT(*) FROM orders WHERE user_id = 1").fetchone()[0])
    print("\n🎉 Database đã sẵn sàng.")
else:
    print("\nDatabase chưa đúng. Tạo lại bằng:  python bench/seed_db.py")
