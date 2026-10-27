# Seminar Redis: Caching · Session Storage · Lệch dữ liệu · So sánh Memcached

Trang web demo trực quan cho các ứng dụng và so sánh công nghệ cache:

| Tab | Demo | Cho thấy điều gì |
|---|---|---|
| **1. Caching** | Lấy hồ sơ người dùng từ database thật (SQLite: 200.000 người dùng, 1 triệu đơn hàng), có và không có Redis | Cache HIT nhanh hơn MISS hàng trăm lần; Redis chứa ~140 MB vẫn lấy 1 key dưới 1 ms |
| **2. Session storage** | 2 server (cổng 3000 và 3001) dùng chung Redis để lưu session | Đăng nhập ở Server A thì Server B vẫn nhận ra; lưu trong RAM riêng của từng server thì không |
| **3. Lệch dữ liệu** | 2 request cùng sửa giá sản phẩm, 1 request bị chậm | "Set cache → ghi DB" và "Ghi DB → set cache" đều làm Redis lệch với DB; "Ghi DB → xóa cache" thì khớp |
| **4. So sánh Redis vs Memcached** | Benchmark tốc độ đọc/ghi batch, cập nhật cấu trúc con (Hash vs String), giám sát realtime | So sánh toàn diện kiến trúc Single-thread vs Multi-thread, Native Data Structure vs Raw String, độ bền vững dữ liệu |

Ngoài ra có phần **benchmark bằng k6** (tùy chọn, xem cuối file).

---

## 1. Chạy nhanh bằng Docker (khuyên dùng)

### Cần cài
- [Docker Desktop](https://www.docker.com/products/docker-desktop/) (đã bật)
- [Git](https://git-scm.com/downloads)

Không cần cài Python, Redis hay Memcached: Docker lo hết.

### Chạy
```powershell
git clone https://github.com/niamipek/seminar.git
cd seminar
docker compose up --build
```
Lần đầu mất khoảng **1–3 phút** (tải image, cài thư viện, tạo database ~60 MB). Các lần sau chỉ khoảng 5 giây.
Khi thấy các dòng `server-a-1 ... Uvicorn running on http://0.0.0.0:3000` thì mở trình duyệt:

**http://localhost:3000/**

Docker Compose chạy 5 thành phần:

| Thành phần | Vai trò | Địa chỉ |
|---|---|---|
| `redis` | Redis server | `localhost:6379` |
| `memcached` | Memcached server | `localhost:11211` |
| `seed` | Tạo database lần đầu, xong thì tự tắt (các lần sau bỏ qua) | — |
| `server-a` | Server A | http://localhost:3000 |
| `server-b` | Server B (dùng cho demo 2) | http://localhost:3001 |

### Dừng, chạy lại, làm mới
```powershell
# dừng (Ctrl+C nếu đang chạy ở terminal, hoặc):
docker compose down

# chạy lại lần sau (nhanh, không cần --build nếu không sửa code):
docker compose up

# chạy nền, không chiếm terminal:
docker compose up -d

# sau khi sửa code: build lại
docker compose up --build

# xóa sạch database và tạo lại từ đầu:
docker compose down -v
docker compose up
```

---

## 2. Cách dùng các demo (4 tab)

Các con số dưới đây đo khi chạy bằng Docker; máy khác sẽ chênh một chút.

### Tab 1: Caching
Bấm **Xóa cache** trước nếu muốn bắt đầu từ trạng thái trống.

| # | Thao tác | Kết quả mong đợi |
|---|---|---|
| 1 | Nhập mã người dùng (mặc định `1`) → **Lấy dữ liệu** | **CACHE MISS ~200 ms**: database quét 1 triệu đơn hàng, server tự lưu kết quả vào Redis (`user:1`, TTL 10 phút) |
| 2 | Bấm **Lấy dữ liệu** lần nữa | **CACHE HIT ~1 ms**: lấy thẳng từ Redis, không gọi xuống database |
| 3 | Bấm **Xóa cache** | Xóa cache hồ sơ vừa lưu; lần lấy tiếp theo sẽ quay lại CACHE MISS |
| 4 | **① Truy vấn database 50 người** | Quét 50 người ngẫu nhiên trực tiếp từ database, mỗi người ~200 ms (không dùng Redis) |
| 5 | **② Import dữ liệu Redis** | Mất ~20–30 giây nạp hồ sơ 200.000 người (cache warming) → Redis chứa ~200.000 key, ~145 MB |
| 6 | **③ Truy vấn lại 50 người đó qua Redis** | 50/50 HIT, mỗi người ~1 ms. Bảng so sánh thời gian giữa ① và ③ hiện ra |

Khung **"Bên trong Redis"** bên phải hiển thị trực tiếp một số key, TTL và tổng số key / RAM đang dùng.

### Tab 2: Session storage
| # | Thao tác | Kết quả mong đợi |
|---|---|---|
| 1 | Chọn chế độ **RAM riêng của từng server** → **Đăng nhập** ở Server A → **Xem profile** ở Server B | **HTTP 401**: Server B không biết session do Server A tạo |
| 2 | Chọn chế độ **Redis (dùng chung)** → làm lại như trên | **HTTP 200**: Server B tra Redis và nhận ra người dùng |
| 3 | **Đăng xuất** ở Server B → **Xem profile** ở Server A | **HTTP 401**: đăng xuất ở một nơi là mất ở mọi nơi |

Server A và Server B là **2 container riêng biệt**, giống 2 máy chủ thật.

### Tab 3: Lệch dữ liệu
A đổi giá sản phẩm 7 thành 100.000 nhưng **bị chậm 1,5 giây** giữa 2 bước; B đổi thành 200.000, đến sau 0,3 giây. Kết quả đúng: cả DB và Redis đều là 200.000.

| Kịch bản | Kết quả |
|---|---|
| 1. Set cache → ghi DB | ❌ **LỆCH**: DB 100.000, Redis 200.000 |
| 2. Ghi DB → set cache | ❌ **LỆCH**: DB 200.000, Redis 100.000 |
| 3. Ghi DB → xóa cache | ✅ **KHỚP**: cả hai 200.000 |

Dòng thời gian hiển thị từng bước kèm giá trị **thật** đọc từ Redis và DB ngay sau bước đó; bước đến muộn được tô đỏ.

### Tab 4: So sánh Redis vs Memcached
Cả Redis và Memcached đều là hệ thống cache in-memory, nhưng khác biệt lớn ở kiến trúc và cấu trúc dữ liệu.

> 📘 Chi tiết về 7 tiêu chí so sánh chuyên sâu (Threading, Data Structure, Persistence...) và bộ câu hỏi phản biện xem tại: [redis_vs_memcached_guide.md](redis_vs_memcached_guide.md).

| # | Thao tác | Kết quả mong đợi |
|---|---|---|
| 1 | **Thử nghiệm 1: Đo tốc độ đọc**<br>Bấm **1.000 / 10.000 / 100.000 lượt xem** | Mô phỏng N lượt xem trang sản phẩm thật: SQLite (truy vấn nặng ~100 ms, ước tính từ 20 lần đo) vs Redis vs Memcached (đo thật qua socket). Cả hai cache nhanh hơn DB ~1.700 lần, chênh nhau chỉ vài % (cùng in-memory). Nút **Dọn dẹp dữ liệu test** để xóa cache test. |
| 2 | **Thử nghiệm 2: Cập nhật trường con (Partial Update vs Full Rewrite)**<br>Nhập User ID + Tên mới → bấm **Đổi tên** | Hồ sơ user thật từ SQLite (users + đơn hàng).<br>• **Redis** dùng `HSET` sửa đúng 1 trường (1 bước, ~70 byte qua mạng).<br>• **Memcached** phải GET → Parse → Sửa → Dump → SET cả hồ sơ (5 bước, ~1.700 byte với user 1).<br>Giao diện mô phỏng từng bước và số byte thật truyền tải qua mạng. |

Kết luận chính:
- **Tốc độ đọc/ghi đơn giản**: gần ngang nhau (cả hai đều in-memory).
- **Cấu trúc dữ liệu phong phú**: Redis thắng tuyệt đối (Hash, List, Set, Sorted Set...) — cho phép thao tác trực tiếp trên server mà không cần tải toàn bộ dữ liệu về client.
- **Độ bền vững (Persistence)**: Redis có RDB + AOF, Memcached mất sạch khi restart.
- **Memcached phù hợp**: cache tĩnh đơn giản, cần tận dụng multi-thread trên nhiều CPU core.

### Xem trực tiếp bên trong Redis và Memcached
```powershell
# Redis
docker compose exec redis redis-cli DBSIZE          # tổng số key
docker compose exec redis redis-cli GET user:1      # hồ sơ người dùng 1 trong cache
docker compose exec redis redis-cli TTL user:1      # còn sống bao nhiêu giây
docker compose exec redis redis-cli INFO memory     # dòng used_memory_human: RAM đang dùng

# Memcached
docker compose exec memcached sh -c 'echo stats | nc localhost 11211'   # thống kê Memcached
```

### Chạy so sánh trên terminal (không cần trình duyệt)
```powershell
# Nếu chạy bằng Docker Compose:
docker compose exec server-a python compare_redis_memcached.py

# Nếu chạy thủ công (môi trường ảo đã kích hoạt, Redis & Memcached đang chạy):
python compare_redis_memcached.py
```

### Ví dụ caching đơn giản trên terminal (caching.py)
File `caching.py` minh họa cơ chế Cache-Aside nguyên bản. Mặc định script gọi server tại cổng `5000`:
```powershell
python source_api.py 5000     # terminal 1: bật server (hoặc đổi URL trong caching.py sang cổng 3000)
python caching.py            # terminal 2: chạy demo đọc cache HIT / MISS
```

---

## 3. Chạy thủ công (không đóng gói app bằng Docker)

Dùng khi muốn sửa code và thấy thay đổi ngay (server tự reload).

### Cần cài
- Python **3.12**
- Docker Desktop (để chạy Redis và Memcached)

### Các bước (PowerShell, trong thư mục dự án)
```powershell
# 1. môi trường ảo + thư viện
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt

# 2. Redis & Memcached (lần đầu dùng "docker run", các lần sau chỉ cần "docker start redis memcached")
docker run -d --name redis -p 6379:6379 redis:7.4
docker run -d --name memcached -p 11211:11211 memcached:1.6-alpine
python connect_redis.py               # phải in ra: Response: True

# 3. tạo database (~20–60 giây, chỉ cần làm 1 lần)
python bench\seed_db.py
python bench\check_db.py              # kiểm tra: 4 bảng đều ✅

# 4. chạy 2 server (2 terminal riêng, đều đã Activate .venv)
python source_api.py 3000             # terminal 1: Server A
python source_api.py 3001             # terminal 2: Server B
```
Mở **http://localhost:3000/**.

*Lưu ý:*
- Nếu chỉ test Demo 1, 2, 3 và không dùng Tab 4, bạn có thể bỏ qua bước chạy Memcached.
- Không chạy cùng lúc cách này với `docker compose up` (cả hai cùng dùng cổng 3000, 3001, 6379, 11211).

---

## 4. (Tùy chọn) Benchmark bằng k6

Đo khả năng chịu tải: 50 người dùng ảo gửi request liên tục, so sánh có Redis và không có Redis.

### Cài k6
```powershell
winget install GrafanaLabs.k6
```
Cài xong, **đóng hẳn và mở lại VS Code / terminal** để lệnh `k6` được nhận.

### Chạy trực tiếp (50 người dùng × 10 giây, không Redis rồi có Redis)
Cần server đang chạy ở cổng 3000 (bằng Docker hoặc thủ công), rồi:
```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File bench\live.ps1
```
Đọc 3 dòng: `http_reqs` (số request/giây, càng cao càng tốt), `http_req_duration ... p(95)` (95% request xong trong bao lâu, càng thấp càng tốt) và dòng vàng (số lần truy vấn database, tỉ lệ cache hit).

Số liệu tham khảo khi server chạy trong Docker (Docker được cấp 4 CPU): không Redis **~16 req/s**, có Redis **~325 req/s**. Chạy thủ công trên máy thật thường ra số cao hơn vì dùng được nhiều CPU hơn.

### Đo đầy đủ nhiều kịch bản (~25 phút)
Cần làm **phần 3 (chạy thủ công)** trước đến hết bước 3 (có `.venv`, Redis, database). Script tự bật server riêng ở cổng 3900:
```powershell
python bench\run_bench.py            # đầy đủ, ~25 phút
python bench\run_bench.py --quick    # chạy thử, ~3 phút
```
Kết quả: `bench\results\results.md` và `results.csv` (mở bằng Excel để vẽ biểu đồ).

### Kiểm tra bằng Postman
Import file `bench\postman_demo3.json` vào Postman: 5 request minh họa MISS (đi database) và HIT (lấy từ Redis), kèm thống kê số lần truy vấn database.

---

## 5. Lỗi thường gặp

| Hiện tượng | Cách xử lý |
|---|---|
| `docker compose up` báo cổng `6379` / `11211` / `3000` / `3001` đã bị dùng | Tắt thứ đang chiếm cổng: container Redis/Memcached cũ (`docker stop redis memcached`) hoặc terminal đang chạy `python source_api.py` |
| `error during connect` / `Cannot connect to the Docker daemon` | Docker Desktop chưa bật, mở Docker Desktop và chờ đến khi chạy xong |
| Trang báo "Không đọc được Redis" | Redis chưa chạy: `docker compose ps` để xem trạng thái |
| Tab 4 báo Memcached Offline (chạy thủ công) | Memcached chưa chạy: `docker run -d --name memcached -p 11211:11211 memcached:1.6-alpine` |
| `no such table: users` (chạy thủ công) | Chưa tạo database: tắt server, chạy `python bench\seed_db.py` |
| `[WinError 10013]` khi chạy `python source_api.py` | Cổng đang bị chương trình khác chiếm (thường là server cũ chưa tắt) |
| Trang vẫn hiện giao diện cũ | Nhấn **Ctrl+F5** |
| `k6` không được nhận | Đóng hẳn VS Code / terminal rồi mở lại sau khi cài |
| Lỗi `conda ... not recognized` khi chạy `live.ps1` | Thêm `-NoProfile` như lệnh mẫu ở trên |
| PowerShell chặn `Activate.ps1` | Chạy `Set-ExecutionPolicy -Scope CurrentUser RemoteSigned` một lần |

---

## 6. Cấu trúc thư mục

```
seminar/
├── source_api.py                # server FastAPI: toàn bộ API cho 4 demo + benchmark
├── demo.html                    # trang demo giao diện trực quan (4 tab)
├── redis_vs_memcached_guide.md  # tài liệu hướng dẫn chuyên sâu so sánh Redis vs Memcached
├── compare_redis_memcached.py   # script so sánh Redis vs Memcached chạy trên terminal
├── requirements.txt             # thư viện Python
├── Dockerfile                   # đóng gói server FastAPI
├── docker-compose.yml           # Redis + Memcached + seed + Server A + Server B
├── connect_redis.py             # script kiểm tra kết nối Redis
├── caching.py                   # ví dụ mẫu cơ chế Cache-Aside chạy trên terminal
└── bench/
    ├── seed_db.py               # tạo database SQLite (shop.db)
    ├── check_db.py              # kiểm tra database đã tạo đúng chưa
    ├── load.js                  # kịch bản tải k6
    ├── live.ps1                 # benchmark trực tiếp (không Redis vs có Redis)
    ├── run_bench.py             # benchmark đầy đủ nhiều kịch bản, xuất báo cáo
    └── postman_demo3.json       # kịch bản test API bằng Postman
```
`bench/shop.db` (database) và `.venv` không nằm trong repo: được tạo lại trên mỗi máy.
