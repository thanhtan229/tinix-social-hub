import {api, esc, toast} from "./api.js";
import {store} from "./store.js";

const PROMPT_TEMPLATE_SELECTION_KEY = "tinix_ai_prompt_template_id";

function parseList(text) {
  if (!text) return [];
  return text
    .split(/[\n,]/)
    .map(item => item.trim())
    .filter(Boolean);
}

function parseExamples(text) {
  if (!text) return [];
  return text
    .split(/\n\s*---\s*\n/)
    .map(item => item.trim())
    .filter(Boolean);
}

export async function refreshBrands(selectedId = null) {
  store.brands = await api("/brand-profiles");
  const aiBrand = document.querySelector("#aiBrand");
  const currentVal = selectedId || aiBrand?.value;

  if (aiBrand) {
    aiBrand.innerHTML = '<option value="">Không chọn</option>' +
      store.brands.map(item => `<option value="${item.id}">${esc(item.name)}</option>`).join("");

    if (currentVal && store.brands.some(b => b.id === currentVal)) {
      aiBrand.value = currentVal;
    } else {
      aiBrand.value = "";
    }
  }

  const editBtn = document.querySelector("#btnQuickEditBrand");
  if (editBtn) {
    editBtn.style.display = (aiBrand && aiBrand.value) ? "inline-flex" : "none";
  }

  const bpSelect = document.querySelector("#bpSelectActive");
  if (bpSelect) {
    bpSelect.innerHTML = '<option value="">＋ Tạo hồ sơ thương hiệu mới</option>' +
      store.brands.map(item => `<option value="${item.id}">${esc(item.name)}</option>`).join("");
    bpSelect.value = (aiBrand && aiBrand.value) || "";
  }
}

function updatePromptTemplateEditButton() {
  const select = document.querySelector("#aiPromptTemplate");
  const editBtn = document.querySelector("#btnQuickEditPromptTemplate");
  if (editBtn) editBtn.style.display = select?.value ? "inline-flex" : "none";
}

export async function refreshPromptTemplates(selectedId = null) {
  store.promptTemplates = await api("/prompt-templates?include_disabled=true");
  const promptSelect = document.querySelector("#aiPromptTemplate");
  const enabledTemplates = (store.promptTemplates || []).filter(item => item.enabled);
  const savedId = selectedId || localStorage.getItem(PROMPT_TEMPLATE_SELECTION_KEY) || "system-write";

  if (promptSelect) {
    promptSelect.innerHTML = enabledTemplates.length
      ? enabledTemplates.map(item => `<option value="${esc(item.id)}">${esc(item.name)}</option>`).join("")
      : '<option value="">Chưa có System Prompt đang bật</option>';
    promptSelect.disabled = !enabledTemplates.length;
    promptSelect.setAttribute("aria-busy", "false");
    promptSelect.value = enabledTemplates.some(item => item.id === savedId) ? savedId : (enabledTemplates[0]?.id || "");
    if (promptSelect.value) localStorage.setItem(PROMPT_TEMPLATE_SELECTION_KEY, promptSelect.value);
  }

  const modalSelect = document.querySelector("#promptTemplateSelectActive");
  if (modalSelect) {
    modalSelect.innerHTML = '<option value="">＋ Tạo System Prompt mới</option>' +
      (store.promptTemplates || []).map(item => `<option value="${esc(item.id)}">${esc(item.name)}${item.enabled ? "" : " (đã tắt)"}</option>`).join("");
    modalSelect.value = promptSelect?.value || "";
  }
  updatePromptTemplateEditButton();
}

function openPromptTemplateModal(templateId = null) {
  const dialog = document.querySelector("#promptTemplateDialog");
  if (!dialog) return;
  const template = templateId ? (store.promptTemplates || []).find(item => item.id === templateId) : null;
  const set = (selector, value) => {
    const element = document.querySelector(selector);
    if (element) element.value = value ?? "";
  };
  set("#promptTemplateId", template?.id || "");
  set("#promptTemplateSelectActive", template?.id || "");
  set("#promptTemplateName", template?.name || "");
  set("#promptTemplateSystemPrompt", template?.system_prompt || "");
  const enabled = document.querySelector("#promptTemplateEnabled");
  if (enabled) enabled.checked = template ? Boolean(template.enabled) : true;
  const title = document.querySelector("#promptTemplateModalTitle");
  if (title) title.textContent = template ? `✏️ Chỉnh sửa: ${template.name}` : "✨ Tạo System Prompt";
  const deleteBtn = document.querySelector("#btnDeletePromptTemplate");
  if (deleteBtn) deleteBtn.style.display = template ? "inline-flex" : "none";
  const saveBtn = document.querySelector("#btnSavePromptTemplate");
  if (saveBtn) saveBtn.textContent = template ? "Cập nhật System Prompt" : "Lưu System Prompt";
  if (dialog.open) dialog.close();
  dialog.showModal();
}

export function openBrandModal(brandId = null) {
  const dialog = document.querySelector("#brandProfileDialog");
  if (!dialog) {
    console.error("Không tìm thấy dialog #brandProfileDialog");
    return;
  }
  const title = document.querySelector("#brandProfileModalTitle");
  const idInput = document.querySelector("#brandProfileId");
  const deleteBtn = document.querySelector("#btnDeleteBrandProfile");
  const saveBtn = document.querySelector("#btnSaveBrandProfile");
  const bpSelect = document.querySelector("#bpSelectActive");

  if (idInput) idInput.value = brandId || "";
  if (bpSelect) bpSelect.value = brandId || "";

  const setVal = (id, val) => {
    const el = document.querySelector(id);
    if (el) el.value = val ?? "";
  };

  if (brandId) {
    const brand = (store.brands || []).find(b => b.id === brandId);
    if (brand) {
      if (title) title.textContent = `✏️ Chỉnh sửa: ${brand.name}`;
      setVal("#bpName", brand.name);
      setVal("#bpTone", brand.tone);
      setVal("#bpPronouns", brand.pronouns);
      setVal("#bpTargetAudience", brand.target_audience);
      setVal("#bpProductsServices", brand.products_services);
      setVal("#bpWebsite", brand.website);
      setVal("#bpContactInfo", brand.contact_info);
      setVal("#bpPreferredKeywords", (brand.preferred_keywords || []).join(", "));
      setVal("#bpForbiddenKeywords", (brand.forbidden_keywords || []).join(", "));
      setVal("#bpSampleCtas", (brand.sample_ctas || []).join("\n"));
      setVal("#bpHashtagRules", brand.hashtag_rules);
      setVal("#bpDescription", brand.description);
      setVal("#bpGoodExamples", (brand.good_examples || []).join("\n\n---\n\n"));

      if (deleteBtn) deleteBtn.style.display = "inline-flex";
      if (saveBtn) saveBtn.textContent = "Cập nhật Brand Profile";
      if (dialog.open) dialog.close();
      dialog.showModal();
      return;
    }
  }

  // Tạo mới
  if (title) title.textContent = "🏢 Thiết lập Hồ sơ Thương hiệu (Brand Profile)";
  setVal("#bpName", "");
  setVal("#bpTone", "");
  setVal("#bpPronouns", "");
  setVal("#bpTargetAudience", "");
  setVal("#bpProductsServices", "");
  setVal("#bpWebsite", "");
  setVal("#bpContactInfo", "");
  setVal("#bpPreferredKeywords", "");
  setVal("#bpForbiddenKeywords", "");
  setVal("#bpSampleCtas", "");
  setVal("#bpHashtagRules", "");
  setVal("#bpDescription", "");
  setVal("#bpGoodExamples", "");

  if (deleteBtn) deleteBtn.style.display = "none";
  if (saveBtn) saveBtn.textContent = "Lưu Brand Profile";
  if (dialog.open) dialog.close();
  dialog.showModal();
}

// Đăng ký global để hỗ trợ gọi trực tiếp
window.openBrandModal = openBrandModal;

export function initAI() {
  const promptSelect = document.querySelector("#aiPromptTemplate");
  if (promptSelect) {
    promptSelect.onchange = () => {
      if (promptSelect.value) localStorage.setItem(PROMPT_TEMPLATE_SELECTION_KEY, promptSelect.value);
      updatePromptTemplateEditButton();
    };
  }
  document.querySelector("#btnQuickAddPromptTemplate")?.addEventListener("click", () => openPromptTemplateModal(null));
  document.querySelector("#btnQuickEditPromptTemplate")?.addEventListener("click", () => {
    if (promptSelect?.value) openPromptTemplateModal(promptSelect.value);
  });
  const promptModalSelect = document.querySelector("#promptTemplateSelectActive");
  if (promptModalSelect) promptModalSelect.onchange = () => openPromptTemplateModal(promptModalSelect.value || null);
  document.querySelector("#btnDeletePromptTemplate")?.addEventListener("click", async () => {
    const templateId = document.querySelector("#promptTemplateId")?.value;
    if (!templateId) return;
    const template = (store.promptTemplates || []).find(item => item.id === templateId);
    if (!confirm(`Bạn có chắc chắn muốn xóa System Prompt “${template?.name || "này"}”?`)) return;
    try {
      await api(`/prompt-templates/${templateId}`, {method: "DELETE"});
      document.querySelector("#promptTemplateDialog")?.close();
      await refreshPromptTemplates();
      toast("Đã xóa System Prompt.");
    } catch (error) {
      toast(`Lỗi khi xóa System Prompt: ${error.message}`);
    }
  });
  const promptForm = document.querySelector("#promptTemplateForm");
  if (promptForm) promptForm.onsubmit = async event => {
    event.preventDefault();
    const templateId = document.querySelector("#promptTemplateId")?.value;
    const body = {
      name: document.querySelector("#promptTemplateName")?.value.trim(),
      system_prompt: document.querySelector("#promptTemplateSystemPrompt")?.value.trim(),
      enabled: Boolean(document.querySelector("#promptTemplateEnabled")?.checked),
    };
    if (!body.name || !body.system_prompt) return toast("Hãy nhập tên và instruction cho System Prompt.");
    const saveBtn = document.querySelector("#btnSavePromptTemplate");
    const oldLabel = saveBtn?.textContent;
    if (saveBtn) { saveBtn.disabled = true; saveBtn.textContent = "Đang lưu…"; }
    try {
      const template = await api(templateId ? `/prompt-templates/${templateId}` : "/prompt-templates", {
        method: templateId ? "PUT" : "POST", body: JSON.stringify(body),
      });
      document.querySelector("#promptTemplateDialog")?.close();
      await refreshPromptTemplates(template.enabled ? template.id : null);
      toast(`Đã ${templateId ? "cập nhật" : "tạo"} System Prompt: “${template.name}”.`);
    } catch (error) {
      toast(`Lỗi khi lưu System Prompt: ${error.message}`);
    } finally {
      if (saveBtn) { saveBtn.disabled = false; saveBtn.textContent = oldLabel || "Lưu System Prompt"; }
    }
  };

  const aiBrand = document.querySelector("#aiBrand");
  if (aiBrand) {
    aiBrand.onchange = () => {
      const editBtn = document.querySelector("#btnQuickEditBrand");
      if (editBtn) {
        editBtn.style.display = aiBrand.value ? "inline-flex" : "none";
      }
    };
  }

  // Event delegation cho các nút mở Brand Profile
  document.addEventListener("click", (event) => {
    const addBtn = event.target.closest("#btnQuickAddBrand, #btnManageBrandProfiles");
    if (addBtn) {
      event.preventDefault();
      openBrandModal(null);
      return;
    }
    const editBtn = event.target.closest("#btnQuickEditBrand");
    if (editBtn) {
      event.preventDefault();
      const currentBrand = document.querySelector("#aiBrand");
      if (currentBrand?.value) openBrandModal(currentBrand.value);
      return;
    }
  });

  const bpSelect = document.querySelector("#bpSelectActive");
  if (bpSelect) {
    bpSelect.onchange = () => {
      openBrandModal(bpSelect.value || null);
    };
  }

  const deleteBtn = document.querySelector("#btnDeleteBrandProfile");
  if (deleteBtn) {
    deleteBtn.onclick = async () => {
      const profileId = document.querySelector("#brandProfileId").value;
      if (!profileId) return;
      const brand = (store.brands || []).find(b => b.id === profileId);
      const brandName = brand ? `"${brand.name}"` : "này";
      if (!confirm(`Bạn có chắc chắn muốn xóa Hồ sơ Thương hiệu ${brandName}?\n(Các bài viết cũ liên kết sẽ tự động chuyển về không gắn Brand Profile).`)) {
        return;
      }
      try {
        await api(`/brand-profiles/${profileId}`, {method: "DELETE"});
        document.querySelector("#brandProfileDialog")?.close();
        await refreshBrands();
        toast("Đã xóa Hồ sơ Thương hiệu thành công");
      } catch (err) {
        toast(`Lỗi khi xóa: ${err.message}`);
      }
    };
  }

  const brandForm = document.querySelector("#brandProfileForm");
  if (brandForm) {
    brandForm.onsubmit = async (event) => {
      event.preventDefault();
      const profileId = document.querySelector("#brandProfileId").value;
      const name = document.querySelector("#bpName").value.trim();
      if (!name) return toast("Vui lòng nhập tên thương hiệu");

      const body = {
        name,
        description: document.querySelector("#bpDescription").value.trim() || null,
        products_services: document.querySelector("#bpProductsServices").value.trim() || null,
        target_audience: document.querySelector("#bpTargetAudience").value.trim() || null,
        tone: document.querySelector("#bpTone").value.trim() || null,
        pronouns: document.querySelector("#bpPronouns").value.trim() || null,
        preferred_keywords: parseList(document.querySelector("#bpPreferredKeywords").value),
        forbidden_keywords: parseList(document.querySelector("#bpForbiddenKeywords").value),
        sample_ctas: parseList(document.querySelector("#bpSampleCtas").value),
        website: document.querySelector("#bpWebsite").value.trim() || null,
        contact_info: document.querySelector("#bpContactInfo").value.trim() || null,
        hashtag_rules: document.querySelector("#bpHashtagRules").value.trim() || null,
        good_examples: parseExamples(document.querySelector("#bpGoodExamples").value),
      };

      const saveBtn = document.querySelector("#btnSaveBrandProfile");
      const originalText = saveBtn ? saveBtn.textContent : "";
      if (saveBtn) {
        saveBtn.disabled = true;
        saveBtn.textContent = "Đang lưu…";
      }

      try {
        let result;
        if (profileId) {
          result = await api(`/brand-profiles/${profileId}`, {
            method: "PUT",
            body: JSON.stringify(body),
          });
          toast(`Đã cập nhật Brand Profile: "${result.name}"`);
        } else {
          result = await api("/brand-profiles", {
            method: "POST",
            body: JSON.stringify(body),
          });
          toast(`Đã tạo Brand Profile: "${result.name}"`);
        }
        document.querySelector("#brandProfileDialog")?.close();
        await refreshBrands(result.id);
      } catch (err) {
        toast(`Lỗi khi lưu Brand Profile: ${err.message}`);
      } finally {
        if (saveBtn) {
          saveBtn.disabled = false;
          saveBtn.textContent = originalText;
        }
      }
    };
  }

  // --- AI STUDIO GENERATION HISTORY MANAGEMENT ---
  const HISTORY_STORAGE_KEY = "tinix_ai_studio_history_v1";
  const MAX_HISTORY_ITEMS = 40;

  const OPERATION_LABELS = {
    write: "Viết mới",
    rewrite: "Viết lại",
    shorten: "Rút gọn",
    expand: "Mở rộng",
    hook: "Tạo hook",
    cta: "Tạo CTA",
    hashtags: "Tạo hashtag",
    variants: "Nhiều phiên bản",
    cross_platform: "Chuyển đa nền tảng",
    video_script: "Video script",
  };

  let historyItems = [];
  let currentHistoryIndex = -1;

  function formatTime(isoStr) {
    if (!isoStr) return "";
    try {
      const d = new Date(isoStr);
      if (isNaN(d.getTime())) return "";
      const pad = n => String(n).padStart(2, "0");
      return `${pad(d.getHours())}:${pad(d.getMinutes())} ${pad(d.getDate())}/${pad(d.getMonth() + 1)}`;
    } catch {
      return "";
    }
  }

  function loadHistoryFromStorage() {
    try {
      const raw = localStorage.getItem(HISTORY_STORAGE_KEY);
      if (!raw) return [];
      const parsed = JSON.parse(raw);
      return Array.isArray(parsed) ? parsed : [];
    } catch (e) {
      console.warn("Lỗi đọc lịch sử AI từ localStorage:", e);
      return [];
    }
  }

  function saveHistoryToStorage(items) {
    try {
      localStorage.setItem(HISTORY_STORAGE_KEY, JSON.stringify(items));
    } catch (e) {
      console.warn("Lỗi lưu lịch sử AI vào localStorage, cắt bớt bản ghi cũ...", e);
      while (items.length > 5) {
        items.shift();
        try {
          localStorage.setItem(HISTORY_STORAGE_KEY, JSON.stringify(items));
          return;
        } catch {}
      }
    }
  }

  let currentRawJson = "";
  let lastCreatedContentId = null;
  let currentImagePrompt = "";
  let lastCreatedAsset = null;
  let selectedReferenceImages = [];
  let referenceImageLibraryAssets = [];
  const REFERENCE_IMAGE_FILE_EXTENSIONS = /\.(?:jpe?g|png|webp|gif|jfif)$/i;

  const referenceImageUrl = asset => `/api/media/${encodeURI(asset.thumbnail_relative_path || asset.relative_path)}`;

  function renderReferenceImages() {
    const list = document.querySelector("#aiReferenceImageList");
    const status = document.querySelector("#aiReferenceImageStatus");
    if (list) {
      list.innerHTML = selectedReferenceImages.map(asset => `
        <article class="ai-reference-image-card">
          <img src="${referenceImageUrl(asset)}" alt="${esc(asset.alt_text || asset.original_name)}">
          <div><strong title="${esc(asset.original_name)}">${esc(asset.original_name)}</strong><small>${esc(asset.alt_text || "Ảnh tham chiếu")}</small></div>
          <button type="button" class="danger ai-reference-image-remove" data-reference-image-remove="${esc(asset.id)}" title="Bỏ ảnh">×</button>
        </article>
      `).join("");
      list.querySelectorAll("[data-reference-image-remove]").forEach(button => {
        button.onclick = () => {
          selectedReferenceImages = selectedReferenceImages.filter(asset => asset.id !== button.dataset.referenceImageRemove);
          renderReferenceImages();
        };
      });
    }
    if (status) status.textContent = selectedReferenceImages.length
      ? `Đã chọn ${selectedReferenceImages.length}/4 ảnh. Ảnh sẽ được gửi đến AI để phân tích.`
      : "Kéo thả tối đa 4 ảnh vào đây, hoặc dùng Tải ảnh / Thư viện.";
  }

  function addReferenceImages(assets) {
    const known = new Set(selectedReferenceImages.map(asset => asset.id));
    const additions = assets.filter(asset => asset?.media_type === "image" && asset.id && !known.has(asset.id));
    if (selectedReferenceImages.length + additions.length > 4) {
      toast("Mỗi lần tạo nội dung chỉ dùng tối đa 4 ảnh tham chiếu.");
      return false;
    }
    selectedReferenceImages = [...selectedReferenceImages, ...additions];
    renderReferenceImages();
    return true;
  }

  async function openReferenceImageLibrary() {
    const dialog = document.querySelector("#referenceImageDialog");
    const library = document.querySelector("#referenceImageLibrary");
    if (!dialog || !library) return;
    library.innerHTML = '<p class="muted">Đang tải ảnh…</p>';
    if (!dialog.open) dialog.showModal();
    try {
      referenceImageLibraryAssets = await api("/media-assets?media_type=image&limit=200");
      const selectedIds = new Set(selectedReferenceImages.map(asset => asset.id));
      library.innerHTML = referenceImageLibraryAssets.length ? referenceImageLibraryAssets.map(asset => `
        <label class="reference-image-option" title="${esc(asset.original_name)}">
          <input type="checkbox" value="${esc(asset.id)}" ${selectedIds.has(asset.id) ? "checked" : ""}>
          <img src="${referenceImageUrl(asset)}" alt="${esc(asset.alt_text || asset.original_name)}">
          <span>${esc(asset.original_name)}</span>
        </label>
      `).join("") : '<p class="muted">Chưa có ảnh trong Media Library. Hãy tải ảnh lên trước.</p>';
    } catch (error) {
      library.innerHTML = `<p class="error">Không tải được Media Library: ${esc(error.message)}</p>`;
    }
  }

  document.querySelector("#btnChooseReferenceImages")?.addEventListener("click", openReferenceImageLibrary);
  document.querySelector("#btnConfirmReferenceImages")?.addEventListener("click", () => {
    const library = document.querySelector("#referenceImageLibrary");
    const chosenIds = [...(library?.querySelectorAll("input[type=checkbox]:checked") || [])].map(input => input.value);
    const chosen = referenceImageLibraryAssets.filter(asset => chosenIds.includes(asset.id));
    if (chosen.length > 4) return toast("Chỉ được chọn tối đa 4 ảnh tham chiếu.");
    selectedReferenceImages = chosen;
    renderReferenceImages();
    document.querySelector("#referenceImageDialog")?.close();
  });

  async function uploadReferenceImageFiles(files) {
    const providedFiles = [...(files || [])];
    const imageFiles = providedFiles.filter(file => REFERENCE_IMAGE_FILE_EXTENSIONS.test(file?.name || ""));
    if (!imageFiles.length) {
      if (providedFiles.length) toast("Ảnh tham chiếu chỉ nhận JPG, PNG, WebP hoặc GIF.");
      return;
    }
    if (imageFiles.length !== providedFiles.length) {
      toast("Một số tệp không phải ảnh hợp lệ đã được bỏ qua.");
    }
    if (selectedReferenceImages.length + imageFiles.length > 4) {
      toast("Chỉ được chọn tối đa 4 ảnh tham chiếu.");
      return;
    }
    const status = document.querySelector("#aiReferenceImageStatus");
    if (status) status.textContent = "Đang tải ảnh lên Media Library…";
    try {
      const uploads = [];
      for (const file of imageFiles) {
        const form = new FormData();
        form.append("file", file);
        uploads.push(await api("/media-assets", {method: "POST", body: form}));
      }
      addReferenceImages(uploads);
    } catch (error) {
      toast(`Không thể tải ảnh: ${error.message}`);
      renderReferenceImages();
    }
  }

  const referenceImageUpload = document.querySelector("#aiReferenceImageUpload");
  const referenceImageDropzone = document.querySelector("#aiReferenceImageDropzone");
  document.querySelector("#btnUploadReferenceImages")?.addEventListener("click", () => referenceImageUpload?.click());
  referenceImageUpload?.addEventListener("change", async event => {
    await uploadReferenceImageFiles(event.target.files);
    event.target.value = "";
  });
  const isFileDrag = event => [...(event.dataTransfer?.types || [])].includes("Files");
  referenceImageDropzone?.addEventListener("dragenter", event => {
    if (!isFileDrag(event)) return;
    event.preventDefault();
    referenceImageDropzone.classList.add("is-dragging");
  });
  referenceImageDropzone?.addEventListener("dragover", event => {
    if (!isFileDrag(event)) return;
    event.preventDefault();
    event.dataTransfer.dropEffect = "copy";
    referenceImageDropzone.classList.add("is-dragging");
  });
  referenceImageDropzone?.addEventListener("dragleave", event => {
    if (!referenceImageDropzone.contains(event.relatedTarget)) {
      referenceImageDropzone.classList.remove("is-dragging");
    }
  });
  referenceImageDropzone?.addEventListener("drop", async event => {
    if (!isFileDrag(event)) return;
    event.preventDefault();
    referenceImageDropzone.classList.remove("is-dragging");
    await uploadReferenceImageFiles(event.dataTransfer.files);
  });
  renderReferenceImages();

  const btnVisual = document.querySelector("#btnAiViewVisual");
  const btnJson = document.querySelector("#btnAiViewJson");
  const visualBox = document.querySelector("#aiVisualResult");
  const jsonBox = document.querySelector("#aiResult");
  const actionsBar = document.querySelector("#aiResultActions");
  const btnCopy = document.querySelector("#btnCopyAiJson");
  const btnGoToPost = document.querySelector("#btnGoToPost");

  const elHistorySelect = document.querySelector("#aiHistorySelect");
  const elHistoryPrev = document.querySelector("#btnAiHistoryPrev");
  const elHistoryNext = document.querySelector("#btnAiHistoryNext");
  const elHistoryCounter = document.querySelector("#aiHistoryCounter");
  const elHistoryNew = document.querySelector("#btnAiNewPrompt");
  const elHistoryClear = document.querySelector("#btnAiClearHistory");

  function renderHistorySelectUi() {
    if (!elHistorySelect) return;
    if (!historyItems.length) {
      elHistorySelect.innerHTML = '<option value="">(Chưa có nội dung nào được lưu)</option>';
      elHistorySelect.disabled = true;
      return;
    }

    elHistorySelect.disabled = false;
    elHistorySelect.innerHTML = historyItems.map((item, idx) => {
      const opName = item.promptTemplateName || item.operationLabel || OPERATION_LABELS[item.inputs?.operation] || "Tạo nội dung";
      const snippet = item.briefSnippet || (item.inputs?.brief || "").slice(0, 32).replace(/\n/g, " ");
      const platStr = (item.inputs?.platforms || []).join(", ");
      return `<option value="${idx}">#${idx + 1} · [${item.displayTime}] ${opName}: "${esc(snippet)}" (${esc(platStr)})</option>`;
    }).join("");
  }

  function updateHistoryNavControls() {
    const total = historyItems.length;
    if (total === 0) {
      if (elHistoryCounter) elHistoryCounter.textContent = "0 / 0";
      if (elHistoryPrev) elHistoryPrev.disabled = true;
      if (elHistoryNext) elHistoryNext.disabled = true;
      if (elHistoryClear) elHistoryClear.disabled = true;
      renderHistorySelectUi();
      return;
    }

    if (elHistoryClear) elHistoryClear.disabled = false;
    renderHistorySelectUi();

    if (currentHistoryIndex === -1) {
      if (elHistoryCounter) elHistoryCounter.textContent = `Mới (+${total})`;
      if (elHistoryPrev) {
        elHistoryPrev.disabled = false;
        elHistoryPrev.title = `Xem bản ghi mới nhất #${total} (Alt + ←)`;
      }
      if (elHistoryNext) elHistoryNext.disabled = true;
      if (elHistorySelect) elHistorySelect.value = "";
    } else {
      if (elHistoryCounter) elHistoryCounter.textContent = `${currentHistoryIndex + 1} / ${total}`;
      if (elHistoryPrev) {
        elHistoryPrev.disabled = currentHistoryIndex <= 0;
        elHistoryPrev.title = currentHistoryIndex > 0 ? `Xem bản ghi #${currentHistoryIndex} (Alt + ←)` : "Đã là bản ghi đầu tiên";
      }
      if (elHistoryNext) {
        elHistoryNext.disabled = currentHistoryIndex >= total - 1;
        elHistoryNext.title = currentHistoryIndex < total - 1 ? `Xem bản ghi #${currentHistoryIndex + 2} (Alt + →)` : "Đã là bản ghi mới nhất";
      }
      if (elHistorySelect) elHistorySelect.value = String(currentHistoryIndex);
    }
  }

  function loadHistoryItemToUi(index) {
    if (index < 0 || index >= historyItems.length) return;
    currentHistoryIndex = index;
    const item = historyItems[index];

    // 1. Inputs into form
    const promptSelect = document.querySelector("#aiPromptTemplate");
    const savedTemplateId = item.inputs?.prompt_template_id;
    if (promptSelect && savedTemplateId && [...promptSelect.options].some(option => option.value === savedTemplateId)) {
      promptSelect.value = savedTemplateId;
      localStorage.setItem(PROMPT_TEMPLATE_SELECTION_KEY, savedTemplateId);
      updatePromptTemplateEditButton();
    }

    const brandSelect = document.querySelector("#aiBrand");
    if (brandSelect) {
      brandSelect.value = item.inputs?.brand_profile_id || "";
      const editBtn = document.querySelector("#btnQuickEditBrand");
      if (editBtn) editBtn.style.display = brandSelect.value ? "inline-flex" : "none";
    }

    const briefInput = document.querySelector("#aiBrief");
    if (briefInput) briefInput.value = item.inputs?.brief || "";

    const plats = item.inputs?.platforms || ["facebook"];
    ["Facebook", "Instagram", "Tiktok", "Youtube", "X"].forEach(name => {
      const el = document.querySelector(`#ai${name}`);
      if (el) el.checked = plats.includes(name.toLowerCase());
    });
    const knownAssets = item.inputs?.reference_images || [];
    selectedReferenceImages = knownAssets.map(asset => ({
      ...asset,
      id: asset.id || asset.asset_id,
      relative_path: asset.relative_path || "",
      thumbnail_relative_path: asset.thumbnail_relative_path || asset.relative_path || "",
    })).filter(asset => asset.id && asset.relative_path);
    renderReferenceImages();

    // 2. Outputs into result panel
    currentRawJson = item.output?.raw_json || JSON.stringify(item.output?.structured_content || {}, null, 2);
    lastCreatedContentId = item.output?.content_id || null;
    currentImagePrompt = item.output?.image_prompt || item.output?.structured_content?.image_prompt || "";

    if (jsonBox) jsonBox.textContent = currentRawJson;
    renderStructuredVisual(item.output?.structured_content);

    if (actionsBar) actionsBar.style.display = "flex";
    setViewMode("visual");

    const subtitle = document.querySelector("#aiResultSubtitle");
    if (subtitle) {
      subtitle.textContent = `Bản ghi #${index + 1}/${historyItems.length} (${item.displayTime}) · ${item.promptTemplateName || item.operationLabel || "AI Content"}`;
    }

    // 3. Image prompt & button
    const promptInput = document.querySelector("#aiCustomImagePrompt");
    const promptWrap = document.querySelector("#aiImagePromptInputWrap");
    if (promptInput) promptInput.value = currentImagePrompt || "";
    if (promptWrap) promptWrap.style.display = currentImagePrompt ? "flex" : "none";
    const imageControls = document.querySelector("#aiImageControls");
    if (imageControls) imageControls.style.display = "grid";

    const btnGenImg = document.querySelector("#btnGenerateImage");
    if (btnGenImg) {
      btnGenImg.disabled = !imageGenerationAvailable();
      btnGenImg.title = currentImagePrompt
        ? `Tạo ảnh: ${currentImagePrompt.slice(0, 80)}...`
        : "Tạo ảnh minh họa theo nội dung";
    }

    // 4. Stored Image result
    if (item.image && item.image.url) {
      const savedImages = Array.isArray(item.image.images) && item.image.images.length
        ? item.image.images
        : [{ url: item.image.url, asset: item.image.asset || null, source_model: item.image.source_model }];
      renderImageResults(savedImages, {
        prompt: item.image.prompt || currentImagePrompt,
        source_model: item.image.source_model,
        attached_content_id: item.image.attached ? (lastCreatedContentId || "attached") : null,
      });
      if (btnAttachAiImageToDraft) {
        if (item.image.attached) {
          btnAttachAiImageToDraft.textContent = "✓ Đã gắn vào bài viết";
          btnAttachAiImageToDraft.disabled = true;
        } else {
          btnAttachAiImageToDraft.textContent = "📎 Gắn vào bài viết";
          btnAttachAiImageToDraft.disabled = !lastCreatedContentId;
        }
      }
      lastCreatedAsset = item.image.asset || null;
    } else {
      if (aiImageResultBox) aiImageResultBox.style.display = "none";
      if (aiGeneratedImg) aiGeneratedImg.src = "";
      lastCreatedAsset = null;
    }

    updateHistoryNavControls();
  }

  function startNewDraft() {
    currentHistoryIndex = -1;
    const briefInput = document.querySelector("#aiBrief");
    if (briefInput) {
      briefInput.value = "";
      briefInput.focus();
    }
    const promptSelect = document.querySelector("#aiPromptTemplate");
    if (promptSelect?.value) localStorage.setItem(PROMPT_TEMPLATE_SELECTION_KEY, promptSelect.value);

    ["Facebook", "Instagram", "Tiktok", "Youtube", "X"].forEach((name, i) => {
      const el = document.querySelector(`#ai${name}`);
      if (el) el.checked = (i === 0);
    });

    currentRawJson = "";
    lastCreatedContentId = null;
    currentImagePrompt = "";
    lastCreatedAsset = null;
    selectedReferenceImages = [];
    renderReferenceImages();

    const customPromptEl = document.querySelector("#aiCustomImagePrompt");
    const customPromptWrap = document.querySelector("#aiImagePromptInputWrap");
    if (customPromptEl) customPromptEl.value = "";
    if (customPromptWrap) customPromptWrap.style.display = "none";
    const imageControls = document.querySelector("#aiImageControls");
    if (imageControls) imageControls.style.display = "grid";

    if (jsonBox) {
      jsonBox.textContent = "";
      jsonBox.innerHTML = `<div class="empty-state-ai"><span class="empty-icon">💡</span><p>Chưa có kết quả.</p><small>Nhập Brief bên trái và bấm <b>"Tạo bản nháp"</b> để AI sinh nội dung và kịch bản cho từng mạng xã hội.</small></div>`;
      jsonBox.style.display = "block";
    }
    if (visualBox) {
      visualBox.innerHTML = "";
      visualBox.style.display = "none";
    }
    if (actionsBar) actionsBar.style.display = "none";
    if (aiImageResultBox) aiImageResultBox.style.display = "none";
    if (aiGeneratedImg) aiGeneratedImg.src = "";

    const btnGenImg = document.querySelector("#btnGenerateImage");
    if (btnGenImg) {
      btnGenImg.disabled = true;
      btnGenImg.title = "Tạo ảnh dựa trên prompt sau khi AI sinh nội dung";
    }

    const subtitle = document.querySelector("#aiResultSubtitle");
    if (subtitle) subtitle.textContent = "Dữ liệu bài viết chuẩn hóa theo từng nền tảng";

    updateHistoryNavControls();
    toast("Đã mở soạn thảo mới. Hãy nhập brief và bấm Tạo bản nháp.");
  }

  if (elHistoryPrev) {
    elHistoryPrev.onclick = () => {
      if (!historyItems.length) return;
      if (currentHistoryIndex === -1) {
        loadHistoryItemToUi(historyItems.length - 1);
      } else if (currentHistoryIndex > 0) {
        loadHistoryItemToUi(currentHistoryIndex - 1);
      }
    };
  }

  if (elHistoryNext) {
    elHistoryNext.onclick = () => {
      if (!historyItems.length) return;
      if (currentHistoryIndex >= 0 && currentHistoryIndex < historyItems.length - 1) {
        loadHistoryItemToUi(currentHistoryIndex + 1);
      }
    };
  }

  if (elHistorySelect) {
    elHistorySelect.onchange = () => {
      const val = elHistorySelect.value;
      if (val !== "") {
        loadHistoryItemToUi(Number(val));
      }
    };
  }

  if (elHistoryNew) {
    elHistoryNew.onclick = () => startNewDraft();
  }

  if (elHistoryClear) {
    elHistoryClear.onclick = () => {
      if (!historyItems.length) return;
      if (confirm("Bạn có chắc chắn muốn xóa toàn bộ lịch sử tạo nội dung AI đã lưu?")) {
        historyItems = [];
        saveHistoryToStorage([]);
        startNewDraft();
        toast("Đã xóa toàn bộ lịch sử");
      }
    };
  }

  // Keyboard navigation Alt + Left / Alt + Right
  window.addEventListener("keydown", (e) => {
    const activeTab = document.querySelector(".tab.active")?.id;
    if (activeTab !== "tab-ai") return;
    if (e.altKey && e.key === "ArrowLeft") {
      e.preventDefault();
      elHistoryPrev?.click();
    } else if (e.altKey && e.key === "ArrowRight") {
      e.preventDefault();
      elHistoryNext?.click();
    }
  });

  function setViewMode(mode) {
    if (mode === "visual") {
      btnVisual?.classList.add("active");
      btnJson?.classList.remove("active");
      if (visualBox) visualBox.style.display = "flex";
      if (jsonBox) jsonBox.style.display = "none";
    } else {
      btnVisual?.classList.remove("active");
      btnJson?.classList.add("active");
      if (visualBox) visualBox.style.display = "none";
      if (jsonBox) jsonBox.style.display = "block";
    }
  }

  btnVisual?.addEventListener("click", () => setViewMode("visual"));
  btnJson?.addEventListener("click", () => setViewMode("json"));

  btnCopy?.addEventListener("click", async () => {
    if (!currentRawJson) return toast("Không có nội dung để chép");
    try {
      await navigator.clipboard.writeText(currentRawJson);
      toast("✓ Đã sao chép JSON vào clipboard");
    } catch {
      toast("Không thể sao chép vào clipboard");
    }
  });

  btnGoToPost?.addEventListener("click", async () => {
    const postTabBtn = document.querySelector('nav button[data-tab="posts"]');
    if (postTabBtn) {
      postTabBtn.click();
      toast("Đã chuyển sang Kho bài viết");
    }
    if (lastCreatedContentId) {
      try {
        const { openPostEditor } = await import("./posts.js?v=2.3.5");
        await openPostEditor(lastCreatedContentId);
      } catch (e) {
        console.error("openPostEditor error:", e);
      }
    }
  });

  function renderStructuredVisual(data) {
    if (!visualBox || !data) return;

    const platformIcons = {
      facebook: "Facebook",
      instagram: "Instagram",
      tiktok: "TikTok",
      youtube: "YouTube",
      x: "X",
    };

    const platformBadgeClass = {
      facebook: "badge-facebook",
      instagram: "badge-instagram",
      tiktok: "badge-tiktok",
      youtube: "badge-youtube",
      x: "badge-x",
    };

    let html = "";

    if (data.topic || data.summary) {
      html += `
        <div class="ai-card-meta">
          ${data.topic ? `<div class="ai-topic-title">📌 ${esc(data.topic)}</div>` : ""}
          ${data.summary ? `<div class="ai-summary-text">${esc(data.summary)}</div>` : ""}
        </div>
      `;
    }

    if (Array.isArray(data.warnings) && data.warnings.length) {
      html += data.warnings
        .map(w => `<div class="warning ai-warning-box">⚠️ <strong>Cảnh báo:</strong> ${esc(w)}</div>`)
        .join("");
    }

    // 1. Resolve image prompt (from field, aliases, or fallback from caption/topic)
    const rawPrompt = (
      data.image_prompt ||
      data.imagePrompt ||
      data.image_description ||
      data.prompt_tao_anh ||
      data.prompt ||
      ""
    ).trim();

    const finalPrompt = rawPrompt || (() => {
      const firstCap = Object.values(data.platform_variants || {}).find(v => v?.caption)?.caption || data.topic || "";
      return firstCap
        ? `A professional, vibrant commercial photograph representing: ${firstCap.slice(0, 150)}. Cinematic lighting, highly detailed, realistic.`
        : "";
    })();

    currentImagePrompt = finalPrompt;

    // Sync with left-column prompt input if available
    const promptInput = document.querySelector("#aiCustomImagePrompt");
    const promptWrap = document.querySelector("#aiImagePromptInputWrap");
    if (promptInput) promptInput.value = finalPrompt;
    if (promptWrap) promptWrap.style.display = finalPrompt ? "flex" : "none";
    const imageControls = document.querySelector("#aiImageControls");
    if (imageControls) imageControls.style.display = "grid";

    // Prominent Image Prompt placed right at the top of the Result Panel
    if (finalPrompt) {
      html += `
        <div class="ai-prompt-box">
          <div class="ai-prompt-head">
            <span class="ai-prompt-title">🎨 <strong>Prompt tạo ảnh AI (Dựa trên nội dung caption):</strong></span>
            <div class="ai-prompt-actions">
              <button type="button" class="btn-prompt-action" data-prompt="${esc(finalPrompt)}" title="Sao chép prompt vào clipboard">📋 Sao chép</button>
              <button type="button" class="btn-prompt-action primary" id="btnVisualQuickGenImg" title="Tạo ảnh ngay bằng AI">🎨 Tạo ảnh ngay</button>
            </div>
          </div>
          <div class="ai-prompt-text" title="Prompt tạo ảnh cho AI (DALL-E, Midjourney, FLUX...)">${esc(finalPrompt)}</div>
        </div>
      `;
    }

    const variants = data.platform_variants || {};
    for (const [platform, variant] of Object.entries(variants)) {
      if (!variant) continue;
      const pName = platformIcons[platform] || platform.toUpperCase();
      const pBadge = platformBadgeClass[platform] || "badge-gray";

      html += `
        <div class="ai-variant-card">
          <div class="ai-variant-head">
            <span class="badge ${pBadge}">${pName}</span>
            ${variant.title ? `<span class="ai-variant-title">${esc(variant.title)}</span>` : ""}
          </div>

          ${variant.video_hook ? `
            <div class="ai-variant-section">
              <span class="ai-variant-label">🎣 Hook mở đầu:</span>
              <div class="ai-variant-content" style="border-left: 3px solid var(--color-primary);">${esc(variant.video_hook)}</div>
            </div>
          ` : ""}

          ${variant.video_script ? `
            <div class="ai-variant-section">
              <span class="ai-variant-label">🎬 Kịch bản video chi tiết:</span>
              <div class="ai-variant-content">${esc(variant.video_script)}</div>
            </div>
          ` : ""}

          ${variant.caption ? `
            <div class="ai-variant-section">
              <span class="ai-variant-label">📝 Caption bài viết:</span>
              <div class="ai-variant-content">${esc(variant.caption)}</div>
            </div>
          ` : ""}

          ${Array.isArray(variant.hashtags) && variant.hashtags.length ? `
            <div class="ai-variant-section">
              <span class="ai-variant-label">🏷️ Hashtags:</span>
              <div class="ai-hashtags-list">
                ${variant.hashtags.map(tag => `<span class="ai-hashtag-pill">${esc(tag.startsWith("#") ? tag : "#" + tag)}</span>`).join("")}
              </div>
            </div>
          ` : ""}

          ${variant.cta ? `
            <div class="ai-variant-section">
              <span class="ai-variant-label">📢 Kêu gọi hành động (CTA):</span>
              <div class="ai-variant-content" style="font-weight:600; color:var(--color-teal-dark);">${esc(variant.cta)}</div>
            </div>
          ` : ""}

          ${variant.pinned_comment ? `
            <div class="ai-variant-section">
              <span class="ai-variant-label">💬 Gợi ý bình luận ghim:</span>
              <div class="ai-variant-content" style="font-style:italic;">${esc(variant.pinned_comment)}</div>
            </div>
          ` : ""}
        </div>
      `;
    }

    if (Array.isArray(data.media_suggestions) && data.media_suggestions.length) {
      html += `
        <div class="ai-media-sug-box">
          <div class="ai-media-sug-title">💡 Gợi ý Media & Hình ảnh:</div>
          <ul class="ai-media-sug-list">
            ${data.media_suggestions.map(item => `<li>${esc(item)}</li>`).join("")}
          </ul>
        </div>
      `;
    }

    visualBox.innerHTML = html;

    visualBox.querySelectorAll(".btn-copy-prompt, .btn-prompt-action[data-prompt]").forEach(btn => {
      btn.onclick = async () => {
        const text = btn.dataset.prompt;
        if (!text) return;
        try {
          await navigator.clipboard.writeText(text);
          toast("✓ Đã sao chép prompt tạo ảnh vào clipboard");
        } catch {
          toast("Không thể sao chép vào clipboard");
        }
      };
    });

    const quickGen = visualBox.querySelector("#btnVisualQuickGenImg");
    if (quickGen) {
      quickGen.onclick = () => {
        const genBtn = document.querySelector("#btnGenerateImage");
        if (genBtn) {
          genBtn.click();
        }
      };
    }
  }

  const aiForm = document.querySelector("#aiForm");
  if (aiForm) {
    aiForm.onsubmit = async event => {
      event.preventDefault();
      const platforms = ["Facebook", "Instagram", "Tiktok", "Youtube", "X"]
        .filter(name => document.querySelector(`#ai${name}`)?.checked)
        .map(name => name.toLowerCase());

      if (!platforms.length) return toast("Hãy chọn ít nhất một nền tảng");
      const promptTemplateId = document.querySelector("#aiPromptTemplate")?.value;
      if (!promptTemplateId) return toast("Hãy chọn một System Prompt đang bật.");
      const promptTemplate = (store.promptTemplates || []).find(item => item.id === promptTemplateId);

      const submitBtn = document.querySelector("#btnGenerateDraft");
      const origBtnText = submitBtn ? submitBtn.innerHTML : "✨ Tạo bản nháp";
      if (submitBtn) {
        submitBtn.disabled = true;
        submitBtn.innerHTML = "⏳ Đang tạo bản nháp…";
      }

      if (jsonBox) {
        jsonBox.style.display = "block";
        jsonBox.innerHTML = `
          <div class="ai-loading-box">
            <div class="ai-spinner"></div>
            <p><b>AI đang phân tích Brief & tạo nội dung đa nền tảng…</b></p>
            <small>Vui lòng đợi giây lát...</small>
          </div>
        `;
      }
      if (visualBox) visualBox.style.display = "none";
      if (actionsBar) actionsBar.style.display = "none";

      try {
        const result = await api("/ai/generate", {
          method: "POST",
          body: JSON.stringify({
            prompt_template_id: promptTemplateId,
            brief: document.querySelector("#aiBrief").value,
            brand_profile_id: document.querySelector("#aiBrand").value || null,
            media_asset_ids: selectedReferenceImages.map(asset => asset.id),
            platforms,
            save_draft: true,
          }),
        });

        currentRawJson = JSON.stringify(result.structured_content, null, 2);
        lastCreatedContentId = result.content?.id || null;
        lastCreatedAsset = null;
        currentImagePrompt = result.structured_content?.image_prompt || "";

        const briefVal = document.querySelector("#aiBrief")?.value || "";
        const briefSnippet = briefVal.trim().replace(/\s+/g, " ").slice(0, 36) + (briefVal.trim().length > 36 ? "..." : "");
        const referenceImages = selectedReferenceImages.map(asset => ({
          id: asset.id,
          original_name: asset.original_name,
          alt_text: asset.alt_text,
          relative_path: asset.relative_path,
          thumbnail_relative_path: asset.thumbnail_relative_path,
        }));

        const newRecord = {
          id: "ai_hist_" + Date.now(),
          createdAt: new Date().toISOString(),
          displayTime: formatTime(new Date().toISOString()),
          promptTemplateName: result.prompt_template?.name || promptTemplate?.name || "System Prompt",
          operation: promptTemplate?.operation || "custom",
          operationLabel: result.prompt_template?.name || promptTemplate?.name || "System Prompt",
          inputs: {
            prompt_template_id: promptTemplateId,
            operation: promptTemplate?.operation || "custom",
            brand_profile_id: document.querySelector("#aiBrand")?.value || null,
            reference_images: referenceImages,
            brief: briefVal,
            platforms: [...platforms],
          },
          briefSnippet,
          output: {
            structured_content: result.structured_content,
            raw_json: currentRawJson,
            content_id: lastCreatedContentId,
            image_prompt: currentImagePrompt,
          },
          image: null,
        };

        historyItems.push(newRecord);
        if (historyItems.length > MAX_HISTORY_ITEMS) {
          historyItems.shift();
        }
        currentHistoryIndex = historyItems.length - 1;
        saveHistoryToStorage(historyItems);
        updateHistoryNavControls();

        const btnGenImg = document.querySelector("#btnGenerateImage");
        if (btnGenImg) {
          btnGenImg.disabled = !imageGenerationAvailable();
          btnGenImg.title = currentImagePrompt
            ? `Tạo ảnh: ${currentImagePrompt.slice(0, 80)}...`
            : "Tạo ảnh minh họa theo nội dung";
        }

        if (jsonBox) jsonBox.textContent = currentRawJson;
        renderStructuredVisual(result.structured_content);

        if (actionsBar) actionsBar.style.display = "flex";
        setViewMode("visual");

        const subtitle = document.querySelector("#aiResultSubtitle");
        if (subtitle) {
          subtitle.textContent = `Bản ghi mới #${historyItems.length}/${historyItems.length} (${newRecord.displayTime}) · ${newRecord.operationLabel}`;
        }

        toast("✨ Đã lưu kết quả thành bản nháp trong Kho bài viết");
      } catch (error) {
        if (jsonBox) {
          jsonBox.style.display = "block";
          jsonBox.textContent = `Lỗi: ${error.message}`;
        }
        if (visualBox) visualBox.style.display = "none";
        toast(error.message);
      } finally {
        if (submitBtn) {
          submitBtn.disabled = false;
          submitBtn.innerHTML = origBtnText;
        }
      }
    };
  }

  // --- Image Generation Handlers ---
  const btnGenerateImage = document.querySelector("#btnGenerateImage");
  const btnCancelAiImage = document.querySelector("#btnCancelAiImage");
  const aiImageResultBox = document.querySelector("#aiImageResultBox");
  const aiGeneratedImg = document.querySelector("#aiGeneratedImg");
  const btnDownloadAiImg = document.querySelector("#btnDownloadAiImg");
  const btnAttachAiImageToDraft = document.querySelector("#btnAttachAiImageToDraft");
  const aiImagePromptMeta = document.querySelector("#aiImagePromptMeta");
  const aiImageSourceBadge = document.querySelector("#aiImageSourceBadge");
  const aiImageGallery = document.querySelector("#aiImageGallery");
  const aiImageStatus = document.querySelector("#aiImageJobStatus");
  const aiImageSource = document.querySelector("#aiImageSource");
  const aiImageAspectRatio = document.querySelector("#aiImageAspectRatio");
  const aiImageCount = document.querySelector("#aiImageCount");
  const aiImageLightboxDialog = document.querySelector("#aiImageLightboxDialog");
  const aiImageLightboxImg = document.querySelector("#aiImageLightboxImg");
  const aiImageLightboxTitle = document.querySelector("#aiImageLightboxTitle");
  const aiImageLightboxIndex = document.querySelector("#aiImageLightboxIndex");
  const aiImageLightboxPrev = document.querySelector("#aiImageLightboxPrev");
  const aiImageLightboxNext = document.querySelector("#aiImageLightboxNext");
  let imageOptions = null;
  let activeImageJobId = "";
  let imageJobTimer = null;
  let activeImages = [];
  let activeImageIndex = 0;

  function setImageJobStatus(message) {
    if (aiImageStatus) aiImageStatus.textContent = message || "";
  }

  function setImageSourcePlaceholder(message) {
    if (!aiImageSource) return;
    aiImageSource.innerHTML = "";
    const option = document.createElement("option");
    option.value = "";
    option.textContent = message;
    aiImageSource.appendChild(option);
    aiImageSource.disabled = true;
    aiImageSource.setAttribute("aria-busy", "false");
  }

  function imageGenerationAvailable() {
    return Boolean(imageOptions?.media_creator?.available && aiImageSource?.value);
  }

  function imageSourceLabel(item) {
    return item.label || item.name || item.id || "Provider không xác định";
  }

  function populateImageSources() {
    if (!aiImageSource || !imageOptions) return;
    const selectedSource = aiImageSource.value;
    const entries = Array.isArray(imageOptions.media_creator?.providers)
      ? imageOptions.media_creator.providers.map(item => ({ value: item.id, label: imageSourceLabel(item) }))
      : [];
    aiImageSource.innerHTML = "";
    if (!entries.length) {
      setImageSourcePlaceholder("Tinix Media Creator chưa có provider ảnh sẵn sàng");
    } else {
      for (const entry of entries) {
        const option = document.createElement("option");
        option.value = entry.value;
        option.textContent = entry.label;
        aiImageSource.appendChild(option);
      }
      aiImageSource.disabled = false;
      aiImageSource.setAttribute("aria-busy", "false");
      if (entries.some(item => item.value === selectedSource)) {
        aiImageSource.value = selectedSource;
      }
    }
  }

  async function loadImageOptions() {
    try {
      imageOptions = await api("/ai/image-options");
      populateImageSources();
      if (!imageOptions.media_creator?.available) {
        setImageJobStatus(imageOptions.media_creator?.message || "Tinix Media Creator chưa sẵn sàng.");
        if (btnGenerateImage) btnGenerateImage.disabled = true;
      } else if (!imageGenerationAvailable()) {
        setImageJobStatus("Tinix Media Creator chưa có provider ảnh sẵn sàng.");
        if (btnGenerateImage) btnGenerateImage.disabled = true;
      } else {
        setImageJobStatus("");
        if (btnGenerateImage && currentImagePrompt && !activeImageJobId) btnGenerateImage.disabled = !imageGenerationAvailable();
      }
    } catch (error) {
      setImageSourcePlaceholder("Không tải được provider Tinix Media Creator");
      setImageJobStatus(`Không tải được cấu hình tạo ảnh: ${error.message}`);
      if (btnGenerateImage) btnGenerateImage.disabled = true;
    }
  }

  function showSelectedImage(index) {
    const image = activeImages[index];
    if (!image) return;
    activeImageIndex = index;
    lastCreatedAsset = image.asset || null;
    if (aiGeneratedImg) {
      aiGeneratedImg.src = image.url;
      aiGeneratedImg.alt = `Ảnh AI ${index + 1} tạo bởi Tinix Media Creator`;
    }
    if (btnDownloadAiImg) {
      btnDownloadAiImg.href = image.url;
      btnDownloadAiImg.download = `ai-img-${Date.now()}-${index + 1}.png`;
    }
    if (aiImageGallery) {
      aiImageGallery.querySelectorAll("button").forEach((button, itemIndex) => button.classList.toggle("active", itemIndex === index));
    }
  }

  function renderImageLightbox() {
    const image = activeImages[activeImageIndex];
    if (!image) return;
    if (aiImageLightboxImg) {
      aiImageLightboxImg.src = image.url;
      aiImageLightboxImg.alt = `Ảnh AI ${activeImageIndex + 1} tạo bởi Tinix Media Creator`;
    }
    if (aiImageLightboxTitle) aiImageLightboxTitle.textContent = "Ảnh tạo bởi Tinix Media Creator";
    if (aiImageLightboxIndex) aiImageLightboxIndex.textContent = `${activeImageIndex + 1} / ${activeImages.length}`;
    if (aiImageLightboxPrev) aiImageLightboxPrev.disabled = activeImageIndex === 0;
    if (aiImageLightboxNext) aiImageLightboxNext.disabled = activeImageIndex === activeImages.length - 1;
  }

  function openImageLightbox(index = activeImageIndex) {
    if (!aiImageLightboxDialog || !activeImages[index]) return;
    showSelectedImage(index);
    renderImageLightbox();
    if (!aiImageLightboxDialog.open) aiImageLightboxDialog.showModal();
  }

  function renderImageResults(images, metadata = {}) {
    activeImages = Array.isArray(images) ? images : [];
    const first = activeImages[0];
    if (!first) return;
    activeImageIndex = 0;
    lastCreatedAsset = first.asset || null;
    if (aiImageResultBox) aiImageResultBox.style.display = "flex";
    showSelectedImage(0);
    if (aiImageGallery) {
      aiImageGallery.innerHTML = "";
      activeImages.forEach((image, index) => {
        const button = document.createElement("button");
        button.type = "button";
        button.title = `Ảnh ${index + 1}`;
        button.setAttribute("aria-label", `Mở ảnh ${index + 1} kích thước đầy đủ`);
        const thumbnail = document.createElement("img");
        thumbnail.src = image.url;
        thumbnail.alt = `Ảnh AI ${index + 1}`;
        button.appendChild(thumbnail);
        button.onclick = () => openImageLightbox(index);
        aiImageGallery.appendChild(button);
      });
      showSelectedImage(activeImageIndex);
    }
    if (aiImagePromptMeta) {
      aiImagePromptMeta.textContent = `Prompt: ${metadata.prompt || currentImagePrompt || ""}`;
      aiImagePromptMeta.title = metadata.prompt || currentImagePrompt || "";
    }
    if (aiImageSourceBadge) aiImageSourceBadge.textContent = metadata.source_model || first.source_model || "AI Image";
    const attached = Boolean(metadata.attached_content_id);
    if (btnAttachAiImageToDraft) {
      btnAttachAiImageToDraft.textContent = attached ? "✓ Đã gắn vào bài viết" : "📎 Gắn ảnh đang chọn";
      btnAttachAiImageToDraft.disabled = attached || !lastCreatedContentId;
    }
  }

  function finishImageJob() {
    if (imageJobTimer) clearTimeout(imageJobTimer);
    imageJobTimer = null;
    activeImageJobId = "";
    if (btnGenerateImage) {
      btnGenerateImage.disabled = !imageGenerationAvailable();
      btnGenerateImage.innerHTML = "🎨 Tạo Ảnh";
    }
    if (btnCancelAiImage) btnCancelAiImage.hidden = true;
  }

  async function pollImageJob() {
    if (!activeImageJobId) return;
    try {
      const job = await api(`/ai/image-jobs/${encodeURIComponent(activeImageJobId)}`);
      setImageJobStatus(job.message || `Đang xử lý (${job.progress || 0}%)…`);
      if (["queued", "running"].includes(job.status)) {
        imageJobTimer = setTimeout(pollImageJob, 1500);
        return;
      }
      finishImageJob();
      if (job.status === "completed" || job.status === "partial") {
        renderImageResults(job.images, { prompt: job.prompt, source_model: `${job.provider} · ${job.model}`, attached_content_id: job.attached_content_id });
        if (currentHistoryIndex >= 0 && currentHistoryIndex < historyItems.length) {
          historyItems[currentHistoryIndex].image = {
            url: job.images[0]?.url, asset: job.images[0]?.asset || null, images: job.images,
            prompt: job.prompt, source_model: `${job.provider} · ${job.model}`, attached: Boolean(job.attached_content_id),
          };
          saveHistoryToStorage(historyItems);
        }
        toast(job.attached_content_id ? "🎨 Đã tạo ảnh và đính kèm vào bài viết!" : "🎨 Đã tạo ảnh thành công!");
      } else {
        toast(`Lỗi tạo ảnh: ${job.message || "Tác vụ thất bại."}`);
      }
    } catch (error) {
      finishImageJob();
      toast(`Không theo dõi được tác vụ tạo ảnh: ${error.message}`);
    }
  }

  if (btnGenerateImage) {
    btnGenerateImage.onclick = async () => {
      const customPrompt = document.querySelector("#aiCustomImagePrompt")?.value.trim();
      let promptToUse = customPrompt || (currentImagePrompt || "").trim();
      if (!promptToUse) {
        const brief = document.querySelector("#aiBrief")?.value.trim();
        if (brief) promptToUse = brief;
        else return toast("Chưa có prompt tạo ảnh. Hãy tạo bản nháp trước.");
      }

      btnGenerateImage.disabled = true;
      btnGenerateImage.innerHTML = "⏳ Đang tạo ảnh…";
      toast("🎨 AI đang tạo ảnh, vui lòng đợi giây lát…");

      try {
        const source = aiImageSource?.value || "";
        if (!imageGenerationAvailable() || !source) throw new Error("Tinix Media Creator chưa có provider ảnh sẵn sàng.");
        const created = await api("/ai/image-jobs", {
          method: "POST",
          body: JSON.stringify({
            prompt: promptToUse,
            provider: source,
            aspect_ratio: aiImageAspectRatio?.value || "auto",
            count: Number(aiImageCount?.value || 1),
            content_id: lastCreatedContentId || null,
          }),
        });
        activeImageJobId = created.job_id;
        if (btnCancelAiImage) btnCancelAiImage.hidden = false;
        setImageJobStatus("Đã gửi tác vụ tạo ảnh…");
        pollImageJob();
      } catch (err) {
        toast("Lỗi tạo ảnh: " + err.message);
        finishImageJob();
      }
    };
  }

  if (btnCancelAiImage) btnCancelAiImage.onclick = async () => {
    if (!activeImageJobId) return;
    try {
      await api(`/ai/image-jobs/${encodeURIComponent(activeImageJobId)}/cancel`, { method: "POST", body: "{}" });
      setImageJobStatus("Đã hủy tác vụ tạo ảnh.");
    } catch (error) {
      toast(`Không thể hủy tác vụ: ${error.message}`);
    } finally {
      finishImageJob();
    }
  };

  const customPromptEl = document.querySelector("#aiCustomImagePrompt");
  if (customPromptEl) {
    customPromptEl.oninput = () => {
      currentImagePrompt = customPromptEl.value.trim();
      const promptBoxText = document.querySelector(".ai-prompt-box .ai-prompt-text");
      if (promptBoxText) promptBoxText.textContent = currentImagePrompt;
    };
  }

  if (aiGeneratedImg) {
    aiGeneratedImg.onclick = () => openImageLightbox();
    aiGeneratedImg.onkeydown = event => {
      if (event.key === "Enter" || event.key === " ") {
        event.preventDefault();
        openImageLightbox();
      }
    };
  }

  function moveLightboxImage(step) {
    const nextIndex = activeImageIndex + step;
    if (nextIndex < 0 || nextIndex >= activeImages.length) return;
    showSelectedImage(nextIndex);
    renderImageLightbox();
  }

  if (aiImageLightboxPrev) aiImageLightboxPrev.onclick = () => moveLightboxImage(-1);
  if (aiImageLightboxNext) aiImageLightboxNext.onclick = () => moveLightboxImage(1);
  if (aiImageLightboxDialog) {
    aiImageLightboxDialog.onclick = event => {
      if (event.target === aiImageLightboxDialog) aiImageLightboxDialog.close();
    };
  }
  window.addEventListener("keydown", event => {
    if (!aiImageLightboxDialog?.open) return;
    if (event.key === "ArrowLeft") moveLightboxImage(-1);
    if (event.key === "ArrowRight") moveLightboxImage(1);
  });

  if (btnAttachAiImageToDraft) {
    btnAttachAiImageToDraft.onclick = async () => {
      if (!lastCreatedContentId || !lastCreatedAsset) {
        return toast("Không tìm thấy bài viết hoặc file ảnh để gắn.");
      }
      try {
        await api(`/media-assets/${lastCreatedAsset.id}/attach`, {
          method: "POST",
          body: JSON.stringify({ content_id: lastCreatedContentId, sort_order: 0 }),
        });
        btnAttachAiImageToDraft.textContent = "✓ Đã gắn vào bài viết";
        btnAttachAiImageToDraft.disabled = true;

        if (currentHistoryIndex >= 0 && currentHistoryIndex < historyItems.length) {
          if (historyItems[currentHistoryIndex].image) {
            historyItems[currentHistoryIndex].image.attached = true;
            saveHistoryToStorage(historyItems);
          }
        }

        toast("✓ Đã gắn ảnh vào bài viết trong Kho bài viết!");
      } catch (err) {
        toast("Lỗi gắn ảnh: " + err.message);
      }
    };
  }

  loadImageOptions();
  window.addEventListener("tinix:refresh-image-options", () => loadImageOptions());

  // Restore history from storage on initialization
  historyItems = loadHistoryFromStorage();
  if (historyItems.length > 0) {
    loadHistoryItemToUi(historyItems.length - 1);
  } else {
    updateHistoryNavControls();
  }
}
