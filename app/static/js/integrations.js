import {api, esc, toast} from "./api.js";

let catalog = {ai_providers: [], platform_apps: []};
let aiState = {configs: [], defaults: {}};
let platformApps = [];
let editing = null;
let modelDiscoveryTimer = null;

const root = () => document.querySelector("#tab-settings");
const definition = (group, id) => (catalog[group] || []).find(item => item.id === id);
const option = (value, label, selected = false, disabled = false) => `<option value="${esc(value)}"${selected ? " selected" : ""}${disabled ? " disabled" : ""}>${esc(label)}</option>`;
const stamp = value => value ? new Date(value).toLocaleString("vi-VN") : "Chưa test";

async function ensureCatalog() {
  if (!catalog.ai_providers.length || !catalog.platform_apps.length) {
    catalog = await api("/integrations/catalog");
  }
}

function configOptions(selected, capability) {
  return [option("", "— Chưa chọn —", !selected), ...aiState.configs
    .filter(item => item.enabled && (capability !== "image" || item.image_model))
    .map(item => {
      const model = item[`${capability}_model_display_name`] || item[`${capability}_model`] || "Chưa chọn";
      return option(item.id, `${item.name} · ${model}`, selected === item.id);
    })].join("");
}

function aiCard(item) {
  const defaults = aiState.defaults || {};
  const badges = [
    item.id === defaults.text_config_id ? "Mặc định nội dung" : "",
    item.enabled ? "Đang bật" : "Đã tắt",
  ].filter(Boolean).map(value => `<span class="badge">${esc(value)}</span>`).join(" ");
  return `<article class="integration-card"><div class="integration-card-head"><strong>${esc(definition("ai_providers", item.provider)?.name || item.provider)}</strong><span>${badges}</span></div><h4>${esc(item.name)}</h4><p class="muted">Key: ${esc(item.key_hint || "Chưa có")} · Text: ${esc(item.text_model || "Chưa chọn")}</p><p class="muted">Test: ${esc(item.last_test_status)} · ${esc(stamp(item.last_test_at))}${item.last_error_message ? ` · ${esc(item.last_error_message)}` : ""}</p><div class="actions"><button data-ai-action="test" data-id="${esc(item.id)}">Test API</button><button data-ai-action="models" data-id="${esc(item.id)}">Làm mới model</button><button data-ai-action="edit" data-id="${esc(item.id)}">Sửa</button><button data-ai-action="toggle" data-id="${esc(item.id)}">${item.enabled ? "Tắt" : "Bật"}</button><button data-ai-action="delete" data-id="${esc(item.id)}" class="danger">Xóa</button></div></article>`;
}

function platformCard(item) {
  const definitionItem = definition("platform_apps", item.provider) || {};
  const readiness = definitionItem.official_publisher === "available" ? "Official API sẵn sàng" : "Credential đã lưu; Tinix chưa hỗ trợ đăng official API cho nền tảng này.";
  return `<article class="integration-card"><div class="integration-card-head"><strong>${esc(definitionItem.name || item.provider)}</strong><span class="badge">${esc(item.enabled ? "Đang bật" : "Đã tắt")}</span></div><h4>${esc(item.name)}</h4><p class="muted">${esc(definitionItem.client_label || "Client ID")}: ${esc(item.client_id)} · Secret: ${esc(item.secret_hint || "Chưa có")}</p><p class="muted">Callback: ${esc(item.redirect_uri)}</p><p class="muted">${esc(readiness)} · Test: ${esc(item.last_test_status)} · ${esc(stamp(item.last_test_at))}</p><div class="actions"><button data-app-action="test" data-id="${esc(item.id)}">Kiểm tra App</button><button data-app-action="edit" data-id="${esc(item.id)}">Sửa</button><button data-app-action="toggle" data-id="${esc(item.id)}">${item.enabled ? "Tắt" : "Bật"}</button><button data-app-action="delete" data-id="${esc(item.id)}" class="danger">Xóa</button></div></article>`;
}

function render() {
  document.querySelector("#aiProviderCards").innerHTML = aiState.configs.length ? aiState.configs.map(aiCard).join("") : "<p class=\"muted\">Chưa có AI Provider trong kho bảo mật. Cấu hình .env cũ vẫn được dùng nếu có.</p>";
  document.querySelector("#platformAppCards").innerHTML = platformApps.length ? platformApps.map(platformCard).join("") : "<p class=\"muted\">Chưa có Platform Developer App.</p>";
  document.querySelector("#defaultTextProvider").innerHTML = configOptions(aiState.defaults?.text_config_id, "text");
  document.querySelector("#integrationStatus").textContent = aiState.legacy_configured ? "Có cấu hình .env legacy làm fallback." : "Credential mới được lưu mã hóa bằng Windows DPAPI.";
}

export async function refreshIntegrations() {
  if (!root()) return;
  [catalog, aiState, platformApps] = await Promise.all([api("/integrations/catalog"), api("/integrations/ai"), api("/integrations/platform-apps")]);
  render();
}

function field(label, content) { return `<label>${esc(label)}${content}</label>`; }
function modelField(label, value, models, provider, capability) {
  const definitionItem = definition("ai_providers", provider) || {};
  const choices = models.length ? models.filter(model => provider === "gemini" && capability === "text" ? true : (model.capabilities || []).includes(capability)) : (definitionItem[`${capability}_models`] || []).map(model_id => ({model_id, display_name: model_id}));
  const known = choices.some(model => model.model_id === value);
  const optional = capability === "image";
  const useCustom = !known && (!!value || !choices.length) && !optional;
  const customVisible = useCustom || (!known && !!value);
  const modelOption = model => {
    const supported = model.metadata?.supports_generate_content !== false;
    const display = provider === "gemini" ? `${supported ? "✓" : "—"} ${model.display_name || model.model_id}${supported ? "" : " · Không hỗ trợ generateContent"}` : model.display_name || model.model_id;
    return option(model.model_id, display, model.model_id === value, !supported);
  };
  return field(label, `<select name="${capability}_model">${optional ? option("", "— Không dùng —", !value) : ""}${choices.map(modelOption).join("")}${option("__custom__", "Model tùy chỉnh…", customVisible)}</select><input class="model-custom ${customVisible ? "" : "hidden"}" name="${capability}_model_custom" value="${esc(!known ? value || "" : "")}" maxlength="200" ${customVisible ? "" : "disabled"} ${!optional && customVisible ? "required" : ""} placeholder="Nhập ID model tùy chỉnh">`);
}

function aiProviderFields(provider, item, models) {
  const definitionItem = definition("ai_providers", provider) || {};
  const textModel = item?.text_model || definitionItem.recommended_text_model || "";
  const baseUrl = definitionItem.requires_base_url ? field("Base URL", `<input name="base_url" type="url" required maxlength="2000" value="${esc(item?.base_url || "")}" placeholder="https://api.example.com/v1">`) : "";
  return baseUrl + modelField("Model agent", textModel, models, provider, "text");
}

async function discoverAiModels(button, quiet = false) {
  const form = document.querySelector("#integrationForm");
  const provider = formValue(form, "provider");
  const apiKey = formValue(form, "api_key");
  const item = editing?.item;
  const useLegacy = !apiKey && !item && aiState.legacy?.provider === provider;
  if (!apiKey && !item && !useLegacy) throw new Error("Nhập API key trước khi làm mới danh sách model.");
  button.disabled = true;
  const originalLabel = button.textContent;
  button.textContent = "Đang tải model…";
  try {
    let models;
    if (apiKey) {
      const payload = {provider, api_key: apiKey};
      if (form.querySelector("[name=base_url]")) payload.base_url = formValue(form, "base_url");
      models = await api("/integrations/ai/discover-models", {method: "POST", body: JSON.stringify(payload)});
    } else if (item) {
      models = await api(`/integrations/ai/${item.id}/models/refresh`, {method: "POST"});
    } else {
      models = await api("/integrations/ai/legacy-models", {method: "POST"});
    }
    const current = {
      text_model: selectedModel(form, "text"),
      base_url: formValue(form, "base_url"),
    };
    document.querySelector("[data-ai-provider-fields]").innerHTML = aiProviderFields(provider, current, models);
    const compatible = models.filter(model => model.metadata?.supports_generate_content !== false).length;
    if (!quiet) toast(`Đã tải ${models.length} model · ${compatible} model dùng được cho Agent.`);
  } finally {
    button.disabled = false;
    button.textContent = originalLabel;
  }
}

function scheduleModelDiscovery() {
  clearTimeout(modelDiscoveryTimer);
  const form = document.querySelector("#integrationForm");
  if (!form) return;
  const provider = formValue(form, "provider");
  if (!formValue(form, "api_key") && aiState.legacy?.provider !== provider) return;
  modelDiscoveryTimer = setTimeout(() => {
    const button = document.querySelector("[data-ai-discover-models]");
    if (button) discoverAiModels(button, true).catch(error => {
      document.querySelector("#integrationDialogStatus").textContent = error.message;
    });
  }, 600);
}

async function openAiDialog(item = null) {
  await ensureCatalog();
  editing = {type: "ai", item};
  const dialog = document.querySelector("#integrationDialog");
  const title = document.querySelector("#integrationDialogTitle");
  const holder = document.querySelector("#integrationDialogFields");
  let models = [];
  if (item) models = await api(`/integrations/ai/${item.id}/models`);
  const provider = item?.provider || "gemini";
  const providerOptions = catalog.ai_providers.map(entry => option(entry.id, entry.name, entry.id === provider)).join("");
  title.textContent = item ? "Sửa AI Provider" : "Thêm AI Provider";
  holder.innerHTML = field("Provider", `<select name="provider" ${item ? "disabled" : ""}>${providerOptions}</select>`) + field("Tên cấu hình", `<input name="name" required maxlength="100" value="${esc(item?.name || "")}" placeholder="Ví dụ: OpenAI công việc">`) + field(item ? "API key mới (bỏ trống để giữ nguyên)" : "API key", `<input name="api_key" type="password" ${item ? "" : "required"} maxlength="2000" autocomplete="off">`) + `<div class="full"><button type="button" data-ai-discover-models>Làm mới danh sách model</button><p class="muted">Dùng API key vừa nhập hoặc cấu hình legacy trong .env để lấy model khả dụng.</p></div>` + `<div class="provider-fields" data-ai-provider-fields>${aiProviderFields(provider, item, models)}</div>` + `<label class="check full"><input name="enabled" type="checkbox" ${item?.enabled === false ? "" : "checked"}><span>Kích hoạt cấu hình</span></label>`;
  dialog.showModal();
  if (item || aiState.legacy?.provider === provider) discoverAiModels(holder.querySelector("[data-ai-discover-models]"), true).catch(error => {
    document.querySelector("#integrationDialogStatus").textContent = error.message;
  });
}

async function openAppDialog(item = null) {
  await ensureCatalog();
  editing = {type: "app", item};
  const dialog = document.querySelector("#integrationDialog");
  const title = document.querySelector("#integrationDialogTitle");
  const holder = document.querySelector("#integrationDialogFields");
  const provider = item?.provider || "meta";
  const definitionItem = definition("platform_apps", provider) || {};
  title.textContent = item ? "Sửa Platform Developer App" : "Thêm Platform Developer App";
  holder.innerHTML = field("Nền tảng", `<select name="provider" ${item ? "disabled" : ""}>${catalog.platform_apps.map(entry => option(entry.id, entry.name, entry.id === provider)).join("")}</select>`) + field("Tên app / môi trường", `<input name="name" required maxlength="100" value="${esc(item?.name || "")}" placeholder="Ví dụ: Production">`) + field(definitionItem.client_label || "Client ID", `<input name="client_id" required maxlength="1000" value="${esc(item?.client_id || "")}">`) + field(item ? `${definitionItem.secret_label || "Client Secret"} mới (bỏ trống để giữ nguyên)` : definitionItem.secret_label || "Client Secret", `<input name="client_secret" type="password" ${item ? "" : "required"} maxlength="2000" autocomplete="off">`) + field("Redirect URI", `<input name="redirect_uri" required type="url" maxlength="2000" value="${esc(item?.redirect_uri || `${location.origin}${definitionItem.default_redirect_path || ""}`)}">`) + field("API version (nếu có)", `<input name="api_version" maxlength="100" value="${esc(item?.api_version || "")}">`) + field("Scopes (cách nhau bởi dấu phẩy)", `<input name="scopes" maxlength="2000" value="${esc((item?.scopes || definitionItem.scopes || []).join(", "))}">`) + `<label class="check full"><input name="enabled" type="checkbox" ${item?.enabled === false ? "" : "checked"}><span>Kích hoạt Platform App</span></label>`;
  dialog.showModal();
}

function formValue(form, name) { return String(new FormData(form).get(name) || "").trim(); }
function selectedModel(form, capability) { const selected = formValue(form, `${capability}_model`); return selected === "__custom__" ? formValue(form, `${capability}_model_custom`) : selected; }

async function saveDialog(event) {
  event.preventDefault();
  const form = event.currentTarget;
  const button = form.querySelector("button[type=submit]");
  const isAi = editing?.type === "ai";
  const item = editing?.item;
  const payload = isAi ? {provider: formValue(form, "provider"), name: formValue(form, "name"), text_model: selectedModel(form, "text"), enabled: form.querySelector("[name=enabled]").checked} : {provider: formValue(form, "provider"), name: formValue(form, "name"), client_id: formValue(form, "client_id"), redirect_uri: formValue(form, "redirect_uri"), api_version: formValue(form, "api_version"), scopes: formValue(form, "scopes").split(",").map(value => value.trim()).filter(Boolean), enabled: form.querySelector("[name=enabled]").checked};
  if (isAi && form.querySelector("[name=base_url]")) payload.base_url = formValue(form, "base_url");
  const secretName = isAi ? "api_key" : "client_secret";
  const secret = formValue(form, secretName);
  if (secret) payload[secretName] = secret;
  button.disabled = true;
  try {
    await api(item ? `/integrations/${isAi ? "ai" : "platform-apps"}/${item.id}` : `/integrations/${isAi ? "ai" : "platform-apps"}`, {method: item ? "PUT" : "POST", body: JSON.stringify(payload)});
    form.closest("dialog").close();
    await refreshIntegrations();
    if (isAi) window.dispatchEvent(new Event("tinix:refresh-image-options"));
    toast("Đã lưu cấu hình tích hợp.");
  } catch (error) { document.querySelector("#integrationDialogStatus").textContent = error.message; toast(error.message); } finally { button.disabled = false; }
}

async function aiAction(button) {
  const item = aiState.configs.find(entry => entry.id === button.dataset.id);
  if (!item) return;
  const action = button.dataset.aiAction;
  try {
    button.disabled = true;
    if (action === "edit") return await openAiDialog(item);
    if (action === "models") { await api(`/integrations/ai/${item.id}/models/refresh`, {method: "POST"}); toast("Đã làm mới danh sách model."); }
    if (action === "test") { const result = await api(`/integrations/ai/${item.id}/test`, {method: "POST"}); toast(`API hoạt động · ${result.model} · ${result.latency_ms} ms`); }
    if (action === "toggle") await api(`/integrations/ai/${item.id}`, {method: "PUT", body: JSON.stringify({enabled: !item.enabled})});
    if (action === "delete") { if (!confirm(`Xóa AI Provider “${item.name}”?`)) return; await api(`/integrations/ai/${item.id}`, {method: "DELETE"}); }
    await refreshIntegrations();
    if (["models", "toggle", "delete"].includes(action)) window.dispatchEvent(new Event("tinix:refresh-image-options"));
  } catch (error) { toast(error.message); } finally { button.disabled = false; }
}

async function appAction(button) {
  const item = platformApps.find(entry => entry.id === button.dataset.id);
  if (!item) return;
  const action = button.dataset.appAction;
  try {
    button.disabled = true;
    if (action === "edit") return await openAppDialog(item);
    if (action === "test") { const result = await api(`/integrations/platform-apps/${item.id}/test`, {method: "POST"}); toast(result.message); }
    if (action === "toggle") await api(`/integrations/platform-apps/${item.id}`, {method: "PUT", body: JSON.stringify({enabled: !item.enabled})});
    if (action === "delete") { if (!confirm(`Xóa Platform App “${item.name}”?`)) return; await api(`/integrations/platform-apps/${item.id}`, {method: "DELETE"}); }
    await refreshIntegrations();
  } catch (error) { toast(error.message); } finally { button.disabled = false; }
}

export function initIntegrations() {
  if (!root()) return;
  document.querySelector("#addAiProvider").onclick = () => openAiDialog().catch(error => toast(error.message));
  document.querySelector("#addPlatformApp").onclick = () => openAppDialog().catch(error => toast(error.message));
  document.querySelector("#integrationForm").onsubmit = saveDialog;
  document.querySelector("#aiProviderCards").onclick = event => { const button = event.target.closest("[data-ai-action]"); if (button) aiAction(button); };
  document.querySelector("#platformAppCards").onclick = event => { const button = event.target.closest("[data-app-action]"); if (button) appAction(button); };
  document.querySelector("#saveAiDefaults").onclick = async () => { try { await api("/integrations/ai/defaults", {method: "PUT", body: JSON.stringify({text_config_id: document.querySelector("#defaultTextProvider").value || null, image_config_id: null})}); await refreshIntegrations(); toast("Đã lưu AI mặc định."); } catch (error) { toast(error.message); } };
  document.querySelector("#integrationDialogFields").onchange = event => {
    if (event.target.matches("select[name=provider]") && editing?.type === "ai") {
      const provider = event.target.value;
      document.querySelector("[data-ai-provider-fields]").innerHTML = aiProviderFields(provider, null, []);
      scheduleModelDiscovery();
    }
    if (event.target.matches("select[name$=_model]")) {
      const custom = event.target.parentElement.querySelector(".model-custom");
      if (custom) {
        const visible = event.target.value === "__custom__";
        custom.classList.toggle("hidden", !visible);
        custom.disabled = !visible;
        custom.required = visible && event.target.name === "text_model";
      }
    }
  };
  document.querySelector("#integrationDialogFields").onclick = event => {
    const button = event.target.closest("[data-ai-discover-models]");
    if (button) discoverAiModels(button).catch(error => toast(error.message));
  };
  document.querySelector("#integrationDialogFields").oninput = event => {
    if (event.target.matches("input[name=api_key]")) scheduleModelDiscovery();
  };
}
