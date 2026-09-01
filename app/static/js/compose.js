import {api, badge, esc, toast} from "./api.js";
import {store} from "./store.js";

const calendar = {view:"week", anchor:new Date(), releases:[], platforms:[]};
const pad = value => String(value).padStart(2,"0");
const dateKey = value => `${value.getFullYear()}-${pad(value.getMonth()+1)}-${pad(value.getDate())}`;
const localInput = value => { const d=new Date(value); return `${dateKey(d)}T${pad(d.getHours())}:${pad(d.getMinutes())}`; };
const addDays = (date, days) => { const result=new Date(date); result.setDate(result.getDate()+days); return result; };
const startOfDay = date => new Date(date.getFullYear(),date.getMonth(),date.getDate());

function getRange(){
  const anchor=startOfDay(calendar.anchor);
  if(calendar.view==="month"){
    const start=new Date(anchor.getFullYear(),anchor.getMonth(),1);
    return {start,end:new Date(anchor.getFullYear(),anchor.getMonth()+1,1)};
  }
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
  return `<button type="button" class="release-card" data-release="${esc(item.id)}" title="Đổi lịch an toàn"><time>${pad(when.getHours())}:${pad(when.getMinutes())}</time><strong>${esc(releaseTitle(item))}</strong>${badge(item.status)}</button>`;
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
  grid.querySelectorAll("[data-release]").forEach(button=>button.onclick=()=>reschedule(button.dataset.release));
}

async function refreshCalendar(){
  const {start,end}=getRange();
  const query=new URLSearchParams({start:start.toISOString(),end:end.toISOString(),limit:"1000"});
  const platform=document.querySelector("#calendarPlatform").value;
  const status=document.querySelector("#calendarStatus").value;
  if(platform)query.set("platform",platform); if(status)query.set("status",status);
  calendar.releases=await api(`/publication-releases?${query}`);
  store.releases=calendar.releases;
  renderCalendar();
}

async function reschedule(releaseId){
  const release=calendar.releases.find(item=>item.id===releaseId);
  const value=prompt("Ngày giờ mới (theo giờ máy):",localInput(release.scheduled_at||new Date()));
  if(!value)return;
  try{
    await api(`/publication-releases/${releaseId}/schedule`,{method:"PATCH",body:JSON.stringify({scheduled_at:new Date(value).toISOString(),timezone:Intl.DateTimeFormat().resolvedOptions().timeZone||"Asia/Bangkok"})});
    toast("Đã đổi lịch và ghi audit event."); await refreshCalendar();
  }catch(error){toast(error.message);}
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
  document.querySelector("#calendarPrev").onclick=async()=>{calendar.anchor=addDays(calendar.anchor,calendar.view==="month"?-30:-7);document.querySelector("#calendarAnchor").value=dateKey(calendar.anchor);await refreshCalendar();};
  document.querySelector("#calendarNext").onclick=async()=>{calendar.anchor=addDays(calendar.anchor,calendar.view==="month"?30:7);document.querySelector("#calendarAnchor").value=dateKey(calendar.anchor);await refreshCalendar();};
  document.querySelector("#calendarPlatform").onchange=refreshCalendar; document.querySelector("#calendarStatus").onchange=refreshCalendar;
  document.querySelector("#slotForm").onsubmit=async event=>{event.preventDefault();try{const target=document.querySelector("#slotTarget").value;await api(`/targets/${target}/posting-slots`,{method:"PUT",body:JSON.stringify({timezone:document.querySelector("#slotTimezone").value,slots:parseSlots()})});toast("Đã lưu posting slots.");}catch(error){toast(error.message);}};
  document.querySelector("#findNextSlot").onclick=async()=>{try{const result=await api(`/targets/${document.querySelector("#slotTarget").value}/next-slot`);document.querySelector("#scheduleAt").value=localInput(result.scheduled_at);toast("Đã chọn slot trống kế tiếp.");}catch(error){toast(error.message);}};
  document.querySelector("#scheduleForm").onsubmit=async event=>{event.preventDefault();const dry=document.querySelector("#dryRun").checked;if(!dry&&!confirm("Xác nhận tạo job ĐĂNG THẬT? Chỉ tiếp tục sau khi dry-run đã thành công."))return;const settings={};document.querySelectorAll("#platformSettings [data-setting]").forEach(field=>settings[field.dataset.setting]=field.type==="checkbox"?field.checked:field.value);try{const jobs=await api("/schedules",{method:"POST",body:JSON.stringify({content_id:document.querySelector("#scheduleContent").value,account_id:document.querySelector("#scheduleAccount").value,target_ids:[...document.querySelector("#scheduleTargets").selectedOptions].map(option=>option.value),content_format:document.querySelector("#scheduleFormat").value,platform_settings:settings,scheduled_at:document.querySelector("#scheduleAt").value?new Date(document.querySelector("#scheduleAt").value).toISOString():null,dry_run:dry,delay_seconds:Number(document.querySelector("#delaySeconds").value),random_delay_seconds:Number(document.querySelector("#randomDelay").value),missed_policy:document.querySelector("#missedPolicy").value})});toast(`Đã tạo ${jobs.length} job ${dry?"dry-run":"đăng thật"}`);await refreshCalendar();}catch(error){toast(error.message);}};
}
