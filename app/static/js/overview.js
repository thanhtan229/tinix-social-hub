import {api, badge, bytes, esc} from "./api.js";
import {store} from "./store.js";

export async function refreshOverview() {
  const [health, jobs, platforms] = await Promise.all([api("/health"), api("/jobs?limit=6"), api("/platforms")]);
  store.health = health; store.jobs = jobs;
  document.querySelector("#version").textContent = `v${health.version}`;
  const connection = document.querySelector("#connection"); connection.className = "connection ok"; connection.textContent = `Backend ${health.version} · ${health.status}`;
  document.querySelector("#stats").innerHTML = [
    ["Worker", health.worker.state], ["Job đang chạy", health.worker.active_jobs],
    ["Chrome", `${health.chrome.running}/${health.chrome.limit}`], ["RAM ứng dụng", bytes(health.memory.process_bytes)],
    ["Ổ đĩa trống", bytes(health.disk.free_bytes)],
  ].map(([label,value]) => `<div class="stat"><span>${esc(label)}</span><strong>${esc(value)}</strong></div>`).join("");
  document.querySelector("#overviewJobs").innerHTML = jobs.length ? jobs.map(job => `<div class="status-row"><span>${esc(job.kind)} · ${job.dry_run ? "dry-run" : "đăng thật"}</span>${badge(job.status)}</div>`).join("") : '<p class="muted">Chưa có job.</p>';
  document.querySelector("#systemStatus").innerHTML = [
    ["Backend", health.status], ["Scheduler", health.scheduler], ["Database", health.database.result],
    ["AI", health.ai_configured ? "Đã cấu hình" : "Chưa cấu hình"], ["Chrome treo", health.chrome.hung],
  ].map(([label,value]) => `<div class="status-row"><span>${esc(label)}</span><strong>${esc(value)}</strong></div>`).join("");
  document.querySelector("#databaseText").textContent = `SQLite: ${health.database.result} · ${bytes(health.disk.free_bytes)} trống`;
  const stateLabel = {ready:"Sẵn sàng",review_required:"Cần kiểm thử thật",scaffold:"Bộ khung",not_started:"Chưa làm",deferred:"Để sau"};
  const capabilityLabel = {content_variants:"Nội dung",account_session:"Phiên đăng nhập",target_discovery:"Khám phá kênh",dry_run:"Dry-run",publishing:"Đăng bài",result_verification:"Xác minh"};
  document.querySelector("#platformRoadmap").innerHTML = platforms.map(platform => `<section class="platform-card ${platform.operational ? "operational" : "scaffolded"}"><div class="platform-title"><div><strong>${esc(platform.name)}</strong><small>${esc(platform.phase)}</small></div><span class="badge ${platform.operational ? "good" : "warn"}">${platform.operational ? "MVP" : "Bộ khung"}</span></div><div class="capability-list">${Object.entries(platform.capabilities).map(([key,value]) => `<span class="capability ${esc(value)}" title="${esc(capabilityLabel[key] || key)}: ${esc(stateLabel[value] || value)}">${esc(capabilityLabel[key] || key)}</span>`).join("")}</div><p>${esc(platform.next_milestone)}</p><small class="muted">Định dạng: ${platform.content_formats.map(esc).join(" · ")}</small></section>`).join("");
}
