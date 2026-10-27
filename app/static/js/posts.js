import {api, badge, bytes, esc, toast} from "./api.js?v=2.3.5";
import {store} from "./store.js?v=2.3.5";
import {openReleaseDetail} from "./jobs.js?v=1.0.42";

const state = {
  posts: [],
  selectedPostIds: new Set(),
  viewMode: localStorage.getItem("tinix.posts.viewMode") || "grid",
  filter: {
    platform: "",
    status: "",
    media_type: "",
    sort: "newest",
    search: "",
  },
  lightbox: {
    post: null,
    mediaList: [],
    currentIndex: 0,
  },
  editingPost: null,
  activeCardPlatforms: new Map(), // postId -> activePlatform
  quickSchedule: null,
};

function formatDate(isoString) {
  if (!isoString) return "";
  try {
    const d = new Date(isoString);
    if (isNaN(d.getTime())) return isoString;
    const pad = n => String(n).padStart(2, "0");
    return `${pad(d.getHours())}:${pad(d.getMinutes())} ${pad(d.getDate())}/${pad(d.getMonth() + 1)}/${d.getFullYear()}`;
  } catch {
    return isoString;
  }
}

function postStatusBadge(status, error) {
  const map = {
    published: { label: "Đã đăng", cls: "badge-green", icon: "✓" },
    scheduled: { label: "Đã lên lịch", cls: "badge-teal", icon: "🕒" },
    publishing: { label: "Đang đăng", cls: "badge-amber", icon: "↻" },
    failed: { label: "Đăng lỗi", cls: "badge-red", icon: "⚠" },
    draft: { label: "Chưa đăng / Nháp", cls: "badge-gray", icon: "○" },
  };
  const item = map[status] || map.draft;
  const titleAttr = error ? ` title="${esc(error)}"` : "";
  return `<span class="badge ${item.cls}"${titleAttr}>${item.icon} ${item.label}</span>`;
}

export const PLATFORM_ICONS = {
  facebook: '<svg viewBox="0 0 24 24" class="platform-svg" aria-hidden="true" width="16" height="16"><path fill="#1877F2" d="M24 12.07C24 5.4 18.63 0 12 0S0 5.4 0 12.07C0 18.1 4.39 23.1 10.13 24v-8.44H7.08v-3.49h3.05V9.41c0-3.03 1.79-4.7 4.53-4.7 1.31 0 2.68.24 2.68.24v2.96h-1.51c-1.49 0-1.96.93-1.96 1.89v2.27h3.33l-.53 3.49h-2.8V24C19.61 23.1 24 18.1 24 12.07Z"/></svg>',
  instagram: '<svg viewBox="0 0 24 24" class="platform-svg" aria-hidden="true" width="16" height="16"><defs><linearGradient id="ig-pbadge-grad" x1="0" y1="1" x2="1" y2="0"><stop stop-color="#FFD600"/><stop offset=".48" stop-color="#FF0169"/><stop offset="1" stop-color="#7638FA"/></linearGradient></defs><rect width="24" height="24" rx="6" fill="url(#ig-pbadge-grad)"/><circle cx="12" cy="12" r="4.4" fill="none" stroke="#fff" stroke-width="2"/><circle cx="18.1" cy="5.9" r="1.25" fill="#fff"/></svg>',
  tiktok: '<svg viewBox="0 0 24 24" class="platform-svg" aria-hidden="true" width="16" height="16"><rect width="24" height="24" rx="6" fill="#101010"/><path fill="#25F4EE" d="M10.2 17.1a2.3 2.3 0 1 1-1.6-2.2v-2.5a4.8 4.8 0 1 0 4.1 4.7V7.7c1 1.2 2.4 2 4 2.1V7.3a4.2 4.2 0 0 1-3.4-3.1h-3.1v12.9Z"/><path fill="#FE2C55" d="M11.1 17.5a2.3 2.3 0 1 1-1.6-2.2v-2.5a4.8 4.8 0 1 0 4.1 4.7V8.1c1 1.2 2.4 2 4 2.1V7.7a4.2 4.2 0 0 1-3.4-3.1h-3.1v12.9Z"/><path fill="#fff" d="M10.65 17.3a2.3 2.3 0 1 1-1.6-2.2v-2.5a4.8 4.8 0 1 0 4.1 4.7V7.9c1 1.2 2.4 2 4 2.1V7.5a4.2 4.2 0 0 1-3.4-3.1h-3.1v12.9Z"/></svg>',
  youtube: '<svg viewBox="0 0 24 24" class="platform-svg" aria-hidden="true" width="16" height="16"><rect y="3.5" width="24" height="17" rx="5" fill="#FF0000"/><path fill="#fff" d="m9.5 8 7 4-7 4V8Z"/></svg>',
  x: '<svg viewBox="0 0 24 24" class="platform-svg" aria-hidden="true" width="16" height="16"><rect width="24" height="24" rx="6" fill="#050505"/><path fill="#fff" d="M5.2 4h4.4l3.4 4.7L17.1 4h1.7l-5 5.9L19.5 20h-4.4l-3.8-5.3L6.8 20H5.1l5.4-6.5L5.2 4Zm3.5 1.4H7.9l8 13.2h.8l-8-13.2Z"/></svg>',
};

export const PLATFORM_LABELS = {
  facebook: "Facebook",
  instagram: "Instagram",
  tiktok: "TikTok",
  youtube: "YouTube",
  x: "X",
};

function platformBadges(platforms = [], activePlatform = null, postId = null) {
  if (!platforms.length) return `<span class="badge badge-gray" title="Chưa chọn nền tảng">—</span>`;
  return platforms.map(p => {
    const isActive = activePlatform ? (p === activePlatform) : false;
    const clickableClass = postId ? "badge-clickable" : "";
    const activeClass = isActive ? "badge-active" : "";
    const name = PLATFORM_LABELS[p] || p;
    const iconSvg = PLATFORM_ICONS[p] || `<span style="font-size:11px;">${esc(p)}</span>`;
    const attr = postId
      ? `data-card-platform="${esc(p)}" data-post-id="${esc(postId)}" role="button" tabindex="0" title="${name} (Bấm để xem nội dung)"`
      : `title="${name}"`;
    return `<span class="badge-platform badge-platform-icon badge-${esc(p)} ${clickableClass} ${activeClass}" ${attr} aria-label="${name}">${iconSvg}</span>`;
  }).join(" ");
}

function buildQuery() {
  const params = new URLSearchParams({ limit: "200" });
  if (state.filter.search) params.set("search", state.filter.search);
  if (state.filter.platform) params.set("platform", state.filter.platform);
  if (state.filter.status) params.set("post_status", state.filter.status);
  if (state.filter.media_type) params.set("media_type", state.filter.media_type);
  if (state.filter.sort) params.set("sort_by", state.filter.sort);
  return params.toString();
}

export async function refreshPosts() {
  try {
    const [posts, allForStats] = await Promise.all([
      api(`/contents?${buildQuery()}`),
      api(`/contents?limit=500`),
    ]);
    state.posts = posts;
    store.contents = allForStats; // Keep store.contents in sync for composer/other tabs

    // Update stats chips based on all posts
    const total = allForStats.length;
    const published = allForStats.filter(p => p.publishing_status === "published").length;
    const scheduled = allForStats.filter(p => p.publishing_status === "scheduled").length;
    const draft = allForStats.filter(p => p.publishing_status === "draft").length;
    const failed = allForStats.filter(p => p.publishing_status === "failed").length;

    const elTotal = document.querySelector("#statAllPosts");
    const elPub = document.querySelector("#statPublishedPosts");
    const elSched = document.querySelector("#statScheduledPosts");
    const elDraft = document.querySelector("#statDraftPosts");
    const elFail = document.querySelector("#statFailedPosts");

    if (elTotal) elTotal.textContent = total;
    if (elPub) elPub.textContent = published;
    if (elSched) elSched.textContent = scheduled;
    if (elDraft) elDraft.textContent = draft;
    if (elFail) elFail.textContent = failed;

    // Render current view
    if (state.viewMode === "table") {
      renderPostsTable();
    } else {
      renderPostsGrid();
    }
    syncSelectionUi();
  } catch (error) {
    toast(error.message);
  }
}

function renderMediaThumbMarkup(post, context = "grid") {
  const mediaList = post.media || [];
  if (!mediaList.length) {
    return `<div class="post-media-empty"><span>📝 Văn bản</span></div>`;
  }
  const first = mediaList[0];
  const count = mediaList.length;
  const isVideo = first.media_type === "video";
  const thumbUrl = first.thumbnail_relative_path
    ? `/api/media/${esc(first.thumbnail_relative_path)}`
    : (first.media_type === "image" ? `/api/media/${esc(first.relative_path)}` : "");

  return `
    <div class="post-thumb-wrap" data-post-id="${esc(post.id)}" title="Bấm để xem phóng to media">
      ${thumbUrl ? `<img src="${thumbUrl}" alt="${esc(first.original_name)}" loading="lazy" class="post-thumb-img">` : `<div class="post-thumb-placeholder">${isVideo ? "🎬 VIDEO" : "📷 ẢNH"}</div>`}
      ${isVideo ? `<span class="media-video-badge">▶ Video</span>` : ""}
      ${count > 1 ? `<span class="media-count-badge">+${count}</span>` : ""}
    </div>
  `;
}

function renderPostsGrid() {
  const container = document.querySelector("#postsGrid");
  const tableWrap = document.querySelector("#postsTableWrap");
  if (!container) return;
  container.style.display = "grid";
  if (tableWrap) tableWrap.style.display = "none";

  if (!state.posts.length) {
    container.innerHTML = `
      <div class="posts-empty-panel panel" style="text-align: center; padding: 40px 20px;">
        <p class="muted" style="margin-bottom: 14px;">Chưa có bài viết nào hoặc không tìm thấy bài phù hợp với bộ lọc hiện tại.</p>
        <button type="button" class="primary" data-action="new-post">+ Tạo bài viết mới</button>
      </div>
    `;
    return;
  }

  container.innerHTML = state.posts.map(post => {
    const isSelected = state.selectedPostIds.has(post.id);
    const dateText = post.publishing_status === "published" && post.published_at
      ? `<span class="post-date-item text-success" title="Thời gian đăng">✓ ${formatDate(post.published_at)}</span>`
      : (post.scheduled_at ? `<span class="post-date-item text-teal" title="Lịch đăng dự kiến">🕒 ${formatDate(post.scheduled_at)}</span>` : `<span class="post-date-item text-muted">Chưa đặt lịch</span>`);

    // Platform variant resolution
    const availablePlatforms = post.platforms && post.platforms.length ? post.platforms : Object.keys(post.platform_variants || {});
    let activePlatform = state.activeCardPlatforms.get(post.id);
    if (!activePlatform || !availablePlatforms.includes(activePlatform)) {
      activePlatform = availablePlatforms[0] || "facebook";
      state.activeCardPlatforms.set(post.id, activePlatform);
    }

    const externalLinkHtml = post.external_url
      ? `<a href="${esc(post.external_url)}" target="_blank" rel="noopener noreferrer" class="post-external-link" title="Mở bài viết trên ${PLATFORM_LABELS[activePlatform] || 'MXH'}">${PLATFORM_ICONS[activePlatform] || '🔗'} <span>Xem bài</span></a>`
      : "";

    const variant = post.platform_variants?.[activePlatform] || null;
    const displayCaption = (variant && variant.caption) || post.caption || "(Chưa có nội dung văn bản)";
    const displayHashtags = (variant && Array.isArray(variant.hashtags) && variant.hashtags.length) ? variant.hashtags : (post.hashtags || []);
    const displayCta = (variant && variant.cta) || post.cta || null;
    const hasHook = variant && variant.video_hook;
    const hasScript = variant && variant.video_script;
    const hasYtTitle = variant && variant.title && activePlatform === "youtube";
    const releases = post.releases || [];
    const succeeded = releases.filter(item => item.status === "succeeded").length;
    const dryRuns = releases.filter(item => item.dry_run || item.status === "dry_run_ready").length;
    const unknown = releases.filter(item => item.status === "unknown_result").length;
    const failed = releases.filter(item => ["failed", "temporary_failure", "permanent_failure", "login_required", "checkpoint"].includes(item.status)).length;
    const waiting = releases.filter(item => ["scheduled", "queued", "pending_approval", "approved", "opening_browser", "checking_login", "uploading", "publishing", "verifying"].includes(item.status)).length;
    const releaseButtons=items=>items.map(item=>`<button type="button" data-release-detail="${esc(item.id)}">${esc(item.target_name||item.platform)} · ${esc(item.status)}</button>`).join("");
    const releaseSummary = releases.length ? `<div class="post-release-group-summary"><strong>${releases.length} đích</strong> · ${succeeded} thành công · ${waiting} chờ · ${failed} lỗi · ${unknown} cần đối soát · ${dryRuns} dry-run
      <div>${releaseButtons(releases.slice(0,5))}</div>
      ${releases.length>5?`<details><summary>Xem ${releases.length-5} release còn lại</summary><div>${releaseButtons(releases.slice(5))}</div></details>`:""}</div>` : "";

    return `
      <article class="post-card ${isSelected ? "post-selected" : ""}" data-id="${esc(post.id)}">
        <div class="post-card-head">
          <label class="post-card-select-label" title="Chọn bài">
            <input type="checkbox" class="post-item-checkbox" data-id="${esc(post.id)}" ${isSelected ? "checked" : ""}>
          </label>
          <div class="post-card-platform-badges">${platformBadges(availablePlatforms, activePlatform, post.id)}</div>
          <div class="post-card-status">${postStatusBadge(post.publishing_status, post.last_error)}</div>
        </div>

        <div class="post-card-media-slot">
          ${renderMediaThumbMarkup(post, "grid")}
        </div>

        <div class="post-card-body">
          <h3 class="post-card-title" title="${esc(post.title)}">${esc(post.title)}</h3>
          
          ${hasYtTitle ? `<div class="card-yt-title" title="Tiêu đề video YouTube"><span class="card-inline-icon">${PLATFORM_ICONS.youtube}</span> <strong>${esc(variant.title)}</strong></div>` : ""}
          ${hasHook ? `<div class="card-hook-preview" title="Hook mở đầu (3-5s)">🎣 <strong>Hook:</strong> ${esc(variant.video_hook)}</div>` : ""}
          
          <p class="post-card-caption" title="${esc(displayCaption)}">${esc(displayCaption)}</p>

          ${hasScript ? `<div class="card-script-pill" title="${esc(variant.video_script)}">🎬 Có kịch bản video (${variant.video_script.length} ký tự)</div>` : ""}
          ${displayCta ? `<div class="card-cta-preview" title="Lời kêu gọi hành động">📢 CTA: ${esc(displayCta)}</div>` : ""}
          ${displayHashtags.length ? `<div class="post-hashtags-list">${displayHashtags.map(tag => `<span>#${esc(tag.replace(/^#/, ""))}</span>`).join(" ")}</div>` : ""}

          <div class="post-card-meta-row">
            ${dateText}
            ${externalLinkHtml}
          </div>
          ${releaseSummary}
        </div>

        <div class="post-card-actions">
          <button type="button" class="btn btn-sm btn-secondary" data-post-action="edit" data-id="${esc(post.id)}" title="Chỉnh sửa bài viết">✏️ Sửa</button>
          <button type="button" class="btn btn-sm btn-secondary" data-post-action="duplicate" data-id="${esc(post.id)}" title="Tạo bản sao bài viết">📋 Nhân bản</button>
          <button type="button" class="btn btn-sm btn-teal" data-post-action="schedule" data-id="${esc(post.id)}" title="Lên lịch xuất bản">📅 Lên lịch</button>
          <button type="button" class="btn btn-sm btn-danger" data-post-action="delete" data-id="${esc(post.id)}" title="Xóa bài viết">🗑 Xóa</button>
        </div>
      </article>
    `;
  }).join("");

  bindPostCardEvents();
}

function renderPostsTable() {
  const container = document.querySelector("#postsGrid");
  const tableWrap = document.querySelector("#postsTableWrap");
  const tbody = document.querySelector("#postsTableBody");
  if (!tableWrap || !tbody) return;

  if (container) container.style.display = "none";
  tableWrap.style.display = "block";

  if (!state.posts.length) {
    tbody.innerHTML = `<tr><td colspan="9" style="text-align:center; padding:36px;" class="muted"><p style="margin-bottom: 12px;">Chưa có bài viết nào hoặc không tìm thấy bài phù hợp với bộ lọc hiện tại.</p><button type="button" class="primary" data-action="new-post">+ Tạo bài viết mới</button></td></tr>`;
    return;
  }

  tbody.innerHTML = state.posts.map((post, index) => {
    const isSelected = state.selectedPostIds.has(post.id);
    const dateText = post.publishing_status === "published" && post.published_at
      ? `<span class="text-success" title="Thời gian đăng">✓ ${formatDate(post.published_at)}</span>`
      : (post.scheduled_at ? `<span class="text-teal" title="Lịch đăng">🕒 ${formatDate(post.scheduled_at)}</span>` : `<span class="muted">Chưa đặt lịch</span>`);

    // Platform variant resolution
    const availablePlatforms = post.platforms && post.platforms.length ? post.platforms : Object.keys(post.platform_variants || {});
    let activePlatform = state.activeCardPlatforms.get(post.id);
    if (!activePlatform || !availablePlatforms.includes(activePlatform)) {
      activePlatform = availablePlatforms[0] || "facebook";
      state.activeCardPlatforms.set(post.id, activePlatform);
    }

    const externalLinkHtml = post.external_url
      ? `<a href="${esc(post.external_url)}" target="_blank" rel="noopener noreferrer" class="post-table-ext-link" title="Xem bài đăng trên ${PLATFORM_LABELS[activePlatform] || 'MXH'}">${PLATFORM_ICONS[activePlatform] || '🔗'}</a>`
      : `<span class="muted">—</span>`;
    const variant = post.platform_variants?.[activePlatform] || null;
    const displayCaption = (variant && variant.caption) || post.caption || "—";

    return `
      <tr class="${isSelected ? "post-row-selected" : ""}" data-id="${esc(post.id)}">
        <td><input type="checkbox" class="post-item-checkbox" data-id="${esc(post.id)}" ${isSelected ? "checked" : ""}></td>
        <td>${index + 1}</td>
        <td>${renderMediaThumbMarkup(post, "table")}</td>
        <td>
          <div class="post-table-title"><strong>${esc(post.title)}</strong></div>
          <div class="post-table-caption-clamp" title="${esc(displayCaption)}">${esc(displayCaption)}</div>
        </td>
        <td>${platformBadges(availablePlatforms, activePlatform, post.id)}</td>
        <td>${dateText}</td>
        <td>${postStatusBadge(post.publishing_status, post.last_error)}</td>
        <td>${externalLinkHtml}</td>
        <td style="text-align:right;">
          <div class="post-table-actions">
            <button type="button" class="btn-icon" data-post-action="edit" data-id="${esc(post.id)}" title="Sửa">✏️</button>
            <button type="button" class="btn-icon" data-post-action="duplicate" data-id="${esc(post.id)}" title="Nhân bản">📋</button>
            <button type="button" class="btn-icon" data-post-action="schedule" data-id="${esc(post.id)}" title="Lên lịch">📅</button>
            <button type="button" class="btn-icon text-danger" data-post-action="delete" data-id="${esc(post.id)}" title="Xóa">🗑</button>
          </div>
        </td>
      </tr>
    `;
  }).join("");

  bindPostCardEvents();
}

function bindPostCardEvents() {
  document.querySelectorAll("[data-release-detail]").forEach(button => {
    button.onclick = event => { event.stopPropagation(); openReleaseDetail(button.dataset.releaseDetail).catch(error => toast(error.message)); };
  });
  // Interactive platform badge click on card or table
  document.querySelectorAll("[data-card-platform]").forEach(badge => {
    badge.onclick = e => {
      e.stopPropagation();
      const pid = badge.dataset.postId;
      const plat = badge.dataset.cardPlatform;
      if (pid && plat) {
        state.activeCardPlatforms.set(pid, plat);
        if (state.viewMode === "table") renderPostsTable();
        else renderPostsGrid();
      }
    };
  });
  // Checkbox selection
  document.querySelectorAll(".post-item-checkbox").forEach(cb => {
    cb.onchange = e => {
      const id = e.target.dataset.id;
      if (e.target.checked) state.selectedPostIds.add(id);
      else state.selectedPostIds.delete(id);
      syncSelectionUi();
    };
  });

  // Media preview click
  document.querySelectorAll(".post-thumb-wrap").forEach(wrap => {
    wrap.onclick = () => {
      const id = wrap.dataset.postId;
      openLightbox(id, 0);
    };
  });

  // Action buttons
  document.querySelectorAll("[data-post-action]").forEach(btn => {
    btn.onclick = async e => {
      e.stopPropagation();
      const id = btn.dataset.id;
      const action = btn.dataset.postAction;
      if (action === "edit") openPostEditor(id);
      else if (action === "duplicate") duplicatePost(id);
      else if (action === "schedule") openQuickSchedule(id);
      else if (action === "delete") deletePost(id);
    };
  });
}

function syncSelectionUi() {
  const count = state.selectedPostIds.size;
  const selectAllPosts = document.querySelector("#selectAllPosts");
  const selectAllPostsTable = document.querySelector("#selectAllPostsTable");
  const counter = document.querySelector("#selectedPostsCounter");
  const btnBulkDelete = document.querySelector("#btnBulkDeletePosts");

  const total = state.posts.length;
  const allSelected = total > 0 && count === total;

  if (selectAllPosts) selectAllPosts.checked = allSelected;
  if (selectAllPostsTable) selectAllPostsTable.checked = allSelected;
  if (counter) counter.textContent = `${count} bài đã chọn`;
  if (btnBulkDelete) btnBulkDelete.disabled = count === 0;

  // Highlight selected cards / rows
  document.querySelectorAll(".post-card").forEach(card => {
    const id = card.dataset.id;
    card.classList.toggle("post-selected", state.selectedPostIds.has(id));
  });
  document.querySelectorAll("#postsTableBody tr").forEach(row => {
    const id = row.dataset.id;
    row.classList.toggle("post-row-selected", state.selectedPostIds.has(id));
  });
}

// Post Editor Form Media State
let pendingMediaFiles = []; // Array of { file: File, previewUrl: string }
let stagedLibraryAssets = []; // Array of Asset objects from media library
let detachedMediaAssetIds = new Set(); // Set of asset_id strings to detach
let availableMediaAssets = new Map(); // assetId -> asset object
let stagedTargetMediaOverrides = {};
let originalTargetMediaOverrideIds = new Set();
let mediaPickerTargetId = "";
let mediaManagerSelectedAssetIds = new Set();

function handleAddEditorFiles(fileList) {
  if (!fileList || !fileList.length) return;
  for (const f of fileList) {
    const ext = f.name.slice(f.name.lastIndexOf(".")).toLowerCase();
    const isImg = f.type.startsWith("image/") || [".jpg", ".jpeg", ".png", ".webp", ".gif", ".jfif"].includes(ext);
    const isVid = f.type.startsWith("video/") || [".mp4", ".mov", ".webm", ".m4v"].includes(ext);
    if (!isImg && !isVid) {
      toast(`Tệp "${f.name}" không phải là ảnh hoặc video được hỗ trợ.`);
      continue;
    }
    const previewUrl = isImg ? URL.createObjectURL(f) : null;
    pendingMediaFiles.push({ file: f, previewUrl });
  }
  renderEditorMediaList(state.editingPost?.media || []);
}

let editingVariants = {};
let editingComposition = null;
let editingTargets = [];
let activeVariantTab = "global";
let contentSignatures = [];

function variantFromContent(value = {}) {
  return {
    title: value.title ?? null,
    caption: value.caption ?? "",
    hashtags: Array.isArray(value.hashtags) ? [...value.hashtags] : [],
    cta: value.cta ?? "",
    pinned_comment: value.pinned_comment ?? null,
    video_hook: value.video_hook ?? null,
    video_script: value.video_script ?? null,
  };
}

function normalizeComposition(item = null) {
  if (item?.composition?.version === 1) {
    return JSON.parse(JSON.stringify(item.composition));
  }
  const globalContent = variantFromContent(item || {});
  const platformOverrides = {};
  for (const [platform, variant] of Object.entries(item?.platform_variants || {})) {
    platformOverrides[platform] = variantFromContent(variant);
  }
  return {version: 1, global_content: globalContent, platform_overrides: platformOverrides, target_overrides: {}};
}

function activeOverride() {
  if (!editingComposition) return null;
  const targetId = document.querySelector("#postTargetOverride")?.value || "";
  if (targetId) return editingComposition.target_overrides[targetId] || null;
  if (activeVariantTab !== "global") return editingComposition.platform_overrides[activeVariantTab] || null;
  return editingComposition.global_content;
}

function resolvedEditorVariant(platform = activeVariantTab, targetId = "") {
  if (!editingComposition) return variantFromContent(editingVariants[platform] || {});
  let value = variantFromContent(editingComposition.global_content);
  if (platform !== "global") {
    const platformOverride = editingComposition.platform_overrides[platform];
    if (platformOverride) value = {...value, ...variantFromContent(platformOverride)};
  }
  if (targetId && editingComposition.target_overrides[targetId]) {
    value = {...value, ...variantFromContent(editingComposition.target_overrides[targetId])};
  }
  return value;
}

function renderOverrideControl() {
  const button = document.querySelector("#postVariantOverrideToggle");
  if (!button) return;
  const targetId = document.querySelector("#postTargetOverride")?.value || "";
  const isGlobal = activeVariantTab === "global" && !targetId;
  const override = activeOverride();
  const inherited = !isGlobal && !override;
  button.hidden = isGlobal;
  button.textContent = inherited ? "Tùy chỉnh nội dung này" : "Quay về dùng bản kế thừa";
  button.dataset.inherited = String(inherited);
  document.querySelectorAll("#variantEditorContainer input, #variantEditorContainer textarea").forEach(field => {
    field.disabled = inherited;
  });
}

function getCheckedPlatformsInDialog() {
  const platforms = [];
  if (document.querySelector("#postPlatformFB")?.checked) platforms.push("facebook");
  if (document.querySelector("#postPlatformIG")?.checked) platforms.push("instagram");
  if (document.querySelector("#postPlatformTT")?.checked) platforms.push("tiktok");
  if (document.querySelector("#postPlatformYT")?.checked) platforms.push("youtube");
  if (document.querySelector("#postPlatformX")?.checked) platforms.push("x");
  return platforms;
}

function saveActiveVariantFromDom() {
  if (!activeVariantTab) return;
  const targetId = document.querySelector("#postTargetOverride")?.value || "";
  if (targetId && !editingComposition.target_overrides[targetId]) return;
  if (activeVariantTab !== "global" && !targetId && !editingComposition.platform_overrides[activeVariantTab]) return;
  const cur = variantFromContent(activeVariantTab === "global"
    ? editingComposition.global_content
    : targetId
      ? editingComposition.target_overrides[targetId]
      : editingComposition.platform_overrides[activeVariantTab]);
  cur.caption = document.querySelector("#postCaption")?.value || "";
  cur.hashtags = (document.querySelector("#postHashtags")?.value || "")
    .split(/\s+/)
    .map(t => t.trim())
    .filter(Boolean);
  cur.cta = document.querySelector("#postCta")?.value.trim() || "";

  if (activeVariantTab === "youtube") {
    cur.title = document.querySelector("#postVariantTitle")?.value.trim() || null;
  }
  if (activeVariantTab === "tiktok" || activeVariantTab === "youtube") {
    cur.video_hook = document.querySelector("#postVariantHook")?.value.trim() || null;
    cur.video_script = document.querySelector("#postVariantScript")?.value.trim() || null;
  }
  if (activeVariantTab === "facebook") {
    cur.pinned_comment = document.querySelector("#postVariantPinned")?.value.trim() || null;
  }
  if (activeVariantTab === "global") editingComposition.global_content = cur;
  else if (targetId) editingComposition.target_overrides[targetId] = cur;
  else editingComposition.platform_overrides[activeVariantTab] = cur;
  if (activeVariantTab !== "global" && !targetId) editingVariants[activeVariantTab] = cur;
}

function loadActiveVariantToDom(platform) {
  activeVariantTab = platform;
  const targetId = document.querySelector("#postTargetOverride")?.value || "";
  const cur = platform === "global"
    ? variantFromContent(editingComposition?.global_content || {})
    : resolvedEditorVariant(platform, targetId);

  const captionInput = document.querySelector("#postCaption");
  const hashtagsInput = document.querySelector("#postHashtags");
  const ctaInput = document.querySelector("#postCta");
  const titleInput = document.querySelector("#postVariantTitle");
  const hookInput = document.querySelector("#postVariantHook");
  const scriptInput = document.querySelector("#postVariantScript");
  const pinnedInput = document.querySelector("#postVariantPinned");

  if (captionInput) captionInput.value = cur.caption || "";
  if (hashtagsInput) hashtagsInput.value = (cur.hashtags || []).join(" ");
  if (ctaInput) ctaInput.value = cur.cta || "";
  if (titleInput) titleInput.value = cur.title || "";
  if (hookInput) hookInput.value = cur.video_hook || "";
  if (scriptInput) scriptInput.value = cur.video_script || "";
  if (pinnedInput) pinnedInput.value = cur.pinned_comment || "";

  // Show/hide platform specialized wrappers
  const titleWrap = document.querySelector("#variantTitleWrap");
  const hookWrap = document.querySelector("#variantHookWrap");
  const scriptWrap = document.querySelector("#variantScriptWrap");
  const pinnedWrap = document.querySelector("#variantPinnedWrap");
  const captionLabel = document.querySelector("#postCaptionLabel");

  if (titleWrap) titleWrap.style.display = platform === "youtube" ? "block" : "none";
  if (hookWrap) hookWrap.style.display = (platform === "tiktok" || platform === "youtube") ? "block" : "none";
  if (scriptWrap) scriptWrap.style.display = (platform === "tiktok" || platform === "youtube") ? "block" : "none";
  if (pinnedWrap) pinnedWrap.style.display = platform === "facebook" ? "block" : "none";

  const pNames = { facebook: "Facebook", tiktok: "TikTok", youtube: "YouTube", instagram: "Instagram", x: "X" };
  if (captionLabel) {
    captionLabel.innerHTML = `Nội dung Caption <span class="caption-platform-badge" title="${pNames[platform] || platform}">${PLATFORM_ICONS[platform] || ""}</span>`;
  }
  renderOverrideControl();
}

function renderVariantTabs() {
  const container = document.querySelector("#postVariantTabsBar");
  if (!container) return;

  const platforms = getCheckedPlatformsInDialog();
  if (!platforms.length) {
    container.innerHTML = `<span class="muted" style="font-size:12px;">Hãy chọn ít nhất 1 nền tảng bên trên</span>`;
    return;
  }

  if (activeVariantTab !== "global" && !platforms.includes(activeVariantTab)) {
    activeVariantTab = "global";
  }
  const targetId = document.querySelector("#postTargetOverride")?.value || "";
  const availablePlatforms = targetId
    ? [editingTargets.find(target => target.id === targetId)?.platform].filter(Boolean)
    : platforms;

  container.innerHTML = `${targetId ? "" : `<button type="button" class="btn-variant-tab ${activeVariantTab === "global" ? "active" : ""}" data-variant-tab="global">Chung</button>`}` + availablePlatforms.map(p => {
    const isActive = p === activeVariantTab;
    const name = PLATFORM_LABELS[p] || p;
    const iconSvg = PLATFORM_ICONS[p] || `<span style="font-size:11px;">${esc(p)}</span>`;
    return `
      <button type="button" class="btn-variant-tab btn-variant-icon-tab ${isActive ? "active" : ""}" data-variant-tab="${p}" title="Nội dung ${name}" aria-label="${name}">
        ${iconSvg}
      </button>
    `;
  }).join("");

    container.querySelectorAll("[data-variant-tab]").forEach(btn => {
      btn.onclick = () => {
        const targetPlat = btn.dataset.variantTab;
        if (targetPlat === activeVariantTab) return;
        saveActiveVariantFromDom();
        loadActiveVariantToDom(targetPlat);
        renderVariantTabs();
      };
    });
}

export async function openPostEditor(id = null) {
  try {
    const dialog = document.querySelector("#postDialog");
    if (!dialog) {
      console.error("#postDialog element not found in DOM");
      toast("Không tìm thấy hộp thoại tạo bài viết (#postDialog).");
      return;
    }

    // Clean up any existing blob URLs
    pendingMediaFiles.forEach(item => {
      if (item.previewUrl) URL.revokeObjectURL(item.previewUrl);
    });
    pendingMediaFiles = [];
    stagedLibraryAssets = [];
    detachedMediaAssetIds.clear();
    stagedTargetMediaOverrides = {};
    originalTargetMediaOverrideIds = new Set();
    mediaPickerTargetId = "";

    const form = document.querySelector("#postForm");
    if (form) form.reset();
    editingTargets = await api("/targets?enabled=true");
    contentSignatures = await api("/content-signatures");
    renderSignatureSelect();
    const targetMediaSelect = document.querySelector("#postTargetMediaSelect");
    if (targetMediaSelect) {
      const accounts = await api("/accounts");
      const accountNames = new Map(accounts.map(account => [account.id, account.name]));
      targetMediaSelect.innerHTML = '<option value="">Chọn Page/kênh</option>' + editingTargets.map(target =>
        `<option value="${esc(target.id)}">${esc(target.name)} · ${esc(accountNames.get(target.account_id) || "Account")} · ${esc(PLATFORM_LABELS[target.platform] || target.platform)}</option>`
      ).join("");
      targetMediaSelect.value = "";
    }
    const targetOverride = document.querySelector("#postTargetOverride");
    if (targetOverride) {
      const accounts = await api("/accounts");
      const accountNames = new Map(accounts.map(account => [account.id, account.name]));
      targetOverride.innerHTML = '<option value="">Không chỉnh riêng theo đích</option>' + editingTargets.map(target =>
        `<option value="${esc(target.id)}">${esc(target.name)} · ${esc(accountNames.get(target.account_id) || "Account")} · ${esc(PLATFORM_LABELS[target.platform] || target.platform)}</option>`
      ).join("");
      targetOverride.value = "";
    }

    const postIdInput = document.querySelector("#postId");
    if (postIdInput) postIdInput.value = id || "";

    const titleHeading = document.querySelector("#postDialogTitle");
    const titleInput = document.querySelector("#postTitle");

    const fbCheck = document.querySelector("#postPlatformFB");
    const igCheck = document.querySelector("#postPlatformIG");
    const ttCheck = document.querySelector("#postPlatformTT");
    const ytCheck = document.querySelector("#postPlatformYT");
    const xCheck = document.querySelector("#postPlatformX");

    if (id) {
      if (titleHeading) titleHeading.textContent = "Chỉnh sửa bài viết";
      try {
        const item = await api(`/contents/${id}`);
        state.editingPost = item;
        stagedTargetMediaOverrides = JSON.parse(JSON.stringify(item.target_media_overrides || {}));
        originalTargetMediaOverrideIds = new Set(Object.keys(item.target_media_overrides || {}));
        if (titleInput) titleInput.value = item.title || "";

        // Platforms
        const plats = item.platforms && item.platforms.length ? item.platforms : Object.keys(item.platform_variants || {});
        if (fbCheck) fbCheck.checked = plats.includes("facebook");
        if (igCheck) igCheck.checked = plats.includes("instagram");
        if (ttCheck) ttCheck.checked = plats.includes("tiktok");
        if (ytCheck) ytCheck.checked = plats.includes("youtube");
        if (xCheck) xCheck.checked = plats.includes("x");

        // Clone platform variants from item
        editingVariants = JSON.parse(JSON.stringify(item.platform_variants || {}));
        editingComposition = normalizeComposition(item);
        plats.forEach(p => {
          if (!editingVariants[p]) {
            editingVariants[p] = {
              caption: item.caption || "",
              hashtags: item.hashtags || [],
              cta: item.cta || "",
            };
          }
        });

        activeVariantTab = "global";
        loadActiveVariantToDom(activeVariantTab);
        renderVariantTabs();

        renderEditorMediaList(item.media || []);
      } catch (err) {
        toast("Lỗi tải thông tin bài viết: " + err.message);
        return;
      }
    } else {
      if (titleHeading) titleHeading.textContent = "Tạo bài viết mới";
        state.editingPost = null;
      stagedTargetMediaOverrides = {};
      originalTargetMediaOverrideIds = new Set();
      if (titleInput) titleInput.value = "";

      if (fbCheck) fbCheck.checked = true;
      if (igCheck) igCheck.checked = false;
      if (ttCheck) ttCheck.checked = false;
      if (ytCheck) ytCheck.checked = false;
      if (xCheck) xCheck.checked = false;

      editingVariants = {
        facebook: { caption: "", hashtags: [], cta: "" }
      };
      editingComposition = normalizeComposition();
      activeVariantTab = "global";
      loadActiveVariantToDom("global");
      renderVariantTabs();

      renderEditorMediaList([]);
    }

    renderTargetMediaOverride();

    if (dialog.open) {
      dialog.close();
    }
    dialog.showModal();
  } catch (err) {
    console.error("openPostEditor error:", err);
    toast("Lỗi mở trình biên tập: " + err.message);
  }
}

function renderEditorMediaList(existingMediaItems = []) {
  const container = document.querySelector("#postMediaList");
  if (!container) return;

  const activeExisting = existingMediaItems.filter(m => !detachedMediaAssetIds.has(m.asset_id || m.id));

  const existingHtml = activeExisting.map(m => `
    <div class="editor-media-item existing-media" data-asset-id="${esc(m.asset_id || m.id)}">
      ${m.thumbnail_relative_path || m.media_type === "image"
        ? `<img src="/api/media/${esc(m.thumbnail_relative_path || m.relative_path)}" alt="${esc(m.original_name)}">`
        : `<div class="video-item-box">🎬 VIDEO</div>`}
      <span class="media-item-name" title="${esc(m.original_name)}">${esc(m.original_name)}</span>
      <button type="button" class="btn-remove-media" data-detach-asset="${esc(m.asset_id || m.id)}" title="Bỏ media này">✕</button>
    </div>
  `).join("");

  const stagedHtml = stagedLibraryAssets.map((asset, idx) => `
    <div class="editor-media-item staged-library-asset">
      ${asset.thumbnail_relative_path || asset.media_type === "image"
        ? `<img src="/api/media/${esc(asset.thumbnail_relative_path || asset.relative_path)}" alt="${esc(asset.original_name)}">`
        : `<div class="video-item-box">🎬 VIDEO</div>`}
      <span class="media-item-name" title="${esc(asset.original_name)}">${esc(asset.original_name)}</span>
      <span class="media-source-pill" title="Đã chọn từ Thư viện Media">📂 Kho</span>
      <button type="button" class="btn-remove-media" data-remove-staged="${idx}" title="Bỏ tệp">✕</button>
    </div>
  `).join("");

  const pendingHtml = pendingMediaFiles.map((item, idx) => {
    const isVideo = item.file.type.startsWith("video/") || item.file.name.match(/\.(mp4|mov|webm|m4v)$/i);
    return `
      <div class="editor-media-item pending-upload">
        ${item.previewUrl && !isVideo
          ? `<img src="${item.previewUrl}" alt="${esc(item.file.name)}">`
          : `<div class="video-item-box">🎬 ${isVideo ? "VIDEO MỚI" : "TỆP MỚI"}</div>`}
        <span class="media-item-name" title="${esc(item.file.name)}">${esc(item.file.name)}</span>
        <span class="media-source-pill" title="Tải từ máy tính">💻 Tải lên</span>
        <button type="button" class="btn-remove-media" data-remove-pending="${idx}" title="Bỏ tệp">✕</button>
      </div>
    `;
  }).join("");

  const totalCount = activeExisting.length + stagedLibraryAssets.length + pendingMediaFiles.length;
  if (totalCount === 0) {
    container.innerHTML = `
      <div class="media-drop-zone-placeholder">
        <p class="muted">Chưa đính kèm media nào. Bấm <strong>➕ Tải tệp từ máy</strong>, <strong>📁 Chọn từ Thư viện</strong> hoặc kéo thả file ảnh/video vào đây.</p>
      </div>
    `;
  } else {
    container.innerHTML = existingHtml + stagedHtml + pendingHtml;
  }

  // Bind detach existing
  container.querySelectorAll("[data-detach-asset]").forEach(btn => {
    btn.onclick = () => {
      const assetId = btn.dataset.detachAsset;
      detachedMediaAssetIds.add(assetId);
      renderEditorMediaList(state.editingPost?.media || []);
    };
  });

  // Bind remove staged library asset
  container.querySelectorAll("[data-remove-staged]").forEach(btn => {
    btn.onclick = () => {
      const idx = Number(btn.dataset.removeStaged);
      stagedLibraryAssets.splice(idx, 1);
      renderEditorMediaList(state.editingPost?.media || []);
    };
  });

  // Bind remove pending local file
  container.querySelectorAll("[data-remove-pending]").forEach(btn => {
    btn.onclick = () => {
      const idx = Number(btn.dataset.removePending);
      const removed = pendingMediaFiles.splice(idx, 1);
      if (removed[0]?.previewUrl) URL.revokeObjectURL(removed[0].previewUrl);
      renderEditorMediaList(state.editingPost?.media || []);
    };
  });
}

function renderTargetMediaOverride() {
  const select = document.querySelector("#postTargetMediaSelect");
  const container = document.querySelector("#postTargetMediaList");
  const hint = document.querySelector("#postTargetMediaHint");
  const targetId = select?.value || "";
  const assets = targetId ? stagedTargetMediaOverrides[targetId] : undefined;
  const inheritButton = document.querySelector("#btnInheritTargetMedia");
  const attachButton = document.querySelector("#btnAttachTargetMedia");
  if (attachButton) attachButton.disabled = !targetId;
  if (inheritButton) inheritButton.disabled = !targetId || assets === undefined;
  if (!container) return;
  if (!targetId) {
    container.innerHTML = "";
    if (hint) hint.textContent = "Page/kênh chưa có thiết lập riêng sẽ dùng media chung. Có thể đặt danh sách rỗng để không đính kèm media cho đích đó.";
    return;
  }
  if (assets === undefined) {
    container.innerHTML = "";
    if (hint) hint.textContent = "Đích này đang kế thừa media chung.";
    return;
  }
  if (hint) hint.textContent = assets.length ? `Đích này dùng ${assets.length} media riêng và không dùng media chung.` : "Đã đặt danh sách riêng rỗng: đích này sẽ không đính kèm media.";
  container.innerHTML = assets.length ? assets.map(asset => {
    const assetId = asset.asset_id || asset.id;
    return `<div class="editor-media-item target-media-item" data-target-asset-id="${esc(assetId)}">
      ${asset.thumbnail_relative_path || asset.media_type === "image"
        ? `<img src="/api/media/${esc(asset.thumbnail_relative_path || asset.relative_path)}" alt="${esc(asset.original_name || "Media")}">`
        : `<div class="video-item-box">🎬 VIDEO</div>`}
      <span class="media-item-name" title="${esc(asset.original_name || "Media")}">${esc(asset.original_name || "Media")}</span>
      <button type="button" class="btn-remove-media" data-remove-target-asset="${esc(assetId)}" title="Bỏ media riêng này">✕</button>
    </div>`;
  }).join("") : `<p class="muted">Danh sách media riêng đang rỗng.</p>`;
  container.querySelectorAll("[data-remove-target-asset]").forEach(button => {
    button.onclick = () => {
      stagedTargetMediaOverrides[targetId] = (stagedTargetMediaOverrides[targetId] || [])
        .filter(asset => (asset.asset_id || asset.id) !== button.dataset.removeTargetAsset);
      renderTargetMediaOverride();
    };
  });
}

function renderSignatureSelect() {
  const select = document.querySelector("#postSignatureSelect");
  if (!select) return;
  select.innerHTML = '<option value="">Chọn mẫu</option>' + contentSignatures.map(signature =>
    `<option value="${esc(signature.id)}">${esc(signature.name)}</option>`
  ).join("");
}

function renderSignatureManager() {
  const container = document.querySelector("#postSignatureList");
  if (!container) return;
  container.innerHTML = `<div class="signature-manager-list">${contentSignatures.map(signature => `
    <div class="signature-manager-row"><span><strong>${esc(signature.name)}</strong><small>${esc(signature.text || signature.hashtags.join(" ") || "(Chưa có nội dung)")}</small></span>
    <button type="button" data-edit-signature="${esc(signature.id)}">Sửa</button><button type="button" class="danger" data-delete-signature="${esc(signature.id)}">Xóa</button></div>
  `).join("") || '<p class="muted">Chưa có mẫu chữ ký.</p>'}</div>`;
  container.querySelectorAll("[data-edit-signature]").forEach(button => {
    button.onclick = () => {
      const signature = contentSignatures.find(item => item.id === button.dataset.editSignature);
      if (!signature) return;
      document.querySelector("#postSignatureId").value = signature.id;
      document.querySelector("#postSignatureName").value = signature.name;
      document.querySelector("#postSignatureText").value = signature.text;
      document.querySelector("#postSignatureHashtags").value = signature.hashtags.join(" ");
    };
  });
  container.querySelectorAll("[data-delete-signature]").forEach(button => {
    button.onclick = async () => {
      const next = contentSignatures.filter(item => item.id !== button.dataset.deleteSignature);
      try {
        contentSignatures = await api("/content-signatures", {method: "PUT", body: JSON.stringify({signatures: next})});
        renderSignatureManager();
        renderSignatureSelect();
      } catch (err) { toast(err.message); }
    };
  });
}

async function handleSavePost(event) {
  event.preventDefault();
  saveActiveVariantFromDom();

  const id = document.querySelector("#postId")?.value;
  const title = document.querySelector("#postTitle")?.value.trim();
  if (!title) {
    toast("Vui lòng nhập tiêu đề bài viết.");
    return;
  }

  const platforms = getCheckedPlatformsInDialog();
  if (!platforms.length) {
    toast("Vui lòng chọn ít nhất một nền tảng xuất bản.");
    return;
  }

  const platform_variants = {};
  platforms.forEach(p => {
    platform_variants[p] = editingVariants[p] || { caption: "", hashtags: [], cta: "" };
  });

  const primaryKey = platforms.includes("facebook") ? "facebook" : platforms[0];
  const globalContent = variantFromContent(editingComposition.global_content);
  const savedPlatformVariants = Object.fromEntries(Object.entries(editingComposition.platform_overrides)
    .filter(([platform]) => platforms.includes(platform)));

  const body = {
    title,
    caption: globalContent.caption,
    hashtags: globalContent.hashtags,
    cta: globalContent.cta,
    platform_variants: {...savedPlatformVariants, ...Object.fromEntries(
      Object.entries(platform_variants).filter(([platform]) => !savedPlatformVariants[platform])
    )},
    composition: editingComposition,
  };

  const saveBtn = document.querySelector("#btnSavePostRecord");
  if (saveBtn) {
    saveBtn.disabled = true;
    saveBtn.textContent = "Đang lưu...";
  }

  try {
    const saved = await api(id ? `/contents/${id}` : "/contents", {
      method: id ? "PUT" : "POST",
      body: JSON.stringify(body),
    });

    // 1. Detach any removed media (for existing posts)
    for (const assetId of detachedMediaAssetIds) {
      await api(`/media-assets/${assetId}/attach/${saved.id}`, { method: "DELETE" });
    }

    // 2. Attach any staged library assets
    for (const [sort_order, asset] of stagedLibraryAssets.entries()) {
      await api(`/media-assets/${asset.id}/attach`, {
        method: "POST",
        body: JSON.stringify({ content_id: saved.id, sort_order }),
      });
    }

    // 3. Upload any pending local files
    for (const item of pendingMediaFiles) {
      const formData = new FormData();
      formData.append("file", item.file);
      formData.append("sort_order", "0");
      await api(`/contents/${saved.id}/media`, {
        method: "POST",
        body: formData,
      });
    }

    // Target media is saved with the post so canceling the editor makes no partial changes.
    const mediaOverrideTargetIds = new Set([
      ...originalTargetMediaOverrideIds,
      ...Object.keys(stagedTargetMediaOverrides),
    ]);
    for (const targetId of mediaOverrideTargetIds) {
      const assets = stagedTargetMediaOverrides[targetId];
      await api(`/contents/${saved.id}/media-targets/${targetId}`, {
        method: "PUT",
        body: JSON.stringify(assets === undefined
          ? {inherit: true}
          : {asset_ids: assets.map(asset => asset.asset_id || asset.id)}),
      });
    }

    // Clean up preview object URLs
    pendingMediaFiles.forEach(item => {
      if (item.previewUrl) URL.revokeObjectURL(item.previewUrl);
    });
    pendingMediaFiles = [];
    stagedLibraryAssets = [];
    detachedMediaAssetIds.clear();
    stagedTargetMediaOverrides = {};
    originalTargetMediaOverrideIds = new Set();
    mediaPickerTargetId = "";

    document.querySelector("#postDialog").close();
    toast(id ? "Đã cập nhật bài viết thành công!" : "Đã tạo bài viết mới thành công!");
    await refreshPosts();
  } catch (err) {
    toast("Lỗi khi lưu bài viết: " + err.message);
  } finally {
    if (saveBtn) {
      saveBtn.disabled = false;
      saveBtn.textContent = "Lưu bài viết";
    }
  }
}


async function duplicatePost(id) {
  try {
    const dup = await api(`/contents/${id}/duplicate`, { method: "POST" });
    toast(`Đã nhân bản: "${dup.title}"`);
    await refreshPosts();
  } catch (err) {
    toast(err.message);
  }
}

async function deletePost(id) {
  if (!confirm("Bạn có chắc chắn muốn xóa bài viết này khỏi hệ thống?")) return;
  try {
    await api(`/contents/${id}?force=true`, { method: "DELETE" });
    state.selectedPostIds.delete(id);
    toast("Đã xóa bài viết.");
    await refreshPosts();
  } catch (err) {
    toast(err.message);
  }
}

async function bulkDeletePosts() {
  const ids = Array.from(state.selectedPostIds);
  if (!ids.length) return;
  if (!confirm(`Bạn có chắc muốn xóa vĩnh viễn ${ids.length} bài viết đã chọn?`)) return;

  try {
    const res = await api("/contents/bulk-delete", {
      method: "POST",
      body: JSON.stringify({ content_ids: ids, force: true }),
    });
    state.selectedPostIds.clear();
    toast(`Đã xóa thành công ${res.deleted_count} bài viết.`);
    await refreshPosts();
  } catch (err) {
    toast(err.message);
  }
}

// Quick Schedule
function renderQuickScheduleTargetTimes() {
  const quickSchedule = state.quickSchedule;
  if (!quickSchedule) return;
  const commonTime = document.querySelector("#quickScheduleTime").value;
  const selected = Array.from(document.querySelector("#quickScheduleTargets").selectedOptions);
  const wrap = document.querySelector("#quickScheduleTargetTimes");
  wrap.innerHTML = selected.length ? `<details open><summary>Định dạng, thiết lập và giờ theo từng đích</summary><div class="quick-schedule-time-list">${selected.map(option => {
    const target = quickSchedule.targets.find(item => item.id === option.value);
    const account = quickSchedule.accounts.find(item => item.id === target?.account_id);
    const platform = quickSchedule.platforms.find(item => item.id === account?.platform);
    const formats = (platform?.format_schemas || []).filter(item => (platform.content_formats || []).includes(item.id));
    const selectedFormat = quickSchedule.targetFormatOverrides[option.value] || formats[0]?.id || "";
    const schema = formats.find(item => item.id === selectedFormat);
    const settings = quickSchedule.targetSettingsOverrides[option.value] || {};
    const renderSetting = field => {
      const value = settings[field.key] ?? (field.key === "title" ? quickSchedule.post.title : field.default);
      if (field.field_type === "checkbox") return `<label class="check"><input type="checkbox" data-target="${esc(option.value)}" data-target-setting="${esc(field.key)}" ${value ? "checked" : ""}><span>${esc(field.label)}</span></label>`;
      if (field.field_type === "select") return `<label>${esc(field.label)}<select data-target="${esc(option.value)}" data-target-setting="${esc(field.key)}" ${field.required ? "required" : ""}>${field.options.map(item => `<option value="${esc(item)}" ${item === value ? "selected" : ""}>${esc(item)}</option>`).join("")}</select></label>`;
      if (field.field_type === "textarea") return `<label>${esc(field.label)}<textarea data-target="${esc(option.value)}" data-target-setting="${esc(field.key)}" ${field.required ? "required" : ""}>${esc(value ?? "")}</textarea></label>`;
      return `<label>${esc(field.label)}<input data-target="${esc(option.value)}" data-target-setting="${esc(field.key)}" value="${esc(value ?? "")}" ${field.required ? "required" : ""}></label>`;
    };
    const value = quickSchedule.targetTimeOverrides[option.value] || commonTime;
    return `<fieldset class="target-schedule-fields"><legend>${esc(target?.name || option.textContent)} · ${esc(account?.name || "Account")} · ${esc(platform?.name || account?.platform || "")}</legend>
      <label>Định dạng<select data-target-format="${esc(option.value)}" required>${formats.map(item => `<option value="${esc(item.id)}" ${item.id === selectedFormat ? "selected" : ""}>${esc(item.label)}</option>`).join("")}</select></label>
      ${(schema?.settings || []).map(renderSetting).join("")}
      <label>Ngày giờ<input type="datetime-local" data-target-time="${esc(option.value)}" value="${esc(value)}" required></label>
    </fieldset>`;
  }).join("")}</div></details>` : "";
  wrap.querySelectorAll("[data-target-time]").forEach(input => input.onchange = () => { quickSchedule.targetTimeOverrides[input.dataset.targetTime] = input.value; });
  wrap.querySelectorAll("[data-target-format]").forEach(input => input.onchange = () => {
    quickSchedule.targetFormatOverrides[input.dataset.targetFormat] = input.value;
    renderQuickScheduleTargetTimes();
  });
  wrap.querySelectorAll("[data-target-setting]").forEach(input => input.onchange = () => {
    const targetId = input.dataset.target;
    quickSchedule.targetSettingsOverrides[targetId] ||= {};
    quickSchedule.targetSettingsOverrides[targetId][input.dataset.targetSetting] = input.type === "checkbox" ? input.checked : input.value;
  });
}

async function openQuickSchedule(id) {
  const post = state.posts.find(p => p.id === id);
  if (!post) return;

  const dialog = document.querySelector("#quickScheduleDialog");
  const form = document.querySelector("#quickScheduleForm");
  form.reset();
  document.querySelector("#quickSchedulePostId").value = id;
  document.querySelector("#quickSchedulePostTitle").textContent = `Bài: "${post.title}"`;

  // Default time: 1 hour from now
  const nextHour = new Date(Date.now() + 3600000);
  const pad = n => String(n).padStart(2, "0");
  const localIso = `${nextHour.getFullYear()}-${pad(nextHour.getMonth() + 1)}-${pad(nextHour.getDate())}T${pad(nextHour.getHours())}:${pad(nextHour.getMinutes())}`;
  document.querySelector("#quickScheduleTime").value = localIso;

  // Load catalog data so the selected format is valid for the account platform.
  try {
    const [accounts, targets, platforms, targetGroups] = await Promise.all([
      api("/accounts"),
      api("/targets?enabled=true"),
      api("/platforms"),
      api("/target-groups"),
    ]);
    const enabledAccounts = accounts.filter(account => account.enabled
      && platforms.some(platform => platform.id === account.platform && platform.operational && platform.content_formats?.length));
    const accountById = new Map(enabledAccounts.map(account => [account.id, account]));
    const selectableTargets = targets.filter(target => accountById.has(target.account_id)
      && target.platform === accountById.get(target.account_id)?.platform && target.enabled
      && ["accessible", "unknown"].includes(target.access_status));
    if (!selectableTargets.length) {
      toast("Cần có ít nhất một Page/kênh đang khả dụng trên nền tảng đã bật.");
      return;
    }
    state.quickSchedule = {post, accounts: enabledAccounts, targets: selectableTargets, platforms, targetGroups, requestSignature: null, requestKey: null, previewReady: false, targetTimeOverrides: {}, targetFormatOverrides: {}, targetSettingsOverrides: {}};
    const preview = document.querySelector("#quickSchedulePreview");
    preview.innerHTML = "";
    preview.classList.add("hidden");
    document.querySelector('#quickScheduleForm button[type="submit"]').textContent = "Kiểm tra Page";

    const targetSelect = document.querySelector("#quickScheduleTargets");
    targetSelect.innerHTML = selectableTargets.map(target => {
      const account = accountById.get(target.account_id);
      return `<option value="${esc(target.id)}" selected>${esc(target.name)} — ${esc(account.name)} · ${esc(account.platform)} (${esc(target.target_type)})</option>`;
    }).join("");
    const groupSelect = document.querySelector("#quickScheduleTargetGroup");
    groupSelect.innerHTML = '<option value="">Chọn bộ Page/kênh</option>' + targetGroups.map(group =>
      `<option value="${esc(group.id)}">${esc(group.name)} (${group.target_ids.length})</option>`
    ).join("");
    const resolveGroup = () => {
      const group = state.quickSchedule.targetGroups.find(item => item.id === groupSelect.value);
      if (!group) return null;
      const known = new Set(selectableTargets.map(target => target.id));
      const missing = group.target_ids.filter(targetId => !known.has(targetId));
      if (missing.length) {
        const names = missing.map(targetId => targets.find(item => item.id === targetId)?.name || targetId);
        toast(`Bộ "${group.name}" có Page/kênh không khả dụng: ${names.join(", ")}. Hãy sửa bộ hoặc trạng thái kết nối trước.`);
        return null;
      }
      return group;
    };
    const defaultsForTargets = target_ids => ({
      target_content_formats: Object.fromEntries(target_ids.filter(targetId => quickSchedule.targetFormatOverrides[targetId])
        .map(targetId => [targetId, quickSchedule.targetFormatOverrides[targetId]])),
      target_platform_settings: Object.fromEntries(target_ids.filter(targetId => quickSchedule.targetSettingsOverrides[targetId])
        .map(targetId => [targetId, quickSchedule.targetSettingsOverrides[targetId]])),
    });
    document.querySelector("#applyTargetGroupReplace").onclick = () => {
      const group = resolveGroup();
      if (!group) return;
      if (!confirm(`Thay toàn bộ lựa chọn hiện tại bằng ${group.target_ids.length} Page/kênh trong bộ "${group.name}"?`)) return;
      for (const option of targetSelect.options) option.selected = group.target_ids.includes(option.value);
      quickSchedule.targetFormatOverrides = {...(group.defaults?.target_content_formats || {})};
      quickSchedule.targetSettingsOverrides = JSON.parse(JSON.stringify(group.defaults?.target_platform_settings || {}));
      targetSelect.dispatchEvent(new Event("change", {bubbles: true}));
    };
    document.querySelector("#applyTargetGroupMerge").onclick = () => {
      const group = resolveGroup();
      if (!group) return;
      const selected = new Set(Array.from(targetSelect.selectedOptions, option => option.value));
      group.target_ids.forEach(targetId => selected.add(targetId));
      for (const option of targetSelect.options) option.selected = selected.has(option.value);
      Object.assign(quickSchedule.targetFormatOverrides, group.defaults?.target_content_formats || {});
      Object.assign(quickSchedule.targetSettingsOverrides, JSON.parse(JSON.stringify(group.defaults?.target_platform_settings || {})));
      targetSelect.dispatchEvent(new Event("change", {bubbles: true}));
    };
    document.querySelector("#updateTargetGroup").onclick = async () => {
      const group = resolveGroup();
      if (!group) return;
      const target_ids = Array.from(targetSelect.selectedOptions, option => option.value);
      if (!confirm(`Cập nhật bộ "${group.name}" bằng đúng ${target_ids.length} Page/kênh đang chọn cùng format/settings hiện tại?`)) return;
      try {
        const updated = await api(`/target-groups/${group.id}`, {
          method: "PUT",
          body: JSON.stringify({name: group.name, description: group.description || null, defaults: defaultsForTargets(target_ids), target_ids}),
        });
        state.quickSchedule.targetGroups = state.quickSchedule.targetGroups.map(item => item.id === group.id ? updated : item);
        groupSelect.selectedOptions[0].textContent = `${updated.name} (${updated.target_ids.length})`;
        toast(`Đã cập nhật bộ "${updated.name}". Lịch đã tạo trước đó không đổi.`);
      } catch (err) { toast(err.message); }
    };
    document.querySelector("#deleteTargetGroup").onclick = async () => {
      const group = state.quickSchedule.targetGroups.find(item => item.id === groupSelect.value);
      if (!group || !confirm(`Xóa bộ "${group.name}"? Các lịch đã tạo và Page/kênh không bị xóa.`)) return;
      try {
        await api(`/target-groups/${group.id}`, {method: "DELETE"});
        state.quickSchedule.targetGroups = state.quickSchedule.targetGroups.filter(item => item.id !== group.id);
        groupSelect.querySelector(`option[value="${CSS.escape(group.id)}"]`)?.remove();
        groupSelect.value = "";
      } catch (err) { toast(err.message); }
    };
    document.querySelector("#saveTargetGroup").onclick = async () => {
      const target_ids = Array.from(targetSelect.selectedOptions, option => option.value);
      if (!target_ids.length) return toast("Hãy chọn ít nhất một Page/kênh để lưu bộ.");
      const name = prompt("Tên bộ Page/kênh:")?.trim();
      if (!name) return;
      const defaults = defaultsForTargets(target_ids);
      try {
        const group = await api("/target-groups", {method: "POST", body: JSON.stringify({name, defaults})});
        const savedGroup = await api(`/target-groups/${group.id}/members`, {
          method: "PUT", body: JSON.stringify({target_ids}),
        });
        state.quickSchedule.targetGroups.push(savedGroup);
        groupSelect.insertAdjacentHTML("beforeend", `<option value="${esc(savedGroup.id)}">${esc(savedGroup.name)} (${savedGroup.target_ids.length})</option>`);
        groupSelect.value = savedGroup.id;
        toast(`Đã lưu bộ "${savedGroup.name}". Việc này không tạo lịch đăng.`);
      } catch (err) {
        toast(err.message);
      }
    };
    targetSelect.onchange = renderQuickScheduleTargetTimes;
    document.querySelector("#quickScheduleTime").onchange = renderQuickScheduleTargetTimes;
    renderQuickScheduleTargetTimes();

    dialog.showModal();
  } catch (err) {
    toast(err.message);
  }
}

async function handleSaveQuickSchedule(event) {
  event.preventDefault();
  const content_id = document.querySelector("#quickSchedulePostId").value;
  const target_ids = Array.from(document.querySelector("#quickScheduleTargets").selectedOptions).map(o => o.value);
  const scheduled_at_str = document.querySelector("#quickScheduleTime").value;
  const dry_run = document.querySelector("#quickScheduleDryRun").checked;
  const content_format = document.querySelector("#quickScheduleFormat").value;
  const quickSchedule = state.quickSchedule;

  if (!target_ids.length) {
    toast("Hãy chọn ít nhất 1 Trang / Kênh đích.");
    return;
  }
  if (!content_format || !quickSchedule) {
    toast("Không tìm thấy định dạng xuất bản phù hợp.");
    return;
  }

  try {
    const scheduled_at = scheduled_at_str ? new Date(scheduled_at_str).toISOString() : null;
    const target_scheduled_at = Object.fromEntries(Array.from(document.querySelectorAll("#quickScheduleTargetTimes [data-target-time]"), input => [
      input.dataset.targetTime, input.value ? new Date(input.value).toISOString() : scheduled_at,
    ]));
    const target_content_formats = Object.fromEntries(Array.from(document.querySelectorAll("#quickScheduleTargetTimes [data-target-format]"), input => [input.dataset.targetFormat, input.value]));
    const target_platform_settings = {};
    document.querySelectorAll("#quickScheduleTargetTimes [data-target-setting]").forEach(input => {
      const targetId = input.dataset.target;
      target_platform_settings[targetId] ||= {};
      target_platform_settings[targetId][input.dataset.targetSetting] = input.type === "checkbox" ? input.checked : input.value;
    });
    const platform_settings = {};
    const signature = JSON.stringify([content_id, [...target_ids].sort(), scheduled_at, target_scheduled_at, dry_run, target_content_formats, target_platform_settings]);
    if (quickSchedule.requestSignature !== signature) {
      quickSchedule.requestSignature = signature;
      quickSchedule.requestKey = globalThis.crypto?.randomUUID?.() || `${Date.now()}-${Math.random().toString(16).slice(2)}-${Math.random().toString(16).slice(2)}`;
      quickSchedule.previewReady = false;
    }
    const payload = {
      content_id, target_ids, scheduled_at, dry_run, missed_policy: "confirm", content_format,
      platform_settings, target_scheduled_at, target_content_formats, target_platform_settings,
      request_key: quickSchedule.requestKey,
    };
    if (!quickSchedule.previewReady) {
      const result = await api("/schedules/batch/preflight", {method: "POST", body: JSON.stringify(payload)});
      const preview = document.querySelector("#quickSchedulePreview");
      preview.innerHTML = `<h3>Kết quả kiểm tra từng Page</h3><ul class="status-list quick-schedule-preview">${(result.targets || []).map(target => `
        <li data-status="${esc(target.status)}">
          <strong>${esc(target.name)}</strong>${target.account_name ? ` · ${esc(target.account_name)}` : ""}${target.platform ? ` · ${esc(target.platform)} ${esc(target.content_format || "")}` : ""}
          ${target.status === "ready"
            ? `<small>${esc(target.transport)}${target.provider ? ` · ${esc(target.provider)}` : ""} · ${esc(new Date(target.scheduled_at).toLocaleString())}<br>${esc([target.caption, (target.hashtags || []).join(" ")].filter(Boolean).join("\n") || "(caption trống)")}${target.media?.length ? `<br>Media: ${esc(target.media.map(item => item.name).join(", "))}` : ""}</small>`
          : `<small>${esc(target.error || "Không thể lên lịch Page này.")}</small>`}
        </li>`).join("")}</ul>${result.ready ? "<p>Kiểm tra xong. Xác nhận lần nữa để tạo lịch cho toàn bộ Page.</p>" : "<p>Sửa hoặc bỏ các Page lỗi rồi kiểm tra lại. Chưa có lịch nào được tạo.</p>"}`;
      preview.classList.remove("hidden");
      quickSchedule.previewReady = Boolean(result.ready);
      document.querySelector('#quickScheduleForm button[type="submit"]').textContent = result.ready
        ? `Tạo lịch cho ${target_ids.length} đích` : "Kiểm tra lại";
      return;
    }
    await api("/schedules/batch", {
      method: "POST",
      body: JSON.stringify(payload),
    });
    document.querySelector("#quickScheduleDialog").close();
    toast("Đã lên lịch xuất bản bài viết.");
    await refreshPosts();
  } catch (err) {
    toast(err.message);
  }
}

// Media Lightbox
function openLightbox(postId, index = 0) {
  const post = state.posts.find(p => p.id === postId);
  if (!post || !post.media || !post.media.length) return;

  state.lightbox.post = post;
  state.lightbox.mediaList = post.media;
  state.lightbox.currentIndex = Math.max(0, Math.min(index, post.media.length - 1));

  renderLightboxCurrent();
  document.querySelector("#mediaLightboxDialog").showModal();
}

function renderLightboxCurrent() {
  const { mediaList, currentIndex, post } = state.lightbox;
  const media = mediaList[currentIndex];
  if (!media) return;

  const slot = document.querySelector("#lightboxMediaSlot");
  const indicator = document.querySelector("#lightboxIndexIndicator");
  const title = document.querySelector("#lightboxTitle");

  if (title) title.textContent = `${post.title} — (${media.original_name})`;
  if (indicator) indicator.textContent = `${currentIndex + 1} / ${mediaList.length}`;

  const isVideo = media.media_type === "video";
  const mediaUrl = `/api/media/${esc(media.relative_path)}`;

  if (isVideo) {
    slot.innerHTML = `
      <video src="${mediaUrl}" controls autoplay class="lightbox-video-player"></video>
    `;
  } else {
    slot.innerHTML = `
      <img src="${mediaUrl}" alt="${esc(media.original_name)}" class="lightbox-image-preview">
    `;
  }

  const prevBtn = document.querySelector("#lightboxPrevBtn");
  const nextBtn = document.querySelector("#lightboxNextBtn");
  if (prevBtn) prevBtn.disabled = currentIndex === 0;
  if (nextBtn) nextBtn.disabled = currentIndex === mediaList.length - 1;
}

// Integrated Media Manager (replaces tab 4)
export async function refreshMediaManager() {
  const search = document.querySelector("#assetSearch")?.value.trim() || "";
  const type = document.querySelector("#assetType")?.value || "";
  const tag = document.querySelector("#assetTag")?.value.trim() || "";
  const orphanOnly = document.querySelector("#assetOrphan")?.checked || false;

  const params = new URLSearchParams({ limit: "300" });
  if (search) params.set("search", search);
  if (type) params.set("media_type", type);
  if (tag) params.set("tag", tag);
  if (orphanOnly) params.set("orphan_only", "true");

  try {
    const assets = await api(`/media-assets?${params.toString()}`);
    assets.forEach(a => availableMediaAssets.set(a.id, a));

    const container = document.querySelector("#assetList");
    if (!container) return;

    container.innerHTML = assets.length ? assets.map(asset => `
      <article class="asset-card">
        ${asset.thumbnail_relative_path || asset.media_type === "image"
          ? `<img src="/api/media/${esc(asset.thumbnail_relative_path || asset.relative_path)}" alt="${esc(asset.original_name)}">`
          : `<div class="video-placeholder">VIDEO</div>`}
        <div>
          <strong>${esc(asset.original_name)}</strong>
          <small>${esc(asset.media_type)} · ${bytes(asset.size_bytes)} · ${asset.width || "?"}×${asset.height || "?"}</small>
          <p>${esc(asset.alt_text || "Chưa có alt text")}</p>
          <div class="tag-list">${asset.tags.map(t => `<span>${esc(t)}</span>`).join("")}</div>
          <small>${asset.reference_count} bài viết đang dùng</small>
          <div class="actions">
          <label class="media-asset-select"><input type="checkbox" data-select-asset="${esc(asset.id)}" ${mediaManagerSelectedAssetIds.has(asset.id) ? "checked" : ""}> Chọn</label>
            <button class="danger" data-delete-asset="${esc(asset.id)}" ${asset.reference_count ? "disabled" : ""}>Xóa tệp</button>
          </div>
        </div>
      </article>
    `).join("") : `<p class="muted">Chưa có tệp media phù hợp.</p>`;

    container.querySelectorAll("[data-delete-asset]").forEach(b => {
      b.onclick = async () => {
        if (!confirm("Xóa tệp media orphan này vĩnh viễn khỏi ổ cứng?")) return;
        try {
          await api(`/media-assets/${b.dataset.deleteAsset}`, { method: "DELETE" });
          toast("Đã xóa tệp media.");
          await refreshMediaManager();
        } catch (err) {
          toast(err.message);
        }
      };
    });

    container.querySelectorAll("[data-select-asset]").forEach(input => {
      input.onchange = () => {
        if (input.checked) mediaManagerSelectedAssetIds.add(input.dataset.selectAsset);
        else mediaManagerSelectedAssetIds.delete(input.dataset.selectAsset);
        updateMediaManagerSelection();
      };
    });
    updateMediaManagerSelection();
  } catch (err) {
    toast(err.message);
  }
}

function updateMediaManagerSelection() {
  const count = mediaManagerSelectedAssetIds.size;
  const label = document.querySelector("#mediaManagerSelectionCount");
  const button = document.querySelector("#applySelectedMediaAssets");
  if (label) label.textContent = `${count} đã chọn`;
  if (button) {
    button.disabled = count === 0;
    button.textContent = `Thêm ${count} media vào bài`;
  }
}

function applySelectedMediaAssets() {
  const postDialog = document.querySelector("#postDialog");
  if (!postDialog?.open) return toast("Hãy mở form Tạo hoặc Sửa bài viết trước khi chọn media.");
  const assets = Array.from(mediaManagerSelectedAssetIds, assetId => availableMediaAssets.get(assetId)).filter(Boolean);
  if (!assets.length) return toast("Các media đã chọn không còn trong danh sách. Hãy tải lại thư viện.");
  if (mediaPickerTargetId) {
    const targetId = mediaPickerTargetId;
    const current = stagedTargetMediaOverrides[targetId] || [];
    const seen = new Set(current.map(item => item.asset_id || item.id));
    stagedTargetMediaOverrides[targetId] = [...current, ...assets.filter(asset => !seen.has(asset.id))];
    renderTargetMediaOverride();
  } else {
    const existingIds = new Set((state.editingPost?.media || []).map(item => item.asset_id || item.id));
    const stagedIds = new Set(stagedLibraryAssets.map(item => item.id));
    for (const asset of assets) {
      if (existingIds.has(asset.id)) detachedMediaAssetIds.delete(asset.id);
      else if (!stagedIds.has(asset.id)) stagedLibraryAssets.push(asset);
    }
    renderEditorMediaList(state.editingPost?.media || []);
  }
  mediaManagerSelectedAssetIds.clear();
  updateMediaManagerSelection();
  document.querySelector("#mediaManagerDialog").close();
  toast(`Đã chọn ${assets.length} media. Thay đổi sẽ được lưu cùng bài viết.`);
}

export function initPosts() {
  document.querySelector("#insertPostSignature")?.addEventListener("click", () => {
    const signature = contentSignatures.find(item => item.id === document.querySelector("#postSignatureSelect")?.value);
    if (!signature) return toast("Hãy chọn một mẫu trước.");
    const caption = document.querySelector("#postCaption");
    const hashtags = document.querySelector("#postHashtags");
    if (caption?.disabled || hashtags?.disabled) return toast("Hãy tạo bản tùy chỉnh cho platform/Page trước khi chèn mẫu.");
    if (signature.text && !caption.value.includes(signature.text)) {
      caption.value = [caption.value.trimEnd(), signature.text].filter(Boolean).join("\n\n");
    }
    const existingTags = hashtags.value.split(/\s+/).filter(Boolean);
    for (const tag of signature.hashtags || []) if (!existingTags.includes(tag)) existingTags.push(tag);
    hashtags.value = existingTags.join(" ");
    caption.dispatchEvent(new Event("input", {bubbles: true}));
    hashtags.dispatchEvent(new Event("input", {bubbles: true}));
  });
  document.querySelector("#managePostSignatures")?.addEventListener("click", () => {
    document.querySelector("#postSignatureId").value = "";
    document.querySelector("#postSignatureName").value = "";
    document.querySelector("#postSignatureText").value = "";
    document.querySelector("#postSignatureHashtags").value = "";
    renderSignatureManager();
    document.querySelector("#postSignatureDialog").showModal();
  });
  document.querySelector("#newPostSignature")?.addEventListener("click", () => {
    document.querySelector("#postSignatureId").value = "";
    document.querySelector("#postSignatureName").value = "";
    document.querySelector("#postSignatureText").value = "";
    document.querySelector("#postSignatureHashtags").value = "";
    document.querySelector("#postSignatureName").focus();
  });
  document.querySelector("#postSignatureForm")?.addEventListener("submit", async event => {
    event.preventDefault();
    const id = document.querySelector("#postSignatureId").value || globalThis.crypto?.randomUUID?.() || String(Date.now());
    const signature = {
      id,
      name: document.querySelector("#postSignatureName").value.trim(),
      text: document.querySelector("#postSignatureText").value.trim(),
      hashtags: document.querySelector("#postSignatureHashtags").value.split(/\s+/).filter(Boolean),
    };
    const next = contentSignatures.filter(item => item.id !== id);
    next.push(signature);
    try {
      contentSignatures = await api("/content-signatures", {method: "PUT", body: JSON.stringify({signatures: next})});
      renderSignatureManager();
      renderSignatureSelect();
      document.querySelector("#postSignatureSelect").value = id;
      document.querySelector("#postSignatureId").value = id;
      toast("Đã lưu mẫu; mẫu chỉ được áp dụng khi bạn chèn vào bài.");
    } catch (err) { toast(err.message); }
  });
  document.querySelector("#postTargetOverride")?.addEventListener("change", () => {
    saveActiveVariantFromDom();
    const targetId = document.querySelector("#postTargetOverride").value;
    if (targetId) {
      const target = editingTargets.find(item => item.id === targetId);
      if (target && activeVariantTab !== target.platform) activeVariantTab = target.platform;
    }
    loadActiveVariantToDom(activeVariantTab);
    renderVariantTabs();
  });
  document.querySelector("#postVariantOverrideToggle")?.addEventListener("click", () => {
    const targetId = document.querySelector("#postTargetOverride")?.value || "";
    const button = document.querySelector("#postVariantOverrideToggle");
    if (button.dataset.inherited === "true") {
      const inherited = resolvedEditorVariant(activeVariantTab, "");
      if (targetId) editingComposition.target_overrides[targetId] = {...inherited};
      else editingComposition.platform_overrides[activeVariantTab] = {...inherited};
      if (!targetId) editingVariants[activeVariantTab] = {...inherited};
    } else {
      if (!confirm("Bỏ bản tùy chỉnh và quay về dùng nội dung kế thừa?")) return;
      if (targetId) delete editingComposition.target_overrides[targetId];
      else delete editingComposition.platform_overrides[activeVariantTab];
    }
    loadActiveVariantToDom(activeVariantTab);
    renderVariantTabs();
  });
  // Navigation & toolbar buttons
  const newPostBtn = document.querySelector("#newPost");
  if (newPostBtn) {
    newPostBtn.onclick = (e) => {
      e.preventDefault();
      openPostEditor();
    };
  }

  // Resilient document-level click delegation for #newPost and any [data-action="new-post"]
  document.addEventListener("click", (e) => {
    const trigger = e.target.closest("#newPost, [data-action='new-post']");
    if (trigger) {
      e.preventDefault();
      openPostEditor();
    }
  });

  const refreshBtn = document.querySelector("#btnRefreshPosts");
  if (refreshBtn) refreshBtn.onclick = refreshPosts;

  const exportBtn = document.querySelector("#btnExportPosts");
  if (exportBtn) {
    exportBtn.onclick = () => {
      const q = buildQuery();
      window.location.href = `/api/contents/export?${q}`;
    };
  }

  const mediaManagerBtn = document.querySelector("#btnMediaManagerModal");
  if (mediaManagerBtn) {
    mediaManagerBtn.onclick = () => {
      document.querySelector("#mediaManagerDialog").showModal();
      refreshMediaManager();
    };
  }

  // Filter toolbar inputs
  const platformSelect = document.querySelector("#postPlatformFilter");
  if (platformSelect) {
    platformSelect.onchange = e => {
      state.filter.platform = e.target.value;
      refreshPosts();
    };
  }

  const statusSelect = document.querySelector("#postStatusFilter");
  if (statusSelect) {
    statusSelect.onchange = e => {
      state.filter.status = e.target.value;
      syncChipUi(e.target.value);
      refreshPosts();
    };
  }

  const mediaTypeSelect = document.querySelector("#postMediaTypeFilter");
  if (mediaTypeSelect) {
    mediaTypeSelect.onchange = e => {
      state.filter.media_type = e.target.value;
      refreshPosts();
    };
  }

  const sortSelect = document.querySelector("#postSortFilter");
  if (sortSelect) {
    sortSelect.onchange = e => {
      state.filter.sort = e.target.value;
      refreshPosts();
    };
  }

  const searchInput = document.querySelector("#postSearch");
  if (searchInput) {
    let searchTimer = null;
    searchInput.oninput = e => {
      clearTimeout(searchTimer);
      searchTimer = setTimeout(() => {
        state.filter.search = e.target.value.trim();
        refreshPosts();
      }, 300);
    };
  }

  // Stats Chips click
  document.querySelectorAll(".post-stat-chip").forEach(chip => {
    chip.onclick = () => {
      const st = chip.dataset.postStatus;
      state.filter.status = st;
      if (statusSelect) statusSelect.value = st;
      syncChipUi(st);
      refreshPosts();
    };
  });

  function syncChipUi(selectedStatus) {
    document.querySelectorAll(".post-stat-chip").forEach(c => {
      c.classList.toggle("active", (c.dataset.postStatus || "") === (selectedStatus || ""));
    });
  }

  // View switch: Grid vs Table
  const btnGrid = document.querySelector("#btnViewGrid");
  const btnTable = document.querySelector("#btnViewTable");
  if (btnGrid && btnTable) {
    btnGrid.onclick = () => {
      state.viewMode = "grid";
      localStorage.setItem("tinix.posts.viewMode", "grid");
      btnGrid.classList.add("active");
      btnTable.classList.remove("active");
      renderPostsGrid();
      syncSelectionUi();
    };
    btnTable.onclick = () => {
      state.viewMode = "table";
      localStorage.setItem("tinix.posts.viewMode", "table");
      btnTable.classList.add("active");
      btnGrid.classList.remove("active");
      renderPostsTable();
      syncSelectionUi();
    };
    if (state.viewMode === "table") {
      btnTable.classList.add("active");
      btnGrid.classList.remove("active");
    } else {
      btnGrid.classList.add("active");
      btnTable.classList.remove("active");
    }
  }

  // Bulk actions
  const selectAll = document.querySelector("#selectAllPosts");
  const selectAllTbl = document.querySelector("#selectAllPostsTable");
  function toggleSelectAll(checked) {
    if (checked) {
      state.posts.forEach(p => state.selectedPostIds.add(p.id));
    } else {
      state.selectedPostIds.clear();
    }
    syncSelectionUi();
  }
  if (selectAll) selectAll.onchange = e => toggleSelectAll(e.target.checked);
  if (selectAllTbl) selectAllTbl.onchange = e => toggleSelectAll(e.target.checked);

  const btnBulkDelete = document.querySelector("#btnBulkDeletePosts");
  if (btnBulkDelete) btnBulkDelete.onclick = bulkDeletePosts;

  // Post form submit
  const postForm = document.querySelector("#postForm");
  if (postForm) postForm.onsubmit = handleSavePost;

  // Platform checkbox change in post editor
  document.querySelectorAll("#postDialogPlatformsBar input[type='checkbox']").forEach(cb => {
    cb.onchange = () => {
      const plat = cb.value;
      if (cb.checked) {
        if (!editingVariants[plat]) {
          saveActiveVariantFromDom();
          const cur = editingVariants[activeVariantTab] || {};
          editingVariants[plat] = {
            caption: cur.caption || "",
            hashtags: [...(cur.hashtags || [])],
            cta: cur.cta || "",
            title: cur.title || "",
            video_hook: cur.video_hook || "",
            video_script: cur.video_script || "",
            pinned_comment: cur.pinned_comment || "",
          };
        }
      }
      renderVariantTabs();
    };
  });

  // Quick schedule form submit
  const quickScheduleForm = document.querySelector("#quickScheduleForm");
  if (quickScheduleForm) quickScheduleForm.onsubmit = handleSaveQuickSchedule;

  // File upload inside post editor
  const fileInput = document.querySelector("#postMediaInput");
  if (fileInput) {
    fileInput.onchange = e => {
      handleAddEditorFiles(e.target.files);
      e.target.value = "";
    };
  }

  // Drag & drop support inside media editor section
  const dropZone = document.querySelector(".media-editor-section");
  if (dropZone) {
    dropZone.addEventListener("dragover", e => {
      e.preventDefault();
      dropZone.classList.add("drag-over");
    });
    dropZone.addEventListener("dragleave", () => {
      dropZone.classList.remove("drag-over");
    });
    dropZone.addEventListener("drop", e => {
      e.preventDefault();
      dropZone.classList.remove("drag-over");
      if (e.dataTransfer?.files?.length) {
        handleAddEditorFiles(e.dataTransfer.files);
      }
    });
  }

  const btnAttachMedia = document.querySelector("#btnAttachFromMediaManager");
  if (btnAttachMedia) {
    btnAttachMedia.onclick = () => {
      mediaPickerTargetId = "";
      mediaManagerSelectedAssetIds.clear();
      availableMediaAssets.clear();
      updateMediaManagerSelection();
      document.querySelector("#mediaManagerDialog").showModal();
      refreshMediaManager();
    };
  }
  const targetMediaSelect = document.querySelector("#postTargetMediaSelect");
  targetMediaSelect?.addEventListener("change", renderTargetMediaOverride);
  document.querySelector("#btnAttachTargetMedia")?.addEventListener("click", () => {
    const targetId = targetMediaSelect?.value || "";
    if (!targetId) return;
    mediaPickerTargetId = targetId;
    mediaManagerSelectedAssetIds.clear();
    availableMediaAssets.clear();
    updateMediaManagerSelection();
    document.querySelector("#mediaManagerDialog").showModal();
    refreshMediaManager();
  });
  document.querySelector("#applySelectedMediaAssets")?.addEventListener("click", applySelectedMediaAssets);
  document.querySelector("#btnInheritTargetMedia")?.addEventListener("click", () => {
    const targetId = targetMediaSelect?.value || "";
    if (!targetId) return;
    delete stagedTargetMediaOverrides[targetId];
    renderTargetMediaOverride();
  });

  // Lightbox navigation
  const prevBtn = document.querySelector("#lightboxPrevBtn");
  const nextBtn = document.querySelector("#lightboxNextBtn");
  if (prevBtn) {
    prevBtn.onclick = () => {
      if (state.lightbox.currentIndex > 0) {
        state.lightbox.currentIndex -= 1;
        renderLightboxCurrent();
      }
    };
  }
  if (nextBtn) {
    nextBtn.onclick = () => {
      if (state.lightbox.currentIndex < state.lightbox.mediaList.length - 1) {
        state.lightbox.currentIndex += 1;
        renderLightboxCurrent();
      }
    };
  }

  // Keyboard navigation for lightbox
  window.addEventListener("keydown", e => {
    const dialog = document.querySelector("#mediaLightboxDialog");
    if (dialog && dialog.open) {
      if (e.key === "ArrowLeft") prevBtn?.click();
      if (e.key === "ArrowRight") nextBtn?.click();
    }
  });

  // Media manager controls in dialog
  const refreshAssetsBtn = document.querySelector("#refreshAssets");
  if (refreshAssetsBtn) refreshAssetsBtn.onclick = refreshMediaManager;

  const assetType = document.querySelector("#assetType");
  if (assetType) assetType.onchange = refreshMediaManager;

  const assetOrphan = document.querySelector("#assetOrphan");
  if (assetOrphan) assetOrphan.onchange = refreshMediaManager;

  const assetSearch = document.querySelector("#assetSearch");
  if (assetSearch) {
    let t = null;
    assetSearch.oninput = () => {
      clearTimeout(t);
      t = setTimeout(refreshMediaManager, 250);
    };
  }

  const assetUpload = document.querySelector("#assetUpload");
  if (assetUpload) {
    assetUpload.onchange = async e => {
      for (const file of e.target.files) {
        const fd = new FormData();
        fd.append("file", file);
        try {
          await api("/media-assets", { method: "POST", body: fd });
        } catch (err) {
          toast(err.message);
        }
      }
      e.target.value = "";
      await refreshMediaManager();
      toast("Upload media thành công.");
    };
  }
}

// Global fallback & console access
window.openPostEditor = openPostEditor;
