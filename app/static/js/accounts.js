import {api, badge, esc, toast} from "./api.js";
import {store} from "./store.js";

export async function refreshAccounts() {
  const [accounts, targets] = await Promise.all([api("/accounts"), api(`/targets?search=${encodeURIComponent(document.querySelector("#targetSearch")?.value || "")}`)]);
  store.accounts = accounts; store.targets = targets;
  const profileSelect = document.querySelector("#profileAccount");
  const selectedProfileAccount = profileSelect.value;
  profileSelect.innerHTML = accounts.length ? accounts.map(account => `<option value="${account.id}">${esc(account.name)} · ${esc(account.platform)}</option>`).join("") : '<option value="">Chưa có account</option>';
  if (accounts.some(account => account.id === selectedProfileAccount)) profileSelect.value = selectedProfileAccount;
  document.querySelectorAll("[data-profile-action]").forEach(button => button.disabled = button.dataset.profileAction !== "import" && !accounts.length);
  document.querySelector("#profileHelp").textContent = accounts.length ? "Export tạo một file ZIP chứa toàn bộ account/profile; Import file đó một lần ở app Tinix khác." : "Import file .tinix-profiles.zip để tạo toàn bộ account và Chrome profile trong một lần.";
  document.querySelector("#accountList").innerHTML = accounts.length ? accounts.map(account => `<div class="list-row"><div><strong>${esc(account.name)}</strong><small class="muted">${esc(account.platform)} · ${badge(account.login_status)}${account.profile_operation_locked ? " · profile đang bảo trì" : ""}</small></div><div class="account-actions"><button data-account-action="chrome" data-id="${account.id}">Mở Chrome</button><button data-account-action="login" data-id="${account.id}">Kiểm tra login</button><button data-account-action="sync" data-id="${account.id}">Đồng bộ ${account.platform==="facebook"?"Page":"kênh"}</button><button data-account-action="backup" data-id="${account.id}">Backup</button><button data-account-action="restore" data-id="${account.id}">Khôi phục</button><button data-account-action="toggle" data-id="${account.id}">${account.enabled ? "Tắt" : "Bật"}</button><button data-account-action="edit" data-id="${account.id}">Sửa</button><button class="danger" data-account-action="delete" data-id="${account.id}">Xóa</button></div></div>`).join("") : '<p class="muted">Chưa có account. Bạn có thể Import một gói profile hoặc tạo account thủ công.</p>';
  document.querySelector("#targetList").innerHTML = targets.length ? targets.map(target => `<div class="list-row"><div><strong>${esc(target.name)}</strong><small class="muted">${esc(target.platform)} · ${esc(target.access_status)} · ${esc((accounts.find(a=>a.id===target.account_id)||{}).name||"")}</small></div><button data-target-id="${target.id}" data-enabled="${target.enabled}">${target.enabled ? "Tắt" : "Bật"}</button></div>`).join("") : '<p class="muted">Chưa có Page hoặc kênh được đồng bộ.</p>';
  bindActions();
}

async function runProfileAction(action, account) {
  if (action === "import") {
    const dialog = document.querySelector("#profileImportDialog");
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
      toast(`Đã Export ${result.accounts_exported} profile tới ${result.archive_path}`);
      return true;
    } finally {
      button.textContent = originalLabel;
      button.disabled = !store.accounts.length;
    }
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
    try {
      if (action === "chrome") await api(`/accounts/${account.id}/chrome/open`, {method:"POST"});
      if (action === "login") { const result = await api(`/accounts/${account.id}/check-login`, {method:"POST"}); toast(`Login: ${result.login_status}`); }
      if (action === "sync") { await api(`/accounts/${account.id}/sync-targets`, {method:"POST"}); toast("Đã đồng bộ Page/profile/channel từ UI"); }
      if (["export","backup","restore"].includes(action)) await runProfileAction(action, account);
      if (action === "toggle") await api(`/accounts/${account.id}/enabled`, {method:"PATCH", body:JSON.stringify({enabled:!account.enabled, reason:"Thay đổi từ WebUI"})});
      if (action === "edit") { const name = prompt("Tên account", account.name); if (name) await api(`/accounts/${account.id}`, {method:"PUT", body:JSON.stringify({name, platform:account.platform})}); }
      if (action === "delete" && confirm("Chỉ xóa account không có Page/job. Chrome profile trên ổ đĩa sẽ được giữ lại. Tiếp tục?")) await api(`/accounts/${account.id}`, {method:"DELETE"});
      await refreshAccounts();
    } catch (error) { toast(error.message); }
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
    importDialog.close();
    toast("Đang Import toàn bộ account/profile. Vui lòng chờ...");
    try {
      const result = await api("/profiles/import", {method:"POST", body:JSON.stringify({bundle_path:archivePath})});
      event.target.reset();
      await refreshAccounts();
      toast(`Đã Import ${result.accounts_imported} account/profile từ ${result.source_app || "gói Tinix"}`);
    } catch (error) {
      toast(error.message);
    }
  };
  document.querySelector("#closeAllChrome").onclick = async () => { const result = await api("/chrome/close-all", {method:"POST"}); toast(`Đã đóng ${result.closed} Chrome`); };
  document.querySelectorAll("[data-profile-action]").forEach(button => button.onclick = async () => {
    const account = store.accounts.find(item => item.id === document.querySelector("#profileAccount").value);
    try { if (await runProfileAction(button.dataset.profileAction, account)) await refreshAccounts(); } catch(error) { toast(error.message); }
  });
  document.querySelector("#targetSearch").oninput = () => { clearTimeout(initAccounts.searchTimer); initAccounts.searchTimer = setTimeout(refreshAccounts, 350); };
}
