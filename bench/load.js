// Script k6: mỗi người dùng ảo (VU) gửi request liên tục, xong cái này gửi cái tiếp theo.
//
// Ví dụ chạy trực tiếp khi thuyết trình (50 người dùng, 10 giây):
//   k6 run --vus 50 --duration 10s -e ENDPOINT=products        bench/load.js   (không Redis)
//   k6 run --vus 50 --duration 10s -e ENDPOINT=products-cached bench/load.js   (có Redis)
//
// Biến môi trường (-e):
//   BASE      địa chỉ server            (mặc định http://localhost:3000)
//   ENDPOINT  products | products-cached | products-light | products-light-cached
//   PICK      fixed  = luôn sản phẩm 42 (mặc định)
//             hot    = 80% request vào 200 sản phẩm "hot", 20% vào 800 sản phẩm còn lại
import http from "k6/http";
import { check } from "k6";

const BASE = __ENV.BASE || "http://localhost:3000";
const ENDPOINT = __ENV.ENDPOINT || "products";
const PICK = __ENV.PICK || "fixed";

const N_PRODUCTS = 1000;
const N_HOT = 200;

function pickProduct() {
  if (PICK === "hot") {
    return Math.random() < 0.8
      ? 1 + Math.floor(Math.random() * N_HOT)                          // 1..200
      : N_HOT + 1 + Math.floor(Math.random() * (N_PRODUCTS - N_HOT));  // 201..1000
  }
  return 42;
}

export default function () {
  const res = http.get(`${BASE}/${ENDPOINT}/${pickProduct()}`);
  check(res, { "status 200": (r) => r.status === 200 });
}
