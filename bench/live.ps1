# Demo 3 trực tiếp khi thuyết trình: 50 người dùng x 10 giây, chạy KHÔNG Redis rồi CÓ Redis.
#
# Trước đó bật server (không ghi log từng request để số liệu chính xác):
#   python -m uvicorn source_api:app --port 3000 --no-access-log
# Rồi chạy:
#   powershell -NoProfile -ExecutionPolicy Bypass -File bench\live.ps1
#   (-NoProfile: không chạy profile.ps1 của máy, tránh in lỗi không liên quan)
param(
    [string]$Base = "http://localhost:3000",
    [int]$Vus = 50,
    [string]$Duration = "10s",
    [switch]$NoPause          # bỏ bước "nhấn Enter" (dùng khi chạy thử)
)

[Console]::OutputEncoding = [Text.Encoding]::UTF8
$k6 = (Get-Command k6 -ErrorAction SilentlyContinue).Source
if (-not $k6) { $k6 = "C:\Program Files\k6\k6.exe" }
$script = Join-Path $PSScriptRoot "load.js"

function Banner($text, $color) {
    Write-Host ""
    Write-Host ("=" * 60) -ForegroundColor $color
    Write-Host "  $text" -ForegroundColor $color
    Write-Host ("=" * 60) -ForegroundColor $color
}

function Run($endpoint) {
    Invoke-RestMethod -Method Post "$Base/bench/reset?flush_cache=true" | Out-Null
    # ẩn khối EXECUTION và NETWORK (không cần cho phần so sánh) cho dễ đọc
    & $k6 run --quiet --vus $Vus --duration $Duration `
        --summary-trend-stats "avg,med,p(95)" `
        -e BASE=$Base -e ENDPOINT=$endpoint $script |
        Where-Object { $_ -notmatch '^\s*(EXECUTION|iteration_duration|iterations|vus|vus_max|NETWORK|data_received|data_sent)\b' }
    $s = Invoke-RestMethod "$Base/bench/stats"
    $line = "  Số lần truy vấn database: $($s.db_queries)"
    if ($null -ne $s.hit_rate) { $line += "   |   Cache hit: $($s.hit_rate)%" }
    Write-Host ""
    Write-Host $line -ForegroundColor Yellow
}

Banner "LẦN 1: KHÔNG REDIS ($Vus người dùng, $Duration)" Red
Run "products"

if (-not $NoPause) { Read-Host "`nNhấn Enter để chạy lần 2 (có Redis)" | Out-Null }

Banner "LẦN 2: CÓ REDIS ($Vus người dùng, $Duration)" Green
Run "products-cached"
