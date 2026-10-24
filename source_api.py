import json
import os
import secrets
import sqlite3
import threading
import time
from pathlib import Path

import redis
from fastapi import FastAPI, Header, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse

app = FastAPI()
# cho phép trang demo ở cổng 3000 gọi sang server cổng 3001 (khác origin)
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])
# địa chỉ Redis: mặc định localhost; khi chạy bằng Docker Compose thì REDIS_HOST=redis
r = redis.Redis(host=os.getenv("REDIS_HOST", "localhost"), port=int(os.getenv("REDIS_PORT", "6379")), db=0)

# địa chỉ Memcached: mặc định localhost; khi chạy bằng Docker Compose thì MEMCACHED_HOST=memcached
try:
    from pymemcache.client.base import Client as MemcacheClient
    MC_HOST = os.getenv("MEMCACHED_HOST", "localhost")
    MC_PORT = int(os.getenv("MEMCACHED_PORT", "11211"))
    mc = MemcacheClient((MC_HOST, MC_PORT), connect_timeout=1, timeout=1)
    MC_AVAILABLE = True
except Exception:
    mc = None
    MC_AVAILABLE = False


def check_memcached_ok():
    if not MC_AVAILABLE or mc is None:
        return False, "pymemcache chưa sẵn sàng"
    try:
        mc.stats()
        return True, "ok"
    except Exception as e:
        return False, str(e)

SESSION_TTL = 500  # giây, cố định kể từ lúc đăng nhập (không gia hạn)

# "Database" giả: 3 người dùng
USERS = {
    "1": {"id": 1, "name": "Nguyen Van A", "city": "Ho Chi Minh"},
    "2": {"id": 2, "name": "Tran Thi B", "city": "Ha Noi"},
    "3": {"id": 3, "name": "Le Van C", "city": "Da Nang"},
}


# ---------- Nguồn dữ liệu (dùng cho demo caching) ----------

@app.get("/api/users")
def list_users():
    return list(USERS.values())


@app.get("/api/users/{user_id}")
def get_user(user_id: str):
    time.sleep(0)  # giả lập nguồn dữ liệu chậm 2 giây
    user = USERS.get(user_id)
    if user is None:
        raise HTTPException(status_code=404, detail="not found")
    return user


# ---------- Session storage (Redis + TTL) ----------

SESSION_INDEX = "demo:session-index"   # danh sách session_id đã tạo (phục vụ trang demo)


def session_key(session_id: str) -> str:
    return f"session:{session_id}"


def get_session(session_id: str | None) -> dict:
    """Trả về dữ liệu session, hoặc 401 nếu không có / đã hết hạn."""
    if not session_id:
        raise HTTPException(status_code=401, detail="thiếu session_id")
    data = r.get(session_key(session_id))
    if data is None:
        raise HTTPException(status_code=401, detail="session không tồn tại hoặc đã hết hạn")
    return json.loads(data)


def served_by(request: Request) -> str:
    """Cho biết server nào (cổng nào) đã xử lý yêu cầu."""
    return f"localhost:{request.url.port}"


@app.post("/login")
def login(user_id: str, request: Request):
    user = USERS.get(user_id)
    if user is None:
        raise HTTPException(status_code=404, detail="user không tồn tại")
    session_id = secrets.token_urlsafe(32)
    r.set(session_key(session_id), json.dumps(user), ex=SESSION_TTL)
    r.zadd(SESSION_INDEX, {session_id: time.time()})   # chỉ để khung "Bên trong Redis" tìm nhanh session
    return {"session_id": session_id, "expires_in": SESSION_TTL,
            "served_by": served_by(request)}


@app.get("/profile")
def profile(request: Request, x_session_id: str | None = Header(default=None)):
    return {**get_session(x_session_id), "served_by": served_by(request)}


@app.get("/session/ttl")
def session_ttl(x_session_id: str | None = Header(default=None)):
    get_session(x_session_id)
    return {"ttl_seconds": r.ttl(session_key(x_session_id))}


@app.post("/logout")
def logout(request: Request, x_session_id: str | None = Header(default=None)):
    get_session(x_session_id)
    r.delete(session_key(x_session_id))
    return {"message": "đã đăng xuất", "served_by": served_by(request)}


# ---------- Đối chứng: session lưu trong RAM của từng server (KHÔNG dùng Redis) ----------
# Mỗi tiến trình server có dict riêng => server khác không thấy session này.

MEMORY_SESSIONS: dict[str, dict] = {}


@app.post("/memory/login")
def memory_login(user_id: str, request: Request):
    user = USERS.get(user_id)
    if user is None:
        raise HTTPException(status_code=404, detail="user không tồn tại")
    session_id = secrets.token_urlsafe(32)
    MEMORY_SESSIONS[session_id] = user
    return {"session_id": session_id, "served_by": served_by(request)}


@app.get("/memory/profile")
def memory_profile(request: Request, x_session_id: str | None = Header(default=None)):
    user = MEMORY_SESSIONS.get(x_session_id or "")
    if user is None:
        raise HTTPException(status_code=401, detail=f"server {served_by(request)} không có session này trong RAM")
    return {**user, "served_by": served_by(request)}


@app.post("/memory/logout")
def memory_logout(request: Request, x_session_id: str | None = Header(default=None)):
    if MEMORY_SESSIONS.pop(x_session_id or "", None) is None:
        raise HTTPException(status_code=401, detail=f"server {served_by(request)} không có session này trong RAM")
    return {"message": "đã đăng xuất", "served_by": served_by(request)}


# ---------- Trang demo trực quan (phục vụ thuyết trình) ----------

CACHE_TTL = 1800  # giây (30 phút): đủ dài để cache không hết hạn giữa buổi thuyết trình
USER_COUNT = 200_000

# Hồ sơ người dùng lấy từ database thật (bench/shop.db, tạo bằng python bench/seed_db.py).
# Bảng orders có 1 triệu dòng và KHÔNG có index user_id => mỗi lần MISS database phải quét toàn bộ.
USER_SQL = "SELECT id, name, email, phone, city, address, created_at FROM users WHERE id = ?"
USER_STATS_SQL = "SELECT COUNT(*), COALESCE(SUM(amount), 0) FROM orders WHERE user_id = ?"
USER_RECENT_SQL = """
    SELECT o.id, p.name, o.amount, o.created_at
    FROM orders o JOIN products p ON p.id = o.product_id
    WHERE o.user_id = ? ORDER BY o.created_at DESC, o.id DESC LIMIT 3"""


def build_profile(user_row, order_count, total_spent, recent) -> dict:
    uid, name, email, phone, city, address, created_at = user_row
    return {"id": uid, "name": name, "email": email, "phone": phone, "city": city,
            "address": address, "member_since": created_at,
            "order_count": order_count, "total_spent": total_spent,
            "recent_orders": [{"order_id": o, "product": p, "amount": a, "date": d}
                              for o, p, a, d in recent]}


def query_user_profile(user_id: int) -> dict:
    """Truy vấn database (~200-300 ms): thông tin + tổng đơn + tổng tiền + 3 đơn gần nhất."""
    db = _db()
    user = db.execute(USER_SQL, (user_id,)).fetchone()
    if user is None:
        raise HTTPException(status_code=404, detail=f"không có người dùng {user_id} (1..{USER_COUNT})")
    count, total = db.execute(USER_STATS_SQL, (user_id,)).fetchone()
    return build_profile(user, count, total, db.execute(USER_RECENT_SQL, (user_id,)).fetchall())


def dump_profile(profile: dict) -> str:
    return json.dumps(profile, ensure_ascii=False)


@app.get("/", include_in_schema=False)
def demo_page():
    return FileResponse(Path(__file__).with_name("demo.html"))


@app.get("/demo/cache/{user_id}")
def demo_cache(user_id: int):
    """Cache-aside: hỏi Redis trước, MISS thì truy vấn database rồi TỰ LƯU vào Redis."""
    start = time.perf_counter()
    key = f"user:{user_id}"
    cached = r.get(key)
    if cached is not None:
        source, data = "redis", json.loads(cached)
    else:
        data = query_user_profile(user_id)
        r.set(key, dump_profile(data), ex=CACHE_TTL)
        source = "db"
    return {"source": source, "ms": round((time.perf_counter() - start) * 1000, 2),
            "data": data, "ttl": CACHE_TTL}


@app.get("/demo/db/user/{user_id}")
def demo_db_user(user_id: int):
    """KHÔNG dùng Redis: lần nào cũng truy vấn database (để so sánh với /demo/cache)."""
    start = time.perf_counter()
    data = query_user_profile(user_id)
    return {"source": "db", "ms": round((time.perf_counter() - start) * 1000, 2), "data": data}


@app.post("/demo/cache/import")
def demo_import_cache():
    """Cache warming: tính sẵn hồ sơ của TẤT CẢ người dùng và nạp vào Redis (~100 MB).

    Thay vì 200.000 truy vấn riêng lẻ (~13 giờ), đọc bảng orders MỘT lượt rồi tính hết trong Python.
    """
    start = time.perf_counter()
    db = _db()
    products = dict(db.execute("SELECT id, name FROM products"))
    stats: dict[int, list] = {}   # user_id -> [số đơn, tổng tiền, các đơn gần nhất]
    for uid, oid, pid, amount, created in db.execute(
            "SELECT user_id, id, product_id, amount, created_at FROM orders"):
        s = stats.setdefault(uid, [0, 0, []])
        s[0] += 1
        s[1] += amount
        s[2].append((created, oid, pid, amount))
        if len(s[2]) > 3:   # chỉ giữ 3 đơn mới nhất (cùng thứ tự với USER_RECENT_SQL)
            s[2].remove(min(s[2]))
    for s in stats.values():
        s[2] = [(oid, products[pid], amount, created)
                for created, oid, pid, amount in sorted(s[2], reverse=True)]

    pipe = r.pipeline(transaction=False)
    n = 0
    for user in db.execute("SELECT id, name, email, phone, city, address, created_at FROM users"):
        count, total, recent = stats.get(user[0], (0, 0, []))
        pipe.set(f"user:{user[0]}", dump_profile(build_profile(user, count, total, recent)), ex=CACHE_TTL)
        n += 1
        if n % 10_000 == 0:   # gửi theo lô 10.000 lệnh để giảm số lượt đi-về mạng
            pipe.execute()
    pipe.execute()
    return {"imported": n, "seconds": round(time.perf_counter() - start, 1), **redis_totals()}


@app.delete("/demo/cache")
def demo_clear_cache():
    deleted, batch = 0, []
    for k in r.scan_iter("user:*", count=10_000):
        batch.append(k)
        if len(batch) == 10_000:
            deleted += r.unlink(*batch)
            batch.clear()
    if batch:
        deleted += r.unlink(*batch)
    return {"deleted": deleted}


def redis_totals() -> dict:
    mem = r.info("memory")
    return {"total_keys": r.dbsize(), "used_memory_mb": round(mem["used_memory"] / 1_000_000, 1)}


@app.get("/demo/redis")
def demo_redis():
    """Một vài key mẫu (session trước, rồi tới cache) + tổng số key và RAM Redis đang dùng.

    Không liệt kê hết: Redis có thể chứa 200.000 key, đọc hết mỗi giây sẽ làm chậm cả hệ thống.
    """
    # session: đọc từ danh sách riêng thay vì dò cả 200.000 key; bỏ các session đã hết hạn / đăng xuất
    sessions = []
    for sid in r.zrevrange(SESSION_INDEX, 0, 19):
        if r.exists(session_key(sid.decode())):
            sessions.append(session_key(sid.decode()).encode())
        else:
            r.zrem(SESSION_INDEX, sid)
    sessions = sessions[:5]
    users = []
    for k in r.scan_iter("user:*", count=1000):
        users.append(k)
        if len(users) >= 10:
            break
    items = []
    for k in sessions + sorted(users, key=lambda k: int(k.split(b":")[1])):
        v = r.get(k)
        if v is not None:
            items.append({"key": k.decode(), "ttl": r.ttl(k), "value": v.decode()})
    return {"items": items, **redis_totals()}


# ---------- Demo "Lệch dữ liệu": Redis khác Database khi 2 request cùng ghi ----------
# A và B là 2 request HTTP thật chạy song song, cùng đổi giá sản phẩm 7.
# A bị chậm cố ý ở giữa (mô phỏng sự cố: mạng chậm, server khựng) để tái hiện được mỗi lần chạy.

RACE_PRODUCT = 7
RACE_KEY = f"price:{RACE_PRODUCT}"
RACE_START_PRICE = 50_000
RACE_STRATEGIES = {
    "s1": "Set cache → ghi DB",
    "s2": "Ghi DB → set cache",
    "s3": "Ghi DB → xóa cache",
}
_race_lock = threading.Lock()
_race = {"t0": time.perf_counter(), "events": []}


def race_db_price() -> int:
    return _db().execute("SELECT price FROM products WHERE id = ?", (RACE_PRODUCT,)).fetchone()[0]


def race_redis_price() -> int | None:
    v = r.get(RACE_KEY)
    return int(v) if v is not None else None


def race_log(who: str, action: str, late: bool = False):
    """Ghi lại 1 bước kèm giá trị THẬT trong Redis và DB ngay sau bước đó."""
    with _race_lock:
        _race["events"].append({
            "t": round(time.perf_counter() - _race["t0"], 2), "who": who, "action": action, "late": late,
            "redis": race_redis_price(), "db": race_db_price()})


def race_write_db(price: int):
    db = _db()
    db.execute("UPDATE products SET price = ? WHERE id = ?", (price, RACE_PRODUCT))
    db.commit()


@app.post("/demo/race/reset")
def race_reset():
    race_write_db(RACE_START_PRICE)
    r.delete(RACE_KEY)
    with _race_lock:
        _race["t0"], _race["events"] = time.perf_counter(), []
    race_log("Hệ thống", f"Đặt lại: DB = {RACE_START_PRICE:,}, xóa cache")
    return race_state()


@app.post("/demo/race/write")
def race_write(who: str, price: int, strategy: str, delay: float = 0):
    """Một request cập nhật giá theo chiến lược đã chọn. delay > 0: bị chậm giữa 2 bước."""
    if strategy not in RACE_STRATEGIES:
        raise HTTPException(status_code=400, detail="strategy phải là s1, s2 hoặc s3")
    late = delay > 0

    # bước 1
    if strategy == "s1":
        r.set(RACE_KEY, price)
        race_log(who, f"set Redis = {price:,}")
    else:
        race_write_db(price)
        race_log(who, f"ghi DB = {price:,}")

    if late:
        race_log(who, f"bị chậm {delay} giây (mô phỏng sự cố)…")
        time.sleep(delay)

    # bước 2
    if strategy == "s1":
        race_write_db(price)
        race_log(who, f"ghi DB = {price:,}", late)
    elif strategy == "s2":
        r.set(RACE_KEY, price)
        race_log(who, f"set Redis = {price:,}", late)
    else:
        r.delete(RACE_KEY)
        race_log(who, "xóa Redis", late)
    return {"who": who, "done": True}


@app.get("/demo/race/read")
def race_read():
    """Người dùng xem giá: cache-aside (Redis có thì dùng, MISS thì đọc DB rồi lưu vào Redis)."""
    cached = race_redis_price()
    if cached is not None:
        race_log("Người đọc", f"đọc Redis → HIT = {cached:,}")
        return {"price": cached, "source": "redis"}
    price = race_db_price()
    r.set(RACE_KEY, price)
    race_log("Người đọc", f"đọc Redis → MISS → đọc DB = {price:,} → lưu vào Redis")
    return {"price": price, "source": "db"}


@app.get("/demo/race/state")
def race_state():
    with _race_lock:
        events = list(_race["events"])
    return {"redis": race_redis_price(), "db": race_db_price(), "events": events}


# ---------- Demo 4: So sánh Redis vs Memcached ----------

def get_memcached_stats():
    ok, _ = check_memcached_ok()
    if not ok:
        return {"status": "offline", "error": "Memcached chưa kết nối được (kiểm tra cổng 11211)"}
    try:
        st = mc.stats()
        curr_items = int(st.get(b"curr_items", st.get("curr_items", 0)))
        bytes_val = int(st.get(b"bytes", st.get("bytes", 0)))
        uptime_val = int(st.get(b"uptime", st.get("uptime", 0)))
        threads_val = int(st.get(b"threads", st.get("threads", 4)))
        curr_conn = int(st.get(b"curr_connections", st.get("curr_connections", 0)))
        ver_raw = st.get(b"version", st.get("version", b"1.6"))
        ver = ver_raw.decode("latin1") if isinstance(ver_raw, bytes) else str(ver_raw)
        return {
            "status": "online",
            "curr_items": curr_items,
            "used_memory_mb": round(bytes_val / 1_000_000, 3),
            "uptime_seconds": uptime_val,
            "version": ver,
            "threads": threads_val,
            "curr_connections": curr_conn,
            "data_structures": "Pure Key-Value (String / Bytes)",
            "persistence": "Không (Volatile - mất khi restart)",
            "threading": "Multi-threaded (tận dụng đa lõi CPU)"
        }
    except Exception as e:
        return {"status": "offline", "error": f"Lỗi đọc Memcached: {e}"}


@app.get("/demo/compare/stats")
def compare_stats():
    mem = r.info("memory")
    srv = r.info("server")
    cli = r.info("clients")
    redis_data = {
        "status": "online",
        "total_keys": r.dbsize(),
        "used_memory_mb": round(mem.get("used_memory", 0) / 1_000_000, 2),
        "uptime_seconds": srv.get("uptime_in_seconds", 0),
        "version": srv.get("redis_version", "7.4"),
        "connected_clients": cli.get("connected_clients", 1),
        "threads": 1,
        "data_structures": "Strings, Hashes, Lists, Sets, ZSets, Streams...",
        "persistence": "RDB + AOF (Durable)",
        "threading": "Single-thread event loop (I/O threads)"
    }
    mc_data = get_memcached_stats()
    return {"redis": redis_data, "memcached": mc_data}


@app.post("/demo/compare/speed")
def compare_speed(n: int = 500):
    """Đo thời gian ghi và đọc tuần tự n items để so sánh latency và ops/sec."""
    n = max(10, min(n, 2000))
    data = {f"cmp_k_{i}": f"sample_val_{i}_{time.time()}" for i in range(n)}

    # 1. Đo Redis
    t0 = time.perf_counter()
    for k, v in data.items():
        r.set(k, v, ex=120)
    r_w_time = (time.perf_counter() - t0) * 1000

    t0 = time.perf_counter()
    for k in data.keys():
        _ = r.get(k)
    r_r_time = (time.perf_counter() - t0) * 1000

    # Dọn dẹp key Redis
    pipe = r.pipeline(transaction=False)
    for k in data.keys():
        pipe.delete(k)
    pipe.execute()

    # 2. Đo Memcached
    mc_ok, _ = check_memcached_ok()
    if mc_ok:
        try:
            t0 = time.perf_counter()
            for k, v in data.items():
                mc.set(k, v, expire=120, noreply=False)
            mc_w_time = (time.perf_counter() - t0) * 1000

            t0 = time.perf_counter()
            for k in data.keys():
                _ = mc.get(k)
            mc_r_time = (time.perf_counter() - t0) * 1000

            for k in data.keys():
                mc.delete(k, noreply=False)

            mc_result = {
                "status": "ok",
                "write_ms": round(mc_w_time, 2),
                "read_ms": round(mc_r_time, 2),
                "write_ops": round(n / (mc_w_time / 1000)) if mc_w_time > 0 else 0,
                "read_ops": round(n / (mc_r_time / 1000)) if mc_r_time > 0 else 0,
            }
        except Exception as e:
            mc_result = {"status": "error", "error": str(e)}
    else:
        mc_result = {"status": "error", "error": "Memcached chưa sẵn sàng"}

    return {
        "n": n,
        "redis": {
            "status": "ok",
            "write_ms": round(r_w_time, 2),
            "read_ms": round(r_r_time, 2),
            "write_ops": round(n / (r_w_time / 1000)) if r_w_time > 0 else 0,
            "read_ops": round(n / (r_r_time / 1000)) if r_r_time > 0 else 0,
        },
        "memcached": mc_result
    }


@app.post("/demo/compare/datastruct")
def compare_datastruct():
    """So sánh: Cập nhật 1 trường (partial update) trong một User Profile lớn."""
    profile = {
        "id": "1001",
        "name": "Nguyen Van A",
        "email": "nguyenvana@example.com",
        "city": "Ho Chi Minh",
        "address": "123 Le Loi, Quan 1, TP.HCM",
        "points": 1500,
        "level": "Gold Member",
        "bio": "Khách hàng thân thiết từ năm 2021, có 45 đơn hàng.",
        "preferences": "Đồ công nghệ, giao hàng nhanh, thông báo SMS.",
        "security_tags": "verified, 2fa_enabled, phone_confirmed"
    }

    # 1. Thao tác trên Redis (dùng Native Hash)
    r_key = "profile:hash:1001"
    r.hset(r_key, mapping={k: str(v) for k, v in profile.items()})

    t0 = time.perf_counter()
    new_points = r.hincrby(r_key, "points", 10)
    r_elapsed_us = round((time.perf_counter() - t0) * 1_000_000, 2)
    r_network_bytes = len("HINCRBY profile:hash:1001 points 10") + len(str(new_points))

    # 2. Thao tác trên Memcached (String JSON)
    mc_ok, _ = check_memcached_ok()
    if mc_ok:
        try:
            mc_key = "profile:json:1001"
            initial_json = json.dumps(profile, ensure_ascii=False)
            mc.set(mc_key, initial_json.encode("utf-8"))

            t0 = time.perf_counter()
            # Bước 1: GET toàn bộ JSON lớn về
            raw_data = mc.get(mc_key)
            # Bước 2: Parse JSON
            obj = json.loads(raw_data if isinstance(raw_data, str) else raw_data.decode("utf-8"))
            # Bước 3: Sửa trường points
            obj["points"] += 10
            # Bước 4: Dump JSON
            updated_json = json.dumps(obj, ensure_ascii=False)
            # Bước 5: SET toàn bộ JSON lớn trở lại
            mc.set(mc_key, updated_json.encode("utf-8"))
            mc_elapsed_us = round((time.perf_counter() - t0) * 1_000_000, 2)

            raw_len = len(raw_data) if isinstance(raw_data, (bytes, str)) else 0
            updated_bytes = updated_json.encode("utf-8")
            mc_network_bytes = (len(f"get {mc_key}\r\n") + raw_len +
                                len(f"set {mc_key} 0 0 {len(updated_bytes)}\r\n") +
                                len(updated_bytes) + len(b"STORED\r\n"))

            mc_info = {
                "status": "ok",
                "method": "5 bước: GET full JSON -> Parse dict -> Sửa field -> Dump JSON -> SET full JSON",
                "steps": 5,
                "network_bytes": mc_network_bytes,
                "elapsed_us": mc_elapsed_us,
                "new_points": obj["points"]
            }
        except Exception as e:
            mc_info = {"status": "error", "error": str(e)}
    else:
        mc_info = {"status": "error", "error": "Memcached chưa sẵn sàng"}

    saved_bytes = (mc_info.get("network_bytes", 1200) - r_network_bytes) if mc_info.get("status") == "ok" else 0
    saved_percent = round((saved_bytes / mc_info["network_bytes"]) * 100, 1) if mc_info.get("status") == "ok" and mc_info.get("network_bytes", 0) > 0 else 0

    return {
        "task": "Tăng trường points (+10) trong hồ sơ User (10 thuộc tính, ~1.2 KB)",
        "redis": {
            "method": "1 bước duy nhất: HINCRBY profile:hash:1001 points 10 (thực thi trên RAM của server)",
            "steps": 1,
            "network_bytes": r_network_bytes,
            "elapsed_us": r_elapsed_us,
            "new_points": new_points
        },
        "memcached": mc_info,
        "bandwidth_saved_percent": saved_percent
    }


@app.post("/demo/compare/flush")
def compare_flush():
    mc_ok, _ = check_memcached_ok()
    mc_msg = "Chưa kết nối"
    if mc_ok:
        try:
            mc.flush_all()
            mc_msg = "Đã xóa sạch Memcached (flush_all)"
        except Exception as e:
            mc_msg = f"Lỗi: {e}"
    cmp_keys = list(r.scan_iter("cmp_*")) + list(r.scan_iter("profile:*"))
    if cmp_keys:
        r.delete(*cmp_keys)
    return {"message": "Đã dọn dẹp dữ liệu so sánh", "redis_keys_deleted": len(cmp_keys), "memcached": mc_msg}


# ---------- Demo 3: Benchmark có Redis / không Redis (database SQLite thật) ----------
# Tạo dữ liệu trước: python bench/seed_db.py

SHOP_DB = Path(os.getenv("SHOP_DB", Path(__file__).parent / "bench" / "shop.db"))
BENCH_CACHE_TTL = 60  # giây
_local = threading.local()          # mỗi luồng một kết nối SQLite
_stats_lock = threading.Lock()
bench_stats = {"db_queries": 0, "cache_hits": 0, "cache_misses": 0}

PRODUCT_SQL = """
    SELECT p.id, p.name, p.category, p.price, COUNT(r.id), ROUND(AVG(r.rating), 2)
    FROM products p LEFT JOIN reviews r ON r.product_id = p.id
    WHERE p.id = ? GROUP BY p.id"""
SIMILAR_SQL = """
    SELECT p.id, p.name, ROUND(AVG(r.rating), 2) AS avg_rating
    FROM products p JOIN reviews r ON r.product_id = p.id
    WHERE p.category = ? AND p.id <> ?
    GROUP BY p.id ORDER BY avg_rating DESC LIMIT 5"""


def _db() -> sqlite3.Connection:
    if not hasattr(_local, "conn"):
        _local.conn = sqlite3.connect(SHOP_DB)
    return _local.conn


def _count(name: str):
    with _stats_lock:
        bench_stats[name] += 1


def query_product_page(product_id: int) -> dict:
    """Truy vấn NẶNG (~100 ms): thông tin + điểm đánh giá + 5 sản phẩm tương tự cùng danh mục."""
    _count("db_queries")
    row = _db().execute(PRODUCT_SQL, (product_id,)).fetchone()
    if row is None:
        raise HTTPException(status_code=404, detail="not found")
    similar = _db().execute(SIMILAR_SQL, (row[2], product_id)).fetchall()
    return {"id": row[0], "name": row[1], "category": row[2], "price": row[3],
            "review_count": row[4], "avg_rating": row[5],
            "similar": [{"id": s[0], "name": s[1], "avg_rating": s[2]} for s in similar]}


def query_product_light(product_id: int) -> dict:
    """Truy vấn NHẸ (<1 ms): lấy 1 dòng theo khóa chính."""
    _count("db_queries")
    row = _db().execute("SELECT id, name, category, price FROM products WHERE id = ?",
                        (product_id,)).fetchone()
    if row is None:
        raise HTTPException(status_code=404, detail="not found")
    return {"id": row[0], "name": row[1], "category": row[2], "price": row[3]}


def cached(key: str, loader, *args) -> dict:
    """Cache-aside: hỏi Redis trước, MISS thì gọi loader (database) rồi lưu lại."""
    hit = r.get(key)
    if hit is not None:
        _count("cache_hits")
        return json.loads(hit)
    _count("cache_misses")
    data = loader(*args)
    r.set(key, json.dumps(data), ex=BENCH_CACHE_TTL)
    return data


@app.get("/products/{product_id}")
def product_no_cache(product_id: int):
    return query_product_page(product_id)


@app.get("/products-cached/{product_id}")
def product_cached(product_id: int):
    return cached(f"product:{product_id}", query_product_page, product_id)


@app.get("/products-light/{product_id}")
def product_light_no_cache(product_id: int):
    return query_product_light(product_id)


@app.get("/products-light-cached/{product_id}")
def product_light_cached(product_id: int):
    return cached(f"product-light:{product_id}", query_product_light, product_id)


@app.get("/bench/stats")
def get_bench_stats():
    with _stats_lock:
        s = dict(bench_stats)
    total = s["cache_hits"] + s["cache_misses"]
    s["hit_rate"] = round(s["cache_hits"] / total * 100, 1) if total else None
    return s


@app.post("/bench/reset")
def reset_bench(flush_cache: bool = True):
    """Đưa bộ đếm về 0 và (mặc định) xóa cache sản phẩm để bắt đầu lần đo mới."""
    with _stats_lock:
        for k in bench_stats:
            bench_stats[k] = 0
    deleted = 0
    if flush_cache:
        keys = list(r.scan_iter("product*"))
        if keys:
            deleted = r.delete(*keys)
    return {"reset": True, "cache_keys_deleted": deleted}


if __name__ == "__main__":
    import sys
    import uvicorn
    # chạy nhiều server: python source_api.py 3000  |  python source_api.py 3001
    port = int(sys.argv[1]) if len(sys.argv) > 1 else 5000
    uvicorn.run("source_api:app", port=port, reload=True)
