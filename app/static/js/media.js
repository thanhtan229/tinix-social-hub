import {api, bytes, esc, toast} from "./api.js";
import {store} from "./store.js";

function query(){const value=new URLSearchParams({limit:"300"});const search=document.querySelector("#assetSearch").value.trim(),type=document.querySelector("#assetType").value,tag=document.querySelector("#assetTag").value.trim();if(search)value.set("search",search);if(type)value.set("media_type",type);if(tag)value.set("tag",tag);if(document.querySelector("#assetOrphan").checked)value.set("orphan_only","true");return value;}

export async function refreshMedia(){
  const [assets,contents]=await Promise.all([api(`/media-assets?${query()}`),api("/contents?limit=200")]);store.assets=assets;store.contents=contents;
  document.querySelector("#assetList").innerHTML=assets.length?assets.map(asset=>`<article class="asset-card">${asset.thumbnail_relative_path?`<img src="/api/media/${esc(asset.thumbnail_relative_path)}" alt="${esc(asset.alt_text||asset.original_name)}">`:`<div class="video-placeholder">VIDEO</div>`}<div><strong>${esc(asset.original_name)}</strong><small>${esc(asset.media_type)} · ${bytes(asset.size_bytes)} · ${asset.width||"?"}×${asset.height||"?"}</small><p>${esc(asset.alt_text||"Chưa có alt text")}</p><div class="tag-list">${asset.tags.map(tag=>`<span>${esc(tag)}</span>`).join("")}</div><small>${asset.reference_count} reference(s)</small><div class="actions"><button data-edit-asset="${asset.id}">Metadata</button><button data-attach-asset="${asset.id}">Gắn content</button><button class="danger" data-delete-asset="${asset.id}" ${asset.reference_count?"disabled":""}>Xóa</button></div></div></article>`).join(""):`<p class="muted">Chưa có asset phù hợp.</p>`;
  document.querySelectorAll("[data-edit-asset]").forEach(button=>button.onclick=()=>editAsset(button.dataset.editAsset));
  document.querySelectorAll("[data-attach-asset]").forEach(button=>button.onclick=()=>attachAsset(button.dataset.attachAsset));
  document.querySelectorAll("[data-delete-asset]").forEach(button=>button.onclick=()=>deleteAsset(button.dataset.deleteAsset));
}

async function editAsset(id){const asset=store.assets.find(item=>item.id===id);const alt=prompt("Alt text:",asset.alt_text||"");if(alt===null)return;const tags=prompt("Tags, cách nhau bằng dấu phẩy:",asset.tags.join(", "));if(tags===null)return;try{await api(`/media-assets/${id}`,{method:"PATCH",body:JSON.stringify({alt_text:alt||null,tags:tags.split(",").map(item=>item.trim()).filter(Boolean),thumbnail_timestamp:asset.thumbnail_timestamp})});await refreshMedia();}catch(error){toast(error.message);}}
async function attachAsset(id){if(!store.contents.length){toast("Cần tạo content trước.");return;}const listing=store.contents.map((item,index)=>`${index+1}. ${item.title}`).join("\n");const choice=Number(prompt(`Chọn content:\n${listing}`,"1"));const content=store.contents[choice-1];if(!content)return;try{await api(`/media-assets/${id}/attach`,{method:"POST",body:JSON.stringify({content_id:content.id,sort_order:0})});toast("Đã gắn asset vào content.");await refreshMedia();}catch(error){toast(error.message);}}
async function deleteAsset(id){if(!confirm("Xóa asset orphan và file vật lý?"))return;try{await api(`/media-assets/${id}`,{method:"DELETE"});toast("Đã xóa asset.");await refreshMedia();}catch(error){toast(error.message);}}

export function initMedia(){
  document.querySelector("#refreshAssets").onclick=refreshMedia;
  document.querySelector("#assetType").onchange=refreshMedia;document.querySelector("#assetOrphan").onchange=refreshMedia;
  document.querySelector("#assetSearch").oninput=()=>{clearTimeout(initMedia.timer);initMedia.timer=setTimeout(()=>refreshMedia().catch(()=>{}),250);};
  document.querySelector("#assetTag").oninput=document.querySelector("#assetSearch").oninput;
  document.querySelector("#assetUpload").onchange=async event=>{for(const file of event.target.files){const form=new FormData();form.append("file",file);try{await api("/media-assets",{method:"POST",body:form});}catch(error){toast(error.message);}}event.target.value="";await refreshMedia();toast("Upload hoàn tất.");};
}
