import {api,toast} from "./api.js?v=2.3.9";
import {refreshOverview} from "./overview.js?v=2.3.9";
import {initAccounts,refreshAccounts} from "./accounts.js?v=1.0.7";
import {initPosts,refreshPosts} from "./posts.js?v=2.3.9";
import {initAnalytics,refreshAnalytics} from "./analytics.js?v=2.3.9";
import {initAI,refreshBrands} from "./ai.js?v=2.3.9";
import {initCompose,refreshComposer} from "./compose.js?v=2.3.9";
import {initJobs,refreshJobs} from "./jobs.js?v=2.3.9";
import {initSettings,refreshProfileCleanupSettings} from "./settings.js?v=2.3.9";
import {initIntegrations,refreshIntegrations} from "./integrations.js?v=2.3.9";

const refreshers={overview:refreshOverview,ai:refreshBrands,posts:refreshPosts,content:refreshPosts,compose:refreshComposer,jobs:async()=>{await refreshAccounts();await refreshJobs();},analytics:refreshAnalytics,accounts:refreshAccounts,settings:async()=>{await Promise.all([refreshOverview(),refreshProfileCleanupSettings(),refreshIntegrations()]);}};
async function openTab(name){const targetTab=name==="content"||name==="media"?"posts":name;document.querySelectorAll(".tab").forEach(tab=>tab.classList.toggle("active",tab.id===`tab-${targetTab}`));document.querySelectorAll("#nav button").forEach(button=>button.classList.toggle("active",button.dataset.tab===targetTab));location.hash=targetTab;try{await refreshers[targetTab]?.();}catch(error){toast(error.message);}}
document.querySelectorAll("#nav button").forEach(button=>button.onclick=()=>openTab(button.dataset.tab));document.querySelectorAll("[data-go]").forEach(button=>button.onclick=()=>openTab(button.dataset.go));document.querySelectorAll("[data-close]").forEach(button=>button.onclick=()=>button.closest("dialog")?.close());
async function refreshShell(){try{const health=await api("/health");document.querySelector("#version").textContent=`v${health.version}`;const connection=document.querySelector("#connection");connection.className="connection ok";connection.textContent=`Backend ${health.version} · ${health.status}`;}catch(error){const connection=document.querySelector("#connection");connection.className="connection";connection.textContent="Mất kết nối backend";}}
[initAccounts,initPosts,initAnalytics,initAI,initCompose,initJobs,initSettings,initIntegrations].forEach(fn=>{try{fn?.();}catch(err){console.error("Init module error:",err);}});
refreshShell();openTab(location.hash.slice(1)||"overview");
setInterval(()=>{const active=document.querySelector(".tab.active")?.id;if(active==="tab-overview")refreshOverview().catch(()=>{});if(active==="tab-jobs")refreshJobs().catch(()=>{});if(active==="tab-posts")refreshPosts().catch(()=>{});},10000);

