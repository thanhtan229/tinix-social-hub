import {api, badge, esc, toast} from "./api.js";
import {store} from "./store.js";

export async function refreshAccounts() {
  const [accounts, targets] = await Promise.all([api("/accounts"), api(`/targets?search=${encodeURIComponent(document.querySelector("#targetSearch")?.value || "")}`)]);
  store.accounts = accounts; store.targets = targets;
  document.querySelector("#accountList").innerHTML = accounts.length ? accounts.map(account => `<div class="list-row"><div><strong>${esc(account.name)}</strong><small class="muted">${esc(account.platform)} · ${badge(account.login_status)}</small></div><div class="account-actions"><button data-account-action="chrome" data-id="${account.id}">Mở Chrome</button>${account.platform === "facebook" ? `<button data-account-action="login" data-id="${account.id}">Kiểm tra login</button><button data-account-action="sync" data-id="${account.id}">Đồng bộ Page</button>` : ""}<button data-account-action="toggle" data-id="${account.id}">${account.enabled ? "Tắt" : "Bật"}</button><button data-account-action="edit" data-id="${account.id}">Sửa</button><button class="danger" data-account-action="delete" data-id="${account.id}">Xóa</button></div></div>`).join("") : '<p class="muted">Chưa có account.</p>';
  document.querySelector("#targetList").innerHTML = targets.length ? targets.map(target => `<div class="list-row"><div><strong>${esc(target.name)}</strong><small class="muted">${esc(target.platform)} · ${esc(target.access_status)} · ${esc((accounts.find(a=>a.id===target.account_id)||{}).name||"")}</small></div><button data-target-id="${target.id}" data-enabled="${target.enabled}">${target.enabled ? "Tắt" : "Bật"}</button></div>`).join("") : '<p class="muted">Chưa có Page hoặc kênh được đồng bộ.</p>';
  bindActions();
}

function bindActions() {
  document.querySelectorAll("[data-account-action]").forEach(button => button.onclick = async () => {
    const account = store.accounts.find(item => item.id === button.dataset.id); const action = button.dataset.accountAction;
    try {
      if (action === "chrome") await api(`/accounts/${account.id}/chrome/open`, {method:"POST"});
      if (action === "login") { const result = await api(`/accounts/${account.id}/check-login`, {method:"POST"}); toast(`Login: ${result.login_status}`); }
      if (action === "sync") { await api(`/accounts/${account.id}/sync-pages`, {method:"POST"}); toast("Đã đồng bộ Facebook Page"); }
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
  document.querySelector("#closeAllChrome").onclick = async () => { const result = await api("/chrome/close-all", {method:"POST"}); toast(`Đã đóng ${result.closed} Chrome`); };
  document.querySelector("#targetSearch").oninput = () => { clearTimeout(initAccounts.searchTimer); initAccounts.searchTimer = setTimeout(refreshAccounts, 350); };
}
