# 📘 Hướng dẫn thành viên nhóm: Phần So sánh Redis vs Memcached (Tab 4)

## Mục đích của phần này trong bài Seminar

3 tab đầu demo **Redis làm được gì** (caching, session, xử lý lệch dữ liệu).
Tab 4 trả lời câu hỏi mà giảng viên / người nghe **chắc chắn sẽ hỏi**:

> "Tại sao chọn Redis mà không dùng Memcached? Hai cái khác nhau chỗ nào?"

---

## 1. Redis và Memcached giống nhau ở đâu?

Cả hai đều là **in-memory cache** — lưu dữ liệu hoàn toàn trong RAM để truy xuất cực nhanh (micro-giây), thay vì phải đọc từ ổ cứng như database truyền thống.

```
Client  ──request──►  [Cache Server (RAM)]  ──miss──►  [Database (Ổ cứng)]
                           ▲
                     Cực nhanh (~0.1ms)           Chậm hơn (~200ms)
```

**Giống nhau:**
- Đều lưu dữ liệu dạng **Key → Value** trong RAM
- Đều có **TTL** (Time To Live) — tự xóa sau một thời gian
- Đều dùng làm cache layer để giảm tải cho database
- Tốc độ đọc/ghi đơn giản **gần ngang nhau** (đã kiểm chứng trong demo)

---

## 2. Khác nhau ở đâu? (7 điểm cốt lõi)

### 2.1. Cấu trúc dữ liệu ⭐ (Điểm khác biệt LỚN NHẤT)

| Redis | Memcached |
|---|---|
| **Nhiều kiểu**: String, Hash, List, Set, Sorted Set, Bitmap, Stream... | **Chỉ có 1 kiểu**: String (chuỗi byte thô) |

**Ví dụ thực tế — Lưu hồ sơ người dùng:**

```
Redis dùng Hash (giống 1 bảng nhỏ trong RAM):
┌─────────────────────────────┐
│  Key: "user:1001"           │
│  ├── name  = "Nguyen Van A" │
│  ├── city  = "Ho Chi Minh"  │
│  ├── points = 1500          │  ← Muốn sửa CHỈ trường này
│  └── level = "Gold"         │
└─────────────────────────────┘
→ Redis: HINCRBY user:1001 points 10   (1 lệnh, ~39 bytes qua mạng)
```

```
Memcached chỉ lưu được chuỗi JSON:
┌──────────────────────────────────────────────────────┐
│  Key: "user:1001"                                    │
│  Value: '{"name":"Nguyen Van A","city":"Ho Chi Minh",│
│          "points":1500,"level":"Gold"}'              │
└──────────────────────────────────────────────────────┘
→ Muốn sửa points:
  Bước 1: GET toàn bộ JSON (~826 bytes) về client
  Bước 2: Parse JSON thành dict trong Python
  Bước 3: dict["points"] += 10
  Bước 4: Dump dict thành JSON
  Bước 5: SET toàn bộ JSON (~826 bytes) lại server
→ Tốn 5 bước, ~826 bytes qua mạng (gấp 21 lần Redis!)
```

> **Demo Tab 4 — "Thực hiện cập nhật điểm"** cho thấy chính xác điều này:
> Redis tiết kiệm ~95% băng thông mạng so với Memcached.

### 2.2. Mô hình xử lý luồng (Threading)

| Redis | Memcached |
|---|---|
| **Single-threaded** event loop | **Multi-threaded** |
| 1 luồng xử lý mọi lệnh tuần tự | Nhiều luồng xử lý song song |

- **Redis single-thread** không có nghĩa là chậm! Nó tránh được overhead lock/context-switch, và xử lý hàng trăm nghìn request/giây nhờ I/O multiplexing.
- **Memcached multi-thread** tận dụng được nhiều CPU core hơn khi có rất nhiều kết nối đồng thời.

### 2.3. Lưu trữ bền vững (Persistence)

| Redis | Memcached |
|---|---|
| **RDB** (chụp ảnh toàn bộ RAM theo chu kỳ) + **AOF** (ghi log từng lệnh) | **Không có** |
| Restart → dữ liệu khôi phục được | Restart → **mất sạch 100%** |

### 2.4. Giới hạn kích thước Value

| Redis | Memcached |
|---|---|
| Tối đa **512 MB** / value | Mặc định tối đa **1 MB** / value |

### 2.5. Replication & Clustering

| Redis | Memcached |
|---|---|
| Master-Replica, Redis Sentinel (tự failover), Redis Cluster (sharding) | Không có sẵn — client tự chia dữ liệu (consistent hashing) |

### 2.6. Tính năng nâng cao

| Redis | Memcached |
|---|---|
| Pub/Sub (message queue nhẹ), Lua scripting, Transactions, Geospatial, HyperLogLog... | Chỉ có GET / SET / DELETE / CAS |

### 2.7. Tốc độ đơn giản (GET/SET)

| Redis | Memcached |
|---|---|
| ~5.500 ops/s (tuần tự qua Docker) | ~8.500 ops/s (tuần tự qua Docker) |

> Memcached nhỉnh hơn ~1.5x cho thao tác đơn giản vì protocol nhẹ hơn và multi-threaded.
> Nhưng khi cần thao tác phức tạp (Hash, List...) thì Redis nhanh hơn **hàng trăm lần** vì xử lý ngay trên server.

---

## 3. Khi nào chọn cái nào?

```
┌────────────────────────────────────────────────────────────┐
│                    BẠN CẦN GÌ?                            │
│                                                            │
│  Cache đơn giản, chỉ GET/SET chuỗi? ──────► MEMCACHED     │
│  (VD: cache HTML page, cache API response)                 │
│                                                            │
│  Cần cấu trúc dữ liệu phức tạp? ─────────► REDIS         │
│  (VD: leaderboard, shopping cart, session)                  │
│                                                            │
│  Cần dữ liệu sống sót khi restart? ──────► REDIS          │
│                                                            │
│  Cần Pub/Sub, Queue, Transactions? ──────► REDIS           │
│                                                            │
│  Cần tận dụng tối đa nhiều CPU core? ────► MEMCACHED       │
│  (VD: hệ thống cache tĩnh cực lớn)                        │
└────────────────────────────────────────────────────────────┘
```

**Thực tế**: Đa số dự án chọn **Redis** vì linh hoạt hơn nhiều. Memcached phù hợp khi chỉ cần cache tĩnh thuần túy và muốn tối ưu tận cùng cho multi-core.

---

## 4. Cách demo trước lớp (kịch bản thuyết trình Tab 4)

### Bước 1: Giới thiệu (30 giây)
> "3 tab trước đã cho thấy Redis làm được gì. Bây giờ so sánh Redis với đối thủ nổi tiếng nhất của nó: Memcached."

### Bước 2: Bảng đối chiếu (1 phút)
Cuộn qua bảng 7 tiêu chí, nhấn mạnh 2 điểm:
- **Cấu trúc dữ liệu**: Redis có Hash, List, Set... còn Memcached chỉ có String
- **Persistence**: Redis khôi phục được, Memcached mất hết

### Bước 3: Demo tốc độ (1 phút)
Bấm **"100.000 lượt xem"** (chờ ~15 giây), chỉ vào thanh ngang, nhận xét:
> "100.000 lượt khách xem trang sản phẩm. Nếu lần nào cũng truy vấn database thì mất gần 3 tiếng. Redis và Memcached chỉ mất khoảng 6 giây, nhanh hơn khoảng 1.700 lần. Còn giữa Redis và Memcached thì gần như ngang nhau, chênh vài phần trăm. Vậy chọn Redis không bị thiệt về tốc độ. Khác nhau ở đâu? Mời xem thử nghiệm 2..."

### Bước 4: Demo cấu trúc dữ liệu — ĐIỂM NHẤN (2 phút)
Để user ID = 1, tên mới "Nguyễn Văn C", bấm **"Đổi tên"**, chỉ vào từng bước:
> "Cùng bài toán: đổi tên user Nguyen Van A thành Nguyễn Văn C. Redis lưu hồ sơ dạng Hash nên chỉ cần 1 lệnh HSET sửa đúng trường name, khoảng 70 byte. Memcached chỉ thấy 1 chuỗi JSON, nên phải tải cả hồ sơ về, sửa, rồi đẩy cả hồ sơ lên lại — khoảng 1.700 byte, gấp khoảng 25 lần. Hồ sơ càng lớn thì chênh lệch càng lớn."

### Bước 5: Kết luận (30 giây)
> "Tóm lại: nếu chỉ cần cache đơn giản thì Memcached đủ rồi. Nhưng khi cần cấu trúc dữ liệu phức tạp, persistence, pub/sub — Redis là lựa chọn toàn diện hơn. Đó cũng là lý do Redis phổ biến hơn nhiều trong thực tế."

---

## 5. Câu hỏi có thể bị hỏi và cách trả lời

**Q: "Memcached nhanh hơn Redis một chút, tại sao không dùng Memcached?"**
> A: Với GET/SET đơn giản thì hai bên gần như ngang nhau (chênh vài phần trăm, khoảng 0,005 ms mỗi lệnh). Nhưng trong thực tế, ứng dụng thường cần thao tác phức tạp hơn (sửa 1 trường, thêm vào danh sách, đếm số lượng...). Lúc đó Redis nhanh hơn hàng trăm lần vì xử lý ngay trên server, không cần truyền dữ liệu qua lại.

**Q: "Redis single-thread thì có chậm không khi nhiều người dùng?"**
> A: Không. Redis xử lý ~100.000+ request/giây trên 1 thread nhờ I/O multiplexing (epoll/kqueue). Đa số ứng dụng không bao giờ đạt tới giới hạn này. Nếu cần scale, dùng Redis Cluster để chia tải.

**Q: "Memcached mất dữ liệu khi restart, vậy có ổn không?"**
> A: Nếu chỉ dùng làm cache (dữ liệu gốc vẫn ở database) thì mất cache không sao — chỉ chậm lại lúc đầu. Nhưng nếu dùng lưu session, queue, counter... thì cần Redis vì có persistence.

**Q: "Trong dự án thật thì dùng cái nào?"**
> A: Hầu hết dùng Redis vì linh hoạt hơn. Facebook từng dùng Memcached cho cache tĩnh quy mô rất lớn. Nhưng xu hướng hiện tại, Redis chiếm ưu thế trong hầu hết use case.
