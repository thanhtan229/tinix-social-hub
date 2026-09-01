import {toast} from "./api.js";
import {refreshOverview} from "./overview.js";
import {initAccounts,refreshAccounts} from "./accounts.js";
import {initContent,refreshContent} from "./content.js";
import {initMedia,refreshMedia} from "./media.js";
import {initAI,refreshBrands} from "./ai.js";
import {initCompose,refreshComposer} from "./compose.js";
import {initJobs,refreshJobs} from "./jobs.js";
import {initSettings} from "./settings.js";

const refreshers={overview:refreshOverview,ai:refreshBrands,content:refreshContent,media:refreshMedia,compose:refreshComposer,jobs:async()=>{await refreshAccounts();await refreshJobs();},accounts:refreshAccounts,settings:refreshOverview};
async function openTab(name){document.querySelectorAll(".tab").forEach(tab=>tab.classList.toggle("active",tab.id===`tab-${name}`));document.querySelectorAll("#nav button").forEach(button=>button.classList.toggle("active",button.dataset.tab===name));location.hash=name;try{await refreshers[name]?.();}catch(error){toast(error.message);}}
document.querySelectorAll("#nav button").forEach(button=>button.onclick=()=>openTab(button.dataset.tab));document.querySelectorAll("[data-go]").forEach(button=>button.onclick=()=>openTab(button.dataset.go));document.querySelectorAll("[data-close]").forEach(button=>button.onclick=()=>button.closest("dialog").close());
initAccounts();initContent();initMedia();initAI();initCompose();initJobs();initSettings();openTab(location.hash.slice(1)||"overview");
setInterval(()=>{const active=document.querySelector(".tab.active")?.id;if(active==="tab-overview")refreshOverview().catch(()=>{});if(active==="tab-jobs")refreshJobs().catch(()=>{});},10000);
