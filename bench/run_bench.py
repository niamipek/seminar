"""Chạy toàn bộ benchmark Demo 3 (có Redis vs không Redis) và xuất bảng kết quả.

Chuẩn bị:  docker (Redis) đang chạy, đã cài k6, đã chạy  python bench/seed_db.py
Chạy:      python bench/run_bench.py            (đầy đủ, ~25 phút)
           python bench/run_bench.py --quick    (chạy thử nhanh, ~3 phút, số liệu kém tin cậy)

Script tự bật một server riêng ở cổng 3900 (không reload, không log từng request)
nên không ảnh hưởng tới server demo đang chạy ở 3000/3001.
Kết quả: bench/results/results.md, results.csv và file JSON gốc của từng lần chạy.
"""
import argparse
import csv
import json
import os
import platform
import shutil
import statistics
import subprocess
import sys
import time
import urllib.request
from datetime import datetime
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8")

ROOT = Path(__file__).resolve().parent.parent
BENCH = ROOT / "bench"
OUT = BENCH / "results"
PORT = 3900
BASE = f"http://localhost:{PORT}"
PYTHON = sys.executable

NO_CACHE, CACHE = "Không Redis", "Có Redis"


# ---------- kịch bản ----------

def scenarios(quick: bool):
    dur = "5s" if quick else "30s"
    iters = 100 if quick else 200
    levels = [10, 50] if quick else [10, 50, 100]
    heavy = {NO_CACHE: "products", CACHE: "products-cached"}
    light = {NO_CACHE: "products-light", CACHE: "products-light-cached"}

    yield dict(id="1", name="Độ trễ khi ít tải (1 người dùng)", endpoints=heavy,
               load=dict(vus=1, iterations=iters), pick="fixed")
    for v in levels:
        yield dict(id=f"2-{v}", name=f"Chịu tải: {v} người dùng đồng thời", endpoints=heavy,
                   load=dict(vus=v, duration=dur), pick="fixed")
    # truy cập ngẫu nhiên trên 1000 sản phẩm: cần làm nóng lâu hơn để cache đạt trạng thái ổn định
    long_warmup = dict(vus=50, duration="5s" if quick else "15s")
    yield dict(id="3", name="Truy cập thực tế (80% vào 20% sản phẩm hot)", endpoints=heavy,
               load=dict(vus=50, duration=dur), pick="hot", warmup=long_warmup)
    # kịch bản 4: chỉ so cache lạnh (vừa xóa) với cache nóng (đã làm nóng)
    yield dict(id="4", name="Cache lạnh vs cache nóng (50 người dùng, 10 giây)",
               endpoints={"Cache lạnh": "products-cached", "Cache nóng": "products-cached"},
               load=dict(vus=50, duration="5s" if quick else "10s"), pick="hot",
               warmup=long_warmup, cold={"Cache lạnh"})
    yield dict(id="5a", name="Phản ví dụ: truy vấn nhẹ, 1 người dùng", endpoints=light,
               load=dict(vus=1, iterations=iters), pick="fixed")
    yield dict(id="5b", name="Phản ví dụ: truy vấn nhẹ, 50 người dùng", endpoints=light,
               load=dict(vus=50, duration=dur), pick="fixed")


# ---------- tiện ích ----------

def find_k6() -> str:
    k6 = shutil.which("k6") or r"C:\Program Files\k6\k6.exe"
    if not Path(k6).exists():
        sys.exit("Không tìm thấy k6. Cài bằng:  winget install GrafanaLabs.k6")
    return k6


def http(method: str, path: str) -> dict:
    req = urllib.request.Request(BASE + path, method=method)
    with urllib.request.urlopen(req, timeout=10) as res:
        return json.loads(res.read())


def start_server() -> subprocess.Popen:
    proc = subprocess.Popen(
        [PYTHON, "-m", "uvicorn", "source_api:app", "--port", str(PORT),
         "--no-access-log", "--log-level", "warning"],
        cwd=ROOT,
    )
    for _ in range(50):
        try:
            http("GET", "/bench/stats")
            return proc
        except OSError:
            time.sleep(0.2)
    proc.kill()
    sys.exit("Server benchmark không khởi động được (Redis đã chạy chưa?)")


def run_k6(k6: str, endpoint: str, pick: str, load: dict, summary: Path | None):
    cmd = [k6, "run", "--quiet", "--vus", str(load["vus"]),
           "--summary-trend-stats", "avg,med,p(95),p(99),max",
           "-e", f"BASE={BASE}", "-e", f"ENDPOINT={endpoint}", "-e", f"PICK={pick}"]
    cmd += ["--iterations", str(load["iterations"])] if "iterations" in load \
        else ["--duration", load["duration"]]
    if summary:
        cmd += ["--summary-export", str(summary)]
    cmd.append(str(BENCH / "load.js"))
    subprocess.run(cmd, check=True, stdout=subprocess.DEVNULL)


def parse_summary(path: Path) -> dict:
    m = json.loads(path.read_text(encoding="utf-8"))["metrics"]
    dur, reqs, failed = m["http_req_duration"], m["http_reqs"], m["http_req_failed"]
    return {"rps": reqs["rate"], "requests": reqs["count"],
            "avg": dur["avg"], "p50": dur["med"], "p95": dur["p(95)"], "p99": dur["p(99)"],
            "error_pct": failed.get("value", 0) * 100}


def machine_info() -> str:
    cpu = platform.processor()
    try:
        import winreg
        key = winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, r"HARDWARE\DESCRIPTION\System\CentralProcessor\0")
        cpu = winreg.QueryValueEx(key, "ProcessorNameString")[0].strip()
    except OSError:
        pass
    return f"{cpu}, {os.cpu_count()} luồng CPU, {platform.system()} {platform.release()}, Python {platform.python_version()}"


# ---------- chạy ----------

def run_one(k6, sc, label, endpoint, rep):
    cold = label in sc.get("cold", ())
    http("POST", "/bench/reset?flush_cache=true")
    if not cold:   # làm nóng (mặc định 200 request), không tính vào kết quả
        run_k6(k6, endpoint, sc["pick"], sc.get("warmup", dict(vus=10, iterations=200)), None)
    http("POST", "/bench/reset?flush_cache=false")   # chỉ đưa bộ đếm về 0, giữ cache
    summary = OUT / "raw" / f"s{sc['id']}_{endpoint}_{'cold' if cold else 'warm'}_r{rep}.json"
    run_k6(k6, endpoint, sc["pick"], sc["load"], summary)
    return {**parse_summary(summary), **http("GET", "/bench/stats")}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--quick", action="store_true", help="chạy thử nhanh")
    ap.add_argument("--reps", type=int, help="số lần lặp mỗi cấu hình (mặc định 3, quick 1)")
    args = ap.parse_args()
    reps = args.reps or (1 if args.quick else 3)

    if not (BENCH / "shop.db").exists():
        sys.exit("Chưa có database. Chạy trước:  python bench/seed_db.py")
    try:
        import redis
        redis.Redis(host="localhost", port=6379, socket_connect_timeout=3).ping()
    except Exception:
        sys.exit("Không kết nối được Redis (localhost:6379). Bật Docker Desktop rồi chạy:  docker start redis")
    k6 = find_k6()
    (OUT / "raw").mkdir(parents=True, exist_ok=True)

    server = start_server()
    rows = []
    try:
        for sc in scenarios(args.quick):
            print(f"\n=== Kịch bản {sc['id']}: {sc['name']}")
            runs = {label: [] for label in sc["endpoints"]}
            for rep in range(1, reps + 1):          # chạy xen kẽ hai trường hợp
                for label, endpoint in sc["endpoints"].items():
                    res = run_one(k6, sc, label, endpoint, rep)
                    runs[label].append(res)
                    print(f"  lần {rep} | {label:<12} | {res['rps']:8.1f} req/s | "
                          f"p50 {res['p50']:7.1f} ms | p95 {res['p95']:7.1f} ms | "
                          f"DB {res['db_queries']:>6} | hit {res['hit_rate'] if res['hit_rate'] is not None else '-'}%")
            for label, rs in runs.items():
                med = {k: statistics.median(r[k] for r in rs)
                       for k in ("rps", "requests", "avg", "p50", "p95", "p99", "error_pct", "db_queries")}
                hits = [r["hit_rate"] for r in rs if r["hit_rate"] is not None]
                med["hit_rate"] = statistics.median(hits) if hits else None
                rows.append({"scenario": sc["id"], "name": sc["name"], "case": label, **med})
    finally:
        server.kill()

    write_results(rows, reps, args.quick)


def write_results(rows, reps, quick):
    with open(OUT / "results.csv", "w", newline="", encoding="utf-8-sig") as f:   # utf-8-sig: Excel đọc đúng tiếng Việt
        w = csv.DictWriter(f, fieldnames=list(rows[0].keys()))
        w.writeheader()
        w.writerows(rows)

    def fmt(x, nd=1):
        return "-" if x is None else f"{x:,.{nd}f}"

    lines = [
        "# Kết quả benchmark: có Redis vs không Redis",
        "",
        f"- Thời điểm: {datetime.now():%Y-%m-%d %H:%M}",
        f"- Máy: {machine_info()}",
        f"- Mỗi cấu hình chạy {reps} lần, lấy trung vị" + (" (**chế độ chạy thử --quick, không dùng cho slide**)" if quick else ""),
        "- Truy vấn nặng: thông tin sản phẩm + điểm đánh giá + 5 sản phẩm tương tự (SQLite, 300.000 đánh giá)",
        "- Truy vấn nhẹ: lấy 1 sản phẩm theo khóa chính",
        "",
        "| Kịch bản | Trường hợp | req/s | p50 (ms) | p95 (ms) | p99 (ms) | Lỗi % | Số truy vấn DB | Cache hit % |",
        "|---|---|---:|---:|---:|---:|---:|---:|---:|",
    ]
    for r in rows:
        lines.append(f"| {r['scenario']}. {r['name']} | {r['case']} | {fmt(r['rps'])} | {fmt(r['p50'])} | "
                     f"{fmt(r['p95'])} | {fmt(r['p99'])} | {fmt(r['error_pct'], 2)} | "
                     f"{fmt(r['db_queries'], 0)} | {fmt(r['hit_rate'])} |")
    (OUT / "results.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(f"\nĐã ghi kết quả: {OUT / 'results.md'}  và  {OUT / 'results.csv'}")


if __name__ == "__main__":
    main()
