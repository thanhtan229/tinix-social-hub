import {api, badge, esc, toast} from "./api.js";
import {store} from "./store.js";

const retryable=new Set(["temporary_failure","permanent_failure","login_required","checkpoint"]);
const activeHistory=new Set(["scheduled","queued","opening_browser","checking_login","uploading","publishing","verifying","running","retry_wait"]);
let currentJob=null;
let cleanupPreview=null;

function selectedJobs(){return [...document.querySelectorAll("[data-job-select]:checked")].map(item=>item.value);}

async function refreshNotifications(){
  const items=await api("/notifications?unread_only=true&limit=20");
  document.querySelector("#notificationList").innerHTML=items.length?items.map(item=>`<button class="notification-row ${esc(item.severity)}" data-notification="${item.id}" data-entity="${item.entity_id||""}"><strong>${esc(item.title)}</strong><span>${esc(item.message)}</span><small>${new Date(item.created_at).toLocaleString("vi-VN")}</small></button>`).join(""):`<p class="muted">Không có cảnh báo mới.</p>`;
  document.querySelectorAll("[data-notification]").forEach(button=>button.onclick=async()=>{await api(`/notifications/${button.dataset.notification}/read`,{method:"POST"});if(button.dataset.entity)await showDetail(button.dataset.entity);await refreshNotifications();});
}

export async function refreshJobs(){
  const [jobs]=await Promise.all([api("/jobs?limit=100"),refreshNotifications()]);store.jobs=jobs;
  document.querySelector("#jobsTable").innerHTML=jobs.length?jobs.map(job=>`<tr><td>${!activeHistory.has(job.status)?`<input type="checkbox" data-job-select value="${job.id}" aria-label="Chọn tác vụ"> `:""}${esc(job.kind)}</td><td>${esc((store.accounts.find(account=>account.id===job.account_id)||{}).name||"—")}</td><td>${badge(job.status)}</td><td>${job.dry_run?'<span class="badge good">Dry-run</span>':'<span class="badge bad">Đăng thật</span>'}</td><td>${new Date(job.created_at).toLocaleString("vi-VN")}</td><td><button data-job-detail="${job.id}">Chi tiết</button>${job.status==="succeeded"?` <button data-job-open="${job.id}" title="${job.result?.post_url?"Mở bài đăng":"Mở Page chứa bài đăng"}">Mở</button>`:""}${retryable.has(job.status)&&!job.commit_reached_at?` <button data-job-retry="${job.id}">Retry</button>`:""}${["scheduled","queued","opening_browser","checking_login","uploading","publishing"].includes(job.status)?` <button class="danger" data-job-cancel="${job.id}">Hủy</button>`:""}</td></tr>`).join(""):'<tr><td colspan="6" class="muted">Chưa có job.</td></tr>';
  document.querySelector("#selectAllJobs").checked=false;
  document.querySelectorAll("[data-job-cancel]").forEach(button=>button.onclick=async()=>{try{await api(`/jobs/${button.dataset.jobCancel}/cancel`,{method:"POST"});await refreshJobs();}catch(error){toast(error.message);}});
  document.querySelectorAll("[data-job-retry]").forEach(button=>button.onclick=async()=>{try{await api(`/jobs/${button.dataset.jobRetry}/retry`,{method:"POST"});toast("Đã đưa job vào queue.");await refreshJobs();}catch(error){toast(error.message);}});
  document.querySelectorAll("[data-job-detail]").forEach(button=>button.onclick=()=>showDetail(button.dataset.jobDetail));
  document.querySelectorAll("[data-job-open]").forEach(button=>button.onclick=()=>openPublishedJob(button.dataset.jobOpen));
  document.querySelectorAll("[data-job-select]").forEach(item=>item.onchange=()=>{document.querySelector("#selectAllJobs").checked=false;invalidateCleanupPreview();});
}

function formatBytes(value){
  if(!value)return "0 B";
  const units=["B","KB","MB","GB"];let size=value,index=0;
  while(size>=1024&&index<units.length-1){size/=1024;index++;}
  return `${size.toFixed(index?1:0)} ${units[index]}`;
}

function invalidateCleanupPreview(){
  cleanupPreview=null;
  document.querySelector("#executeHistoryCleanup").disabled=true;
  document.querySelector("#historyCleanupPreview").className="cleanup-preview muted";
  document.querySelector("#historyCleanupPreview").textContent="Phạm vi đã thay đổi. Bấm Xem trước để kiểm tra lại.";
}

function historyCleanupPayload(){
  const range=document.querySelector("#historyRange").value;
  const payload={mode:"older_than",older_than_days:null,from_date:null,to_date:null,status_filter:document.querySelector("#historyStatus").value,job_ids:[],candidate_ids:[],delete_artifacts:document.querySelector("#historyDeleteArtifacts").checked,preview:true,confirm:false};
  if(["7","30","90"].includes(range))payload.older_than_days=Number(range);
  else if(range==="custom"){
    payload.mode="custom";
    const from=document.querySelector("#historyFrom").value,to=document.querySelector("#historyTo").value;
    if(!from||!to)throw new Error("Hãy chọn đầy đủ ngày bắt đầu và kết thúc.");
    payload.from_date=new Date(`${from}T00:00:00`).toISOString();
    payload.to_date=new Date(`${to}T23:59:59.999`).toISOString();
  }else if(range==="selected"){
    payload.mode="selected";payload.job_ids=selectedJobs();
    if(!payload.job_ids.length)throw new Error("Hãy chọn ít nhất một tác vụ trong bảng.");
  }else payload.mode="all";
  return payload;
}

function updateHistoryRange(){
  const custom=document.querySelector("#historyRange").value==="custom";
  document.querySelector("#historyFromWrap").classList.toggle("hidden",!custom);
  document.querySelector("#historyToWrap").classList.toggle("hidden",!custom);
  invalidateCleanupPreview();
}

async function previewHistoryCleanup(){
  try{
    const request=historyCleanupPayload();
    const result=await api("/jobs/history/cleanup",{method:"POST",body:JSON.stringify(request)});
    cleanupPreview={request,result};
    const blocked=result.blocked_active?` ${result.blocked_active} tác vụ đang hoạt động được bảo vệ.`:"";
    document.querySelector("#historyCleanupPreview").className="cleanup-preview";
    document.querySelector("#historyCleanupPreview").innerHTML=`<strong>Sẽ xóa ${result.count} tác vụ</strong><span>${result.artifact_count} tệp kỹ thuật · ${formatBytes(result.artifact_bytes)}.${blocked}</span>`;
    const execute=document.querySelector("#executeHistoryCleanup");
    execute.disabled=!result.count;
    execute.textContent=result.count?`Xóa ${result.count} mục`:"Không có mục để xóa";
  }catch(error){toast(error.message);}
}

async function executeHistoryCleanup(){
  if(!cleanupPreview)return toast("Hãy xem trước phạm vi trước khi xóa.");
  const payload={...cleanupPreview.request,preview:false,confirm:true,candidate_ids:cleanupPreview.result.candidate_ids};
  try{
    const result=await api("/jobs/history/cleanup",{method:"POST",body:JSON.stringify(payload)});
    document.querySelector("#historyCleanupDialog").close();
    toast(`Đã xóa ${result.deleted} tác vụ và ${result.removed_artifacts} tệp kỹ thuật (${formatBytes(result.removed_bytes)}).`);
    cleanupPreview=null;await refreshJobs();
  }catch(error){toast(error.message);}
}

async function openPublishedJob(id){
  const job=store.jobs.find(item=>item.id===id);
  if(!job)return toast("Không tìm thấy job đã đăng.");
  const postUrl=job.result?.post_url;
  if(postUrl){window.open(postUrl,"_blank","noopener,noreferrer");return;}
  if(!job.target_id)return toast("Bài đăng chưa có URL để mở.");
  try{await api(`/targets/${job.target_id}/chrome/open`,{method:"POST"});toast("Đã mở Page chứa bài đăng trong Chrome.");}
  catch(error){toast(error.message);}
}

async function showDetail(id){
  const job=await api(`/jobs/${id}`);currentJob=job;
  const release=job.release||{};
  const verification=release.verification_status==="verified"?"Đã xác minh":release.verification_status==="rejected"?"Không xác minh được":release.verification_status==="pending"?"Chưa đối soát":"—";
  document.querySelector("#jobSummary").innerHTML=`<div class="release-summary"><div>${badge(job.status)} ${job.dry_run?'<span class="badge good">Dry-run</span>':'<span class="badge bad">Đăng thật</span>'}</div><p><strong>Commit point:</strong> ${job.commit_reached_at?new Date(job.commit_reached_at).toLocaleString("vi-VN"):"Chưa tới"}</p><p><strong>Xác minh:</strong> ${verification}${release.verification_method?` (${esc(release.verification_method)})`:""}</p><p><strong>Lỗi:</strong> ${esc(job.error||"—")}</p>${job.result?.post_url?`<p><a href="${esc(job.result.post_url)}" target="_blank" rel="noreferrer">Mở bài đăng</a></p>`:""}</div>`;
  const attempts=new Map(job.attempt_history.map(item=>[item.attempt_number,item]));
  document.querySelector("#jobEvents").innerHTML=job.events.map(event=>`<div class="status-row"><span>${esc(event.event_type)}<small class="muted">${new Date(event.created_at).toLocaleString("vi-VN")}</small></span>${badge(event.to_status)}</div>`).join("")+`<p class="muted">${attempts.size} attempt(s)</p>`;
  document.querySelector("#jobArtifacts").innerHTML=job.artifacts.length?job.artifacts.map(item=>`<div class="status-row"><span>${esc(item.artifact_type)}</span><a href="/api/jobs/${encodeURIComponent(job.id)}/artifacts/${encodeURIComponent(item.id)}/file" target="_blank" rel="noreferrer">${esc(item.relative_path)}</a></div>`).join(""):`<p class="muted">Không có artifact.</p>`;
  document.querySelector("#jobFinalize").classList.toggle("hidden",!["unknown_result","verifying"].includes(job.status));
  document.querySelector("#jobDialog").showModal();
}

async function bulkRetry(preview){
  const ids=selectedJobs();if(!ids.length){toast("Hãy chọn ít nhất một job retry an toàn.");return;}
  try{const result=await api("/jobs/retry-bulk",{method:"POST",body:JSON.stringify({job_ids:ids,preview})});document.querySelector("#retryPreview").textContent=`${result.count} job hợp lệ; ${result.blocked.length} job bị chặn.${preview?" Chưa thay đổi dữ liệu.":" Đã đưa vào queue."}`;if(!preview)await refreshJobs();}catch(error){toast(error.message);}
}

async function finalize(succeeded){
  const note=document.querySelector("#finalizeNote").value.trim();if(!note){toast("Cần ghi chú xác minh.");return;}
  try{await api(`/jobs/${currentJob.id}/finalize`,{method:"POST",body:JSON.stringify({succeeded,note,post_url:document.querySelector("#finalizeUrl").value.trim()||null})});document.querySelector("#jobDialog").close();toast("Đã finalize kết quả thủ công.");await refreshJobs();}catch(error){toast(error.message);}
}

export function initJobs(){
  document.querySelector("#refreshJobs").onclick=refreshJobs;
  document.querySelector("#previewRetry").onclick=()=>bulkRetry(true);
  document.querySelector("#executeRetry").onclick=()=>bulkRetry(false);
  document.querySelector("#readAllNotifications").onclick=async()=>{await api("/notifications/read-all",{method:"POST"});await refreshNotifications();};
  document.querySelector("#finalizeSuccess").onclick=()=>finalize(true);
  document.querySelector("#finalizeFailed").onclick=()=>finalize(false);
  document.querySelector("#cleanupJobs").onclick=()=>{cleanupPreview=null;document.querySelector("#historyCleanupPreview").textContent="Chọn phạm vi rồi bấm Xem trước.";document.querySelector("#executeHistoryCleanup").disabled=true;document.querySelector("#historyCleanupDialog").showModal();};
  document.querySelector("#historyRange").onchange=updateHistoryRange;
  document.querySelector("#historyStatus").onchange=invalidateCleanupPreview;
  document.querySelector("#historyDeleteArtifacts").onchange=invalidateCleanupPreview;
  document.querySelector("#historyFrom").onchange=invalidateCleanupPreview;
  document.querySelector("#historyTo").onchange=invalidateCleanupPreview;
  document.querySelector("#previewHistoryCleanup").onclick=previewHistoryCleanup;
  document.querySelector("#executeHistoryCleanup").onclick=executeHistoryCleanup;
  document.querySelector("#selectAllJobs").onchange=event=>{document.querySelectorAll("[data-job-select]").forEach(item=>item.checked=event.target.checked);invalidateCleanupPreview();};
}
