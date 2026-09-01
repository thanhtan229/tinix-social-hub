import {api, badge, esc, toast} from "./api.js";
import {store} from "./store.js";

export async function refreshContent() {
  const search = document.querySelector("#contentSearch").value; const status = document.querySelector("#contentStatus").value;
  store.contents = await api(`/contents?limit=100&search=${encodeURIComponent(search)}&status=${encodeURIComponent(status)}`);
  document.querySelector("#contentList").innerHTML = store.contents.length ? store.contents.map(item => `<article class="content-card"><div class="panel-head"><strong>${esc(item.title)}</strong>${badge(item.approval_status)}</div><p>${esc((item.caption || "Chưa có caption").slice(0,180))}</p><small class="muted">Revision ${item.current_revision}</small><div class="actions"><button data-content="edit" data-id="${item.id}">Sửa</button><button data-content="duplicate" data-id="${item.id}">Nhân bản</button>${item.approval_status === "draft" ? `<button data-content="request" data-id="${item.id}">Gửi duyệt</button>` : ""}${item.approval_status === "pending_approval" ? `<button class="primary" data-content="approve" data-id="${item.id}">Duyệt</button>` : ""}<button class="danger" data-content="delete" data-id="${item.id}">Xóa record</button></div></article>`).join("") : '<p class="muted">Kho nội dung đang trống.</p>';
  bindContentActions();
}

async function openEditor(id = null) {
  const dialog = document.querySelector("#contentDialog"); document.querySelector("#contentForm").reset(); document.querySelector("#contentId").value = id || "";
  if (id) { const item = await api(`/contents/${id}`); document.querySelector("#contentDialogTitle").textContent = "Sửa nội dung"; document.querySelector("#contentTitle").value = item.title; document.querySelector("#contentCaption").value = item.caption; document.querySelector("#contentHashtags").value = item.hashtags.join(" "); document.querySelector("#contentCta").value = item.cta || ""; } else document.querySelector("#contentDialogTitle").textContent = "Tạo nội dung";
  dialog.showModal();
}

function bindContentActions() {
  document.querySelectorAll("[data-content]").forEach(button => button.onclick = async () => { try { const id=button.dataset.id, action=button.dataset.content; if(action==="edit") return openEditor(id); if(action==="duplicate") await api(`/contents/${id}/duplicate`,{method:"POST"}); if(action==="request") await api(`/contents/${id}/request-approval`,{method:"POST"}); if(action==="approve") { const detail=await api(`/contents/${id}`); if(!detail.latest_approval) throw new Error("Không tìm thấy approval"); await api(`/approvals/${detail.latest_approval.id}/decide`,{method:"POST",body:JSON.stringify({approved:true})}); } if(action==="delete"&&confirm("Xóa record nhưng giữ file media trên ổ đĩa?")) await api(`/contents/${id}`,{method:"DELETE"}); await refreshContent(); } catch(error) { toast(error.message); } });
}

export function initContent() {
  document.querySelector("#newContent").onclick=()=>openEditor(); document.querySelector("#refreshContent").onclick=refreshContent; document.querySelector("#contentStatus").onchange=refreshContent;
  document.querySelector("#contentSearch").oninput=()=>{clearTimeout(initContent.timer);initContent.timer=setTimeout(refreshContent,350);};
  document.querySelector("#contentForm").onsubmit=async event=>{event.preventDefault();const id=document.querySelector("#contentId").value;const body={title:document.querySelector("#contentTitle").value,caption:document.querySelector("#contentCaption").value,hashtags:document.querySelector("#contentHashtags").value.split(/\s+/).filter(Boolean),cta:document.querySelector("#contentCta").value||null,platform_variants:{facebook:{caption:document.querySelector("#contentCaption").value,hashtags:document.querySelector("#contentHashtags").value.split(/\s+/).filter(Boolean),cta:document.querySelector("#contentCta").value||""}}};try{const saved=await api(id?`/contents/${id}`:"/contents",{method:id?"PUT":"POST",body:JSON.stringify(body)});for(const file of document.querySelector("#contentMedia").files){const form=new FormData();form.append("file",file);form.append("sort_order","0");await api(`/contents/${saved.id}/media`,{method:"POST",body:form});}document.querySelector("#contentDialog").close();await refreshContent();toast("Đã lưu bản nháp");}catch(error){toast(error.message);}};
}

