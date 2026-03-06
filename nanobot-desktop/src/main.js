import { invoke } from "@tauri-apps/api/core";

const webchatFrame = document.getElementById("webchatFrame");
const statusBadge = document.getElementById("statusBadge");
const updateBtn = document.getElementById("updateBtn");

async function checkStatus() {
  try {
    const ready = await invoke("check_workspace_ready");
    if (ready.success) {
      statusBadge.textContent = "已连接";
      statusBadge.classList.remove("error");
      webchatFrame.onload = () => {
        statusBadge.textContent = "已连接";
        statusBadge.classList.remove("error");
      };
      webchatFrame.onerror = () => {
        statusBadge.textContent = "已断开";
        statusBadge.classList.add("error");
      };
    } else {
      statusBadge.textContent = "已断开";
      statusBadge.classList.add("error");
    }
  } catch (e) {
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

updateBtn.addEventListener("click", async () => {
  updateBtn.disabled = true;
  updateBtn.textContent = "…";
  try {
    const result = await invoke("update_nanobot");
    if (result.success) {
      alert("更新成功！请重启客户端以使更新生效。");
    } else {
      alert("更新失败：" + result.message);
    }
  } catch (e) {
    alert("更新失败：" + e);
  } finally {
    updateBtn.disabled = false;
    updateBtn.textContent = "↻";
  }
});
