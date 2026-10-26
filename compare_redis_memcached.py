"""Script chạy độc lập trên Terminal để so sánh nhanh Redis vs Memcached.

Chạy:
    python compare_redis_memcached.py
"""
import os
import sys
import time
import json

sys.stdout.reconfigure(encoding="utf-8")

REDIS_HOST = os.getenv("REDIS_HOST", "localhost")
REDIS_PORT = int(os.getenv("REDIS_PORT", "6379"))
MC_HOST = os.getenv("MEMCACHED_HOST", "localhost")
MC_PORT = int(os.getenv("MEMCACHED_PORT", "11211"))

print("=" * 65)
print("     SO SÁNH HIỆU NĂNG & ĐẶC TÍNH: REDIS VS MEMCACHED")
print("=" * 65)

# 1. Kết nối
print(f"[*] Đang kết nối Redis ({REDIS_HOST}:{REDIS_PORT})...", end=" ")
try:
    import redis
    r = redis.Redis(host=REDIS_HOST, port=REDIS_PORT, db=0)
    r.ping()
    print("✅ Thành công.")
except Exception as e:
    print(f"❌ Thất bại: {e}")
    sys.exit(1)

print(f"[*] Đang kết nối Memcached ({MC_HOST}:{MC_PORT})...", end=" ")
try:
    from pymemcache.client.base import Client as MemcacheClient
    mc = MemcacheClient((MC_HOST, MC_PORT), timeout=2, connect_timeout=2)
    mc.stats()
    print("✅ Thành công.")
except Exception as e:
    print(f"❌ Thất bại: {e}")
    print("  -> Hãy đảm bảo Memcached đang chạy (docker compose up hoặc docker run -d -p 11211:11211 memcached:alpine)")
    sys.exit(1)

# 2. Đo tốc độ ghi/đọc tuần tự 500 items
N = 500
print(f"\n--- 1. ĐO TỐC ĐỘ GHI VÀ ĐỌC ({N} items) ---")
test_data = {f"test_key_{i}": f"sample_val_{i}" for i in range(N)}

# Redis Write
t0 = time.perf_counter()
for k, v in test_data.items():
    r.set(k, v, ex=60)
r_write_ms = (time.perf_counter() - t0) * 1000

# Redis Read
t0 = time.perf_counter()
for k in test_data.keys():
    _ = r.get(k)
r_read_ms = (time.perf_counter() - t0) * 1000

# Memcached Write (noreply=False: đợi server xác nhận, giống Redis)
t0 = time.perf_counter()
for k, v in test_data.items():
    mc.set(k, v, expire=60, noreply=False)
mc_write_ms = (time.perf_counter() - t0) * 1000

# Memcached Read
t0 = time.perf_counter()
for k in test_data.keys():
    _ = mc.get(k)
mc_read_ms = (time.perf_counter() - t0) * 1000

print(f"{'Hệ thống':<15} | {'Thời gian Ghi':<15} | {'Thời gian Đọc':<15} | {'Throughput Đọc'}")
print("-" * 65)
print(f"{'Redis':<15} | {r_write_ms:>8.2f} ms     | {r_read_ms:>8.2f} ms     | {N/(r_read_ms/1000):>8.0f} ops/s")
print(f"{'Memcached':<15} | {mc_write_ms:>8.2f} ms     | {mc_read_ms:>8.2f} ms     | {N/(mc_read_ms/1000):>8.0f} ops/s")

# 3. Demo cấu trúc dữ liệu con (Partial update vs Full rewrite)
print("\n--- 2. CẬP NHẬT TRƯỜNG CON TRONG OBJECT (PARTIAL UPDATE) ---")
profile = {
    "id": "1001", "name": "Nguyen Van A", "city": "Ho Chi Minh",
    "points": 1000, "level": "VIP", "bio": "Khách hàng thường xuyên",
    "history": "10 giao dịch gần nhất...", "tags": "tech, books, coffee"
}

# Redis Hash
r_key = "cli:profile:1001"
r.hset(r_key, mapping={k: str(v) for k, v in profile.items()})
t0 = time.perf_counter()
r_pts = r.hincrby(r_key, "points", 10)
r_us = (time.perf_counter() - t0) * 1_000_000
r_bytes = len("HINCRBY cli:profile:1001 points 10") + len(str(r_pts))

# Memcached JSON
mc_key = "cli:profile:1001"
mc.set(mc_key, json.dumps(profile).encode("utf-8"), noreply=False)
t0 = time.perf_counter()
raw = mc.get(mc_key)
obj = json.loads(raw if isinstance(raw, str) else raw.decode("utf-8"))
obj["points"] += 10
updated_raw = json.dumps(obj).encode("utf-8")
mc.set(mc_key, updated_raw, noreply=False)
mc_us = (time.perf_counter() - t0) * 1_000_000
mc_bytes = len(f"get {mc_key}\r\n") + len(raw) + len(f"set {mc_key} 0 0 {len(updated_raw)}\r\n") + len(updated_raw) + 8

print(f"• Redis (Hash HINCRBY):")
print(f"  - Thao tác: 1 lệnh trực tiếp trên server RAM.")
print(f"  - Băng thông mạng: {r_bytes} bytes")
print(f"  - Thời gian xử lý: {r_us:.1f} µs")
print(f"\n• Memcached (Full JSON GET -> Parse -> Update -> SET):")
print(f"  - Thao tác: 5 bước qua lại giữa Client & Server.")
print(f"  - Băng thông mạng: {mc_bytes} bytes")
print(f"  - Thời gian xử lý: {mc_us:.1f} µs")
print(f"\n-> Tiết kiệm băng thông với Redis: {(mc_bytes - r_bytes)/mc_bytes * 100:.1f}%")

# Dọn dẹp
for k in test_data.keys():
    r.delete(k)
    mc.delete(k, noreply=False)
r.delete(r_key)
mc.delete(mc_key, noreply=False)
print("\n[+] Đã dọn dẹp các key thử nghiệm.")
print("=" * 65)
