import {api, badge, esc, toast} from "./api.js";

function format(value){return new Intl.NumberFormat("vi-VN",{maximumFractionDigits:1,notation:value>=10000?"compact":"standard"}).format(value);}

export async function refreshAnalytics(){
  const days=document.querySelector("#analyticsDays").value,platform=document.querySelector("#analyticsPlatform").value;
  const query=new URLSearchParams({days});if(platform)query.set("platform",platform);
  const [summary,releases]=await Promise.all([api(`/analytics/summary?${query}`),api(`/publication-releases?${platform?`platform=${platform}&`:""}limit=200`)]);
  const metrics=Object.entries(summary.metrics);
  document.querySelector("#analyticsStats").innerHTML=summary.supported?metrics.map(([key,item])=>`<div class="stat"><span>${esc(key)} · ${days} ngày</span><strong>${format(item.current)}</strong><small class="muted">Kỳ trước ${format(item.previous)}</small></div>`).join(""):`<div class="stat unsupported"><span>Analytics</span><strong>Không hỗ trợ / chưa có dữ liệu</strong><small>Chưa thu thập metric nào từ UI.</small></div>`;
  document.querySelector("#analyticsReleases").innerHTML=releases.length?releases.map(item=>`<div class="status-row"><div><strong>${esc(item.platform)} · ${esc(item.content_format)}</strong><small class="muted">${item.external_url?esc(item.external_url):"Chưa kết nối URL"}</small></div><div class="actions">${badge(item.status)}<button data-connect-release="${item.id}">${item.external_url?"Đổi URL":"Kết nối"}</button><button data-collect-release="${item.id}" ${item.external_url?"":"disabled"}>Thu thập UI</button><button data-view-metrics="${item.id}">Metrics</button></div></div>`).join(""):`<p class="muted">Chưa có release.</p>`;
  document.querySelectorAll("[data-connect-release]").forEach(button=>button.onclick=()=>connect(button.dataset.connectRelease));
  document.querySelectorAll("[data-collect-release]").forEach(button=>button.onclick=()=>collect(button.dataset.collectRelease));
  document.querySelectorAll("[data-view-metrics]").forEach(button=>button.onclick=()=>viewMetrics(button.dataset.viewMetrics));
}
async function connect(id){const url=prompt("URL bài đăng đúng nền tảng:","");if(!url)return;const note=prompt("Ghi chú đối soát:","Kết nối thủ công từ WebUI");if(!note)return;try{await api(`/publication-releases/${id}/connect`,{method:"PATCH",body:JSON.stringify({external_url:url,note})});toast("Đã kết nối release.");await refreshAnalytics();}catch(error){toast(error.message);}}
async function collect(id){try{const result=await api(`/publication-releases/${id}/collect-metrics`,{method:"POST"});toast(result.status==="succeeded"?"Đã thu thập metric từ UI.":result.message);await refreshAnalytics();}catch(error){toast(error.message);}}
async function viewMetrics(id){try{const result=await api(`/publication-releases/${id}/metrics`);alert(result.metrics.length?result.metrics.map(item=>`${item.metric_date} · ${item.metric_key}: ${format(item.value)} · ${item.source}`).join("\n"):"Không hỗ trợ / chưa có metric.");}catch(error){toast(error.message);}}
export function initAnalytics(){document.querySelector("#refreshAnalytics").onclick=refreshAnalytics;document.querySelector("#analyticsDays").onchange=refreshAnalytics;document.querySelector("#analyticsPlatform").onchange=refreshAnalytics;}
