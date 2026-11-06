import {api, badge, esc, STATUS, toast} from "./api.js";

const PAGE_SIZE=50;
const CHANNEL_RUN_LABELS={succeeded:"thành công",unavailable:"Page/bài không còn khả dụng hoặc đã gỡ quyền",needs_connection:"cần kiểm tra kết nối hoặc quyền",needs_scope:"cần cấp quyền Instagram Insights",rate_limited:"Provider đang giới hạn tần suất",retryable:"l\u1ed7i k\u1ebft n\u1ed1i t\u1ea1m th\u1eddi \u00b7 s\u1ebd th\u1eed l\u1ea1i",failed:"Provider từ chối yêu cầu",unsupported:"không hỗ trợ"};
const POST_RUN_LABELS={unavailable:"Bài không còn cho phép đọc",needs_connection:"cần kiểm tra kết nối hoặc quyền",needs_scope:"cần cấp quyền Instagram Insights",rate_limited:"Provider đang giới hạn tần suất",retryable:"l\u1ed7i k\u1ebft n\u1ed1i t\u1ea1m th\u1eddi \u00b7 s\u1ebd th\u1eed l\u1ea1i",failed:"lần đọc analytics thất bại",unsupported:"metric không được hỗ trợ",needs_reconciliation:"cần đối soát bài đăng"};
const POST_RUN_GUIDANCE={unavailable:"Meta kh\u00f4ng cung c\u1ea5p d\u1eef li\u1ec7u cho b\u00e0i n\u00e0y. Ki\u1ec3m tra b\u00e0i c\u00f2n truy c\u1eadp \u0111\u01b0\u1ee3c t\u1eeb Page \u0111\u00e3 li\u00ean k\u1ebft v\u00e0 Page binding c\u00f3 quy\u1ec1n \u0111\u1ecdc. M\u00e3 Graph 100 kh\u00f4ng ph\u00e2n bi\u1ec7t ch\u1eafc ch\u1eafn b\u00e0i kh\u00f4ng t\u1ed3n t\u1ea1i hay thi\u1ebfu quy\u1ec1n.",needs_connection:"K\u1ebft n\u1ed1i l\u1ea1i account/Page API r\u1ed3i th\u1eed l\u1ea5y metrics l\u1ea1i.",needs_scope:"C\u1ea5p quy\u1ec1n Insights c\u1ea7n thi\u1ebft cho k\u1ebft n\u1ed1i r\u1ed3i th\u1eed l\u1ea1i.",rate_limited:"Provider \u0111ang gi\u1edbi h\u1ea1n t\u1ea7n su\u1ea5t; ch\u1edd h\u1ebft th\u1eddi gian gi\u1edbi h\u1ea1n tr\u01b0\u1edbc khi th\u1eed l\u1ea1i.",retryable:"Kh\u00f4ng k\u1ebft n\u1ed1i \u0111\u01b0\u1ee3c Meta Graph API do l\u1ed7i m\u1ea1ng t\u1ea1m th\u1eddi. B\u1ea3n ghi s\u1ebd \u0111\u01b0\u1ee3c t\u1ef1 th\u1eed l\u1ea1i \u1edf chu k\u1ef3 analytics k\u1ebf ti\u1ebfp; kh\u00f4ng c\u1ea7n s\u1eeda quy\u1ec1n Page.",needs_reconciliation:"K\u1ebft n\u1ed1i release v\u1edbi URL ho\u1eb7c ID b\u00e0i \u0111\u0103ng \u0111\u00fang tr\u01b0\u1edbc khi l\u1ea5y metrics.",failed:"Ki\u1ec3m tra k\u1ebft n\u1ed1i v\u00e0 th\u1eed l\u1ea1i sau; snapshot h\u1ee3p l\u1ec7 tr\u01b0\u1edbc \u0111\u00f3 v\u1eabn \u0111\u01b0\u1ee3c gi\u1eef.",unsupported:"Provider kh\u00f4ng tr\u1ea3 metrics cho b\u00e0i ho\u1eb7c lo\u1ea1i n\u1ed9i dung n\u00e0y."};
const META_CONNECTION_LABELS={reauth_required:"Cần kết nối lại Meta API",scope_missing:"Meta API cần quyền bổ sung",revoked:"Quyền Meta API đã bị thu hồi",disconnected:"Meta API đã ngắt"};
const METRIC_LABELS={reach:"Lượt tiếp cận",impressions:"Lượt hiển thị",views:"Lượt xem",daily_views:"Lượt xem mỗi ngày",likes:"Lượt thích",comments:"Bình luận",saved:"Lượt lưu",shares:"Lượt chia sẻ",total_interactions:"Tổng tương tác",profile_views:"Lượt xem trang cá nhân",accounts_engaged:"Tài khoản đã tương tác"};
const SOURCE_LABELS={api_instagram_graph:"Instagram Graph API",api_meta_graph:"Meta Graph API",api_youtube_analytics_v2:"YouTube Analytics API v2"};
let releaseRows=[];
let releaseOffset=0;
let accountsCache=[];
let targetsCache=[];
let refreshSettingsCache=null;
let scheduledRunSyncInFlight=false;

function format(value){if(value===null||value===undefined||value==="")return "—";const numeric=Number(value);if(!Number.isFinite(numeric))return "—";return new Intl.NumberFormat("vi-VN",{maximumFractionDigits:1,notation:numeric>=10000?"compact":"standard"}).format(numeric);}
function metricLabel(key){return METRIC_LABELS[key]||key;}
function formatDateTime(value){if(!value)return "ch\u01b0a r\u00f5";const date=new Date(value);if(Number.isNaN(date.getTime()))return value;return new Intl.DateTimeFormat("vi-VN",{dateStyle:"medium",timeStyle:"short"}).format(date);}
function renderProviderRunSummary(providerRuns,lastRun){
  if(!providerRuns||typeof providerRuns!=="object")return lastRun?"<p class=\"muted\">Chi ti\u1ebft theo provider s\u1ebd c\u00f3 sau l\u01b0\u1ee3t ch\u1ea1y k\u1ebf ti\u1ebfp.</p>":"";
  const names={youtube:"YouTube",facebook:"Facebook",instagram:"Instagram",tracked_posts:"Bài Facebook đã theo dõi (Chrome)"};
  const statusNames={needs_scope:"thi\u1ebfu quy\u1ec1n",needs_connection:"c\u1ea7n k\u1ebft n\u1ed1i l\u1ea1i",needs_reconciliation:"c\u1ea7n \u0111\u1ed1i so\u00e1t",unsupported:"kh\u00f4ng h\u1ed7 tr\u1ee3",rate_limited:"b\u1ecb gi\u1edbi h\u1ea1n",retryable:"l\u1ed7i m\u1ea1ng \u00b7 t\u1ef1 th\u1eed l\u1ea1i",unavailable:"kh\u00f4ng c\u00f2n kh\u1ea3 d\u1ee5ng",failed:"l\u1ed7i provider"};
  return Object.entries(providerRuns).map(([key,run])=>{
    const attempted=Number(run.posts_attempted??0)+Number(run.channels_attempted??0);
    const timing=attempted?"K\u1ebft qu\u1ea3 thu th\u1eadp g\u1ea7n nh\u1ea5t":"Kh\u00f4ng c\u00f3 m\u1ee5c \u0111\u1ebfn h\u1ea1n";
    const details=Object.entries(run.status_counts||{}).filter(([status])=>!['succeeded','no_data'].includes(status)).map(([status,count])=>`${esc(statusNames[status]||status)}: ${Number(count)}`).join(" \u00b7 ");
    return `<div class="analytics-provider-run"><strong>${esc(names[key]||key)}</strong><span>${Number(run.posts_attempted??0)} b\u00e0i \u00b7 ${Number(run.channels_attempted??0)} k\u00eanh</span><span>${Number(run.succeeded??0)} th\u00e0nh c\u00f4ng \u00b7 ${Number(run.no_data??0)} ch\u01b0a c\u00f3 d\u1eef li\u1ec7u \u00b7 ${Number(run.needs_action??0)} c\u1ea7n x\u1eed l\u00fd \u00b7 ${Number(run.failed??0)} l\u1ed7i</span>${details?`<small>Chi ti\u1ebft: ${details}</small>`:""}<small>${timing} \u00b7 Ho\u00e0n t\u1ea5t: ${esc(formatDateTime(run.finished_at||run.started_at))}</small></div>`;
  }).join("");
}
function sourceLabel(source){return SOURCE_LABELS[source]||source;}
function csvCell(value){let text=String(value??"");if(/^[\s\u0000-\u001f]*[=+\-@]/.test(text))text=`'${text}`;return `"${text.replace(/"/g,'""')}"`;}
async function exportAnalyticsReleases(){
  const button=document.querySelector("#exportAnalyticsReleases"),status=document.querySelector("#analyticsExportStatus"),originalLabel=button.textContent;
  const filterControls=["#analyticsDays","#analyticsPlatform","#analyticsAccount","#analyticsTarget"].map(selector=>document.querySelector(selector)),filterDisabled=filterControls.map(control=>control.disabled);
  button.disabled=true;button.setAttribute("aria-busy","true");button.textContent="Đang tải CSV…";status.textContent="Đang chuẩn bị tải dữ liệu.";filterControls.forEach(control=>control.disabled=true);
  try{
    const params=releaseParamsForFilters(document.querySelector("#analyticsDays").value),rows=[];let offset=0,batchSize=1000;
    while(true){
      const pageParams=new URLSearchParams(params);pageParams.set("limit",String(batchSize));pageParams.set("offset",String(offset));pageParams.set("order","desc");
      const page=await api(`/publication-releases?${pageParams}`);rows.push(...page);offset+=page.length;
      status.textContent=`Đã tải ${rows.length} bài${page.length===batchSize?"; đang tải tiếp":"; đang tạo file"}.`;
      if(page.length<batchSize)break;
    }
    if(!rows.length){status.textContent="Không có bài phù hợp bộ lọc.";toast(status.textContent);return;}
    const csvRows=[["Release ID","Nền tảng","Định dạng","Trạng thái","URL bài đăng","Cập nhật"],...rows.map(item=>[item.id,item.platform,item.content_format,STATUS[item.status]||item.status,item.external_url||"",item.updated_at||item.created_at||""])];
    const csv="\uFEFF"+csvRows.map(row=>row.map(csvCell).join(",")).join("\r\n"),blob=new Blob([csv],{type:"text/csv;charset=utf-8"}),url=URL.createObjectURL(blob),link=document.createElement("a");
    link.href=url;link.download=`tinix-posts-${new Date().toISOString().slice(0,10)}.csv`;document.body.append(link);link.click();link.remove();setTimeout(()=>URL.revokeObjectURL(url),1000);status.textContent=`Đã xuất ${rows.length} bài theo bộ lọc hiện tại.`;toast(status.textContent);
  }catch(error){status.textContent=`Xuất CSV thất bại: ${error.message}`;toast(status.textContent);}
  finally{button.disabled=false;button.removeAttribute("aria-busy");button.textContent=originalLabel;filterControls.forEach((control,index)=>{control.disabled=filterDisabled[index];});}
}
function paramsForFilters(days){
  const params=new URLSearchParams({days:String(days)});
  for(const [id,key] of [["analyticsPlatform","platform"],["analyticsAccount","account_id"],["analyticsTarget","target_id"]]){
    const value=document.querySelector(`#${id}`).value;if(value)params.set(key,value);
  }
  return params;
}
function releaseParamsForFilters(days){
  const end=new Date(),start=new Date(end.getTime()-Number(days)*86400000),params=new URLSearchParams({start:start.toISOString(),end:end.toISOString()});
  for(const [id,key] of [["analyticsPlatform","platform"],["analyticsAccount","account_id"],["analyticsTarget","target_id"]]){
    const value=document.querySelector(`#${id}`).value;if(value)params.set(key,value);
  }
  return params;
}
function fillSelect(selector,items,firstLabel,valueKey,labelFor,selected){
  const select=document.querySelector(selector),options=[`<option value="">${firstLabel}</option>`,...items.map(item=>`<option value="${esc(item[valueKey])}">${esc(labelFor(item))}</option>`)];
  select.innerHTML=options.join("");if(selected&&items.some(item=>String(item[valueKey])===selected))select.value=selected;
}
function sparkline(rows,platform){
  const points=rows.filter(row=>(row.metric_key==="daily_views"||row.metric_key==="views")&&row.value!==null&&row.value!==undefined&&row.value!==""&&Number.isFinite(Number(row.value))).sort((a,b)=>a.metric_date.localeCompare(b.metric_date)).slice(-30);
  if(points.length<2)return `<small class="muted">${platform==="instagram"?"Chưa có chuỗi lượt xem theo ngày để vẽ xu hướng; số liệu Instagram đang hiển thị là snapshot.":"Chưa đủ dữ liệu xu hướng theo ngày"}</small>`;
  const values=points.map(row=>Number(row.value)),low=Math.min(...values),range=Math.max(1,Math.max(...values)-low);
  const coords=values.map((value,index)=>`${(index/(values.length-1)*100).toFixed(1)},${(32-(value-low)/range*28).toFixed(1)}`).join(" ");
  return `<svg viewBox="0 0 100 36" role="img" aria-label="Xu hướng lượt xem theo ngày" style="width:150px;height:44px"><polyline points="${coords}" fill="none" stroke="currentColor" stroke-width="2" vector-effect="non-scaling-stroke"/></svg>`;
}

export async function refreshAnalytics(append=false){
  const days=document.querySelector("#analyticsDays").value,filter=paramsForFilters(days);
  if(!append){releaseOffset=0;releaseRows=[];}
  const releaseParams=releaseParamsForFilters(days);releaseParams.set("limit",String(PAGE_SIZE));releaseParams.set("offset",String(releaseOffset));releaseParams.set("order","desc");
  const [summary,releases,accounts,targets,channelMetrics,channelHistory,channelSummary,channelRuns,connectedMetaTargetIds,metaTargetStatuses,refreshSettings,trackedPosts]=await Promise.all([
    api(`/analytics/summary?${filter}`),api(`/publication-releases?${releaseParams}`),api("/accounts"),api("/targets"),
    api(`/analytics/channels?${filter}`),api(`/analytics/channels/history?${filter}`),
    api(`/analytics/channels/summary?${filter}`),api(`/analytics/channels/runs?${filter}`),
    api(`/analytics/channels/connected-meta-targets?${filter}`),api(`/analytics/channels/meta-target-statuses?${filter}`),api("/analytics/refresh-settings"),api("/analytics/tracked-posts"),
  ]);
  refreshSettingsCache=refreshSettings;
  document.querySelector("#analyticsAutoRefresh").checked=Boolean(refreshSettings.enabled);
  document.querySelector("#analyticsMetaAutoRefresh").checked=Boolean(refreshSettings.meta_enabled);
  document.querySelector("#analyticsInstagramAutoRefresh").checked=Boolean(refreshSettings.instagram_enabled);
  document.querySelector("#analyticsTrackedPostsAutoRefresh").checked=Boolean(refreshSettings.tracked_posts_enabled);
  document.querySelector("#analyticsRefreshInterval").value=String(refreshSettings.interval_hours||24);
  const lastRun=refreshSettings.last_run;
  const autoProviders=[refreshSettings.enabled?"YouTube":null,refreshSettings.meta_enabled?"Facebook Page (Meta)":null,refreshSettings.instagram_enabled?"Instagram Insights":null,refreshSettings.tracked_posts_enabled?"bài Facebook đã theo dõi (Chrome)":null].filter(Boolean);
  const lastRunSummary=lastRun?(()=>{const posts=Number(lastRun.posts_attempted??0),channels=Number(lastRun.channels_attempted??0);return ` \u00b7 \u0111\u00e3 th\u1eed ${posts} b\u00e0i, ${channels} k\u00eanh${posts+channels===0?" \u00b7 kh\u00f4ng c\u00f3 m\u1ee5c n\u00e0o \u0111\u1ebfn h\u1ea1n":""} \u00b7 ${Number(lastRun.succeeded??0)} th\u00e0nh c\u00f4ng, ${Number(lastRun.no_data??0)} ch\u01b0a c\u00f3 d\u1eef li\u1ec7u, ${Number(lastRun.needs_action??0)} c\u1ea7n x\u1eed l\u00fd, ${Number(lastRun.failed??0)} l\u1ed7i`;})():"";
  const providerNames={youtube:"YouTube",facebook:"Facebook",instagram:"Instagram"};
  const providerRuns=refreshSettings.provider_last_runs||lastRun?.providers;
  const providerRunSummary=renderProviderRunSummary(providerRuns,lastRun);
  document.querySelector("#analyticsRefreshStatus").textContent=autoProviders.length
    ?`Tự động cập nhật ${autoProviders.join(" và ")} · tối đa ${refreshSettings.posts_per_run} bài và ${refreshSettings.channels_per_run} kênh mỗi lượt/provider · lần chạy gần nhất: ${lastRun?.finished_at?formatDateTime(lastRun.finished_at):"đang chờ"}${lastRunSummary} · lượt dự kiến tiếp theo: ${refreshSettings.next_run_at?formatDateTime(refreshSettings.next_run_at):"đang tính"} (giờ địa phương). Khi Tinix đang đóng, lịch không chạy.`
    :`Tự động cập nhật đang tắt. Không có lượt API nền nào chạy cho đến khi bật YouTube, Meta hoặc Instagram Insights.`;
  document.querySelector("#analyticsProviderRunSummary").innerHTML=providerRunSummary;
  accountsCache=accounts;targetsCache=targets;
  const selectedAccount=document.querySelector("#analyticsAccount").value,selectedTarget=document.querySelector("#analyticsTarget").value;
  const platform=document.querySelector("#analyticsPlatform").value;
  const filteredAccounts=accounts.filter(item=>!platform||item.platform===platform);
  fillSelect("#analyticsAccount",filteredAccounts,"Mọi account","id",item=>`${item.name} · ${item.platform}`,selectedAccount);
  const currentAccount=document.querySelector("#analyticsAccount").value;
  const filteredTargets=targets.filter(item=>(!platform||item.platform===platform)&&(!currentAccount||item.account_id===currentAccount));
  fillSelect("#analyticsTarget",filteredTargets,"Mọi kênh/Page","id",item=>`${item.name} · ${item.platform}`,selectedTarget);
  fillSelect("#trackedPostTarget",targets.filter(item=>item.platform==="facebook"&&(!currentAccount||item.account_id===currentAccount)),"Chọn Page Facebook","id",item=>item.name);
  renderTrackedPosts(trackedPosts.filter(item=>(!platform||platform==="facebook")&&(!currentAccount||item.account_id===currentAccount)&&(!document.querySelector("#analyticsTarget").value||item.target_id===document.querySelector("#analyticsTarget").value)));

  const metrics=Object.entries(summary.metrics);
  document.querySelector("#analyticsStats").innerHTML=summary.supported?metrics.map(([key,item])=>`<div class="stat"><span>${esc(metricLabel(key))} · ${days} ngày</span><strong>${format(item.current)}</strong><small class="muted">Kỳ trước ${format(item.previous)}</small></div>`).join(""):`<div class="stat unsupported"><span>Analytics bài đăng</span><strong>Chưa có dữ liệu</strong><small>Chỉ tính metric đã thu thập trong bộ lọc hiện tại.</small></div>`;

  const filteredChannelMetrics=channelMetrics.filter(item=>(!platform||item.platform===platform)&&(!currentAccount||item.account_id===currentAccount)&&(!document.querySelector("#analyticsTarget").value||item.target_id===document.querySelector("#analyticsTarget").value));
  const filteredHistory=channelHistory.filter(item=>(!platform||item.platform===platform)&&(!currentAccount||item.account_id===currentAccount)&&(!document.querySelector("#analyticsTarget").value||item.target_id===document.querySelector("#analyticsTarget").value));
  const filteredChannelRuns=channelRuns.filter(item=>(!platform||targets.find(target=>target.id===item.target_id)?.platform===platform)&&(!currentAccount||targets.find(target=>target.id===item.target_id)?.account_id===currentAccount)&&(!document.querySelector("#analyticsTarget").value||item.target_id===document.querySelector("#analyticsTarget").value));
  const channelTotals=Object.entries(channelSummary.metrics||{});
  const channelSummaryHtml=channelTotals.length?`<div class="stats">${channelTotals.map(([key,value])=>`<div class="stat"><span>Kênh · ${esc(metricLabel(key))} · ${days} ngày</span><strong>${format(value.current)}</strong><small class="muted">Kỳ trước ${format(value.previous)}</small></div>`).join("")}</div>`:"";
  const filteredConnectedMetaTargetIds=connectedMetaTargetIds.filter(targetId=>{
    const target=targets.find(item=>item.id===targetId);
    return target&&(!platform||target.platform===platform)&&(!currentAccount||target.account_id===currentAccount)&&(!document.querySelector("#analyticsTarget").value||target.id===document.querySelector("#analyticsTarget").value);
  });
  const metaTargetStatusById=new Map(metaTargetStatuses.map(item=>[item.target_id,item]));
  const accountNameById=new Map(accounts.map(item=>[item.id,item.name]));
  const normalizeTargetName=value=>String(value||"").normalize("NFKC").trim().replace(/\s+/g," ").toLocaleLowerCase("vi");
  const connectedMetaTargets=targets.filter(item=>item.platform==="facebook"&&metaTargetStatusById.get(item.id)?.connection_status==="connected"&&metaTargetStatusById.get(item.id)?.binding_status==="connected");
  const targetIds=[...new Set([...filteredChannelMetrics.map(item=>item.target_id),...filteredHistory.map(item=>item.target_id),...filteredChannelRuns.map(item=>item.target_id),...filteredConnectedMetaTargetIds])];
  document.querySelector("#channelAnalytics").innerHTML=channelSummaryHtml+(targetIds.length?targetIds.map(targetId=>{
    const target=targets.find(item=>item.id===targetId);if(!target)return "";
    const current=filteredChannelMetrics.filter(item=>item.target_id===targetId);
    const history=filteredHistory.filter(item=>item.target_id===targetId);
    const latestRun=filteredChannelRuns.find(item=>item.target_id===targetId);
    const metaStatus=target.platform==="facebook"?metaTargetStatusById.get(targetId):null;
    const metaApiReady=metaStatus?.connection_status==="connected"&&metaStatus?.binding_status==="connected";
    const sameNameCandidate=target.platform==="facebook"&&!metaApiReady?connectedMetaTargets.find(item=>item.account_id!==target.account_id&&normalizeTargetName(item.name)===normalizeTargetName(target.name)):null;
    const metaStatusLabel=!metaStatus?"Page chưa có binding Meta API cho account này":metaApiReady?"Meta API đang kết nối":metaStatus.binding_status==="disconnected"?"Page đã ngắt khỏi Meta API":META_CONNECTION_LABELS[metaStatus.connection_status]||"Meta API chưa sẵn sàng";
    const crossAccountHint=sameNameCandidate?`<small class="muted">Tên trùng, chưa xác nhận cùng Page. Mã target của ${esc(accountNameById.get(target.account_id)||target.account_id)}: ${esc(target.external_id||"chưa có")}; Meta Page của ${esc(accountNameById.get(sameNameCandidate.account_id)||sameNameCandidate.account_id)}: ${esc(sameNameCandidate.external_id||"chưa có")}. Target này chưa có binding Meta API cho account ${esc(accountNameById.get(target.account_id)||target.account_id)}.</small>`:"";
    const rendered=current.map(item=>`${esc(metricLabel(item.metric_key))}: ${format(item.value)} <small class="muted">${esc(item.metric_date)} · ${esc(sourceLabel(item.source))} · cập nhật ${esc(item.fetched_at||"")}</small>`).join(" · ");
    const reportState=history.length?`Báo cáo ngày đến ${esc(history.map(item=>item.metric_date).sort().at(-1))}`:target.platform==="instagram"?"Instagram: snapshot tại lần cập nhật gần nhất; chưa có lịch sử theo ngày":"Chưa có lịch sử theo ngày";
    const runState=(latestRun?`Lần cập nhật gần nhất: ${esc(CHANNEL_RUN_LABELS[latestRun.status]||latestRun.status)} · ${esc(latestRun.finished_at||latestRun.started_at||"")}${latestRun.status!=="succeeded"&&current.length?" · đang hiển thị snapshot đã lưu trước đó":""}`:"Chưa từng cập nhật analytics")+(target.platform==="facebook"?` · ${esc(metaStatusLabel)}`:"");
    const canCollect=["youtube","facebook","instagram"].includes(target.platform);
    const action=target.platform==="facebook"&&!metaApiReady?`<button disabled title="${esc(metaStatusLabel)}">Meta API chưa sẵn sàng</button>`:canCollect?`<button data-collect-channel="${target.id}">Cập nhật số liệu</button>`:`<span class="muted">API analytics chưa được bật</span>`;
    return `<div class="status-row"><div><strong>${esc(target.platform)} · ${esc(target.name)}</strong><small class="muted">${rendered||"Chưa có số liệu hiện tại"}</small><small class="muted">${reportState}</small><small class="muted">${runState}</small>${crossAccountHint}<div>${sparkline(history,target.platform)}</div></div><div class="actions">${action}</div></div>`;
  }).join(""):`<p class="muted">Chưa có metric kênh trong bộ lọc này. Hãy kết nối API cho YouTube, Facebook Page hoặc Instagram chuyên nghiệp để bắt đầu thu thập.</p>`);

  releaseRows=append?[...releaseRows,...releases]:releases;
  document.querySelector("#analyticsReleases").innerHTML=releaseRows.length?releaseRows.map(item=>{
    const reconcilable=["succeeded","unknown_result"].includes(item.status);
    const linked=Boolean(item.external_url||item.external_release_id);
    return `<div class="status-row"><div><strong>${esc(item.platform)} · ${esc(item.content_format)}</strong><small class="muted">${item.external_url?esc(item.external_url):"Chưa kết nối URL"}</small><small class="muted">Được cập nhật ${item.updated_at||item.created_at?formatDateTime(item.updated_at||item.created_at):"Chưa có thời gian"}</small></div><div class="actions">${badge(item.status)}<button data-connect-release="${item.id}" ${reconcilable?"":"disabled"}>${item.external_url?"Đổi URL":"Kết nối"}</button><button data-collect-release="${item.id}" ${linked&&reconcilable?"":"disabled"}>Thu thập metrics (API)</button><button data-collect-release-chrome="${item.id}" title="Mở URL bằng phiên Chrome của account và đọc số liệu đang hiển thị" ${item.external_url&&reconcilable?"":"disabled"}>Thu qua Chrome</button><button data-view-metrics="${item.id}">Metrics</button></div></div>`;
  }).join(""):`<p class="muted">Chưa có release trong bộ lọc này.</p>`;
  const more=document.querySelector("#analyticsLoadMore");more.hidden=releases.length<PAGE_SIZE;more.disabled=releases.length===0;
  document.querySelectorAll("[data-connect-release]").forEach(button=>button.onclick=()=>connect(button.dataset.connectRelease));
  document.querySelectorAll("[data-collect-release]").forEach(button=>button.onclick=()=>collect(button.dataset.collectRelease,days));
  document.querySelectorAll("[data-collect-release-chrome]").forEach(button=>button.onclick=()=>collect(button.dataset.collectReleaseChrome,days,"chrome"));
  document.querySelectorAll("[data-view-metrics]").forEach(button=>button.onclick=()=>viewMetrics(button.dataset.viewMetrics));
  document.querySelectorAll("[data-collect-channel]").forEach(button=>button.onclick=()=>collectChannel(button.dataset.collectChannel,days));
  document.querySelectorAll("[data-collect-tracked-post]").forEach(button=>button.onclick=()=>collectTrackedPost(button.dataset.collectTrackedPost));
  document.querySelectorAll("[data-view-tracked-post]").forEach(button=>button.onclick=()=>viewTrackedPost(button.dataset.viewTrackedPost));
  document.querySelectorAll("[data-remove-tracked-post]").forEach(button=>button.onclick=()=>removeTrackedPost(button.dataset.removeTrackedPost));
}

export async function refreshAnalyticsAfterScheduledRun(){
  if(scheduledRunSyncInFlight||document.visibilityState!=="visible")return;
  scheduledRunSyncInFlight=true;
  try{
    const settings=await api("/analytics/refresh-settings");
    const latestFinishedAt=settings.last_run?.finished_at||null;
    if(refreshSettingsCache&&latestFinishedAt&&latestFinishedAt!==refreshSettingsCache.last_run?.finished_at){
      await refreshAnalytics();
    }else if(!refreshSettingsCache){
      refreshSettingsCache=settings;
    }
  }catch{}
  finally{scheduledRunSyncInFlight=false;}
}

function renderTrackedPosts(items){
  document.querySelector("#trackedPosts").innerHTML=items.length?items.map(item=>{
    const metricValues=(item.metrics||[]).slice(0,3).map(metric=>`${esc(metricLabel(metric.metric_key))}: ${format(metric.value)}`).join(" · ");
    const run=item.latest_run,unsupported=run?.status==="unsupported";
    const metrics=metricValues
      ? `${unsupported?"Số liệu đã lưu trước đây · ":""}${metricValues}`
      : unsupported?"Facebook không cung cấp metrics cho bài này; dữ liệu trống không có nghĩa là 0.":"Chưa có metrics";
    const runStatus=unsupported?"Facebook không hỗ trợ metrics bài này":run?.status==="succeeded"?"Đã thu thập metrics":run?.status||"Chưa lấy số liệu";
    const runText=run?`Lần lấy gần nhất: ${esc(runStatus)} · ${esc(formatDateTime(run.finished_at||run.started_at))}${run.message?` · ${esc(run.message)}`:""}`:"Chưa lấy số liệu";
    return `<div class="status-row"><div><strong>Facebook · ${esc(item.target_name)}${item.title?` · ${esc(item.title)}`:""}</strong><a href="${esc(item.external_url)}" target="_blank" rel="noopener noreferrer">${esc(item.external_url)}</a><small class="muted">${metrics}</small><small class="muted">${runText}</small></div><div class="actions"><button data-collect-tracked-post="${esc(item.id)}">Thu qua Chrome</button><button data-view-tracked-post="${esc(item.id)}">Metrics</button><button data-remove-tracked-post="${esc(item.id)}">Bỏ theo dõi</button></div></div>`;
  }).join(""):`<p class="muted">Chưa có bài Facebook bên ngoài Tinix được theo dõi.</p>`;
}

async function collectTrackedPost(id){try{const result=await api(`/analytics/tracked-posts/${id}/collect`,{method:"POST"});toast(result.status==="succeeded"?"Đã lưu metrics cho bài Facebook.":result.message||"Facebook hiện không hiển thị metrics hỗ trợ.");await refreshAnalytics();}catch(error){toast(error.message);}}
async function viewTrackedPost(id){try{const result=await api(`/analytics/tracked-posts/${id}/metrics`),latest=result.fetch_runs?.[0];const text=[latest?`Lần lấy gần nhất: ${latest.status} · ${formatDateTime(latest.finished_at||latest.started_at)}${latest.message?` · ${latest.message}`:""}`:"Chưa lấy số liệu",...(result.metrics||[]).map(item=>`${item.metric_date} · ${metricLabel(item.metric_key)}: ${format(item.value)} · ${item.source}`)].join("\n");document.querySelector("#analyticsMetricsContent").textContent=text;document.querySelector("#analyticsMetricsDialog").showModal();document.querySelector("#analyticsMetricsContent").focus();}catch(error){toast(error.message);}}
async function removeTrackedPost(id){if(!confirm("Bỏ bài này khỏi danh sách theo dõi? Metrics đã lưu của mục này cũng sẽ bị xóa."))return;try{await api(`/analytics/tracked-posts/${id}`,{method:"DELETE"});await refreshAnalytics();}catch(error){toast(error.message);}}
async function submitTrackedPost(event){event.preventDefault();const form=event.currentTarget,status=document.querySelector("#trackedPostFormStatus");if(!form.reportValidity())return;status.textContent="Đang thêm bài vào danh sách theo dõi…";try{await api("/analytics/tracked-posts",{method:"POST",body:JSON.stringify({target_id:document.querySelector("#trackedPostTarget").value,external_url:document.querySelector("#trackedPostUrl").value.trim(),title:document.querySelector("#trackedPostTitle").value.trim(),confirm_target_identity:document.querySelector("#trackedPostConfirmTarget").checked,confirm_post_identity:document.querySelector("#trackedPostConfirmPost").checked})});form.reset();document.querySelector("#trackedPostDialog").close();status.textContent="";toast("Đã thêm bài Facebook vào mục theo dõi riêng.");await refreshAnalytics();}catch(error){status.textContent=error.message;}}

async function connect(id){const url=prompt("URL bài đăng đúng nền tảng:","");if(!url)return;const note=prompt("Ghi chú đối soát:","Kết nối thủ công từ WebUI");if(!note)return;if(!confirm("Bạn xác nhận URL này thuộc đúng Page/channel đã chọn và đúng bài đăng cần đối soát?"))return;try{await api(`/publication-releases/${id}/connect`,{method:"PATCH",body:JSON.stringify({external_url:url,note,confirm_target_identity:true,confirm_post_identity:true})});toast("Đã kết nối release.");await refreshAnalytics();}catch(error){toast(error.message);}}
async function collect(id,days,method="api"){try{const result=await api(`/publication-releases/${id}/collect-metrics?days=${days}&method=${method}`,{method:"POST"});toast(result.status==="succeeded"?`Đã thu thập số hiện tại bằng ${method==="chrome"?"Chrome":"API"}${result.trend?` và xu hướng (${result.trend.status})`:""}.`:result.message);await refreshAnalytics();}catch(error){toast(error.message);}}
async function collectChannel(id,days){try{const result=await api(`/targets/${id}/collect-metrics?days=${days}`,{method:"POST"});toast(result.status==="succeeded"?`Đã cập nhật analytics kênh${result.trend?` (${result.trend.status})`:""}.`:result.message);await refreshAnalytics();}catch(error){toast(error.message);}}
async function viewMetrics(id){try{const result=await api(`/publication-releases/${id}/metrics`);const latest=result.fetch_runs?.[0];const hasMetrics=result.metrics.length>0;let diagnostic="";if(latest?.message){try{const detail=JSON.parse(latest.message);if(detail&&typeof detail==="object"){diagnostic=[detail.provider_message,detail.graph_code?`Graph ${detail.graph_code}${detail.graph_subcode?`/${detail.graph_subcode}`:""}`:"",detail.fbtrace_id?`Trace ${detail.fbtrace_id}`:""].filter(Boolean).join(" | ");}}catch{diagnostic=latest.message;}}const guidance=latest?POST_RUN_GUIDANCE[latest.status]:"";const warning=latest&&latest.status!=="succeeded"?`Lần cập nhật gần nhất: ${POST_RUN_LABELS[latest.status]||latest.status} (${formatDateTime(latest.finished_at||latest.started_at)} \u00b7 gi\u1edd \u0111\u1ecba ph\u01b0\u01a1ng). ${hasMetrics?"Các metric bên dưới là số liệu đã lưu từ lần đọc trước.":"Chưa có snapshot metrics hợp lệ."}${guidance?`\nH\u01b0\u1edbng x\u1eed l\u00fd: ${guidance}`:""}${diagnostic?`\nChi ti\u1ebft t\u1eeb Meta: ${diagnostic}`:""}\n\n`:"";const freshness=latest?.status==="succeeded"?`C\u1eadp nh\u1eadt g\u1ea7n nh\u1ea5t: ${formatDateTime(latest.finished_at||latest.started_at)} (gi\u1edd \u0111\u1ecba ph\u01b0\u01a1ng).\n\n`:"";const metrics=hasMetrics?result.metrics.map(item=>`${item.metric_date} · ${metricLabel(item.metric_key)}: ${format(item.value)} ${item.unit||""} · ${sourceLabel(item.source)}${item.period_start?` [${item.period_start} – ${item.period_end}]`:""}`).join("\n"):"Chưa có metric khả dụng cho bài này.";document.querySelector("#analyticsMetricsContent").textContent=warning+freshness+metrics;document.querySelector("#analyticsMetricsDialog").showModal();document.querySelector("#analyticsMetricsContent").focus();}catch(error){toast(error.message);}}

async function saveRefreshSettings(){
  const current=refreshSettingsCache||{posts_per_run:10,channels_per_run:10};
  const body={enabled:document.querySelector("#analyticsAutoRefresh").checked,
    meta_enabled:document.querySelector("#analyticsMetaAutoRefresh").checked,
    instagram_enabled:document.querySelector("#analyticsInstagramAutoRefresh").checked,
    tracked_posts_enabled:document.querySelector("#analyticsTrackedPostsAutoRefresh").checked,
    interval_hours:Number(document.querySelector("#analyticsRefreshInterval").value),
    days:Number(document.querySelector("#analyticsDays").value),
    posts_per_run:current.posts_per_run||10,channels_per_run:current.channels_per_run||10};
  try{refreshSettingsCache=await api("/analytics/refresh-settings",{method:"PUT",body:JSON.stringify(body)});toast(body.enabled||body.meta_enabled||body.instagram_enabled||body.tracked_posts_enabled?"Đã lưu cấu hình cập nhật analytics theo provider.":"Đã tắt cập nhật metrics tự động.");await refreshAnalytics();}
  catch(error){document.querySelector("#analyticsAutoRefresh").checked=Boolean(current.enabled);document.querySelector("#analyticsMetaAutoRefresh").checked=Boolean(current.meta_enabled);document.querySelector("#analyticsInstagramAutoRefresh").checked=Boolean(current.instagram_enabled);document.querySelector("#analyticsTrackedPostsAutoRefresh").checked=Boolean(current.tracked_posts_enabled);toast(error.message);}
}

export function initAnalytics(){
  document.querySelector("#exportAnalyticsReleases").onclick=exportAnalyticsReleases;
  document.querySelector("#addTrackedPost").onclick=()=>{document.querySelector("#trackedPostForm").reset();document.querySelector("#trackedPostFormStatus").textContent="";document.querySelector("#trackedPostDialog").showModal();};
  document.querySelector("#cancelTrackedPost").onclick=()=>document.querySelector("#trackedPostDialog").close();
  document.querySelector("#trackedPostForm").addEventListener("submit",submitTrackedPost);
  document.querySelector("#copyAnalyticsMetrics").onclick=async()=>{const content=document.querySelector("#analyticsMetricsContent").textContent;if(!navigator.clipboard?.writeText){toast("Clipboard kh\\u00f4ng kh\\u1ea3 d\\u1ee5ng trong phi\\u00ean n\\u00e0y.");return;}try{await navigator.clipboard.writeText(content);toast("\\u0110\\u00e3 sao ch\\u00e9p n\\u1ed9i dung Metrics.");}catch{toast("Kh\\u00f4ng th\\u1ec3 sao ch\\u00e9p Metrics t\\u1eeb tr\\u00ecnh duy\\u1ec7t.");}};
  document.querySelector("#refreshAnalytics").onclick=()=>refreshAnalytics();
  document.querySelector("#analyticsLoadMore").onclick=async()=>{releaseOffset+=PAGE_SIZE;try{await refreshAnalytics(true);}catch(error){releaseOffset=Math.max(0,releaseOffset-PAGE_SIZE);toast(error.message);}};
  for(const id of ["analyticsDays","analyticsPlatform","analyticsAccount","analyticsTarget"])document.querySelector(`#${id}`).onchange=()=>refreshAnalytics();
  document.querySelector("#analyticsAutoRefresh").onchange=saveRefreshSettings;
  document.querySelector("#analyticsMetaAutoRefresh").onchange=saveRefreshSettings;
  document.querySelector("#analyticsInstagramAutoRefresh").onchange=saveRefreshSettings;
  document.querySelector("#analyticsTrackedPostsAutoRefresh").onchange=saveRefreshSettings;
  document.querySelector("#analyticsRefreshInterval").onchange=saveRefreshSettings;
}
