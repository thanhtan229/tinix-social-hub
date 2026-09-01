import {api, badge, esc, toast} from "./api.js";
import {store} from "./store.js";

const retryable=new Set(["temporary_failure","permanent_failure","login_required","checkpoint"]);
let currentJob=null;

function selectedJobs(){return [...document.querySelectorAll("[data-job-select]:checked")].map(item=>item.value);}

async function refreshNotifications(){
  const items=await api("/notifications?unread_only=true&limit=20");
  document.querySelector("#notificationList").innerHTML=items.length?items.map(item=>`<button class="notification-row ${esc(item.severity)}" data-notification="${item.id}" data-entity="${item.entity_id||""}"><strong>${esc(item.title)}</strong><span>${esc(item.message)}</span><small>${new Date(item.created_at).toLocaleString("vi-VN")}</small></button>`).join(""):`<p class="muted">Không có cảnh báo mới.</p>`;
  document.querySelectorAll("[data-notification]").forEach(button=>button.onclick=async()=>{await api(`/notifications/${button.dataset.notification}/read`,{method:"POST"});if(button.dataset.entity)await showDetail(button.dataset.entity);await refreshNotifications();});
}

export async function refreshJobs(){
  const [jobs]=await Promise.all([api("/jobs?limit=100"),refreshNotifications()]);store.jobs=jobs;
  document.querySelector("#jobsTable").innerHTML=jobs.length?jobs.map(job=>`<tr><td>${retryable.has(job.status)&&!job.commit_reached_at?`<input type="checkbox" data-job-select value="${job.id}" aria-label="Chọn retry"> `:""}${esc(job.kind)}</td><td>${esc((store.accounts.find(account=>account.id===job.account_id)||{}).name||"—")}</td><td>${badge(job.status)}</td><td>${job.dry_run?'<span class="badge good">Dry-run</span>':'<span class="badge bad">Đăng thật</span>'}</td><td>${new Date(job.created_at).toLocaleString("vi-VN")}</td><td><button data-job-detail="${job.id}">Chi tiết</button>${retryable.has(job.status)&&!job.commit_reached_at?` <button data-job-retry="${job.id}">Retry</button>`:""}${["scheduled","queued","opening_browser","checking_login","uploading","publishing"].includes(job.status)?` <button class="danger" data-job-cancel="${job.id}">Hủy</button>`:""}</td></tr>`).join(""):'<tr><td colspan="6" class="muted">Chưa có job.</td></tr>';
  document.querySelectorAll("[data-job-cancel]").forEach(button=>button.onclick=async()=>{try{await api(`/jobs/${button.dataset.jobCancel}/cancel`,{method:"POST"});await refreshJobs();}catch(error){toast(error.message);}});
  document.querySelectorAll("[data-job-retry]").forEach(button=>button.onclick=async()=>{try{await api(`/jobs/${button.dataset.jobRetry}/retry`,{method:"POST"});toast("Đã đưa job vào queue.");await refreshJobs();}catch(error){toast(error.message);}});
  document.querySelectorAll("[data-job-detail]").forEach(button=>button.onclick=()=>showDetail(button.dataset.jobDetail));
}

async function showDetail(id){
  const job=await api(`/jobs/${id}`);currentJob=job;
  document.querySelector("#jobSummary").innerHTML=`<div class="release-summary"><div>${badge(job.status)} ${job.dry_run?'<span class="badge good">Dry-run</span>':'<span class="badge bad">Đăng thật</span>'}</div><p><strong>Commit point:</strong> ${job.commit_reached_at?new Date(job.commit_reached_at).toLocaleString("vi-VN"):"Chưa tới"}</p><p><strong>Lỗi:</strong> ${esc(job.error||"—")}</p>${job.result?.post_url?`<p><a href="${esc(job.result.post_url)}" target="_blank" rel="noreferrer">Mở bài đăng</a></p>`:""}</div>`;
  const attempts=new Map(job.attempt_history.map(item=>[item.attempt_number,item]));
  document.querySelector("#jobEvents").innerHTML=job.events.map(event=>`<div class="status-row"><span>${esc(event.event_type)}<small class="muted">${new Date(event.created_at).toLocaleString("vi-VN")}</small></span>${badge(event.to_status)}</div>`).join("")+`<p class="muted">${attempts.size} attempt(s)</p>`;
  document.querySelector("#jobArtifacts").innerHTML=job.artifacts.length?job.artifacts.map(item=>`<div class="status-row"><span>${esc(item.artifact_type)}</span><code>${esc(item.relative_path)}</code></div>`).join(""):`<p class="muted">Không có artifact.</p>`;
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
}
