import {api, badge, bytes, esc, toast} from "./api.js?v=2.3.5";
import {store} from "./store.js?v=2.3.5";

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
let activeVariantTab = "facebook";

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
  if (!editingVariants[activeVariantTab]) {
    editingVariants[activeVariantTab] = {};
  }
  const cur = editingVariants[activeVariantTab];
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
}

function loadActiveVariantToDom(platform) {
  activeVariantTab = platform;
  const cur = editingVariants[platform] || {};

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
}

function renderVariantTabs() {
  const container = document.querySelector("#postVariantTabsBar");
  if (!container) return;

  const platforms = getCheckedPlatformsInDialog();
  if (!platforms.length) {
    container.innerHTML = `<span class="muted" style="font-size:12px;">Hãy chọn ít nhất 1 nền tảng bên trên</span>`;
    return;
  }

  if (!platforms.includes(activeVariantTab)) {
    activeVariantTab = platforms[0];
  }

  container.innerHTML = platforms.map(p => {
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

    const form = document.querySelector("#postForm");
    if (form) form.reset();

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
        plats.forEach(p => {
          if (!editingVariants[p]) {
            editingVariants[p] = {
              caption: item.caption || "",
              hashtags: item.hashtags || [],
              cta: item.cta || "",
            };
          }
        });

        activeVariantTab = plats[0] || "facebook";
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
      if (titleInput) titleInput.value = "";

      if (fbCheck) fbCheck.checked = true;
      if (igCheck) igCheck.checked = false;
      if (ttCheck) ttCheck.checked = false;
      if (ytCheck) ytCheck.checked = false;
      if (xCheck) xCheck.checked = false;

      editingVariants = {
        facebook: { caption: "", hashtags: [], cta: "" }
      };
      activeVariantTab = "facebook";
      loadActiveVariantToDom("facebook");
      renderVariantTabs();

      renderEditorMediaList([]);
    }

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
  const primaryVariant = platform_variants[primaryKey] || {};

  const body = {
    title,
    caption: primaryVariant.caption || "",
    hashtags: primaryVariant.hashtags || [],
    cta: primaryVariant.cta || null,
    platform_variants,
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
      try {
        await api(`/media-assets/${assetId}/attach/${saved.id}`, { method: "DELETE" });
      } catch (e) {
        console.warn("Could not detach media:", e);
      }
    }

    // 2. Attach any staged library assets
    for (const asset of stagedLibraryAssets) {
      try {
        await api(`/media-assets/${asset.id}/attach`, {
          method: "POST",
          body: JSON.stringify({ content_id: saved.id, sort_order: 0 }),
        });
      } catch (e) {
        console.warn("Could not attach staged asset:", e);
      }
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

    // Clean up preview object URLs
    pendingMediaFiles.forEach(item => {
      if (item.previewUrl) URL.revokeObjectURL(item.previewUrl);
    });
    pendingMediaFiles = [];
    stagedLibraryAssets = [];
    detachedMediaAssetIds.clear();

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

  // Load accounts and targets
  try {
    const [accounts, targets] = await Promise.all([
      api("/accounts"),
      api("/targets?enabled=true"),
    ]);

    const accountSelect = document.querySelector("#quickScheduleAccount");
    accountSelect.innerHTML = accounts.map(a => `<option value="${a.id}">${esc(a.name)} (${esc(a.platform)})</option>`).join("");

    const targetSelect = document.querySelector("#quickScheduleTargets");
    function updateTargets() {
      const selectedAccount = accountSelect.value;
      const filteredTargets = targets.filter(t => t.account_id === selectedAccount);
      targetSelect.innerHTML = filteredTargets.map(t => `<option value="${t.id}" selected>${esc(t.name)} (${esc(t.target_type)})</option>`).join("");
    }
    accountSelect.onchange = updateTargets;
    updateTargets();

    dialog.showModal();
  } catch (err) {
    toast(err.message);
  }
}

async function handleSaveQuickSchedule(event) {
  event.preventDefault();
  const content_id = document.querySelector("#quickSchedulePostId").value;
  const account_id = document.querySelector("#quickScheduleAccount").value;
  const target_ids = Array.from(document.querySelector("#quickScheduleTargets").selectedOptions).map(o => o.value);
  const scheduled_at_str = document.querySelector("#quickScheduleTime").value;
  const dry_run = document.querySelector("#quickScheduleDryRun").checked;

  if (!target_ids.length) {
    toast("Hãy chọn ít nhất 1 Trang / Kênh đích.");
    return;
  }

  try {
    const scheduled_at = scheduled_at_str ? new Date(scheduled_at_str).toISOString() : null;
    await api("/schedule", {
      method: "POST",
      body: JSON.stringify({
        content_id,
        account_id,
        target_ids,
        scheduled_at,
        dry_run,
        delay_seconds: 0,
        random_delay_seconds: 0,
        missed_policy: "confirm",
        content_format: "post",
        platform_settings: {},
      }),
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
    availableMediaAssets.clear();
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
            <button data-use-asset="${esc(asset.id)}">Gắn vào bài</button>
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

    container.querySelectorAll("[data-use-asset]").forEach(b => {
      b.onclick = async () => {
        const assetId = b.dataset.useAsset;
        const asset = availableMediaAssets.get(assetId);
        if (!asset) {
          toast("Không tìm thấy thông tin tệp media.");
          return;
        }

        const postDialog = document.querySelector("#postDialog");
        const isEditorOpen = postDialog && postDialog.open;

        if (!isEditorOpen) {
          toast("Hãy mở form Tạo hoặc Sửa bài viết trước khi chọn tệp.");
          return;
        }

        // If editing an existing post in database
        if (state.editingPost?.id) {
          try {
            await api(`/media-assets/${assetId}/attach`, {
              method: "POST",
              body: JSON.stringify({ content_id: state.editingPost.id, sort_order: 0 }),
            });
            toast(`Đã gắn "${asset.original_name}" vào bài viết.`);
            document.querySelector("#mediaManagerDialog").close();
            const refreshed = await api(`/contents/${state.editingPost.id}`);
            state.editingPost = refreshed;
            renderEditorMediaList(refreshed.media || []);
          } catch (err) {
            toast(err.message);
          }
        } else {
          // Creating a new post: stage asset locally
          const alreadyStaged = stagedLibraryAssets.some(a => a.id === assetId);
          if (alreadyStaged) {
            toast("Tệp này đã được chọn trong bài viết.");
            return;
          }
          stagedLibraryAssets.push(asset);
          toast(`Đã chọn "${asset.original_name}".`);
          document.querySelector("#mediaManagerDialog").close();
          renderEditorMediaList([]);
        }
      };
    });
  } catch (err) {
    toast(err.message);
  }
}

export function initPosts() {
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
      document.querySelector("#mediaManagerDialog").showModal();
      refreshMediaManager();
    };
  }

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
