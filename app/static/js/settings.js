import {api, toast} from "./api.js";

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
