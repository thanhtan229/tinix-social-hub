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
  x: '<svg viewBox="0 0 24 24" aria-hidden="true"><rect width="24" height="24" rx="6" fill="#050505"/><path fill="#fff" d="M5.2 4h4.4l3.4 4.7L17.1 4h1.7l-5 5.9L19.5 20h-4.4l-3.8-5.3L6.8 20H5.1l5.4-6.5L5.2 4Zm3.5 1.4H7.9l8 13.2h.8l-8-13.2Z"/></svg>',
};

const PLATFORM_LABELS = {facebook:"Facebook", instagram:"Instagram", tiktok:"TikTok", youtube:"YouTube", x:"X"};
const INVALID_FACEBOOK_TARGETS = new Set(["url:latest", "url:ad_center"]);
const ACCESS_LABELS = {
  accessible:"Có thể truy cập",
  inaccessible:"Không thể truy cập",
  unknown:"Chưa kiểm tra",
};

function targetTypeLabel(target) {
  const labels = {page:"Page", profile:"Hồ sơ", channel:"Kênh"};
  return labels[target.target_type] || "Kênh";
}

function isInvalidFacebookTarget(target) {
  const name = String(target.name || "").trim().toLocaleLowerCase("vi");
  return INVALID_FACEBOOK_TARGETS.has(target.external_id)
    || name.startsWith("unread")
    || name.startsWith("chưa đọc");
}
const accountFilters = {search:"", platform:"", status:"", sort:"platform_name", selectedAccountId:""};
const loginPolls = new Map();
let providerConnections = [];

const ROUTING_LABELS = {
  chrome_preferred:"Ưu tiên Chrome",
  official_api_preferred:"Ưu tiên API",
  chrome_only:"Chỉ Chrome",
  official_api_only:"Chỉ API",
};

function routingControl(account) {
  const preference = account.routing_preference || "chrome_preferred";
  const connection = providerConnections.find(item => item.account_id === account.id && item.transport === "official_api");
  const options = Object.entries(ROUTING_LABELS).map(([value,label]) =>
    `<option value="${value}"${value === preference ? " selected" : ""}>${label}</option>`
  ).join("");
  const apiButton = account.platform === "youtube"
    ? `<button data-account-action="${connection ? "disconnect-api" : "connect-api"}" data-id="${account.id}" data-connection-id="${connection?.id || ""}">${connection ? "API đã nối" : "Kết nối API"}</button>`
    : "";
  return `<div class="account-routing"><select data-routing-account="${account.id}" aria-label="Cách đăng của ${esc(account.name)}">${options}</select>${apiButton}</div>`;
}

function setAccountLoginStatus(accountId, loginStatus) {
  const account = store.accounts.find(item => item.id === accountId);
  if (!account) return;
  account.login_status = loginStatus;
  renderAccountList();
}

function stopLoginPolling(accountId) {
  const timer = loginPolls.get(accountId);
  if (timer) clearTimeout(timer);
  loginPolls.delete(accountId);
}

function pollLoginAfterOpen(account, attempt = 0) {
  stopLoginPolling(account.id);
  if (attempt >= 24) return;
  const timer = setTimeout(async () => {
    try {
      const result = await api(`/accounts/${account.id}/check-login`, {method:"POST"});
      setAccountLoginStatus(account.id, result.login_status);
      if (result.login_status === "logged_in") {
        stopLoginPolling(account.id);
        toast(`${account.name}: ${STATUS[result.login_status]}`);
        return;
      }
      if (result.login_status === "checkpoint") {
        stopLoginPolling(account.id);
        return;
      }
    } catch (_) {
      // Chrome may be navigating while the user signs in; retry within the polling window.
    }
    if (!loginPolls.has(account.id)) return;
    pollLoginAfterOpen(account, attempt + 1);
  }, 5000);
  loginPolls.set(account.id, timer);
}

function platformIcon(platform) {
  const key = String(platform || "").toLowerCase();
  const icon = PLATFORM_ICONS[key] || '<svg viewBox="0 0 24 24" aria-hidden="true"><circle cx="12" cy="12" r="10" fill="#718078"/><path d="M2 12h20M12 2a15 15 0 0 1 0 20M12 2a15 15 0 0 0 0 20" fill="none" stroke="#fff" stroke-width="1.5"/></svg>';
  return `<span class="platform-icon platform-${esc(key)}" title="${esc(platform)}" aria-label="Nền tảng ${esc(platform)}">${icon}</span>`;
}

async function openAccountDialog(account = null) {
  const dialog = document.querySelector("#accountDialog");
  const credentials = account ? await api(`/accounts/${account.id}/credentials`) : {};
  document.querySelector("#accountId").value = account?.id || "";
  document.querySelector("#accountName").value = account?.name || "";
  document.querySelector("#accountPlatform").value = account?.platform || "facebook";
  document.querySelector("#accountUsername").value = account?.username || "";
  document.querySelector("#accountEmail").value = account?.email || "";
  document.querySelector("#accountPassword").value = credentials.password || "";
  document.querySelector("#account2fa").value = credentials.secret_2fa || "";
  document.querySelector("#accountEmailPassword").value = credentials.email_pass || "";
  document.querySelector("#accountCookie").value = credentials.cookie || "";
  document.querySelector("#accountDialogTitle").textContent = account ? "Sửa tài khoản" : "Thêm tài khoản";
  document.querySelector("#saveAccount").textContent = account ? "Lưu thay đổi" : "Tạo";
  dialog.showModal();
  setTimeout(() => document.querySelector("#accountName")?.focus(), 0);
}

function openDeleteAccountDialog(account) {
  const dialog = document.querySelector("#deleteAccountDialog");
  dialog.dataset.accountId = account.id;
  document.querySelector("#deleteAccountName").textContent = account.name;
  dialog.showModal();
}

function renderPlatformFilters() {
  const counts = store.accounts.reduce((result, account) => {
    result[account.platform] = (result[account.platform] || 0) + 1;
    return result;
  }, {});
  if (accountFilters.platform && !counts[accountFilters.platform]) accountFilters.platform = "";
  const platforms = ["facebook", "instagram", "tiktok", "youtube", "x"].filter(platform => counts[platform]);
  const button = (platform, label, count, icon = "") => `<button type="button" class="account-platform-filter${accountFilters.platform === platform ? " active" : ""}" data-account-platform="${platform}">${icon}<span>${label}</span><b>${count}</b></button>`;
  document.querySelector("#accountPlatformFilters").innerHTML = button("", "Tất cả", store.accounts.length) + platforms.map(platform => button(platform, PLATFORM_LABELS[platform] || platform, counts[platform], platformIcon(platform))).join("");
  document.querySelectorAll("[data-account-platform]").forEach(filterButton => filterButton.onclick = () => {
    accountFilters.platform = filterButton.dataset.accountPlatform;
    renderAccountList();
  });
}

function filteredAccounts() {
  const search = accountFilters.search.trim().toLocaleLowerCase("vi");
  const result = store.accounts.filter(account => {
    const haystack = [account.name, account.username, account.email].join(" ").toLocaleLowerCase("vi");
    return (!search || haystack.includes(search)) &&
      (!accountFilters.platform || account.platform === accountFilters.platform) &&
      (!accountFilters.status || account.login_status === accountFilters.status);
  });
  const byName = (left, right) => left.name.localeCompare(right.name, "vi", {numeric:true, sensitivity:"base"});
  result.sort((left, right) => {
    if (accountFilters.sort === "name_asc") return byName(left, right);
    if (accountFilters.sort === "name_desc") return byName(right, left);
    if (accountFilters.sort === "status") return (STATUS[left.login_status] || left.login_status).localeCompare(STATUS[right.login_status] || right.login_status, "vi") || byName(left, right);
    return left.platform.localeCompare(right.platform) || byName(left, right);
  });
  return result;
}

function renderTargetList() {
  const selected = store.accounts.find(account => account.id === accountFilters.selectedAccountId);
  const targets = selected
    ? store.targets.filter(target => target.account_id === selected.id)
    : store.targets;
  const filterLabel = document.querySelector("#targetAccountFilter");
  filterLabel.innerHTML = selected
    ? `<span class="target-filter-note"><span>Đang lọc theo</span><strong>Account: ${esc(selected.name)}</strong><small>Chọn lại account để bỏ lọc</small></span>`
    : `<span class="target-filter-note is-all">Tất cả account</span>`;
  const targetList = document.querySelector("#targetList");
  targetList.innerHTML = targets.length ? `<div class="target-grid">${targets.map(target => {
    const account = store.accounts.find(item => item.id === target.account_id) || {};
    const platform = String(target.platform || "").toLowerCase();
    const access = String(target.access_status || "unknown").toLowerCase();
    const enabled = Boolean(Number(target.enabled));
    return `<article class="target-row ${enabled ? "is-enabled" : "is-disabled"}">
      <button class="target-open-surface" data-open-target="${target.id}" aria-label="Mở ${esc(target.name)} bằng account ${esc(account.name || "không xác định")}">
        <span class="target-platform-mark">${platformIcon(platform)}</span>
        <span class="target-content">
          <strong class="target-name">${esc(target.name)}</strong>
          <span class="target-meta" aria-label="Thông tin kênh">
            <span class="target-chip target-chip-platform">${esc(targetTypeLabel(target))} · ${esc(PLATFORM_LABELS[platform] || platform)}</span>
            <span class="target-chip target-chip-access access-${esc(access)}"><i></i>${esc(ACCESS_LABELS[access] || access)}</span>
            <span class="target-chip target-chip-account" title="Account sở hữu">Account: ${esc(account.name || "Không xác định")}</span>
          </span>
        </span>
      </button>
      <button class="target-toggle ${enabled ? "is-on" : "is-off"}" data-target-id="${target.id}" data-enabled="${target.enabled}" aria-label="${enabled ? "Tắt" : "Bật"} ${esc(target.name)}" title="Bấm để ${enabled ? "tắt" : "bật"} kênh">
        <span class="target-toggle-dot"></span>${enabled ? "Đang bật" : "Đang tắt"}
      </button>
    </article>`;
  }).join("")}</div>` : `<div class="target-empty"><span aria-hidden="true">◎</span><strong>Chưa có Page hoặc kênh</strong><p>${selected ? `Account ${esc(selected.name)} chưa có kênh được đồng bộ.` : "Hãy chọn một account và bấm Quét Page/Kênh."}</p></div>`;
  const openTarget = async trigger => {
    const row = trigger.closest(".target-row");
    if (row.classList.contains("is-opening")) return;
    row.classList.add("is-opening");
    const name = row.querySelector(".target-name")?.textContent || "Page/Kênh";
    toast(`Đang mở ${name} bằng đúng Chrome account…`);
    try {
      await api(`/targets/${trigger.dataset.openTarget}/chrome/open`, {method:"POST"});
      toast(`Đã mở ${name} trong Chrome.`);
    } catch (error) {
      toast(error.message);
    } finally {
      row.classList.remove("is-opening");
    }
  };
  document.querySelectorAll("[data-open-target]").forEach(button => {
    button.onclick = () => openTarget(button);
  });
  document.querySelectorAll("[data-target-id]").forEach(button => button.onclick = async () => {
    try {
      await api(`/targets/${button.dataset.targetId}/enabled`, {method:"PATCH", body:JSON.stringify({enabled:button.dataset.enabled !== "1"})});
      await refreshAccounts();
    } catch(error) { toast(error.message); }
  });
}

function renderAccountList() {
  renderPlatformFilters();
  const accounts = filteredAccounts();
  document.querySelector("#accountResultCount").textContent = `Hiển thị ${accounts.length}/${store.accounts.length}`;
  document.querySelector("#accountList").innerHTML = accounts.length ? `<table class="account-table"><thead><tr><th class="account-index">STT</th><th>Account</th><th>Username / Email</th><th>Trạng thái</th><th>Cách đăng</th><th class="account-action-heading">Thao tác</th></tr></thead><tbody>${accounts.map((account,index) => `<tr data-account-row="${account.id}" class="${account.id === accountFilters.selectedAccountId ? "selected" : ""}" tabindex="0" aria-selected="${account.id === accountFilters.selectedAccountId}"><td class="account-index" data-label="STT">${index+1}</td><td data-label="Account"><div class="account-identity"><strong>${esc(account.name)}</strong>${platformIcon(account.platform)}</div></td><td data-label="Username / Email"><span class="account-contact">${esc(account.username || account.email || "Chưa có username/email")}</span>${account.username && account.email ? `<small>${esc(account.email)}</small>` : ""}</td><td data-label="Trạng thái">${badge(account.login_status)}${account.profile_operation_locked ? '<small class="profile-maintenance">Profile đang bảo trì</small>' : ""}</td><td data-label="Cách đăng">${routingControl(account)}</td><td data-label="Thao tác"><div class="account-actions"><button data-account-action="chrome" data-id="${account.id}">Mở</button><button data-account-action="sync" data-id="${account.id}"${account.profile_operation_locked ? " disabled" : ""}>Quét Page/Kênh</button><button data-account-action="edit" data-id="${account.id}">Sửa</button><button class="danger" data-account-action="delete" data-id="${account.id}">Xóa</button></div></td></tr>`).join("")}</tbody></table>` : `<p class="muted account-empty">${store.accounts.length ? "Không có account phù hợp bộ lọc." : "Chưa có account. Bạn có thể Import một gói profile hoặc tạo account thủ công."}</p>`;
  bindActions();
  document.querySelectorAll("[data-routing-account]").forEach(select => select.onchange = async event => {
    event.stopPropagation();
    try {
      await api(`/accounts/${select.dataset.routingAccount}/routing-preference`, {
        method:"PATCH", body:JSON.stringify({routing_preference:select.value}),
      });
      const account = store.accounts.find(item => item.id === select.dataset.routingAccount);
      if (account) account.routing_preference = select.value;
      toast(`Đã chọn: ${ROUTING_LABELS[select.value]}`);
    } catch (error) { toast(error.message); await refreshAccounts(); }
  });
  bindAccountRows();
}

function selectAccountRow(accountId) {
  accountFilters.selectedAccountId = accountFilters.selectedAccountId === accountId ? "" : accountId;
  renderAccountList();
  renderTargetList();
}

function bindAccountRows() {
  document.querySelectorAll("[data-account-row]").forEach(row => {
    row.onclick = event => {
      if (event.target.closest("button, a, input, select, textarea")) return;
      selectAccountRow(row.dataset.accountRow);
    };
    row.onkeydown = event => {
      if (event.key !== "Enter" && event.key !== " ") return;
      if (event.target.closest("button, a, input, select, textarea")) return;
      event.preventDefault();
      selectAccountRow(row.dataset.accountRow);
    };
  });
}

export async function refreshAccounts() {
  try {
    const [accounts, targets, connections] = await Promise.all([
      api("/accounts"),
      api(`/targets?search=${encodeURIComponent(document.querySelector("#targetSearch")?.value || "")}`),
      api("/connections"),
    ]);
    store.accounts = accounts || [];
    providerConnections = connections || [];
    store.targets = (targets || []).filter(target => !isInvalidFacebookTarget(target));
    if (accountFilters.selectedAccountId && !store.accounts.some(account => account.id === accountFilters.selectedAccountId)) {
      accountFilters.selectedAccountId = "";
    }
    const profileSelect = document.querySelector("#profileAccount");
    if (profileSelect) {
      const selectedProfileAccount = profileSelect.value;
      profileSelect.innerHTML = accounts.length ? accounts.map(account => `<option value="${account.id}">${esc(account.name)} · ${esc(account.platform)}</option>`).join("") : '<option value="">Chưa có account</option>';
      if (accounts.some(account => account.id === selectedProfileAccount)) profileSelect.value = selectedProfileAccount;
    }
    document.querySelectorAll("[data-profile-action]").forEach(button => button.disabled = button.dataset.profileAction !== "import" && !accounts.length);
    const helpEl = document.querySelector("#profileHelp");
    if (helpEl) {
      helpEl.textContent = accounts.length ? "Export tạo ZIP chứa thông tin account, dữ liệu đăng nhập và phiên Chrome; hãy bảo quản file cẩn thận." : "Import file .tinix-profiles.zip để tạo toàn bộ account, thông tin đăng nhập và phiên Chrome trong một lần.";
    }
    renderAccountList();
    renderTargetList();
  } catch (error) {
    console.error("Lỗi khi tải danh sách accounts:", error);
    toast(`Không thể tải accounts: ${error.message}`);
  }
}

async function runProfileAction(action, account = null) {
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
  let targetAccount = account;
  if (!targetAccount) {
    if (!store.accounts.length) { toast("Hãy tạo hoặc import account trước."); return false; }
    if (store.accounts.length === 1) {
      targetAccount = store.accounts[0];
    } else {
      const listing = store.accounts.map((acc, idx) => `${idx + 1}. ${acc.name} (${acc.platform})`).join("\n");
      const choice = prompt(`Chọn account để ${action === "backup" ? "Backup" : "Khôi phục"}:\n${listing}`, "1");
      if (!choice) return false;
      targetAccount = store.accounts[Number(choice) - 1];
      if (!targetAccount) { toast("Lựa chọn không hợp lệ."); return false; }
    }
  }
  if (action === "backup") {
    if (!confirm(`Đóng Chrome của account ${targetAccount.name} trước khi Backup. Tiếp tục?`)) return false;
    const result = await api(`/accounts/${targetAccount.id}/profile/backup`, {method:"POST"});
    toast(`Đã tạo backup ${result.backup_name}`);
  }
  if (action === "restore") {
    const backups = await api(`/accounts/${targetAccount.id}/profile/backups`);
    if (!backups.length) { toast(`Account ${targetAccount.name} chưa có backup profile.`); return false; }
    const choices = backups.map((item,index)=>`${index+1}. ${item.name}`).join("\n");
    const selected = prompt(`Chọn số thứ tự backup cần khôi phục cho ${targetAccount.name}:\n${choices}`);
    if (!selected) return false;
    const backup = backups[Number(selected)-1];
    if (!backup) { toast("Số thứ tự backup không hợp lệ."); return false; }
    if (!confirm(`Khôi phục ${backup.name}? Profile hiện tại sẽ được backup trước khi thay thế.`)) return false;
    const result = await api(`/accounts/${targetAccount.id}/profile/restore`, {method:"POST", body:JSON.stringify({backup_name:backup.name})});
    toast(`Đã khôi phục ${result.restored_from}. Backup trước khôi phục: ${result.backup_name || "không có"}`);
  }
  return true;
}

function bindActions() {
  document.querySelectorAll("[data-account-action]").forEach(button => button.onclick = async event => {
    event.stopPropagation();
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
          setAccountLoginStatus(account.id, result.login_status);
          toast(`${account.name}: ${STATUS[result.login_status] || result.login_status}`);
          if (!["logged_in", "checkpoint"].includes(result.login_status)) pollLoginAfterOpen(account);
        } catch (error) {
          throw new Error(`Đã mở Chrome nhưng kiểm tra đăng nhập thất bại: ${error.message}`);
        }
      }
      if (action === "sync") {
        const syncStatus = document.querySelector("#targetSyncStatus");
        button.disabled = true;
        button.textContent = "Đang quét…";
        syncStatus.className = "operation-status";
        syncStatus.textContent = `Đang quét Page/Kênh của ${account.name}…`;
        const targets = await api(`/accounts/${account.id}/sync-targets`, {method:"POST"});
        const validTargets = targets.filter(target => !isInvalidFacebookTarget(target));
        try {
          await api(`/accounts/${account.id}/chrome/close`, {method:"POST"});
          syncStatus.className = "operation-status success";
          syncStatus.textContent = `Đã quét xong ${account.name}: tìm thấy ${validTargets.length} Page/Kênh. Chrome đã đóng.`;
          toast(`${account.name}: đã quét xong, tìm thấy ${validTargets.length} Page/Kênh.`);
        } catch (closeError) {
          syncStatus.className = "operation-status error";
          syncStatus.textContent = `Đã quét xong ${account.name}: tìm thấy ${validTargets.length} Page/Kênh, nhưng không thể đóng Chrome: ${closeError.message}`;
          toast(`${account.name}: quét xong nhưng không thể đóng Chrome.`);
        }
      }
      if (action === "close") { stopLoginPolling(account.id); const result = await api(`/accounts/${account.id}/chrome/close`, {method:"POST"}); toast(result.closed ? `Đã đóng Chrome của ${account.name}` : `Chrome của ${account.name} chưa chạy`); }
      if (action === "connect-api") {
        const result = await api(`/accounts/${account.id}/connections/youtube/authorize`, {method:"POST"});
        window.open(result.authorization_url, "_blank", "noopener,noreferrer");
        toast("Hãy cấp quyền YouTube trong tab mới, sau đó quay lại và tải lại danh sách account.");
        return;
      }
      if (action === "disconnect-api") {
        if (!confirm(`Ngắt kết nối YouTube API của ${account.name}?`)) return;
        await api(`/accounts/${account.id}/connections/${button.dataset.connectionId}`, {method:"DELETE"});
        toast("Đã ngắt kết nối YouTube API.");
      }
      if (action === "edit") { await openAccountDialog(account); return; }
      if (action === "delete") { openDeleteAccountDialog(account); return; }
      await refreshAccounts();
    } catch (error) {
      if (action === "sync") {
        const syncStatus = document.querySelector("#targetSyncStatus");
        syncStatus.className = "operation-status error";
        syncStatus.textContent = `Quét ${account.name} thất bại: ${error.message}`;
      }
      toast(error.message);
    }
    finally { button.disabled = false; button.textContent = originalLabel; }
  });
}

export function initAccounts() {
  const dialog = document.querySelector("#accountDialog");
  document.querySelector("#newAccount").onclick = () => openAccountDialog();
  document.querySelector("#accountForm").onsubmit = async event => {
    event.preventDefault();
    const accountId = document.querySelector("#accountId").value;
    const payload = JSON.stringify({
      name:document.querySelector("#accountName").value.trim(),
      platform:document.querySelector("#accountPlatform").value,
      username:document.querySelector("#accountUsername").value.trim(),
      email:document.querySelector("#accountEmail").value.trim(),
      password:document.querySelector("#accountPassword").value,
      secret_2fa:document.querySelector("#account2fa").value.trim(),
      email_pass:document.querySelector("#accountEmailPassword").value,
      cookie:document.querySelector("#accountCookie").value.trim(),
    });
    const saveButton = document.querySelector("#saveAccount");
    const originalLabel = saveButton.textContent;
    saveButton.disabled = true;
    saveButton.textContent = "Đang lưu…";
    try {
      await api(accountId ? `/accounts/${accountId}` : "/accounts", {method:accountId ? "PUT" : "POST", body:payload});
      await refreshAccounts();
      dialog.close();
      event.target.reset();
      toast(accountId ? "Đã cập nhật account" : "Đã thêm account");
    } catch(error) { toast(error.message); }
    finally { saveButton.disabled = false; saveButton.textContent = originalLabel; }
  };
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
  const deleteDialog = document.querySelector("#deleteAccountDialog");
  const deleteAccount = async deleteProfile => {
    const accountId = deleteDialog.dataset.accountId;
    const account = store.accounts.find(item => item.id === accountId);
    const buttons = deleteDialog.querySelectorAll("button");
    buttons.forEach(button => button.disabled = true);
    try {
      const result = await api(`/accounts/${accountId}?delete_profile=${deleteProfile}`, {method:"DELETE"});
      deleteDialog.close();
      await refreshAccounts();
      if (result.cleanup_warning) toast(result.cleanup_warning);
      else toast(deleteProfile ? `Đã xóa account và Chrome profile của ${account?.name || "account"}` : "Đã xóa account; Chrome profile vẫn được giữ lại");
    } catch (error) { toast(error.message); }
    finally { buttons.forEach(button => button.disabled = false); }
  };
  document.querySelector("#deleteAccountKeepProfile").onclick = () => deleteAccount(false);
  document.querySelector("#deleteAccountWithProfile").onclick = () => deleteAccount(true);
  document.querySelectorAll("[data-profile-action]").forEach(button => button.onclick = async () => {
    const profileSelect = document.querySelector("#profileAccount");
    const account = profileSelect ? store.accounts.find(item => item.id === profileSelect.value) : null;
    try { if (await runProfileAction(button.dataset.profileAction, account)) await refreshAccounts(); } catch(error) { toast(error.message); }
  });
  document.querySelector("#targetSearch").oninput = () => { clearTimeout(initAccounts.searchTimer); initAccounts.searchTimer = setTimeout(refreshAccounts, 350); };
  document.querySelector("#accountSearch").oninput = event => { accountFilters.search = event.target.value; renderAccountList(); };
  document.querySelector("#accountStatusFilter").onchange = event => { accountFilters.status = event.target.value; renderAccountList(); };
  document.querySelector("#accountSort").onchange = event => { accountFilters.sort = event.target.value; renderAccountList(); };
}
