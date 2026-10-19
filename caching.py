import redis, json, requests, time

r = redis.Redis(host="localhost", port=6379, db=0)

def fetch_user_data(user_id):
    cached = r.get(user_id)
    if cached is not None:
        print("  [HIT]")
        return json.loads(cached)          # sửa: bytes -> dict
    print("  [MISS] -> gọi API gốc")
    response = requests.get(f"http://localhost:5000/api/users/{user_id}")
    data = response.json()
    r.set(user_id, json.dumps(data), ex=500) # sửa: thêm TTL 60 giây
    return data

user_id = "1"
r.delete(user_id)                          # xóa cache cũ để demo từ đầu

for lan in (1, 2):
    start = time.perf_counter()
    cached = fetch_user_data(user_id)
    print(f"Lần {lan}: {(time.perf_counter() - start) * 1000:.0f} ms")

external = requests.get(f"http://localhost:5000/api/users/{user_id}").json()
print("Khớp với nguồn gốc" if cached == external else "Không khớp")