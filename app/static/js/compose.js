import {api, badge, esc, toast} from "./api.js";
import {store} from "./store.js";
import {openReleaseDetail} from "./jobs.js?v=1.0.42";

const calendar = {view:"week", anchor:new Date(), releases:[], platforms:[],rescheduleIds:[],selected:new Map()};
let batchReview = {signature:null, requestKey:null, ready:false};
const pad = value => String(value).padStart(2,"0");
const dateKey = value => `${value.getFullYear()}-${pad(value.getMonth()+1)}-${pad(value.getDate())}`;
const localInput = value => { const d=new Date(value); return `${dateKey(d)}T${pad(d.getHours())}:${pad(d.getMinutes())}`; };
const addDays = (date, days) => { const result=new Date(date); result.setDate(result.getDate()+days); return result; };
const startOfDay = date => new Date(date.getFullYear(),date.getMonth(),date.getDate());
function shiftCalendar(step){
  if(calendar.view==="month") calendar.anchor=new Date(calendar.anchor.getFullYear(),calendar.anchor.getMonth()+step,1);
  else calendar.anchor=addDays(calendar.anchor,step*(calendar.view==="day"?1:7));
  document.querySelector("#calendarAnchor").value=dateKey(calendar.anchor);
  return refreshCalendar();
}

function getRange(){
  const anchor=startOfDay(calendar.anchor);
  if(calendar.view==="month"){
    const start=new Date(anchor.getFullYear(),anchor.getMonth(),1);
    return {start,end:new Date(anchor.getFullYear(),anchor.getMonth()+1,1)};
  }
  if(calendar.view==="day") return {start:anchor,end:addDays(anchor,1)};
  if(calendar.view==="list") return {start:addDays(anchor,-30),end:addDays(anchor,91)};
  const monday=addDays(anchor,-((anchor.getDay()+6)%7));
  return {start:monday,end:addDays(monday,7)};
}

function releaseTitle(item){
  const target=store.targets.find(value=>value.id===item.target_id);
  const content=store.contents.find(value=>value.id===item.content_id);
  return `${content?.title||"Nội dung"} · ${target?.name||item.platform}`;
}

function releaseCard(item){
  const when=new Date(item.scheduled_at||item.created_at);
  return `<div class="release-card"><label class="release-select"><input type="checkbox" data-select-release="${esc(item.id)}" ${calendar.selected.has(item.id)?"checked":""}><span>Chọn</span></label><button type="button" class="release-card-detail" data-release="${esc(item.id)}" title="Mở chi tiết release"><time>${pad(when.getHours())}:${pad(when.getMinutes())}</time><strong>${esc(releaseTitle(item))}</strong>${badge(item.status)}</button><button type="button" class="release-card-reschedule" data-reschedule-release="${esc(item.id)}" title="Đổi lịch release">Đổi lịch</button></div>`;
}

function renderCalendar(){
  const {start,end}=getRange();
  document.querySelector("#calendarRange").textContent=`${start.toLocaleDateString("vi-VN")} – ${addDays(end,-1).toLocaleDateString("vi-VN")}`;
  const grouped=new Map();
  for(const release of calendar.releases){
    const key=dateKey(new Date(release.scheduled_at||release.created_at));
    grouped.set(key,[...(grouped.get(key)||[]),release]);
  }
  const grid=document.querySelector("#calendarGrid");
  if(calendar.view==="list"){
    grid.className="calendar-grid panel list-view";
    grid.innerHTML=calendar.releases.length?calendar.releases.map(item=>`<div class="calendar-list-row"><span>${new Date(item.scheduled_at||item.created_at).toLocaleString("vi-VN")}</span>${releaseCard(item)}</div>`).join(""):`<p class="muted">Chưa có release trong khoảng này.</p>`;
  }else{
    let first=start;
    let last=end;
    if(calendar.view==="month"){
      first=addDays(start,-((start.getDay()+6)%7));
      last=addDays(end,(7-((end.getDay()+6)%7))%7);
    }
    const cells=[];
    for(let day=new Date(first);day<last;day=addDays(day,1)){
      const key=dateKey(day),outside=day<start||day>=end;
      cells.push(`<div class="calendar-day ${outside?"outside":""}"><header><span>${day.toLocaleDateString("vi-VN",{weekday:"short"})}</span><b>${day.getDate()}</b></header><div>${(grouped.get(key)||[]).map(releaseCard).join("")}</div></div>`);
    }
    grid.className=`calendar-grid panel ${calendar.view}-view`;
    grid.innerHTML=cells.join("");
  }
  grid.querySelectorAll("[data-release]").forEach(button=>button.onclick=()=>openReleaseDetail(button.dataset.release).catch(error=>toast(error.message)));
  grid.querySelectorAll("[data-reschedule-release]").forEach(button=>button.onclick=()=>reschedule(button.dataset.rescheduleRelease));
  grid.querySelectorAll("[data-select-release]").forEach(input=>input.onchange=()=>{
    const release=calendar.releases.find(item=>item.id===input.dataset.selectRelease);
    if(input.checked&&release)calendar.selected.set(release.id,release);else calendar.selected.delete(input.dataset.selectRelease);
    document.querySelector("#calendarBulkReschedule").classList.toggle("hidden",calendar.selected.size<2);
  });
  document.querySelector("#calendarBulkReschedule").classList.toggle("hidden",calendar.selected.size<2);
  document.querySelector("#daySlotSuggestions").classList.toggle("hidden",calendar.view!=="day");
}

async function loadDaySlotSuggestions(){
  const panel=document.querySelector("#daySlotSuggestions");
  if(calendar.view!=="day"){panel.classList.add("hidden");return;}
  panel.classList.remove("hidden");
  const accountId=document.querySelector("#calendarAccount").value;
  const targetId=document.querySelector("#calendarTarget").value;
  const platform=document.querySelector("#calendarPlatform").value;
  const targets=store.targets.filter(item=>(!accountId||item.account_id===accountId)&&(!targetId||item.id===targetId)&&(!platform||item.platform===platform));
  panel.innerHTML="<strong>Slot gợi ý cho target trong ngày đã chọn</strong><p class=\"muted\">Đang kiểm tra; đây là gợi ý, slot chưa được giữ chỗ.</p>";
  const start=startOfDay(calendar.anchor);
  const after=new Date(start.getTime()-1).toISOString();
  const suggestions=[];
  for(let index=0;index<targets.length;index+=5){
    const batch=await Promise.all(targets.slice(index,index+5).map(async target=>{
      try{
        const result=await api(`/targets/${encodeURIComponent(target.id)}/next-slot?after=${encodeURIComponent(after)}`);
        const date=new Date(result.scheduled_at);
        return dateKey(date)===dateKey(calendar.anchor)?{target,date}:null;
      }catch{return null;}
    }));
    suggestions.push(...batch);
  }
  const rows=suggestions.filter(Boolean);
  panel.innerHTML=`<strong>Slot gợi ý cho target trong ngày đã chọn</strong>${rows.length?`<ul>${rows.map(item=>`<li>${esc(item.target.name)} · ${esc(item.target.platform)} — ${item.date.toLocaleTimeString("vi-VN",{hour:"2-digit",minute:"2-digit"})}</li>`).join("")}</ul>`:'<p class="muted">Không có slot cấu hình phù hợp trong ngày này.</p>'}<small class="muted">Gợi ý không giữ chỗ; giờ được hiển thị theo giờ máy.</small>`;
}

async function refreshCalendar(){
  const {start,end}=getRange();
  const query=new URLSearchParams({start:start.toISOString(),end:end.toISOString(),limit:"1000"});
  const platform=document.querySelector("#calendarPlatform").value;
  const status=document.querySelector("#calendarStatus").value;
  if(platform)query.set("platform",platform); if(status)query.set("status",status);
  const account=document.querySelector("#calendarAccount").value;
  const target=document.querySelector("#calendarTarget").value;
  if(account)query.set("account_id",account); if(target)query.set("target_id",target);
  calendar.releases=await api(`/publication-releases?${query}`);
  const visible=new Set(calendar.releases.map(item=>item.id));
  for(const id of calendar.selected.keys())if(!visible.has(id))calendar.selected.delete(id);
  store.releases=calendar.releases;
  renderCalendar();
  await loadDaySlotSuggestions();
}

async function reschedule(releaseId){
  const releases=releaseId?calendar.releases.filter(item=>item.id===releaseId):[...calendar.selected.values()];
  if(!releases.length||(!releaseId&&releases.length<2))return toast("Chọn ít nhất hai release đang hiển thị để đổi lịch nhóm.");
  calendar.rescheduleIds=releases.map(item=>item.id);
  const descriptions=releases.map(release=>{
    const account=store.accounts.find(item=>item.id===release.account_id);
    return `${releaseTitle(release)} · ${account?.name||"Account"} · ${release.scheduled_at?new Date(release.scheduled_at).toLocaleString("vi-VN"):"không có lịch"} · ${release.status}`;
  });
  document.querySelector("#calendarRescheduleSummary").textContent=`${releases.length} release đã chọn. Backend từ chối toàn bộ nếu bất kỳ mục nào không còn đổi lịch an toàn.\n${descriptions.join("\n")}`;
  document.querySelector("#calendarRescheduleAt").value=localInput(releases[0].scheduled_at||new Date());
  document.querySelector("#calendarRescheduleTimezone").value=Intl.DateTimeFormat().resolvedOptions().timeZone||"Asia/Bangkok";
  document.querySelector("#calendarRescheduleError").textContent="";
  document.querySelector("#calendarRescheduleDialog").showModal();
}

async function saveReschedule(event){
  event.preventDefault();
  const value=document.querySelector("#calendarRescheduleAt").value;
  if(!value)return;
  const parsed=new Date(value);
  if(Number.isNaN(parsed.getTime())||localInput(parsed)!==value){
    document.querySelector("#calendarRescheduleError").textContent="Thời điểm này không hợp lệ theo múi giờ của máy.";
    return;
  }
  const matches=[];
  for(let offset=-180;offset<=180;offset+=15){const candidate=new Date(parsed.getTime()+offset*60000);if(localInput(candidate)===value)matches.push(candidate.getTime());}
  if(new Set(matches).size>1){document.querySelector("#calendarRescheduleError").textContent="Giờ này bị lặp do đổi giờ mùa hè. Hãy chọn thời điểm rõ ràng khác.";return;}
  if(parsed.getTime()<Date.now()&&!confirm("Thời điểm đã qua. Tiếp tục sẽ áp dụng chính sách job bị lỡ đã lưu cho từng release. Bạn muốn tiếp tục?"))return;
  try{
    const timezone=document.querySelector("#calendarRescheduleTimezone").value;
    if(calendar.rescheduleIds.length>1){
      await api("/publication-releases/reschedule-bulk",{method:"POST",body:JSON.stringify({release_ids:calendar.rescheduleIds,scheduled_at:parsed.toISOString(),timezone})});
      for(const id of calendar.rescheduleIds)calendar.selected.delete(id);
    }else await api(`/publication-releases/${calendar.rescheduleIds[0]}/schedule`,{method:"PATCH",body:JSON.stringify({scheduled_at:parsed.toISOString(),timezone})});
    document.querySelector("#calendarRescheduleDialog").close();
    calendar.rescheduleIds=[];
    toast("Đã đổi lịch và ghi audit event."); await refreshCalendar();
  }catch(error){document.querySelector("#calendarRescheduleError").textContent=error.message;}
}

function selectedAccount(){return store.accounts.find(item=>item.id===document.querySelector("#scheduleAccount").value);}
function selectedPlatform(){return calendar.platforms.find(item=>item.id===selectedAccount()?.platform);}
function selectedFormat(){return selectedPlatform()?.format_schemas?.find(item=>item.id===document.querySelector("#scheduleFormat").value);}

function renderSettings(){
  const holder=document.querySelector("#platformSettings");
  holder.innerHTML=(selectedFormat()?.settings||[]).map(field=>{
    const required=field.required?" required":"";
    if(field.field_type==="select") return `<label>${esc(field.label)}<select data-setting="${esc(field.key)}"${required}>${field.options.map(option=>`<option value="${esc(option)}" ${option===field.default?"selected":""}>${esc(option)}</option>`).join("")}</select></label>`;
    if(field.field_type==="checkbox") return `<label class="check"><input type="checkbox" data-setting="${esc(field.key)}" ${field.default?"checked":""}><span>${esc(field.label)}</span></label>`;
    if(field.field_type==="textarea") return `<label>${esc(field.label)}<textarea data-setting="${esc(field.key)}"${required}></textarea></label>`;
    return `<label>${esc(field.label)}<input data-setting="${esc(field.key)}" value="${esc(field.default??"")}"${required}></label>`;
  }).join("");
  updatePreview();
}

function refreshFormats(){
  const platform=selectedPlatform();
  document.querySelector("#scheduleFormat").innerHTML=(platform?.format_schemas||[]).map(item=>`<option value="${esc(item.id)}">${esc(item.label)}</option>`).join("");
  renderSettings();
}

function refreshTargetOptions(){
  const account=selectedAccount();
  document.querySelector("#scheduleTargets").innerHTML=store.targets.filter(target=>target.account_id===account?.id).map(target=>`<option value="${target.id}">${esc(target.name)}</option>`).join("");
  refreshFormats();
}

function updatePreview(){
  const content=store.contents.find(item=>item.id===document.querySelector("#scheduleContent").value);
  const format=selectedFormat();
  if(!content){document.querySelector("#composerPreview").textContent="Chọn nội dung để xem preview.";return;}
  const variant=content.platform_variants?.[selectedAccount()?.platform]||{};
  const caption=variant.caption||content.caption||"";
  document.querySelector("#formatCounter").textContent=format?`${caption.length}/${format.max_caption_length} ký tự · media ${format.min_media}–${format.max_media}`:"";
  document.querySelector("#composerPreview").innerHTML=`<h3>${esc(content.title)}</h3><p>${esc(caption)}</p><small>${esc((variant.hashtags||content.hashtags||[]).join?.(" ")||variant.hashtags||content.hashtags||"")}</small>`;
}

async function loadSlots(){
  const targetId=document.querySelector("#slotTarget").value;
  if(!targetId)return;
  const slots=await api(`/targets/${targetId}/posting-slots`);
  document.querySelector("#slotTimezone").value=slots[0]?.timezone||Intl.DateTimeFormat().resolvedOptions().timeZone||"Asia/Bangkok";
  document.querySelector("#slotLines").value=slots.map(item=>`${item.weekday} ${pad(Math.floor(item.minute_of_day/60))}:${pad(item.minute_of_day%60)}`).join("\n");
}

function refreshSlotTargets(){
  document.querySelector("#slotTarget").innerHTML=store.targets.map(item=>`<option value="${item.id}">${esc(item.name)}</option>`).join("");
  loadSlots().catch(error=>toast(error.message));
}

function parseSlots(){
  return document.querySelector("#slotLines").value.split(/\r?\n/).map(line=>line.trim()).filter(Boolean).map(line=>{
    const match=line.match(/^([0-6])\s+([01]?\d|2[0-3]):([0-5]\d)$/);
    if(!match)throw new Error(`Slot không hợp lệ: ${line}`);
    return {weekday:Number(match[1]),minute_of_day:Number(match[2])*60+Number(match[3])};
  });
}

export async function refreshComposer(){
  const [contents,accounts,targets,platforms]=await Promise.all([api("/contents?limit=200"),api("/accounts"),api("/targets?enabled=true"),api("/platforms")]);
  Object.assign(store,{contents,accounts,targets,platforms}); calendar.platforms=platforms;
  document.querySelector("#calendarAccount").innerHTML='<option value="">Mọi tài khoản</option>'+accounts.map(item=>`<option value="${esc(item.id)}">${esc(item.name)} · ${esc(item.platform)}</option>`).join("");
  document.querySelector("#calendarTarget").innerHTML='<option value="">Mọi Page/kênh</option>'+targets.map(item=>`<option value="${esc(item.id)}">${esc(item.name)} · ${esc(item.platform)}</option>`).join("");
  document.querySelector("#scheduleContent").innerHTML=contents.map(item=>`<option value="${item.id}">${esc(item.title)} · ${item.approval_status}</option>`).join("");
  document.querySelector("#scheduleAccount").innerHTML=accounts.filter(item=>item.enabled).map(item=>`<option value="${item.id}">${esc(item.name)} · ${esc(item.platform)}</option>`).join("");
  refreshTargetOptions(); refreshSlotTargets(); updatePreview(); await refreshCalendar();
}

export function initCompose(){
  document.querySelector("#calendarAnchor").value=dateKey(calendar.anchor);
  document.querySelector("#scheduleAccount").onchange=refreshTargetOptions;
  document.querySelector("#scheduleContent").onchange=updatePreview;
  document.querySelector("#scheduleFormat").onchange=renderSettings;
  document.querySelector("#slotTarget").onchange=()=>loadSlots().catch(error=>toast(error.message));
  document.querySelector("#dryRun").onchange=()=>document.querySelector("#realWarning").classList.toggle("hidden",document.querySelector("#dryRun").checked);
  document.querySelectorAll("[data-calendar-view]").forEach(button=>button.onclick=async()=>{calendar.view=button.dataset.calendarView;document.querySelectorAll("[data-calendar-view]").forEach(item=>item.classList.toggle("active",item===button));await refreshCalendar();});
  document.querySelector("#calendarAnchor").onchange=async event=>{calendar.anchor=new Date(`${event.target.value}T12:00:00`);await refreshCalendar();};
  document.querySelector("#calendarToday").onclick=async()=>{calendar.anchor=new Date();document.querySelector("#calendarAnchor").value=dateKey(calendar.anchor);await refreshCalendar();};
  document.querySelector("#calendarPrev").onclick=()=>shiftCalendar(-1);
  document.querySelector("#calendarNext").onclick=()=>shiftCalendar(1);
  document.querySelector("#calendarPlatform").onchange=refreshCalendar; document.querySelector("#calendarStatus").onchange=refreshCalendar;
  document.querySelector("#calendarAccount").onchange=refreshCalendar; document.querySelector("#calendarTarget").onchange=refreshCalendar;
  document.querySelector("#calendarRescheduleForm").onsubmit=saveReschedule;
  document.querySelector("#calendarBulkReschedule").onclick=()=>reschedule(null);
  document.querySelector("#slotForm").onsubmit=async event=>{event.preventDefault();try{const target=document.querySelector("#slotTarget").value;await api(`/targets/${target}/posting-slots`,{method:"PUT",body:JSON.stringify({timezone:document.querySelector("#slotTimezone").value,slots:parseSlots()})});toast("Đã lưu posting slots.");}catch(error){toast(error.message);}};
  document.querySelector("#findNextSlot").onclick=async()=>{try{const result=await api(`/targets/${document.querySelector("#slotTarget").value}/next-slot`);document.querySelector("#scheduleAt").value=localInput(result.scheduled_at);toast("Đã chọn slot trống kế tiếp.");}catch(error){toast(error.message);}};
  document.querySelector("#scheduleForm").onsubmit=async event=>{
    event.preventDefault();
    const dry=document.querySelector("#dryRun").checked;
    if(!dry&&!confirm("Xác nhận tạo job ĐĂNG THẬT? Chỉ tiếp tục sau khi dry-run đã thành công."))return;
    const settings={};
    document.querySelectorAll("#platformSettings [data-setting]").forEach(field=>settings[field.dataset.setting]=field.type==="checkbox"?field.checked:field.value);
    const account=selectedAccount();
    const targets=[...document.querySelector("#scheduleTargets").selectedOptions].map(option=>option.value);
    const scheduled_at=new Date(document.querySelector("#scheduleAt").value).toISOString();
    const content_id=document.querySelector("#scheduleContent").value;
    const content_format=document.querySelector("#scheduleFormat").value;
    const missed_policy=document.querySelector("#missedPolicy").value;
    try{
      if(account?.platform==="facebook"){
        const signature=JSON.stringify([content_id,[...targets].sort(),scheduled_at,dry,missed_policy,content_format,settings,document.querySelector("#delaySeconds").value,document.querySelector("#randomDelay").value]);
        if(batchReview.signature!==signature){batchReview={signature,requestKey:globalThis.crypto?.randomUUID?.()||`${Date.now()}-${Math.random().toString(16).slice(2)}`,ready:false};}
        const body={content_id,target_ids:targets,scheduled_at,dry_run:dry,missed_policy,content_format,platform_settings:settings,request_key:batchReview.requestKey,delay_seconds:Number(document.querySelector("#delaySeconds").value),random_delay_seconds:Number(document.querySelector("#randomDelay").value)};
        if(!batchReview.ready){
          const result=await api("/schedules/batch/preflight",{method:"POST",body:JSON.stringify(body)});
          const preview=document.querySelector("#calendarBatchPreview");
          preview.innerHTML=`<h3>Kết quả kiểm tra từng Page</h3><ul class="status-list quick-schedule-preview">${(result.targets||[]).map(item=>`<li data-status="${esc(item.status)}"><strong>${esc(item.name)}</strong>${item.account_name?` · ${esc(item.account_name)}`:""}${item.platform?` · ${esc(item.platform)} ${esc(item.content_format||"")}`:""}<small>${item.status==="ready"?`${esc(item.transport)} · ${esc(new Date(item.scheduled_at).toLocaleString())}<br>${esc([item.caption,(item.hashtags||[]).join(" ")].filter(Boolean).join("\n")||"(caption trống)")}${item.media?.length?`<br>Media: ${esc(item.media.map(media=>media.name).join(", "))}`:""}`:esc(item.error||"Page không hợp lệ.")}</small></li>`).join("")}</ul><p>${result.ready?"Kiểm tra xong. Gửi lại để tạo lịch cho toàn bộ Page.":"Sửa lựa chọn rồi kiểm tra lại. Chưa có lịch nào được tạo."}</p>`;
          preview.classList.remove("hidden");
          batchReview.ready=Boolean(result.ready);
          document.querySelector('#scheduleForm button[type="submit"]').textContent=result.ready?`Tạo lịch cho ${targets.length} Page`:"Kiểm tra lại";
          return;
        }
        const jobs=await api("/schedules/batch",{method:"POST",body:JSON.stringify(body)});
        batchReview={signature:null,requestKey:null,ready:false};
        document.querySelector("#calendarBatchPreview").classList.add("hidden");
        document.querySelector('#scheduleForm button[type="submit"]').textContent="Lưu lịch";
        toast(`Đã tạo ${jobs.length} job ${dry?"dry-run":"đăng thật"}`);
      }else{
        const jobs=await api("/schedules",{method:"POST",body:JSON.stringify({content_id,account_id:document.querySelector("#scheduleAccount").value,target_ids:targets,content_format,platform_settings:settings,scheduled_at,dry_run:dry,delay_seconds:Number(document.querySelector("#delaySeconds").value),random_delay_seconds:Number(document.querySelector("#randomDelay").value),missed_policy})});
        toast(`Đã tạo ${jobs.length} job ${dry?"dry-run":"đăng thật"}`);
      }
      await refreshCalendar();
    }catch(error){toast(error.message);}
  };
}
