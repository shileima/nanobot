import { invoke } from "@tauri-apps/api/core";
import { relaunch } from "@tauri-apps/plugin-process";
import { check } from "@tauri-apps/plugin-updater";

const webchatFrame = document.getElementById("webchatFrame");
const statusBadge = document.getElementById("statusBadge");
const updateBtn = document.getElementById("updateBtn");
const updateBanner = document.getElementById("updateBanner");
const updateVersion = document.getElementById("updateVersion");
const updateCurrent = document.getElementById("updateCurrent");
const doUpdateBtn = document.getElementById("doUpdateBtn");
const dismissUpdateBtn = document.getElementById("dismissUpdateBtn");
const appVersion = document.getElementById("appVersion");

// 始终显示桌面应用版本（来自 package.json），而非 Python 包版本
if (appVersion && typeof __APP_VERSION__ !== "undefined") {
  appVersion.textContent = `v${__APP_VERSION__}`;
}

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

// --- Tauri Updater ---

let dismissedVersion = null;
let pendingUpdate = null;

const FAST_INTERVAL = 10_000;
const FAST_PHASE_DURATION = 60_000;
const SLOW_INTERVAL = 30 * 60_000;
const appStartTime = Date.now();

async function checkForUpdate() {
  try {
    const update = await check();
    if (update?.available && update.version !== dismissedVersion) {
      pendingUpdate = update;
      showUpdateBanner(update.currentVersion, update.version);
    }
  } catch (e) {
    console.warn("Tauri update check failed:", e);
  }
}

function scheduleNextCheck() {
  const elapsed = Date.now() - appStartTime;
  const interval = elapsed < FAST_PHASE_DURATION ? FAST_INTERVAL : SLOW_INTERVAL;
  setTimeout(() => {
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

// Start update checking after 3s
setTimeout(() => {
  checkForUpdate();
  scheduleNextCheck();
}, 3000);

// --- Update actions ---

doUpdateBtn.addEventListener("click", async () => {
  if (!pendingUpdate) return;

  doUpdateBtn.disabled = true;
  doUpdateBtn.textContent = "更新中…";
  updateBanner.classList.add("updating");

  try {
    // 使用 Tauri 官方 updater 下载并安装整包（含 Rust + 前端 + Python）
    await pendingUpdate.downloadAndInstall((event) => {
      switch (event.event) {
        case "Started":
          doUpdateBtn.textContent = `下载中 0%`;
          break;
        case "Progress": {
          const { chunkLength, contentLength } = event.data;
          if (contentLength) {
            const pct = Math.round((chunkLength / contentLength) * 100);
            doUpdateBtn.textContent = `下载中 ${pct}%`;
          }
          break;
        }
        case "Finished":
          doUpdateBtn.textContent = "安装中…";
          break;
      }
    });

    // 下载安装成功，显示重启按钮
    updateBanner.style.background = "linear-gradient(90deg, #064e3b 0%, #022c22 100%)";
    updateBanner.style.borderBottomColor = "rgba(16, 185, 129, 0.3)";
    updateBanner.classList.remove("updating");

    const textEl = updateBanner.querySelector(".update-text");
    textEl.innerHTML = '<span class="update-icon" style="color:#10b981">✓</span> 更新成功，重启后生效';
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
  } catch (e) {
    doUpdateBtn.textContent = "重试";
    doUpdateBtn.disabled = false;
    updateBanner.classList.remove("updating");
    console.error("Update failed:", e);
    alert("更新失败：" + e);
  }
});

dismissUpdateBtn.addEventListener("click", () => {
  dismissedVersion = updateVersion.textContent.replace("v", "");
  hideUpdateBanner();
});

// --- Manual check button in header ---
updateBtn.addEventListener("click", async () => {
  updateBtn.disabled = true;
  updateBtn.textContent = "…";
  try {
    const update = await check();
    if (update?.available) {
      pendingUpdate = update;
      showUpdateBanner(update.currentVersion, update.version);
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
