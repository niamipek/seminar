# Seminar Redis: Caching · Session Storage · Lệch dữ liệu

Trang web demo trực quan cho 3 ứng dụng của Redis:

| Tab | Demo | Cho thấy điều gì |
|---|---|---|
| **1. Caching** | Lấy hồ sơ người dùng từ database thật (SQLite: 200.000 người dùng, 1 triệu đơn hàng), có và không có Redis | Cache HIT nhanh hơn MISS hàng trăm lần; Redis chứa ~140 MB vẫn lấy 1 key dưới 1 ms |
| **2. Session storage** | 2 server (cổng 3000 và 3001) dùng chung Redis để lưu session | Đăng nhập ở Server A thì Server B vẫn nhận ra; lưu trong RAM riêng của từng server thì không |
| **3. Lệch dữ liệu** | 2 request cùng sửa giá sản phẩm, 1 request bị chậm | "Set cache → ghi DB" và "Ghi DB → set cache" đều làm Redis lệch với DB; "Ghi DB → xóa cache" thì khớp |

Ngoài ra có phần **benchmark bằng k6** (tùy chọn, xem cuối file).

---

## 1. Chạy nhanh bằng Docker (khuyên dùng)

### Cần cài
- [Docker Desktop](https://www.docker.com/products/docker-desktop/) (đã bật)
- [Git](https://git-scm.com/downloads)

Không cần cài Python hay Redis: Docker lo hết.

### Chạy
```powershell
git clone <link-repo-github>
cd <tên-thư-mục-vừa-clone>
docker compose up --build
```
Lần đầu mất khoảng **1–3 phút** (tải image, cài thư viện, tạo database ~60 MB). Các lần sau chỉ khoảng 5 giây.
Khi thấy các dòng `server-a-1 ... Uvicorn running on http://0.0.0.0:3000` thì mở trình duyệt:

**http://localhost:3000/**

Docker Compose chạy 4 thành phần:

| Thành phần | Vai trò | Địa chỉ |
|---|---|---|
| `redis` | Redis server | `localhost:6379` |
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

## 2. Cách dùng 3 demo

Các con số dưới đây đo khi chạy bằng Docker; máy khác sẽ chênh một chút.

### Tab 1: Caching
Bấm **Xóa cache** trước để bắt đầu từ trạng thái trống.

| # | Thao tác | Kết quả mong đợi |
|---|---|---|
| 1 | Chọn "Nguyen Van A" → **Đăng nhập** | Hiện `session_id` (dùng tiếp ở tab 2), ô mã người dùng tự điền `1` |
| 2 | **Lấy dữ liệu** | **CACHE MISS ~200 ms**: database quét 1 triệu đơn hàng, server tự lưu kết quả vào Redis (`user:1`) |
| 3 | **Lấy dữ liệu** lần nữa | **CACHE HIT ~1 ms**: lấy thẳng từ Redis |
| 4 | **① Truy vấn database 50 người** | 50 người ngẫu nhiên, mỗi người ~200 ms (không dùng Redis) |
| 5 | **② Import dữ liệu Redis** | ~25 giây, nạp sẵn hồ sơ 200.000 người (cache warming) → Redis ~200.000 key, ~145 MB |
| 6 | **③ Truy vấn lại 50 người đó qua Redis** | 50/50 HIT, mỗi người ~1 ms. Bảng so sánh ① và ③ hiện ra |
| 7 | **Sang phần 2: Session →** | Chuyển sang tab 2, giữ nguyên session |

Khung **"Bên trong Redis"** bên phải hiển thị trực tiếp một số key, TTL và tổng số key / RAM.

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

### Xem trực tiếp bên trong Redis
```powershell
docker compose exec redis redis-cli DBSIZE          # tổng số key
docker compose exec redis redis-cli GET user:1      # hồ sơ người dùng 1 trong cache
docker compose exec redis redis-cli TTL user:1      # còn sống bao nhiêu giây
docker compose exec redis redis-cli INFO memory     # dòng used_memory_human: RAM đang dùng
```

---

## 3. Chạy thủ công (không đóng gói app bằng Docker)

Dùng khi muốn sửa code và thấy thay đổi ngay (server tự reload).

### Cần cài
- Python **3.12**
- Docker Desktop (chỉ để chạy Redis)

### Các bước (PowerShell, trong thư mục dự án)
```powershell
# 1. môi trường ảo + thư viện
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt

# 2. Redis (lần đầu dùng "docker run", các lần sau chỉ cần "docker start redis")
docker run -d --name redis -p 6379:6379 redis:7.4
python connect_redis.py               # phải in ra: Response: True

# 3. tạo database (~20–60 giây, chỉ cần làm 1 lần)
python bench\seed_db.py
python bench\check_db.py              # kiểm tra: 4 bảng đều ✅

# 4. chạy 2 server (2 terminal riêng, đều đã Activate .venv)
python source_api.py 3000             # terminal 1: Server A
python source_api.py 3001             # terminal 2: Server B
```
Mở **http://localhost:3000/**.

Không chạy cùng lúc cách này với `docker compose up` (cả hai cùng dùng cổng 3000, 3001, 6379).

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
| `docker compose up` báo cổng `6379` / `3000` / `3001` đã bị dùng | Tắt thứ đang chiếm cổng: container Redis cũ (`docker stop redis`) hoặc terminal đang chạy `python source_api.py` |
| `error during connect` / `Cannot connect to the Docker daemon` | Docker Desktop chưa bật, mở Docker Desktop và chờ đến khi chạy xong |
| Trang báo "Không đọc được Redis" | Redis chưa chạy: `docker compose ps` để xem trạng thái |
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
├── source_api.py         # server FastAPI: toàn bộ API cho 3 demo + benchmark
├── demo.html             # trang demo (3 tab)
├── requirements.txt      # thư viện Python
├── Dockerfile            # đóng gói server
├── docker-compose.yml    # Redis + seed + Server A + Server B
├── connect_redis.py      # kiểm tra kết nối Redis
├── caching.py            # ví dụ caching đơn giản chạy trên terminal
└── bench/
    ├── seed_db.py        # tạo database SQLite (shop.db)
    ├── check_db.py       # kiểm tra database đã tạo đúng chưa
    ├── load.js           # kịch bản k6
    ├── live.ps1          # benchmark trực tiếp (không Redis vs có Redis)
    ├── run_bench.py      # benchmark đầy đủ, xuất bảng kết quả
    └── postman_demo3.json
```
`bench/shop.db` (database) và `.venv` không nằm trong repo: được tạo lại trên mỗi máy.
