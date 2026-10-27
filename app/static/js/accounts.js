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

const READINESS_LABELS = {
  dry_run_ready: "Dry-run đạt",
  published_unverified: "Đã đăng, chưa đối soát",
  real_publish_verified: "Đã xác minh đăng thật",
  review_required: "Cần dry-run lại",
  attention_required: "Lần thử mới nhất cần xử lý",
  latest_attempt_pending: "Đang chờ kết quả mới nhất",
  no_successful_evidence: "Chưa có lần chạy thành công",
};

function readinessSummary(account) {
  const items = account.readiness || [];
  if (!items.length) return "Chưa có bằng chứng dry-run";
  return items.map(item => `${item.content_format}/${item.transport || "chrome"}: ${READINESS_LABELS[item.state] || item.state}`).join(" · ");
}

function youtubeApiState(account) {
  if (account.platform !== "youtube") return null;
  const connection = providerConnections.find(item =>
    item.account_id === account.id && item.transport === "official_api"
  );
  if (!connection || connection.status === "disconnected") {
    return {state:"disconnected", label:"Chưa kết nối", action:"Kết nối API"};
  }
  if (connection.status === "connected") {
    return {state:"connected", label:"Đã kết nối", action:""};
  }
  return {state:"reauth", label:"Cần kết nối lại", action:"Kết nối lại API"};
}

function metaApiState(account) {
  if (account.platform !== "facebook") return null;
  const connection = providerConnections.find(item =>
    item.account_id === account.id && item.transport === "official_api" && item.provider === "meta"
  );
  if (!connection || connection.status === "disconnected") return {state:"disconnected", label:"Chưa kết nối", action:"Kết nối Meta API"};
  if (connection.status === "connected") {
    const method = connection.refresh_metadata?.auth_method === "system_user" ? "System User" : "OAuth";
    const rawCount = connection.refresh_metadata?.connected_page_count;
    const countLabel = rawCount === undefined ? "" : ` · ${Number(rawCount) || 0} Page`;
    return {state:"connected", label:`Đã kết nối · ${method}${countLabel}`, action:""};
  }
  return {state:"reauth", label:"Cần kết nối lại", action:"Kết nối lại API"};
}

function instagramApiState(account) {
  if (account.platform !== "instagram") return null;
  const connection = providerConnections.find(item =>
    item.account_id === account.id && item.transport === "official_api" && item.provider === "instagram"
  );
  if (!connection || connection.status === "disconnected") return {state:"disconnected", label:"Chưa kết nối", action:"Kết nối Instagram Login"};
  if (connection.status === "connected") {
    const username = connection.refresh_metadata?.username;
    const expiresAt = Date.parse(connection.expires_at || "");
    if (Number.isFinite(expiresAt) && expiresAt <= Date.now()) {
      return {state:"reauth", label:"Token đã hết hạn", action:"Kết nối lại Instagram", connectionId:connection.id};
    }
    const refreshAvailable = Number.isFinite(expiresAt) && expiresAt - Date.now() <= 7 * 24 * 60 * 60 * 1000;
    return {state:"connected", label:`Đã kết nối${username ? ` · @${username}` : ""}`, action:"",
      connectionId:connection.id, refreshAvailable};
  }
  return {state:"reauth", label:"Cần kết nối lại", action:"Kết nối lại Instagram"};
}

function routingControl(account) {
  const preference = account.routing_preference || "chrome_preferred";
  const apiState = youtubeApiState(account) || metaApiState(account) || instagramApiState(account);
  const options = Object.entries(ROUTING_LABELS).map(([value,label]) =>
    `<option value="${value}"${value === preference ? " selected" : ""}>${label}</option>`
  ).join("");
  const provider = account.platform === "facebook" ? "meta" : account.platform === "instagram" ? "instagram" : "google_youtube";
  const connection = providerConnections.find(item => item.account_id === account.id && item.transport === "official_api" && item.provider === provider);
  const connected = apiState?.state === "connected";
  const apiButton = account.platform === "facebook"
    ? connected
      ? `<button data-account-action="manage-meta-api" data-id="${account.id}">Cập nhật Meta API</button><button data-account-action="disconnect-api" data-id="${account.id}" data-connection-id="${connection?.id || ""}">Ngắt API</button>`
      : `<button data-account-action="connect-api" data-id="${account.id}">${apiState?.action || "Kết nối Meta API"}</button>`
    : account.platform === "youtube"
      ? `<button data-account-action="${connected ? "disconnect-api" : "connect-api"}" data-id="${account.id}" data-connection-id="${connection?.id || ""}">${connected ? "Ngắt API" : apiState?.action || "Kết nối API"}</button>`
      : account.platform === "instagram"
      ? `<button data-account-action="${connected ? "disconnect-api" : "connect-api"}" data-id="${account.id}" data-connection-id="${connection?.id || ""}">${connected ? "Ngắt Instagram Login" : apiState?.action || "Kết nối Instagram Login"}</button>`
      : "";
  const refreshButton = account.platform === "instagram" && connected && apiState?.refreshAvailable
    ? `<button data-account-action="refresh-instagram-api" data-id="${account.id}" data-connection-id="${apiState.connectionId}">Gia hạn Instagram token</button>` : "";
  const syncButton = account.platform === "facebook" && connected
    ? `<button data-account-action="sync-meta-api" data-id="${account.id}">Đồng bộ Page API</button>` : "";
  return `<div class="account-routing"><select data-routing-account="${account.id}" aria-label="Cách đăng của ${esc(account.name)}">${options}</select>${apiButton}${refreshButton}${syncButton}</div>`;
}

function refreshConnectionsWhenAppReturns() {
  let timeoutId;
  const cleanup = () => {
    window.removeEventListener("focus", onReturn);
    document.removeEventListener("visibilitychange", onReturn);
    clearTimeout(timeoutId);
  };
  const onReturn = () => {
    if (document.visibilityState === "hidden") return;
    cleanup();
    window.setTimeout(() => refreshAccounts(), 300);
  };
  window.addEventListener("focus", onReturn);
  document.addEventListener("visibilitychange", onReturn);
  timeoutId = window.setTimeout(cleanup, 120000);
}

async function openMetaConnectionDialog(account) {
  const apps = (await api("/integrations/platform-apps"))
    .filter(item => item.provider === "meta" && item.enabled);
  if (!apps.length) {
    toast("Hãy thêm và bật Meta App ID cùng Graph API version trong Cài đặt → Tích hợp. Secret và Redirect URI chỉ cần nếu chọn OAuth.");
    return;
  }
  let bindings = [];
  try { bindings = await api(`/accounts/${account.id}/connections/meta/targets`); } catch (_) {}
  const dialog = document.querySelector("#metaSystemUserDialog");
  const form = document.querySelector("#metaSystemUserForm");
  const appSelect = document.querySelector("#metaSystemUserApp");
  appSelect.innerHTML = apps.map(item => `<option value="${esc(item.id)}">${esc(item.name)} · ${esc(item.api_version || "chưa có Graph API version")}</option>`).join("");
  form.dataset.connectedPageIds = JSON.stringify(bindings.filter(item => item.status === "connected")
    .map(item => String(item.external_target_id || "")).filter(value => /^\d+$/.test(value)));
  document.querySelector("#metaSystemUserDiscoveryStatus").textContent = "";
  document.querySelector("#metaSystemUserManualPageIds").value = "";
  const choices = bindings.map(item => ({
    id:String(item.external_target_id || ""), name:item.target_name || item.external_target_id,
    tasks:item.tasks || [], status:item.status, binding_id:item.id,
    can_publish:Boolean(item.can_publish), permissions_verified:Boolean(item.permissions_verified),
    source:"binding",
  })).filter(item => item.id);
  form.dataset.pageChoices = JSON.stringify(choices);
  renderMetaPageChoices(choices);
  document.querySelector("#metaSystemUserAccountName").textContent = account.name;
  document.querySelector("#metaSystemUserStatus").textContent = "";
  document.querySelector("#metaSystemUserToken").value = "";
  dialog.dataset.accountId = account.id;
  dialog.showModal();
  form.dataset.accountId = account.id;
}

function renderMetaPageChoices(pages) {
  const holder = document.querySelector("#metaSystemUserPageList");
  const form = document.querySelector("#metaSystemUserForm");
  const connectedIds = new Set(JSON.parse(form.dataset.connectedPageIds || "[]"));
  const unique = new Map();
  for (const page of pages || []) {
    const id = String(page.id || "");
    if (!/^\d+$/.test(id)) continue;
    const prior = unique.get(id);
    const hasFreshTasks = Array.isArray(page.tasks);
    const tasks = hasFreshTasks ? page.tasks : prior?.tasks || [];
    const canPublish = page.can_publish ?? (hasFreshTasks ? tasks.some(task =>
      ["CREATE_CONTENT", "PROFILE_PLUS_CREATE_CONTENT", "FULL_CONTROL", "PROFILE_PLUS_FULL_CONTROL"].includes(task)
    ) : Boolean(prior?.can_publish));
    unique.set(id, {...prior, ...page, tasks, can_publish:Boolean(canPublish), id, bound:Boolean(prior?.bound || page.source === "binding"),
      status:prior?.status === "connected" ? "connected" : page.status || prior?.status || "candidate"});
  }
  form.dataset.pageChoices = JSON.stringify([...unique.values()]);
  if (!unique.size) {
    holder.innerHTML = `<p class="muted">Chưa có Page để hiển thị. Hãy tìm Page bằng token hoặc nhập ID thủ công.</p>`;
    return;
  }
  holder.innerHTML = [...unique.values()].map(page => {
    const active = page.bound && page.status === "connected";
    const disconnected = page.bound && page.status === "disconnected";
    const taskLabel = page.permissions_verified === false
      ? "quyền Page chưa xác minh"
      : page.can_publish ? "có quyền đăng" : "chỉ đọc/thiếu quyền đăng";
    return `<div class="meta-page-choice ${disconnected ? "is-disconnected" : ""}">
      <label><input type="checkbox" data-meta-page-choice value="${esc(page.id)}" ${active || connectedIds.has(page.id) ? "checked" : ""} ${disconnected ? "disabled" : ""}>
        <span><strong>${esc(page.name || page.id)}</strong><small>Page ID ${esc(page.id)} · ${disconnected ? "đã ngắt" : taskLabel}</small></span>
      </label>
      ${active ? `<button type="button" data-meta-disconnect="${esc(page.binding_id || "")}" data-page-name="${esc(page.name || page.id)}">Ngắt Page</button>` : ""}
    </div>`;
  }).join("");
  holder.querySelectorAll("[data-meta-disconnect]").forEach(button => {
    button.onclick = async () => {
      const bindingId = button.dataset.metaDisconnect;
      if (!bindingId || !confirm(`Ngắt API cho Page ${button.dataset.pageName}? Target và dữ liệu lịch sử vẫn được giữ.`)) return;
      button.disabled = true;
      try {
        await api(`/accounts/${form.dataset.accountId}/connections/meta/targets/${bindingId}`, {method:"DELETE"});
        document.querySelector("#metaSystemUserDialog").close();
        await refreshAccounts();
        await openMetaConnectionDialog(store.accounts.find(item => item.id === form.dataset.accountId));
        toast("Đã ngắt Page API.");
      } catch (error) { toast(error.message); }
      finally { button.disabled = false; }
    };
  });
}

async function openMetaOAuth(accountId, platformAppId) {
  await api(`/accounts/${accountId}/connections/meta/authorize/open`, {
    method:"POST", body:JSON.stringify({platform_app_id:platformAppId}),
  });
  refreshConnectionsWhenAppReturns();
  toast("Đã mở Meta OAuth trong Chrome profile của account. Hoàn tất consent rồi quay lại Tinix.");
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
    ? `<span class="target-filter-note"><span>Đang lọc theo</span><strong>Account: ${esc(selected.name)}</strong><button type="button" class="btn-sync-chip" data-account-action="sync" data-id="${selected.id}" ${selected.profile_operation_locked ? "disabled" : ""}>Quét Page/Kênh</button><small>Chọn lại account để bỏ lọc</small></span>`
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
  bindActions();
}

let detailAutoSaveTimer = null;

function initSplitter() {
  const container = document.querySelector("#accountsSplitContainer");
  const divider = document.querySelector("#accountsSplitDivider");
  if (!container || !divider) return;

  const savedRatio = localStorage.getItem("tinix_accounts_split_ratio");
  if (savedRatio) {
    container.style.setProperty("--accounts-split-left", savedRatio);
  }

  let isDragging = false;

  divider.onmousedown = event => {
    event.preventDefault();
    isDragging = true;
    divider.classList.add("is-dragging");
    document.body.style.cursor = "col-resize";
    document.body.style.userSelect = "none";
  };

  window.addEventListener("mousemove", event => {
    if (!isDragging) return;
    const rect = container.getBoundingClientRect();
    const offsetX = event.clientX - rect.left;
    const percentage = Math.min(Math.max((offsetX / rect.width) * 100, 25), 75);
    const val = `${percentage.toFixed(1)}%`;
    container.style.setProperty("--accounts-split-left", val);
    localStorage.setItem("tinix_accounts_split_ratio", val);
  });

  window.addEventListener("mouseup", () => {
    if (isDragging) {
      isDragging = false;
      divider.classList.remove("is-dragging");
      document.body.style.cursor = "";
      document.body.style.userSelect = "";
    }
  });
}

async function saveAccountChanges(accountId) {
  const statusEl = document.querySelector("#detailSaveStatus");
  if (statusEl) {
    statusEl.className = "detail-save-indicator saving";
    statusEl.textContent = "Đang lưu…";
  }

  const account = store.accounts.find(item => item.id === accountId);
  if (!account) return;

  const nameVal = document.querySelector("#detailName")?.value.trim() || account.name;
  const emailVal = document.querySelector("#detailEmail")?.value.trim() || "";
  const recoveryEmailVal = document.querySelector("#detailRecoveryEmail")?.value.trim() || "";
  const passwordVal = document.querySelector("#detailPassword")?.value || "";
  const secret2faVal = document.querySelector("#detail2fa")?.value.trim() || "";
  const recoveryCodesVal = document.querySelector("#detailRecoveryCodes")?.value || "";
  const notesVal = document.querySelector("#detailNotes")?.value || "";
  const credentialsLoaded = document.querySelector("#detailAccountForm")?.dataset.credentialsLoaded === "true";

  const payload = {
    name: nameVal,
    platform: account.platform,
    username: account.username || "",
    email: emailVal,
    recovery_email: recoveryEmailVal,
    notes: notesVal,
    starred: Boolean(account.starred),
  };
  if (credentialsLoaded) {
    Object.assign(payload, {
      password: passwordVal,
      secret_2fa: secret2faVal,
      recovery_codes: recoveryCodesVal,
    });
  }

  try {
    const updated = await api(`/accounts/${accountId}`, {
      method: "PUT",
      body: JSON.stringify(payload),
    });
    Object.assign(account, updated);

    const headerTitle = document.querySelector("#detailHeaderTitle");
    if (headerTitle) headerTitle.textContent = updated.name;

    const listRow = document.querySelector(`[data-account-row="${accountId}"]`);
    if (listRow) {
      const titleEl = listRow.querySelector(".account-identity-title");
      if (titleEl) titleEl.textContent = updated.name;
      const emailEl = listRow.querySelector(".account-email-text");
      if (emailEl) {
        emailEl.textContent = updated.email || updated.username || "Chưa có email";
        emailEl.title = updated.email || updated.username || "";
      }
    }

    if (statusEl) {
      statusEl.className = "detail-save-indicator saved";
      statusEl.textContent = "Saved";
    }
  } catch (error) {
    if (statusEl) {
      statusEl.className = "detail-save-indicator error";
      statusEl.textContent = "Lỗi: " + error.message;
    }
    toast(error.message);
  }
}

function bindDetailEvents(account) {
  const accountId = account.id;

  document.querySelectorAll("[data-toggle-type]").forEach(btn => {
    btn.onclick = () => {
      const input = document.getElementById(btn.dataset.toggleType);
      if (!input) return;
      const isPass = input.type === "password";
      input.type = isPass ? "text" : "password";
      btn.textContent = isPass ? "Hide" : "Show";
    };
  });

  const systemUserTokenInput = document.querySelector("#detailSystemUserToken");
  const systemUserTokenStatus = document.querySelector("#detailSystemUserTokenStatus");
  const revealSystemUserToken = async () => {
    const response = await api(`/accounts/${accountId}/connections/meta/system-user/token`);
    return response.access_token || "";
  };
  const revealSystemUserTokenButton = document.querySelector("#detailSystemUserTokenToggle");
  if (systemUserTokenInput && revealSystemUserTokenButton) {
    revealSystemUserTokenButton.onclick = async () => {
      if (systemUserTokenInput.type === "text") {
        systemUserTokenInput.type = "password";
        systemUserTokenInput.value = "";
        revealSystemUserTokenButton.textContent = "Show";
        if (systemUserTokenStatus) systemUserTokenStatus.textContent = "";
        return;
      }
      revealSystemUserTokenButton.disabled = true;
      if (systemUserTokenStatus) systemUserTokenStatus.textContent = "Đang tải token…";
      try {
        systemUserTokenInput.value = await revealSystemUserToken();
        systemUserTokenInput.type = "text";
        revealSystemUserTokenButton.textContent = "Hide";
        if (systemUserTokenStatus) systemUserTokenStatus.textContent = "";
      } catch (error) {
        if (systemUserTokenStatus) systemUserTokenStatus.textContent = error.message;
        toast(error.message);
      } finally {
        revealSystemUserTokenButton.disabled = false;
      }
    };
    document.querySelector("#detailSystemUserTokenCopy").onclick = async event => {
      const button = event.currentTarget;
      button.disabled = true;
      if (systemUserTokenStatus) systemUserTokenStatus.textContent = "Đang tải token…";
      try {
        const token = await revealSystemUserToken();
        await navigator.clipboard.writeText(token);
        if (systemUserTokenStatus) systemUserTokenStatus.textContent = "Đã sao chép token.";
      } catch (error) {
        if (systemUserTokenStatus) systemUserTokenStatus.textContent = error.message;
        toast(error.message);
      } finally {
        button.disabled = false;
      }
    };
  }

  const enabledToggle = document.querySelector("#detailEnabled");
  if (enabledToggle) {
    enabledToggle.onchange = async () => {
      const isChecked = enabledToggle.checked;
      try {
        await api(`/accounts/${accountId}/enabled`, {
          method: "PATCH",
          body: JSON.stringify({enabled: isChecked}),
        });
        account.enabled = isChecked ? 1 : 0;
        toast(isChecked ? `Đã bật account ${account.name}` : `Đã tắt account ${account.name}`);
      } catch (error) {
        enabledToggle.checked = !isChecked;
        toast(error.message);
      }
    };
  }

  const routingSelect = document.querySelector(`[data-routing-account="${accountId}"]`);
  if (routingSelect) {
    routingSelect.onchange = async () => {
      const previousPreference = account.routing_preference || "chrome_preferred";
      const routingPreference = routingSelect.value;
      try {
        const updated = await api(`/accounts/${accountId}/routing-preference`, {
          method: "PATCH",
          body: JSON.stringify({routing_preference: routingPreference}),
        });
        account.routing_preference = updated.routing_preference;
        toast(`Đã lưu cách đăng cho ${account.name}.`);
      } catch (error) {
        routingSelect.value = previousPreference;
        toast(error.message);
      }
    };
  }

  const clearBtn = document.querySelector("#detailClearCredentialsBtn");
  if (clearBtn) {
    clearBtn.onclick = async () => {
      if (!confirm(`Xóa sạch thông tin mật khẩu, 2FA, mã khôi phục của account ${account.name}?`)) return;
      try {
        await api(`/accounts/${accountId}/clear-credentials`, {method: "POST"});
        const pwInput = document.querySelector("#detailPassword");
        if (pwInput) { pwInput.value = ""; pwInput.placeholder = "Chưa lưu"; }
        const tfaInput = document.querySelector("#detail2fa");
        if (tfaInput) { tfaInput.value = ""; tfaInput.placeholder = "Chưa lưu"; }
        const rcInput = document.querySelector("#detailRecoveryCodes");
        if (rcInput) rcInput.value = "";
        const statusEl = document.querySelector("#detailSaveStatus");
        if (statusEl) {
          statusEl.className = "detail-save-indicator saved";
          statusEl.textContent = "Saved";
        }
        toast(`Đã xóa credentials của ${account.name}`);
      } catch (error) {
        toast(error.message);
      }
    };
  }

  const form = document.querySelector("#detailAccountForm");
  if (form) {
    form.oninput = () => {
      clearTimeout(detailAutoSaveTimer);
      const statusEl = document.querySelector("#detailSaveStatus");
      if (statusEl) {
        statusEl.className = "detail-save-indicator saving";
        statusEl.textContent = "Đang lưu…";
      }
      detailAutoSaveTimer = setTimeout(() => saveAccountChanges(accountId), 400);
    };

    form.onchange = () => {
      clearTimeout(detailAutoSaveTimer);
      saveAccountChanges(accountId);
    };
  }
}

async function renderAccountDetail(account) {
  const detailContainer = document.querySelector("#accountDetailContent");
  if (!detailContainer) return;
  if (!account) {
    detailContainer.innerHTML = `<div class="detail-empty-state"><span aria-hidden="true">👤</span><p>Chọn một account bên trái để xem và sửa thông tin chi tiết.</p></div>`;
    return;
  }

  const currentAccountId = account.id;
  let credentials = {password: "", secret_2fa: "", recovery_codes: "", email_pass: "", cookie: ""};
  let credentialsLoaded = false;
  let metaBindings = [];
  try {
    credentials = await api(`/accounts/${account.id}/credentials`);
    credentialsLoaded = true;
  } catch (_) {}
  if (account.platform === "facebook" && metaApiState(account)?.state === "connected") {
    try { metaBindings = await api(`/accounts/${account.id}/connections/meta/targets`); } catch (_) {}
  }

  if (accountFilters.selectedAccountId !== currentAccountId) return;

  const workerSubtitle = `tinix-03 · http://127.0.0.1:${account.chrome_port || 9324}`;
  const metaConnection = providerConnections.find(item =>
    item.account_id === account.id && item.transport === "official_api" && item.provider === "meta"
  );
  const hasSystemUserToken = account.platform === "facebook"
    && metaConnection?.status === "connected"
    && metaConnection.refresh_metadata?.auth_method === "system_user";
  const lastCheck = account.last_login_check_at ? "đã kiểm tra" : "chưa có maintenance activity";
  const statusBanner = `${account.chrome_state || "stopped"} · health:${account.login_status || "unknown"} · ${lastCheck}`;

  detailContainer.innerHTML = `
    <div class="detail-header">
      <div class="detail-title-row">
        <span class="accent-bar" aria-hidden="true"></span>
        <h2 class="detail-account-name" id="detailHeaderTitle">${esc(account.name)}</h2>
        <span class="badge-details">DETAILS</span>
        <span class="detail-worker-subtitle">${esc(workerSubtitle)}</span>
      </div>
      <label class="detail-enabled-toggle">
        <input type="checkbox" id="detailEnabled" ${account.enabled ? "checked" : ""}>
        <span>Enabled</span>
      </label>
    </div>

    <div class="detail-status-banner">
      ${esc(statusBanner)}
    </div>
    <p class="muted" title="Kết quả được đối chiếu theo account, kênh, định dạng và phiên bản adapter hiện tại.">${esc(readinessSummary(account))}</p>
    ${routingControl(account)}
    ${account.platform === "facebook" ? `<p class="muted">Page API đang kết nối: ${metaBindings.filter(item => item.status === "connected").length}${metaBindings.length ? ` · ${metaBindings.map(item => `${esc(item.target_name || item.external_target_id)} · ${item.status === "connected" ? (item.permissions_verified ? (item.can_publish ? "có quyền đăng" : "chỉ đọc") : "chưa xác minh quyền") : "đã ngắt"}`).join("; ")}` : " · chưa có Page binding"}</p>` : ""}

    <form id="detailAccountForm" data-credentials-loaded="${credentialsLoaded}" onsubmit="return false;">
      <div class="detail-form-grid">
        <div class="detail-field">
          <label class="detail-field-label" for="detailName">Tên account</label>
          <input id="detailName" name="name" value="${esc(account.name)}" required autocomplete="off">
        </div>
        <div class="detail-field">
          <label class="detail-field-label" for="detailEmail">Email</label>
          <input id="detailEmail" name="email" type="email" value="${esc(account.email || "")}" autocomplete="off">
        </div>
        <div class="detail-field">
          <label class="detail-field-label" for="detailRecoveryEmail">Recovery email</label>
          <input id="detailRecoveryEmail" name="recovery_email" type="email" value="${esc(account.recovery_email || "")}" autocomplete="off">
        </div>

        <div class="detail-field">
          <label class="detail-field-label" for="detailPassword">Password</label>
          <div class="input-with-button">
            <input id="detailPassword" name="password" type="password" value="${esc(credentials.password || "")}" placeholder="${credentials.password ? "Đã lưu - nhập để thay thế" : "Chưa lưu"}" autocomplete="new-password">
            <button type="button" class="btn-inline-toggle" data-toggle-type="detailPassword">Show</button>
          </div>
        </div>
        <div class="detail-field">
          <label class="detail-field-label" for="detail2fa">2FA / TOTP secret (Base32)</label>
          <div class="input-with-button">
            <input id="detail2fa" name="secret_2fa" type="password" value="${esc(credentials.secret_2fa || "")}" placeholder="${credentials.secret_2fa ? "Đã lưu - nhập để thay thế" : "Chưa lưu"}" autocomplete="off">
            <button type="button" class="btn-inline-toggle" data-toggle-type="detail2fa">Show</button>
          </div>
        </div>
        <div class="detail-field">
          <label class="detail-field-label" for="detailWorker">Chrome worker</label>
          <input id="detailWorker" readonly value="tinix-03 · CDP ${account.chrome_port || 9324}">
        </div>

        ${account.platform === "facebook" ? `<div class="detail-field span-3">
          <label class="detail-field-label" for="detailSystemUserToken">System User access token</label>
          <div class="input-with-button">
            <input id="detailSystemUserToken" type="password" readonly ${hasSystemUserToken ? "placeholder=\"Bấm Show để tải token đã lưu\"" : "placeholder=\"Chỉ khả dụng khi account kết nối bằng System User\" disabled"} autocomplete="off" spellcheck="false">
            ${hasSystemUserToken ? `<button type="button" class="btn-inline-toggle" id="detailSystemUserTokenToggle">Show</button>` : ""}
          </div>
          ${hasSystemUserToken ? `<div class="detail-token-actions"><button type="button" id="detailSystemUserTokenCopy">Copy token</button><span id="detailSystemUserTokenStatus" class="muted" role="status" aria-live="polite"></span></div>` : `<small class="muted">Account chưa kết nối Meta bằng System User.</small>`}
        </div>` : ""}

        <div class="detail-field span-3">
          <label class="detail-field-label" for="detailRecoveryCodes">Recovery codes (mỗi mã một dòng)</label>
          <textarea id="detailRecoveryCodes" name="recovery_codes" rows="3" placeholder="Mỗi mã một dòng">${esc(credentials.recovery_codes || "")}</textarea>
        </div>

        <div class="detail-field span-3">
          <label class="detail-field-label" for="detailNotes">Notes</label>
          <textarea id="detailNotes" name="notes" rows="2" placeholder="Ghi chú về account...">${esc(account.notes || "")}</textarea>
        </div>
      </div>

      <div class="detail-footer">
        <button type="button" id="detailClearCredentialsBtn" class="btn-clear-credentials">Clear Credentials</button>
        <span id="detailSaveStatus" class="detail-save-indicator saved">Saved</span>
      </div>
    </form>
  `;

  bindDetailEvents(account);
  bindActions();
}

function renderAccountList() {
  renderPlatformFilters();
  const accounts = filteredAccounts();
  document.querySelector("#accountResultCount").textContent = `Hiển thị ${accounts.length}/${store.accounts.length}`;

  const selectedAccount = store.accounts.find(acc => acc.id === accountFilters.selectedAccountId) || null;

  document.querySelector("#accountList").innerHTML = accounts.length ? `
    <table class="account-table">
      <thead>
        <tr>
          <th class="account-index">STT</th>
          <th>Account</th>
          <th>Trạng thái</th>
          <th class="account-action-heading">Thao tác</th>
        </tr>
      </thead>
      <tbody>
        ${accounts.map((account, index) => {
          const apiState = youtubeApiState(account) || metaApiState(account) || instagramApiState(account);
          return `
          <tr data-account-row="${account.id}" class="${account.id === accountFilters.selectedAccountId ? "selected" : ""}" tabindex="0" aria-selected="${account.id === accountFilters.selectedAccountId}">
            <td class="account-index-cell" data-label="STT">
              <div class="account-meta-col">
                <span class="account-index account-index-num">${index + 1}</span>
                <input type="checkbox" class="account-checkbox" aria-label="Chọn account ${esc(account.name)}">
                <button type="button" class="account-star-btn ${account.starred ? "is-starred" : ""}" data-star-account="${account.id}" title="${account.starred ? "Bỏ đánh dấu sao" : "Đánh dấu sao"}">
                  ${account.starred ? "★" : "☆"}
                </button>
              </div>
            </td>
            <td data-label="Account">
              <div class="account-cell-identity">
                <div class="account-identity-title">${esc(account.name)}</div>
                <div class="account-identity-sub">
                  <span class="account-platform-badge">${platformIcon(account.platform)} ${esc(PLATFORM_LABELS[account.platform] || account.platform)}</span>
                  <span class="account-email-text" title="${esc(account.email || account.username || "")}">${esc(account.email || account.username || "Chưa có email")}</span>
                </div>
              </div>
            </td>
            <td data-label="Trạng thái" class="account-cell-status">
              ${badge(account.login_status)}
              ${account.profile_operation_locked ? '<small class="profile-maintenance">Đang bảo trì</small>' : ""}
              <small class="muted">${esc(readinessSummary(account))}</small>
              ${apiState ? `<small class="api-connection-status api-connection-${apiState.state}">${account.platform === "facebook" ? "Meta Page API" : account.platform === "instagram" ? "Instagram Login" : "YouTube API"} · ${apiState.label}</small>` : ""}
            </td>
            <td data-label="Thao tác" class="account-cell-actions">
              ${apiState && apiState.state !== "connected" ? `<button data-account-action="connect-api" class="btn-card-api-reconnect" data-id="${account.id}">${apiState.action}</button>` : ""}
              ${apiState?.refreshAvailable ? `<button data-account-action="refresh-instagram-api" class="btn-card-api-reconnect" data-id="${account.id}" data-connection-id="${apiState.connectionId}">Gia hạn token</button>` : ""}
              <button data-account-action="chrome" class="btn-card-chrome" data-id="${account.id}" title="Mở Chrome">
                <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" aria-hidden="true"><circle cx="12" cy="12" r="10"/><line x1="2" y1="12" x2="22" y2="12"/><path d="M12 2a15.3 15.3 0 0 1 4 10 15.3 15.3 0 0 1-4 10 15.3 15.3 0 0 1-4-10 15.3 15.3 0 0 1 4-10z"/></svg>
                Mở
              </button>
              <button data-account-action="delete" class="btn-card-delete danger" data-id="${account.id}" title="Xóa account">
                <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" aria-hidden="true"><path d="M3 6h18M19 6v14a2 2 0 0 1-2 2H7a2 2 0 0 1-2-2V6m3 0V4a2 2 0 0 1 2-2h4a2 2 0 0 1 2 2v2M10 11v6M14 11v6"/></svg>
                Xóa
              </button>
            </td>
          </tr>
          `;
        }).join("")}
      </tbody>
    </table>
  ` : `<p class="muted account-empty">${store.accounts.length ? "Không có account phù hợp bộ lọc." : "Chưa có account. Bạn có thể Import một gói profile hoặc tạo account thủ công."}</p>`;

  bindActions();
  bindStarButtons();
  bindAccountRows();
  renderAccountDetail(selectedAccount);
}

function bindStarButtons() {
  document.querySelectorAll("[data-star-account]").forEach(button => {
    button.onclick = async event => {
      event.stopPropagation();
      const accountId = button.dataset.starAccount;
      try {
        const res = await api(`/accounts/${accountId}/star`, {method: "PATCH"});
        const account = store.accounts.find(item => item.id === accountId);
        if (account) account.starred = res.starred;
        button.classList.toggle("is-starred", Boolean(res.starred));
        button.textContent = res.starred ? "★" : "☆";
      } catch (error) {
        toast(error.message);
      }
    };
  });
}

function selectAccountRow(accountId) {
  accountFilters.selectedAccountId = accountFilters.selectedAccountId === accountId ? "" : accountId;
  const selectedAccount = store.accounts.find(a => a.id === accountFilters.selectedAccountId) || null;
  document.querySelectorAll("[data-account-row]").forEach(row => {
    const isSelected = row.dataset.accountRow === accountFilters.selectedAccountId;
    row.classList.toggle("selected", isSelected);
    row.setAttribute("aria-selected", isSelected ? "true" : "false");
  });
  renderAccountDetail(selectedAccount);
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
      helpEl.textContent = accounts.length ? "Export mặc định chỉ chứa thông tin account và phiên Chrome. Có thể chọn kèm credential được bảo vệ bằng Windows DPAPI của tài khoản hiện tại." : "Import file .tinix-profiles.zip để tạo toàn bộ account và phiên Chrome trong một lần.";
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
    const dialog = document.querySelector("#profileExportDialog");
    dialog.querySelector("form").reset();
    dialog.showModal();
    setTimeout(() => document.querySelector("#profileExportPassword")?.focus(), 0);
    return false;
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
        if (account.platform === "facebook") {
          await openMetaConnectionDialog(account);
          return;
        }
        const appProvider = account.platform === "instagram" ? "instagram" : "google_youtube";
        const authorizationProvider = account.platform === "instagram" ? "instagram" : "youtube";
        const apps = (await api("/integrations/platform-apps")).filter(item => item.provider === appProvider && item.enabled);
        let platformAppId = null;
        if (apps.length > 1) {
          const appLabel = appProvider === "instagram" ? "Instagram" : "YouTube";
          const answer = prompt(`Chọn Platform App ${appLabel}:\n${apps.map((item, index) => `${index + 1}. ${item.name}`).join("\n")}`, "1");
          const selected = apps[Number(answer) - 1];
          if (!selected) return toast("Chưa chọn Platform App hợp lệ.");
          platformAppId = selected.id;
        } else if (apps.length === 1) platformAppId = apps[0].id;
        await api(`/accounts/${account.id}/connections/${authorizationProvider}/authorize/open`, {method:"POST",body:JSON.stringify({platform_app_id:platformAppId})});
        refreshConnectionsWhenAppReturns();
        const providerLabel = appProvider === "instagram" ? "Instagram Login" : "YouTube";
        toast(`Đã mở OAuth ${providerLabel} trong Chrome profile của account. Hãy cấp quyền rồi quay lại Tinix.`);
        return;
      }
      if (action === "manage-meta-api") {
        await openMetaConnectionDialog(account);
        return;
      }
      if (action === "refresh-instagram-api") {
        await api(`/accounts/${account.id}/connections/${button.dataset.connectionId}/instagram/refresh`, {method:"POST"});
        toast("Đã gia hạn Instagram token và xác minh lại profile.");
      }
      if (action === "disconnect-api") {
        const providerLabel = account.platform === "facebook" ? "Meta Page" : account.platform === "instagram" ? "Instagram Login" : "YouTube";
        if (!confirm(`Ngắt kết nối ${providerLabel} API của ${account.name}?`)) return;
        await api(`/accounts/${account.id}/connections/${button.dataset.connectionId}`, {method:"DELETE"});
        toast("Đã ngắt kết nối API.");
      }
      if (action === "sync-meta-api") {
        button.disabled = true;
        button.textContent = "Đang đồng bộ…";
        const targets = await api(`/accounts/${account.id}/connections/meta/sync-targets`, {method:"POST"});
        toast(`Meta API đã đồng bộ ${targets.length} Page.`);
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
  const metaSystemUserDialog = document.querySelector("#metaSystemUserDialog");
  document.querySelector("#metaSystemUserDiscover").onclick = async event => {
    const button = event.currentTarget;
    const token = document.querySelector("#metaSystemUserToken").value.trim();
    const status = document.querySelector("#metaSystemUserDiscoveryStatus");
    if (!token) {
      status.className = "operation-status error";
      status.textContent = "Nhập System User token để tìm danh sách Page.";
      return;
    }
    button.disabled = true;
    button.textContent = "Đang tìm…";
    status.className = "operation-status";
    status.textContent = "Đang hỏi Meta về các Page token này có thể truy cập…";
    try {
      const result = await api(`/accounts/${document.querySelector("#metaSystemUserForm").dataset.accountId}/connections/meta/system-user/discover`, {
        method:"POST", body:JSON.stringify({
          platform_app_id:document.querySelector("#metaSystemUserApp").value,
          access_token:token,
        }),
      });
      const bindings = JSON.parse(document.querySelector("#metaSystemUserForm").dataset.pageChoices || "[]");
      renderMetaPageChoices([...bindings, ...(result.pages || []).map(page => ({...page, status:"candidate", source:"discovery"}))]);
      status.className = result.status === "available" ? "operation-status success" : "operation-status";
      status.textContent = result.message || "Hoàn tất tìm Page.";
    } catch (error) {
      status.className = "operation-status error";
      status.textContent = error.message;
    } finally {
      button.disabled = false;
      button.textContent = "Tìm Page bằng token";
    }
  };
  document.querySelector("#metaSystemUserForm").onsubmit = async event => {
    event.preventDefault();
    const form = event.currentTarget;
    const accountId = form.dataset.accountId;
    const status = document.querySelector("#metaSystemUserStatus");
    const submit = document.querySelector("#saveMetaSystemUser");
    const accessToken = document.querySelector("#metaSystemUserToken").value.trim();
    const existingPageIds = JSON.parse(form.dataset.connectedPageIds || "[]");
    const pageIds = [...new Set([
      ...[...document.querySelectorAll("#metaSystemUserPageList [data-meta-page-choice]:checked")].map(input => input.value),
      ...document.querySelector("#metaSystemUserManualPageIds").value.split(/[\s,;]+/).map(value => value.trim()).filter(Boolean),
    ])];
    if (!pageIds.length) {
      status.className = "operation-status error";
      status.textContent = "Chọn ít nhất một Page hoặc nhập Page ID dạng số.";
      return;
    }
    const disconnectPageIds = accessToken
      ? existingPageIds.filter(pageId => !pageIds.includes(pageId)) : [];
    if (disconnectPageIds.length && !confirm(
      `Token mới sẽ thay token hiện tại. Các Page sau sẽ bị ngắt: ${disconnectPageIds.join(", ")}. Target và lịch sử vẫn được giữ. Tiếp tục?`,
    )) return;
    status.className = "operation-status";
    status.textContent = "Đang xác minh token, các Page đã chọn và quyền được cấp…";
    submit.disabled = true;
    try {
      const result = await api(`/accounts/${accountId}/connections/meta/system-user`, {
        method:"POST",
        body:JSON.stringify({
          platform_app_id:document.querySelector("#metaSystemUserApp").value,
          access_token:accessToken,
          page_ids:pageIds,
          disconnect_page_ids:disconnectPageIds,
        }),
      });
      document.querySelector("#metaSystemUserToken").value = "";
      document.querySelector("#metaSystemUserManualPageIds").value = "";
      status.className = "operation-status success";
      const publishable = result.pages.filter(page => page.can_publish).length;
      status.textContent = `Đã kết nối ${result.pages.length} Page; ${publishable} Page có quyền đăng đã xác minh, ${result.pages.length - publishable} Page chỉ đọc hoặc chưa xác minh quyền.`;
      await refreshAccounts();
      setTimeout(() => metaSystemUserDialog.close(), 900);
      toast(`Đã kết nối ${result.connected_page_count} Facebook Page qua System User.`);
    } catch (error) {
      status.className = "operation-status error";
      status.textContent = error.message;
      document.querySelector("#metaSystemUserToken").value = "";
    } finally {
      submit.disabled = false;
    }
  };
  metaSystemUserDialog.addEventListener("close", () => {
    document.querySelector("#metaSystemUserToken").value = "";
    document.querySelector("#metaSystemUserManualPageIds").value = "";
  });
  document.querySelector("#metaSystemUserOAuth").onclick = async event => {
    const button = event.currentTarget;
    const accountId = document.querySelector("#metaSystemUserForm").dataset.accountId;
    const appId = document.querySelector("#metaSystemUserApp").value;
    button.disabled = true;
    try {
      await openMetaOAuth(accountId, appId);
      metaSystemUserDialog.close();
    } catch (error) {
      const status = document.querySelector("#metaSystemUserStatus");
      status.className = "operation-status error";
      status.textContent = error.message;
    } finally {
      button.disabled = false;
    }
  };
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
      const savedAccount = await api(accountId ? `/accounts/${accountId}` : "/accounts", {method:accountId ? "PUT" : "POST", body:payload});
      await refreshAccounts();
      dialog.close();
      event.target.reset();
      toast(accountId ? "Đã cập nhật account" : "Đã thêm account");
      if (!accountId) {
        try {
          await api(`/accounts/${savedAccount.id}/chrome/open`, {method:"POST"});
          try {
            const result = await api(`/accounts/${savedAccount.id}/check-login`, {method:"POST"});
            setAccountLoginStatus(savedAccount.id, result.login_status);
            if (!["logged_in", "checkpoint"].includes(result.login_status)) pollLoginAfterOpen(savedAccount);
            toast(`Đã mở Chrome của ${savedAccount.name}. Hãy đăng nhập account trên nền tảng tương ứng.`);
          } catch (error) {
            toast(`Đã thêm account và mở Chrome nhưng kiểm tra đăng nhập thất bại: ${error.message}`);
          }
        } catch (error) {
          toast(`Đã thêm account nhưng chưa mở được Chrome: ${error.message}. Hãy thử lại bằng nút Mở.`);
        }
        await refreshAccounts();
      }
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
    const passwordInput = document.querySelector("#profileArchivePassword");
    status.className = "operation-status";
    status.textContent = "Đang đọc gói profile và khôi phục các phiên đăng nhập… Việc này có thể mất vài phút.";
    submitButton.disabled = true;
    submitButton.textContent = "Đang Import…";
    cancelButton.disabled = true;
    pathInput.disabled = true;
    passwordInput.disabled = true;
    toast("Đang Import toàn bộ account/profile. Vui lòng chờ...");
    try {
      const result = await api("/profiles/import", {method:"POST", body:JSON.stringify({bundle_path:archivePath,password:passwordInput.value || null})});
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
      passwordInput.disabled = false;
    }
  };
  document.querySelector("#profileExportForm").onsubmit = async event => {
    event.preventDefault();
    const dialog = document.querySelector("#profileExportDialog");
    const includeCredentials = document.querySelector("#profileExportIncludeCredentials").checked;
    const password = document.querySelector("#profileExportPassword").value;
    const submitButton = document.querySelector("#confirmProfileExport");
    const actionButton = document.querySelector('[data-profile-action="export"]');
    const originalLabel = submitButton.textContent;
    submitButton.disabled = true;
    submitButton.textContent = "Đang Export…";
    if (actionButton) actionButton.disabled = true;
    toast("Đang Export toàn bộ profile. Vui lòng chờ, không đóng app...");
    try {
      const result = await api("/profiles/export", {
        method:"POST", body:JSON.stringify({include_credentials:includeCredentials, password:password || null}),
      });
      dialog.close();
      event.target.reset();
      toast(`Đã Export ${result.accounts_exported} phiên (${formatBytes(result.bytes_copied)})${result.package_encrypted ? "; toàn bộ gói đã được mã hóa" : ""}${result.credentials_included ? "; credential đã được bảo vệ" : "; không kèm credential"} tới ${result.archive_path}`);
    } catch (error) {
      toast(error.message);
    } finally {
      submitButton.disabled = false;
      submitButton.textContent = originalLabel;
      if (actionButton) actionButton.disabled = !store.accounts.length;
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
  initSplitter();
}
