import {api,toast} from "./api.js?v=2.0.4";
import {refreshOverview} from "./overview.js?v=2.0.4";
import {initAccounts,refreshAccounts} from "./accounts.js?v=2.0.11";
import {initContent,refreshContent} from "./content.js?v=2.0.4";
import {initMedia,refreshMedia} from "./media.js?v=2.0.4";
import {initAnalytics,refreshAnalytics} from "./analytics.js?v=2.0.4";
import {initAI,refreshBrands} from "./ai.js?v=2.0.4";
import {initCompose,refreshComposer} from "./compose.js?v=2.0.4";
import {initJobs,refreshJobs} from "./jobs.js?v=2.0.6";
import {initSettings,refreshProfileCleanupSettings} from "./settings.js?v=2.0.6";

const refreshers={overview:refreshOverview,ai:refreshBrands,content:refreshContent,media:refreshMedia,compose:refreshComposer,jobs:async()=>{await refreshAccounts();await refreshJobs();},analytics:refreshAnalytics,accounts:refreshAccounts,settings:async()=>{await Promise.all([refreshOverview(),refreshProfileCleanupSettings()]);}};
async function openTab(name){document.querySelectorAll(".tab").forEach(tab=>tab.classList.toggle("active",tab.id===`tab-${name}`));document.querySelectorAll("#nav button").forEach(button=>button.classList.toggle("active",button.dataset.tab===name));location.hash=name;try{await refreshers[name]?.();}catch(error){toast(error.message);}}
document.querySelectorAll("#nav button").forEach(button=>button.onclick=()=>openTab(button.dataset.tab));document.querySelectorAll("[data-go]").forEach(button=>button.onclick=()=>openTab(button.dataset.go));document.querySelectorAll("[data-close]").forEach(button=>button.onclick=()=>button.closest("dialog").close());
async function refreshShell(){try{const health=await api("/health");document.querySelector("#version").textContent=`v${health.version}`;const connection=document.querySelector("#connection");connection.className="connection ok";connection.textContent=`Backend ${health.version} · ${health.status}`;}catch(error){const connection=document.querySelector("#connection");connection.className="connection";connection.textContent="Mất kết nối backend";}}
initAccounts();initContent();initMedia();initAnalytics();initAI();initCompose();initJobs();initSettings();refreshShell();openTab(location.hash.slice(1)||"overview");
setInterval(()=>{const active=document.querySelector(".tab.active")?.id;if(active==="tab-overview")refreshOverview().catch(()=>{});if(active==="tab-jobs")refreshJobs().catch(()=>{});},10000);
