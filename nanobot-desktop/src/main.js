import { invoke } from "@tauri-apps/api/core";
import { relaunch } from "@tauri-apps/plugin-process";

const webchatFrame = document.getElementById("webchatFrame");
const statusBadge = document.getElementById("statusBadge");
const updateBtn = document.getElementById("updateBtn");
const updateBanner = document.getElementById("updateBanner");
const updateVersion = document.getElementById("updateVersion");
const updateCurrent = document.getElementById("updateCurrent");
const doUpdateBtn = document.getElementById("doUpdateBtn");
const dismissUpdateBtn = document.getElementById("dismissUpdateBtn");
const appVersion = document.getElementById("appVersion");

// --- Connection status ---

async function checkStatus() {
  try {
    const ready = await invoke("check_workspace_ready");
    if (ready.success) {
      statusBadge.textContent = "已连接";
      statusBadge.classList.remove("error");
    } else {
      statusBadge.textContent = "已断开";
      statusBadge.classList.add("error");
    }
  } catch {
    statusBadge.textContent = "已断开";
    statusBadge.classList.add("error");
  }
}

webchatFrame.onload = () => {
  statusBadge.textContent = "已连接";
  statusBadge.classList.remove("error");
};

webchatFrame.onerror = () => {
  statusBadge.textContent = "已断开";
  statusBadge.classList.add("error");
};

setTimeout(checkStatus, 2000);
setInterval(checkStatus, 10000);

// --- Update detection with progressive polling ---
// First 1 minute: check every 10s (6 times)
// After that: check every 30 minutes

let dismissedVersion = null;
let updateCheckCount = 0;
let updateTimer = null;
const FAST_INTERVAL = 10_000;       // 10s
const FAST_PHASE_DURATION = 60_000; // 1 min
const SLOW_INTERVAL = 30 * 60_000;  // 30 min
const appStartTime = Date.now();

async function checkForUpdate() {
  updateCheckCount++;
  try {
    const info = await invoke("check_for_update");
    if (info.current && info.current !== "unknown") {
      appVersion.textContent = `v${info.current}`;
    }
    if (info.has_update && info.latest !== dismissedVersion) {
      showUpdateBanner(info.current, info.latest);
    }
  } catch (e) {
    console.warn("Update check failed:", e);
  }
}

function scheduleNextCheck() {
  const elapsed = Date.now() - appStartTime;
  const interval = elapsed < FAST_PHASE_DURATION ? FAST_INTERVAL : SLOW_INTERVAL;

  updateTimer = setTimeout(() => {
    checkForUpdate();
    scheduleNextCheck();
  }, interval);
}

function showUpdateBanner(current, latest) {
  updateVersion.textContent = `v${latest}`;
  updateCurrent.textContent = `（当前 v${current}）`;
  updateBanner.classList.remove("hidden");
}

function hideUpdateBanner() {
  updateBanner.classList.add("hidden");
}

// Start progressive update checking
setTimeout(() => {
  checkForUpdate();
  scheduleNextCheck();
}, 3000);

// --- Update actions ---

doUpdateBtn.addEventListener("click", async () => {
  doUpdateBtn.disabled = true;
  doUpdateBtn.textContent = "更新中…";
  updateBanner.classList.add("updating");

  try {
    const result = await invoke("perform_update");
    if (result.success) {
      updateBanner.style.background = "linear-gradient(90deg, #064e3b 0%, #022c22 100%)";
      updateBanner.style.borderBottomColor = "rgba(16, 185, 129, 0.3)";
      updateBanner.classList.remove("updating");

      const textEl = updateBanner.querySelector(".update-text");
      textEl.innerHTML = '<span class="update-icon" style="color:#10b981">✓</span> 更新成功，重启客户端即可生效';
      textEl.style.color = "#6ee7b7";

      doUpdateBtn.textContent = "立即重启";
      doUpdateBtn.classList.add("restart-btn");
      doUpdateBtn.disabled = false;
      doUpdateBtn.onclick = async () => {
        doUpdateBtn.disabled = true;
        doUpdateBtn.textContent = "重启中…";
        await relaunch();
      };

      dismissUpdateBtn.style.display = "none";
    } else {
      doUpdateBtn.textContent = "重试";
      doUpdateBtn.disabled = false;
      updateBanner.classList.remove("updating");
      alert("更新失败：" + result.message);
    }
  } catch (e) {
    doUpdateBtn.textContent = "重试";
    doUpdateBtn.disabled = false;
    updateBanner.classList.remove("updating");
    alert("更新失败：" + e);
  }
});

dismissUpdateBtn.addEventListener("click", () => {
  dismissedVersion = updateVersion.textContent.replace("v", "");
  hideUpdateBanner();
});

// Legacy manual update button in header
updateBtn.addEventListener("click", async () => {
  updateBtn.disabled = true;
  updateBtn.textContent = "…";
  try {
    const info = await invoke("check_for_update");
    if (info.has_update) {
      showUpdateBanner(info.current, info.latest);
    } else {
      statusBadge.textContent = "已是最新版";
      setTimeout(() => checkStatus(), 3000);
    }
  } catch (e) {
    alert("检查更新失败：" + e);
  } finally {
    updateBtn.disabled = false;
    updateBtn.textContent = "↻";
  }
});
