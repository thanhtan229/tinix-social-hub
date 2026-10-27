import {api, badge, esc, toast} from "./api.js";

const PAGE_SIZE=50;
const CHANNEL_RUN_LABELS={succeeded:"thành công",unavailable:"Page/bài không còn khả dụng hoặc đã gỡ quyền",needs_connection:"cần kiểm tra kết nối hoặc quyền",rate_limited:"Meta đang giới hạn tần suất",failed:"Meta từ chối yêu cầu",unsupported:"không hỗ trợ"};
const POST_RUN_LABELS={unavailable:"Meta không còn cho phép đọc bài",needs_connection:"cần kiểm tra kết nối hoặc quyền Meta",rate_limited:"Meta đang giới hạn tần suất",failed:"lần đọc từ Meta thất bại",unsupported:"metric không được hỗ trợ",needs_reconciliation:"cần đối soát bài đăng"};
const META_CONNECTION_LABELS={reauth_required:"Cần kết nối lại Meta API",scope_missing:"Meta API cần quyền bổ sung",revoked:"Quyền Meta API đã bị thu hồi",disconnected:"Meta API đã ngắt"};
let releaseRows=[];
let releaseOffset=0;
let accountsCache=[];
let targetsCache=[];
let refreshSettingsCache=null;

function format(value){return new Intl.NumberFormat("vi-VN",{maximumFractionDigits:1,notation:Number(value)>=10000?"compact":"standard"}).format(Number(value)||0);}
function paramsForFilters(days){
  const params=new URLSearchParams({days:String(days)});
  for(const [id,key] of [["analyticsPlatform","platform"],["analyticsAccount","account_id"],["analyticsTarget","target_id"]]){
    const value=document.querySelector(`#${id}`).value;if(value)params.set(key,value);
  }
  return params;
}
function fillSelect(selector,items,firstLabel,valueKey,labelFor,selected){
  const select=document.querySelector(selector),options=[`<option value="">${firstLabel}</option>`,...items.map(item=>`<option value="${esc(item[valueKey])}">${esc(labelFor(item))}</option>`)];
  select.innerHTML=options.join("");if(selected&&items.some(item=>String(item[valueKey])===selected))select.value=selected;
}
function sparkline(rows){
  const points=rows.filter(row=>row.metric_key==="daily_views"||row.metric_key==="views").sort((a,b)=>a.metric_date.localeCompare(b.metric_date)).slice(-30);
  if(points.length<2)return `<small class="muted">Chưa đủ dữ liệu xu hướng theo ngày</small>`;
  const values=points.map(row=>Number(row.value)||0),low=Math.min(...values),range=Math.max(1,Math.max(...values)-low);
  const coords=values.map((value,index)=>`${(index/(values.length-1)*100).toFixed(1)},${(32-(value-low)/range*28).toFixed(1)}`).join(" ");
  return `<svg viewBox="0 0 100 36" role="img" aria-label="Xu hướng lượt xem theo ngày" style="width:150px;height:44px"><polyline points="${coords}" fill="none" stroke="currentColor" stroke-width="2" vector-effect="non-scaling-stroke"/></svg>`;
}

export async function refreshAnalytics(append=false){
  const days=document.querySelector("#analyticsDays").value,filter=paramsForFilters(days);
  if(!append){releaseOffset=0;releaseRows=[];}
  const releaseParams=new URLSearchParams(filter);releaseParams.set("limit",String(PAGE_SIZE));releaseParams.set("offset",String(releaseOffset));releaseParams.set("order","desc");
  const [summary,releases,accounts,targets,channelMetrics,channelHistory,channelSummary,channelRuns,connectedMetaTargetIds,metaTargetStatuses,refreshSettings]=await Promise.all([
    api(`/analytics/summary?${filter}`),api(`/publication-releases?${releaseParams}`),api("/accounts"),api("/targets"),
    api(`/analytics/channels?${filter}`),api(`/analytics/channels/history?${filter}`),
    api(`/analytics/channels/summary?${filter}`),api(`/analytics/channels/runs?${filter}`),
    api(`/analytics/channels/connected-meta-targets?${filter}`),api(`/analytics/channels/meta-target-statuses?${filter}`),api("/analytics/refresh-settings"),
  ]);
  refreshSettingsCache=refreshSettings;
  document.querySelector("#analyticsAutoRefresh").checked=Boolean(refreshSettings.enabled);
  document.querySelector("#analyticsMetaAutoRefresh").checked=Boolean(refreshSettings.meta_enabled);
  document.querySelector("#analyticsRefreshInterval").value=String(refreshSettings.interval_hours||24);
  const lastRun=refreshSettings.last_run;
  const autoProviders=[refreshSettings.enabled?"YouTube":null,refreshSettings.meta_enabled?"Facebook Page (Meta)":null].filter(Boolean);
  document.querySelector("#analyticsRefreshStatus").textContent=autoProviders.length
    ?`Tự động cập nhật ${autoProviders.join(" và ")} · tối đa ${refreshSettings.posts_per_run} bài và ${refreshSettings.channels_per_run} kênh mỗi lượt/provider · lần chạy gần nhất: ${lastRun?.finished_at||"đang chờ"}${lastRun?` · ${lastRun.succeeded} thành công, ${lastRun.no_data} chưa có dữ liệu, ${lastRun.needs_action} cần xử lý`:""} · lượt dự kiến tiếp theo: ${refreshSettings.next_run_at||"đang tính"}. Khi Tinix đang đóng, lịch không chạy.`
    :`Tự động cập nhật đang tắt. Không có lượt API nền nào chạy cho đến khi bật YouTube hoặc Meta.`;
  accountsCache=accounts;targetsCache=targets;
  const selectedAccount=document.querySelector("#analyticsAccount").value,selectedTarget=document.querySelector("#analyticsTarget").value;
  const platform=document.querySelector("#analyticsPlatform").value;
  const filteredAccounts=accounts.filter(item=>!platform||item.platform===platform);
  fillSelect("#analyticsAccount",filteredAccounts,"Mọi account","id",item=>`${item.name} · ${item.platform}`,selectedAccount);
  const currentAccount=document.querySelector("#analyticsAccount").value;
  const filteredTargets=targets.filter(item=>(!platform||item.platform===platform)&&(!currentAccount||item.account_id===currentAccount));
  fillSelect("#analyticsTarget",filteredTargets,"Mọi kênh/Page","id",item=>`${item.name} · ${item.platform}`,selectedTarget);

  const metrics=Object.entries(summary.metrics);
  document.querySelector("#analyticsStats").innerHTML=summary.supported?metrics.map(([key,item])=>`<div class="stat"><span>${esc(key)} · ${days} ngày</span><strong>${format(item.current)}</strong><small class="muted">Kỳ trước ${format(item.previous)}</small></div>`).join(""):`<div class="stat unsupported"><span>Analytics bài đăng</span><strong>Chưa có dữ liệu</strong><small>Chỉ tính metric đã thu thập trong bộ lọc hiện tại.</small></div>`;

  const filteredChannelMetrics=channelMetrics.filter(item=>(!platform||item.platform===platform)&&(!currentAccount||item.account_id===currentAccount)&&(!document.querySelector("#analyticsTarget").value||item.target_id===document.querySelector("#analyticsTarget").value));
  const filteredHistory=channelHistory.filter(item=>(!platform||item.platform===platform)&&(!currentAccount||item.account_id===currentAccount)&&(!document.querySelector("#analyticsTarget").value||item.target_id===document.querySelector("#analyticsTarget").value));
  const filteredChannelRuns=channelRuns.filter(item=>(!platform||targets.find(target=>target.id===item.target_id)?.platform===platform)&&(!currentAccount||targets.find(target=>target.id===item.target_id)?.account_id===currentAccount)&&(!document.querySelector("#analyticsTarget").value||item.target_id===document.querySelector("#analyticsTarget").value));
  const channelTotals=Object.entries(channelSummary.metrics||{});
  const channelSummaryHtml=channelTotals.length?`<div class="stats">${channelTotals.map(([key,value])=>`<div class="stat"><span>Kênh · ${esc(key)} · ${days} ngày</span><strong>${format(value.current)}</strong><small class="muted">Kỳ trước ${format(value.previous)}</small></div>`).join("")}</div>`:"";
  const filteredConnectedMetaTargetIds=connectedMetaTargetIds.filter(targetId=>{
    const target=targets.find(item=>item.id===targetId);
    return target&&(!platform||target.platform===platform)&&(!currentAccount||target.account_id===currentAccount)&&(!document.querySelector("#analyticsTarget").value||target.id===document.querySelector("#analyticsTarget").value);
  });
  const metaTargetStatusById=new Map(metaTargetStatuses.map(item=>[item.target_id,item]));
  const targetIds=[...new Set([...filteredChannelMetrics.map(item=>item.target_id),...filteredHistory.map(item=>item.target_id),...filteredChannelRuns.map(item=>item.target_id),...filteredConnectedMetaTargetIds])];
  document.querySelector("#channelAnalytics").innerHTML=channelSummaryHtml+(targetIds.length?targetIds.map(targetId=>{
    const target=targets.find(item=>item.id===targetId);if(!target)return "";
    const current=filteredChannelMetrics.filter(item=>item.target_id===targetId);
    const history=filteredHistory.filter(item=>item.target_id===targetId);
    const latestRun=filteredChannelRuns.find(item=>item.target_id===targetId);
    const metaStatus=target.platform==="facebook"?metaTargetStatusById.get(targetId):null;
    const metaApiReady=metaStatus?.connection_status==="connected"&&metaStatus?.binding_status==="connected";
    const metaStatusLabel=!metaStatus?"Page chưa liên kết Meta API":metaApiReady?"Meta API đang kết nối":metaStatus.binding_status==="disconnected"?"Page đã ngắt khỏi Meta API":META_CONNECTION_LABELS[metaStatus.connection_status]||"Meta API chưa sẵn sàng";
    const rendered=current.map(item=>`${esc(item.metric_key)}: ${format(item.value)} <small class="muted">${esc(item.metric_date)} · ${esc(item.source)} · cập nhật ${esc(item.fetched_at||"")}</small>`).join(" · ");
    const reportState=history.length?`Báo cáo ngày đến ${esc(history.map(item=>item.metric_date).sort().at(-1))}`:"Chưa có lịch sử theo ngày";
    const runState=(latestRun?`Lần cập nhật gần nhất: ${esc(CHANNEL_RUN_LABELS[latestRun.status]||latestRun.status)} · ${esc(latestRun.finished_at||latestRun.started_at||"")}${latestRun.status!=="succeeded"&&current.length?" · đang hiển thị snapshot đã lưu trước đó":""}`:"Chưa từng cập nhật analytics")+(target.platform==="facebook"?` · ${esc(metaStatusLabel)}`:"");
    const canCollect=["youtube","facebook"].includes(target.platform);
    const action=target.platform==="facebook"&&!metaApiReady?`<button disabled title="${esc(metaStatusLabel)}">Cần kết nối lại API</button>`:canCollect?`<button data-collect-channel="${target.id}">Cập nhật số liệu</button>`:`<span class="muted">API analytics chưa được bật</span>`;
    return `<div class="status-row"><div><strong>${esc(target.platform)} · ${esc(target.name)}</strong><small class="muted">${rendered||"Chưa có số liệu hiện tại"}</small><small class="muted">${reportState}</small><small class="muted">${runState}</small><div>${sparkline(history)}</div></div><div class="actions">${action}</div></div>`;
  }).join(""):`<p class="muted">Chưa có metric kênh trong bộ lọc này. Hãy kết nối API cho YouTube hoặc Facebook Page để bắt đầu thu thập.</p>`);

  releaseRows=append?[...releaseRows,...releases]:releases;
  document.querySelector("#analyticsReleases").innerHTML=releaseRows.length?releaseRows.map(item=>{
    const reconcilable=["succeeded","unknown_result"].includes(item.status);
    const linked=Boolean(item.external_url||item.external_release_id);
    return `<div class="status-row"><div><strong>${esc(item.platform)} · ${esc(item.content_format)}</strong><small class="muted">${item.external_url?esc(item.external_url):"Chưa kết nối URL"}</small><small class="muted">${esc(item.status)} · ${esc(item.updated_at||item.created_at||"")}</small></div><div class="actions">${badge(item.status)}<button data-connect-release="${item.id}" ${reconcilable?"":"disabled"}>${item.external_url?"Đổi URL":"Kết nối"}</button><button data-collect-release="${item.id}" ${linked&&reconcilable?"":"disabled"}>Thu thập metrics</button><button data-view-metrics="${item.id}">Metrics</button></div></div>`;
  }).join(""):`<p class="muted">Chưa có release trong bộ lọc này.</p>`;
  const more=document.querySelector("#analyticsLoadMore");more.hidden=releases.length<PAGE_SIZE;more.disabled=releases.length===0;
  document.querySelectorAll("[data-connect-release]").forEach(button=>button.onclick=()=>connect(button.dataset.connectRelease));
  document.querySelectorAll("[data-collect-release]").forEach(button=>button.onclick=()=>collect(button.dataset.collectRelease,days));
  document.querySelectorAll("[data-view-metrics]").forEach(button=>button.onclick=()=>viewMetrics(button.dataset.viewMetrics));
  document.querySelectorAll("[data-collect-channel]").forEach(button=>button.onclick=()=>collectChannel(button.dataset.collectChannel,days));
}

async function connect(id){const url=prompt("URL bài đăng đúng nền tảng:","");if(!url)return;const note=prompt("Ghi chú đối soát:","Kết nối thủ công từ WebUI");if(!note)return;if(!confirm("Bạn xác nhận URL này thuộc đúng Page/channel đã chọn và đúng bài đăng cần đối soát?"))return;try{await api(`/publication-releases/${id}/connect`,{method:"PATCH",body:JSON.stringify({external_url:url,note,confirm_target_identity:true,confirm_post_identity:true})});toast("Đã kết nối release.");await refreshAnalytics();}catch(error){toast(error.message);}}
async function collect(id,days){try{const result=await api(`/publication-releases/${id}/collect-metrics?days=${days}`,{method:"POST"});toast(result.status==="succeeded"?`Đã thu thập số hiện tại${result.trend?` và xu hướng (${result.trend.status})`:""}.`:result.message);await refreshAnalytics();}catch(error){toast(error.message);}}
async function collectChannel(id,days){try{const result=await api(`/targets/${id}/collect-metrics?days=${days}`,{method:"POST"});toast(result.status==="succeeded"?`Đã cập nhật analytics kênh${result.trend?` (${result.trend.status})`:""}.`:result.message);await refreshAnalytics();}catch(error){toast(error.message);}}
async function viewMetrics(id){try{const result=await api(`/publication-releases/${id}/metrics`);const latest=result.fetch_runs?.[0];const hasMetrics=result.metrics.length>0;const warning=latest&&latest.status!=="succeeded"?`Lần cập nhật gần nhất: ${POST_RUN_LABELS[latest.status]||latest.status} (${latest.finished_at||latest.started_at}). ${hasMetrics?"Các metric bên dưới là số liệu đã lưu từ lần đọc trước.":"Chưa có snapshot metrics hợp lệ."}\n\n`:"";const metrics=hasMetrics?result.metrics.map(item=>`${item.metric_date} · ${item.metric_key}: ${format(item.value)} ${item.unit||""} · ${item.source}${item.period_start?` [${item.period_start} – ${item.period_end}]`:""}`).join("\n"):"Không hỗ trợ / chưa có metric.";alert(warning+metrics);}catch(error){toast(error.message);}}

async function saveRefreshSettings(){
  const current=refreshSettingsCache||{posts_per_run:10,channels_per_run:10};
  const body={enabled:document.querySelector("#analyticsAutoRefresh").checked,
    meta_enabled:document.querySelector("#analyticsMetaAutoRefresh").checked,
    interval_hours:Number(document.querySelector("#analyticsRefreshInterval").value),
    days:Number(document.querySelector("#analyticsDays").value),
    posts_per_run:current.posts_per_run||10,channels_per_run:current.channels_per_run||10};
  try{refreshSettingsCache=await api("/analytics/refresh-settings",{method:"PUT",body:JSON.stringify(body)});toast(body.enabled||body.meta_enabled?"Đã lưu cấu hình cập nhật analytics theo provider.":"Đã tắt cập nhật metrics tự động.");await refreshAnalytics();}
  catch(error){document.querySelector("#analyticsAutoRefresh").checked=Boolean(current.enabled);document.querySelector("#analyticsMetaAutoRefresh").checked=Boolean(current.meta_enabled);toast(error.message);}
}

export function initAnalytics(){
  document.querySelector("#refreshAnalytics").onclick=()=>refreshAnalytics();
  document.querySelector("#analyticsLoadMore").onclick=async()=>{releaseOffset+=PAGE_SIZE;try{await refreshAnalytics(true);}catch(error){releaseOffset=Math.max(0,releaseOffset-PAGE_SIZE);toast(error.message);}};
  for(const id of ["analyticsDays","analyticsPlatform","analyticsAccount","analyticsTarget"])document.querySelector(`#${id}`).onchange=()=>refreshAnalytics();
  document.querySelector("#analyticsAutoRefresh").onchange=saveRefreshSettings;
  document.querySelector("#analyticsMetaAutoRefresh").onchange=saveRefreshSettings;
  document.querySelector("#analyticsRefreshInterval").onchange=saveRefreshSettings;
}
