# nanobot Desktop

基于 Tauri 的 nanobot 桌面客户端，将 Web Chat 嵌入本地应用，自动管理 nanobot 服务。

## 功能

- **Web Chat 前端**：嵌入 http://localhost:17798 作为主界面
- **自动启动 nanobot**：启动客户端时自动运行 `nanobot gateway`，包含 cron、heartbeat 等完整服务
- **关闭时清理**：退出客户端时自动终止所有 nanobot 进程
- **nanobot 更新**：通过界面按钮执行 `nanobot update`（pip install -U nanobot-ai）
- **工作区初始化**：首次运行自动执行 `nanobot onboard`，并将内置技能拷贝到 `~/.nanobot/workspace/skills`
- **多会话支持**：Web Chat 支持多会话切换、删除、历史记录持久化
- **日志**：客户端日志 `~/.nanobot/logs/client.log`，网关日志 `~/.nanobot/logs/gateway.log`

## 环境要求

- [Rust](https://rustup.rs/)
- [Node.js](https://nodejs.org/) >= 18
- [nanobot](https://github.com/HKUDS/nanobot)：`pip install nanobot-ai`

## 开发

```bash
# 在 nanobot 项目根目录
cd nanobot-desktop
pnpm install
pnpm run tauri dev
```

## 打包

```bash
pnpm run tauri build
```

产物在 `src-tauri/target/release/bundle/`。

## 工作区目录

客户端初始化后，`~/.nanobot/workspace/` 结构：

- `skills/`：技能（从 nanobot 内置拷贝，webchat 可调用）
- `scripts/`：Agent 生成的自动化脚本（.py, .sh）
- `out/`：Agent 生成的其他输出文件
- `sessions/`：会话历史（JSONL）

## 自动更新（Tauri 应用）

若要启用 Tauri 应用自身的自动更新，需配置更新服务端。详见 [Tauri Updater](https://v2.tauri.app/plugin/updater)。

当前版本通过「更新」按钮更新的是 nanobot（Python 包），而非 Tauri 应用本身。
