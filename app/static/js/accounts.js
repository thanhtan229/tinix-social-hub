import {api, badge, esc, STATUS, toast} from "./api.js";
import {store} from "./store.js";

function formatBytes(value) {
  if (!value) return "0 B";
  const units = ["B", "KB", "MB", "GB"];
  const index = Math.min(Math.floor(Math.log(value) / Math.log(1024)), units.length - 1);
  return `${(value / (1024 ** index)).toFixed(index ? 1 : 0)} ${units[index]}`;
}

const PLATFORM_ICONS = {
  facebook: '<svg viewBox="0 0 24 24" aria-hidden="true"><path fill="#1877F2" d="M24 12.07C24 5.4 18.63 0 12 0S0 5.4 0 12.07C0 18.1 4.39 23.1 10.13 24v-8.44H7.08v-3.49h3.05V9.41c0-3.03 1.79-4.7 4.53-4.7 1.31 0 2.68.24 2.68.24v2.96h-1.51c-1.49 0-1.96.93-1.96 1.89v2.27h3.33l-.53 3.49h-2.8V24C19.61 23.1 24 18.1 24 12.07Z"/></svg>',
  instagram: '<svg viewBox="0 0 24 24" aria-hidden="true"><defs><linearGradient id="ig" x1="0" y1="1" x2="1" y2="0"><stop stop-color="#FFD600"/><stop offset=".48" stop-color="#FF0169"/><stop offset="1" stop-color="#7638FA"/></linearGradient></defs><rect width="24" height="24" rx="6" fill="url(#ig)"/><circle cx="12" cy="12" r="4.4" fill="none" stroke="#fff" stroke-width="2"/><circle cx="18.1" cy="5.9" r="1.25" fill="#fff"/></svg>',
  tiktok: '<svg viewBox="0 0 24 24" aria-hidden="true"><rect width="24" height="24" rx="6" fill="#101010"/><path fill="#25F4EE" d="M10.2 17.1a2.3 2.3 0 1 1-1.6-2.2v-2.5a4.8 4.8 0 1 0 4.1 4.7V7.7c1 1.2 2.4 2 4 2.1V7.3a4.2 4.2 0 0 1-3.4-3.1h-3.1v12.9Z"/><path fill="#FE2C55" d="M11.1 17.5a2.3 2.3 0 1 1-1.6-2.2v-2.5a4.8 4.8 0 1 0 4.1 4.7V8.1c1 1.2 2.4 2 4 2.1V7.7a4.2 4.2 0 0 1-3.4-3.1h-3.1v12.9Z"/><path fill="#fff" d="M10.65 17.3a2.3 2.3 0 1 1-1.6-2.2v-2.5a4.8 4.8 0 1 0 4.1 4.7V7.9c1 1.2 2.4 2 4 2.1V7.5a4.2 4.2 0 0 1-3.4-3.1h-3.1v12.9Z"/></svg>',
  youtube: '<svg viewBox="0 0 24 24" aria-hidden="true"><rect y="3.5" width="24" height="17" rx="5" fill="#FF0000"/><path fill="#fff" d="m9.5 8 7 4-7 4V8Z"/></svg>',
};

function platformIcon(platform) {
  const key = String(platform || "").toLowerCase();
  const icon = PLATFORM_ICONS[key] || '<svg viewBox="0 0 24 24" aria-hidden="true"><circle cx="12" cy="12" r="10" fill="#718078"/><path d="M2 12h20M12 2a15 15 0 0 1 0 20M12 2a15 15 0 0 0 0 20" fill="none" stroke="#fff" stroke-width="1.5"/></svg>';
  return `<span class="platform-icon platform-${esc(key)}" title="${esc(platform)}" aria-label="Nền tảng ${esc(platform)}">${icon}</span>`;
}

export async function refreshAccounts() {
  const [accounts, targets] = await Promise.all([api("/accounts"), api(`/targets?search=${encodeURIComponent(document.querySelector("#targetSearch")?.value || "")}`)]);
  store.accounts = accounts; store.targets = targets;
  const profileSelect = document.querySelector("#profileAccount");
  const selectedProfileAccount = profileSelect.value;
  profileSelect.innerHTML = accounts.length ? accounts.map(account => `<option value="${account.id}">${esc(account.name)} · ${esc(account.platform)}</option>`).join("") : '<option value="">Chưa có account</option>';
  if (accounts.some(account => account.id === selectedProfileAccount)) profileSelect.value = selectedProfileAccount;
  document.querySelectorAll("[data-profile-action]").forEach(button => button.disabled = button.dataset.profileAction !== "import" && !accounts.length);
  document.querySelector("#profileHelp").textContent = accounts.length ? "Export tạo ZIP gọn nhẹ chứa account và phiên đăng nhập; Dọn dẹp xóa cache nhưng giữ nguyên phiên." : "Import file .tinix-profiles.zip để tạo toàn bộ account và phiên đăng nhập trong một lần.";
  document.querySelector("#accountList").innerHTML = accounts.length ? accounts.map(account => `<div class="list-row"><div><div class="account-identity"><strong>${esc(account.name)}</strong>${platformIcon(account.platform)}</div><small class="muted">${badge(account.login_status)}${account.profile_operation_locked ? " · profile đang bảo trì" : ""}</small></div><div class="account-actions"><button data-account-action="chrome" data-id="${account.id}">Mở</button><button data-account-action="close" data-id="${account.id}">Đóng</button><button data-account-action="edit" data-id="${account.id}">Sửa</button><button class="danger" data-account-action="delete" data-id="${account.id}">Xóa</button></div></div>`).join("") : '<p class="muted">Chưa có account. Bạn có thể Import một gói profile hoặc tạo account thủ công.</p>';
  document.querySelector("#targetList").innerHTML = targets.length ? targets.map(target => `<div class="list-row"><div><strong>${esc(target.name)}</strong><small class="muted">${esc(target.platform)} · ${esc(target.access_status)} · ${esc((accounts.find(a=>a.id===target.account_id)||{}).name||"")}</small></div><button data-target-id="${target.id}" data-enabled="${target.enabled}">${target.enabled ? "Tắt" : "Bật"}</button></div>`).join("") : '<p class="muted">Chưa có Page hoặc kênh được đồng bộ.</p>';
  bindActions();
}

async function runProfileAction(action, account) {
  if (action === "import") {
    const dialog = document.querySelector("#profileImportDialog");
    const status = document.querySelector("#profileImportStatus");
    status.textContent = "";
    status.className = "operation-status hidden";
    dialog.showModal();
    setTimeout(() => document.querySelector("#profileArchivePath")?.focus(), 0);
    return false;
  }
  if (action === "export") {
    if (!store.accounts.length) { toast("App chưa có account để Export."); return false; }
    const button = document.querySelector('[data-profile-action="export"]');
    const originalLabel = button.textContent;
    button.disabled = true;
    button.textContent = "Đang sao chép và nén...";
    toast("Đang Export toàn bộ profile. Vui lòng chờ, không đóng app...");
    try {
      const result = await api("/profiles/export", {method:"POST"});
      toast(`Đã Export ${result.accounts_exported} phiên (${formatBytes(result.bytes_copied)}) tới ${result.archive_path}`);
      return true;
    } finally {
      button.textContent = originalLabel;
      button.disabled = !store.accounts.length;
    }
  }
  if (action === "cleanup") {
    const preview = await api("/profiles/cleanup-preview");
    const summary = document.querySelector("#profileCleanupSummary");
    summary.textContent = `Có thể giải phóng khoảng ${formatBytes(preview.bytes_removable)} (${preview.files_removable} file) trong ${preview.profiles_scanned} profile.`;
    const confirmButton = document.querySelector("#confirmProfileCleanup");
    confirmButton.disabled = preview.chrome_running > 0 || preview.bytes_removable === 0;
    if (preview.chrome_running) summary.textContent += ` Có ${preview.chrome_running} profile đang được Chrome sử dụng; hãy đóng Chrome trước.`;
    if (!preview.bytes_removable) summary.textContent += " Hiện không có dữ liệu cần dọn.";
    document.querySelector("#profileCleanupDialog").showModal();
    return false;
  }
  if (!account) { toast("Hãy tạo hoặc chọn account trước."); return false; }
  if (action === "backup") {
    if (!confirm("Đóng Chrome của account trước khi Backup. Tiếp tục?")) return false;
    const result = await api(`/accounts/${account.id}/profile/backup`, {method:"POST"});
    toast(`Đã tạo backup ${result.backup_name}`);
  }
  if (action === "restore") {
    const backups = await api(`/accounts/${account.id}/profile/backups`);
    if (!backups.length) { toast("Account chưa có backup profile."); return false; }
    const choices = backups.map((item,index)=>`${index+1}. ${item.name}`).join("\n");
    const selected = prompt(`Chọn số thứ tự backup cần khôi phục:\n${choices}`);
    if (!selected) return false;
    const backup = backups[Number(selected)-1];
    if (!backup) { toast("Số thứ tự backup không hợp lệ."); return false; }
    if (!confirm(`Khôi phục ${backup.name}? Profile hiện tại sẽ được backup trước khi thay thế.`)) return false;
    const result = await api(`/accounts/${account.id}/profile/restore`, {method:"POST", body:JSON.stringify({backup_name:backup.name})});
    toast(`Đã khôi phục ${result.restored_from}. Backup trước khôi phục: ${result.backup_name || "không có"}`);
  }
  return true;
}

function bindActions() {
  document.querySelectorAll("[data-account-action]").forEach(button => button.onclick = async () => {
    const account = store.accounts.find(item => item.id === button.dataset.id); const action = button.dataset.accountAction;
    const originalLabel = button.textContent;
    try {
      if (action === "chrome") {
        button.disabled = true;
        button.textContent = "Đang mở…";
        await api(`/accounts/${account.id}/chrome/open`, {method:"POST"});
        button.textContent = "Đang kiểm tra…";
        try {
          const result = await api(`/accounts/${account.id}/check-login`, {method:"POST"});
          toast(`${account.name}: ${STATUS[result.login_status] || result.login_status}`);
        } catch (error) {
          throw new Error(`Đã mở Chrome nhưng kiểm tra đăng nhập thất bại: ${error.message}`);
        }
      }
      if (action === "close") { const result = await api(`/accounts/${account.id}/chrome/close`, {method:"POST"}); toast(result.closed ? `Đã đóng Chrome của ${account.name}` : `Chrome của ${account.name} chưa chạy`); }
      if (action === "edit") { const name = prompt("Tên account", account.name); if (name) await api(`/accounts/${account.id}`, {method:"PUT", body:JSON.stringify({name, platform:account.platform})}); }
      if (action === "delete" && confirm("Chỉ xóa account không có Page/job. Chrome profile trên ổ đĩa sẽ được giữ lại. Tiếp tục?")) await api(`/accounts/${account.id}`, {method:"DELETE"});
      await refreshAccounts();
    } catch (error) { toast(error.message); }
    finally { button.disabled = false; button.textContent = originalLabel; }
  });
  document.querySelectorAll("[data-target-id]").forEach(button => button.onclick = async () => { try { await api(`/targets/${button.dataset.targetId}/enabled`, {method:"PATCH", body:JSON.stringify({enabled:button.dataset.enabled !== "1"})}); await refreshAccounts(); } catch(error) { toast(error.message); } });
}

export function initAccounts() {
  const dialog = document.querySelector("#accountDialog");
  document.querySelector("#newAccount").onclick = () => dialog.showModal();
  document.querySelector("#accountForm").onsubmit = async event => { event.preventDefault(); try { await api("/accounts", {method:"POST", body:JSON.stringify({name:document.querySelector("#accountName").value, platform:document.querySelector("#accountPlatform").value})}); dialog.close(); event.target.reset(); await refreshAccounts(); toast("Đã thêm account"); } catch(error) { toast(error.message); } };
  document.querySelector("#profileImportForm").onsubmit = async event => {
    event.preventDefault();
    const archivePath = document.querySelector("#profileArchivePath").value.trim();
    if (!archivePath) return;
    const importDialog = document.querySelector("#profileImportDialog");
    const status = document.querySelector("#profileImportStatus");
    const submitButton = document.querySelector("#confirmProfileImport");
    const cancelButton = document.querySelector("#cancelProfileImport");
    const pathInput = document.querySelector("#profileArchivePath");
    status.className = "operation-status";
    status.textContent = "Đang đọc file ZIP và khôi phục các phiên đăng nhập… Việc này có thể mất vài phút.";
    submitButton.disabled = true;
    submitButton.textContent = "Đang Import…";
    cancelButton.disabled = true;
    pathInput.disabled = true;
    toast("Đang Import toàn bộ account/profile. Vui lòng chờ...");
    try {
      const result = await api("/profiles/import", {method:"POST", body:JSON.stringify({bundle_path:archivePath})});
      event.target.reset();
      await refreshAccounts();
      importDialog.close();
      toast(`Đã Import ${result.accounts_imported} account/profile từ ${result.source_app || "gói Tinix"}`);
    } catch (error) {
      status.className = "operation-status error";
      status.textContent = `Import thất bại: ${error.message}`;
      toast(error.message);
    } finally {
      submitButton.disabled = false;
      submitButton.textContent = "Bắt đầu Import";
      cancelButton.disabled = false;
      pathInput.disabled = false;
    }
  };
  document.querySelector("#profileCleanupForm").onsubmit = async event => {
    event.preventDefault();
    const dialog = document.querySelector("#profileCleanupDialog");
    const button = document.querySelector("#confirmProfileCleanup");
    button.disabled = true;
    button.textContent = "Đang dọn dẹp...";
    try {
      const result = await api("/profiles/cleanup", {method:"POST"});
      dialog.close();
      toast(`Đã dọn ${result.profiles_cleaned} profile, giải phóng ${formatBytes(result.bytes_freed)}.`);
    } catch (error) {
      toast(error.message);
    } finally {
      button.textContent = "Dọn dẹp ngay";
      button.disabled = false;
    }
  };
  document.querySelector("#closeAllChrome").onclick = async () => { const result = await api("/chrome/close-all", {method:"POST"}); toast(`Đã đóng ${result.closed} Chrome`); };
  document.querySelectorAll("[data-profile-action]").forEach(button => button.onclick = async () => {
    const account = store.accounts.find(item => item.id === document.querySelector("#profileAccount").value);
    try { if (await runProfileAction(button.dataset.profileAction, account)) await refreshAccounts(); } catch(error) { toast(error.message); }
  });
  document.querySelector("#targetSearch").oninput = () => { clearTimeout(initAccounts.searchTimer); initAccounts.searchTimer = setTimeout(refreshAccounts, 350); };
}
