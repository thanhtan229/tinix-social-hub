export async function api(path, options = {}) {
  const headers = options.body instanceof FormData ? {"X-Tinix-Request": "1"} : {"Content-Type": "application/json", "X-Tinix-Request": "1"};
  const response = await fetch(`/api${path}`, {...options, headers: {...headers, ...(options.headers || {})}});
  if (!response.ok) {
    let message = response.statusText;
    try { const body = await response.json(); message = typeof body.detail === "string" ? body.detail : body.detail?.message || JSON.stringify(body.detail); } catch {}
    throw new Error(message);
  }
  if (response.status === 204) return null;
  return response.json();
}

export function toast(message) {
  const element = document.querySelector("#toast");
  element.textContent = message;
  element.classList.add("show");
  clearTimeout(toast.timer);
  toast.timer = setTimeout(() => element.classList.remove("show"), 3200);
}

export function esc(value) {
  return String(value ?? "").replace(/[&<>'"]/g, char => ({"&":"&amp;","<":"&lt;",">":"&gt;","'":"&#39;",'"':"&quot;"}[char]));
}

export function bytes(value) {
  if (value >= 1e9) return `${(value / 1e9).toFixed(1)} GB`;
  if (value >= 1e6) return `${(value / 1e6).toFixed(1)} MB`;
  return `${value} B`;
}

export const STATUS = {
  draft:"Bản nháp", pending_approval:"Chờ duyệt", approved:"Đã duyệt", scheduled:"Đã lên lịch",
  queued:"Đang chờ", opening_browser:"Mở Chrome", checking_login:"Kiểm tra đăng nhập", uploading:"Tải media",
  publishing:"Đang đăng", verifying:"Đang xác minh", succeeded:"Thành công", dry_run_ready:"Dry-run sẵn sàng",
  temporary_failure:"Lỗi tạm thời", permanent_failure:"Lỗi vĩnh viễn", login_required:"Cần đăng nhập",
  checkpoint:"Checkpoint", unknown_result:"Chưa rõ kết quả", cancelled:"Đã hủy",
  logged_in:"Đã đăng nhập", logged_out:"Chưa đăng nhập", session_lost:"Mất phiên", unknown:"Chưa kiểm tra",
};

export function badge(status) { return `<span class="badge ${esc(status)}">${esc(STATUS[status] || status)}</span>`; }

