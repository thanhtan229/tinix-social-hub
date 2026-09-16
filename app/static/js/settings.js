import {api, esc, toast} from "./api.js";

function selectedThreshold() {
  const preset = document.querySelector("#profileCleanupThreshold").value;
  return preset === "custom"
    ? Number(document.querySelector("#profileCleanupCustom").value)
    : Number(preset);
}

function syncCustomThreshold() {
  const custom = document.querySelector("#profileCleanupCustomWrap");
  custom.classList.toggle("hidden", document.querySelector("#profileCleanupThreshold").value !== "custom");
}

export async function refreshProfileCleanupSettings() {
  const status = document.querySelector("#profileCleanupPolicyText");
  try {
    const settings = await api("/settings/profile-cleanup");
    document.querySelector("#profileCleanupEnabled").checked = settings.enabled;
    const preset = document.querySelector("#profileCleanupThreshold");
    const known = [2, 5, 10].includes(settings.threshold_gb);
    preset.value = known ? String(settings.threshold_gb) : "custom";
    document.querySelector("#profileCleanupCustom").value = settings.threshold_gb;
    status.textContent = settings.enabled
      ? `Tự kiểm tra mỗi ${Math.round(settings.check_interval_seconds / 3600)} giờ; dọn khi cache đạt ${settings.threshold_gb} GB hoặc ổ đĩa còn dưới ${settings.disk_floor_gb} GB.`
      : "Tự động dọn profile đang tắt. Bạn vẫn có thể dọn thủ công trong Quản lý account.";
    syncCustomThreshold();
  } catch (error) {
    status.textContent = "Không tải được thiết lập. Hãy khởi động lại app để backend nhận phiên bản mới.";
    throw error;
  }
}

export async function refreshReadinessDiagnostics() {
  const status = document.querySelector("#readinessText");
  const checks = document.querySelector("#readinessChecks");
  try {
    const result = await api("/diagnostics/readiness");
    status.textContent = result.status === "ready"
      ? "Thiết bị sẵn sàng cho các luồng local đã cấu hình."
      : "Có điều kiện cần xử lý trước khi dùng đầy đủ tính năng.";
    checks.innerHTML = result.checks.map(item => {
      const label = {ready:"Sẵn sàng", warning:"Cần chú ý", error:"Chưa sẵn sàng", optional:"Tùy chọn"}[item.state] || item.state;
      const kind = item.state === "ready" ? "good" : item.state === "error" ? "bad" : "warn";
      return `<div class="status-row"><span><strong>${esc(item.label)}</strong><small>${esc(item.detail)}</small></span><span class="badge ${kind}">${label}</span></div>`;
    }).join("");
    return result;
  } catch (error) {
    status.textContent = "Không thể chạy kiểm tra sẵn sàng.";
    checks.innerHTML = "";
    throw error;
  }
}

export function initSettings() {
  document.querySelector("#integrity").onclick = async () => {
    try {
      const result = await api("/database/integrity");
      toast(result.ok ? "Database integrity: OK" : result.result);
    } catch (error) { toast(error.message); }
  };
  document.querySelector("#backup").onclick = async () => {
    try {
      const result = await api("/database/backups", {method:"POST"});
      toast(`Đã tạo ${result.name}`);
    } catch (error) { toast(error.message); }
  };
  document.querySelector("#restore").onclick = async () => {
    try {
      const backups = await api("/database/backups");
      if (!backups.length) return toast("Chưa có backup");
      if (!confirm(`Khôi phục ${backups[0].name}? Hệ thống sẽ safety backup dữ liệu hiện tại.`)) return;
      await api("/database/restore", {method:"POST", body:JSON.stringify({name:backups[0].name})});
      toast("Khôi phục thành công");
    } catch (error) { toast(error.message); }
  };
  document.querySelector("#maintenance").onclick = async () => {
    try {
      const result = await api("/maintenance/run", {method:"POST"});
      const profile = result.profile_cleanup || {};
      const profileText = profile.status === "cleaned"
        ? ` Đã dọn ${profile.profiles_cleaned} profile.`
        : profile.status === "deferred_chrome_running" ? " Dọn profile đang chờ Chrome đóng." : "";
      document.querySelector("#maintenanceText").textContent = `Đã xóa ${result.screenshots_removed} screenshot và ${result.temporary_removed} file tạm.${profileText}`;
      toast("Bảo trì hoàn tất");
    } catch (error) { toast(error.message); }
  };
  document.querySelector("#runReadiness").onclick = async () => {
    try {
      await refreshReadinessDiagnostics();
      toast("Đã cập nhật kiểm tra sẵn sàng.");
    } catch (error) { toast(error.message); }
  };
  document.querySelector("#exportRecovery").onclick = () => {
    const dialog = document.querySelector("#recoveryExportDialog");
    dialog.querySelector("form").reset();
    dialog.showModal();
    setTimeout(() => document.querySelector("#recoveryExportPassword")?.focus(), 0);
  };
  document.querySelector("#restoreRecovery").onclick = () => {
    const dialog = document.querySelector("#recoveryRestoreDialog");
    dialog.querySelector("form").reset();
    dialog.showModal();
    setTimeout(() => document.querySelector("#recoveryBundlePath")?.focus(), 0);
  };
  document.querySelector("#recoveryExportForm").onsubmit = async event => {
    event.preventDefault();
    const button = document.querySelector("#confirmRecoveryExport");
    const password = document.querySelector("#recoveryExportPassword").value;
    button.disabled = true;
    button.textContent = "Đang tạo…";
    try {
      const result = await api("/recovery/export", {method:"POST", body:JSON.stringify({
        password, include_environment:document.querySelector("#recoveryIncludeEnvironment").checked,
      })});
      document.querySelector("#recoveryExportDialog").close();
      event.target.reset();
      toast(`Đã tạo recovery bundle: ${result.bundle_path}`);
    } catch (error) {
      toast(error.message);
    } finally {
      button.disabled = false;
      button.textContent = "Tạo bundle";
    }
  };
  document.querySelector("#recoveryRestoreForm").onsubmit = async event => {
    event.preventDefault();
    const path = document.querySelector("#recoveryBundlePath").value.trim();
    const password = document.querySelector("#recoveryRestorePassword").value;
    if (!confirm("Khôi phục bundle này? Database, media và Chrome profile hiện tại sẽ được thay thế sau khi tạo safety copy.")) return;
    const button = document.querySelector("#confirmRecoveryRestore");
    button.disabled = true;
    button.textContent = "Đang khôi phục…";
    try {
      const result = await api("/recovery/restore", {method:"POST", body:JSON.stringify({bundle_path:path, password})});
      document.querySelector("#recoveryRestoreDialog").close();
      event.target.reset();
      toast(`Đã khôi phục bundle ${result.source_app_version || ""}. Hãy khởi động lại app nếu bundle có .env.`);
    } catch (error) {
      toast(error.message);
    } finally {
      button.disabled = false;
      button.textContent = "Khôi phục ngay";
    }
  };
  document.querySelector("#profileCleanupThreshold").onchange = syncCustomThreshold;
  document.querySelector("#profileCleanupSettingsForm").onsubmit = async event => {
    event.preventDefault();
    const saveButton = event.submitter || event.target.querySelector('button[type="submit"]');
    const threshold = selectedThreshold();
    if (!Number.isFinite(threshold) || threshold < 0.5 || threshold > 100) {
      toast("Ngưỡng tùy chỉnh phải từ 0,5 đến 100 GB.");
      return;
    }
    try {
      saveButton.disabled = true;
      saveButton.textContent = "Đang lưu…";
      await api("/settings/profile-cleanup", {
        method:"PUT",
        body:JSON.stringify({
          enabled:document.querySelector("#profileCleanupEnabled").checked,
          threshold_gb:threshold,
        }),
      });
      await refreshProfileCleanupSettings();
      toast("Đã lưu thiết lập tự dọn profile.");
    } catch (error) {
      document.querySelector("#profileCleanupPolicyText").textContent = "Không thể lưu thiết lập. Hãy khởi động lại app rồi thử lại.";
      toast(error.message);
    } finally {
      saveButton.disabled = false;
      saveButton.textContent = "Lưu thiết lập";
    }
  };
}
