---
name: playwright-automation
description: 使用 Playwright 生成并执行浏览器自动化脚本。适用于：网页登录、表单填写、数据抓取、UI 自动化测试、点击/输入/截图等任何需要控制浏览器的任务。核心原则：先观察分析页面状态，再智能决策操作步骤。
---

# Playwright 浏览器自动化

## 核心原则

**观察分析 → 智能决策 → 快速执行**。不盲目试选择器，不滥用固定等待。

## 性能铁律

| 规则 | 说明 |
|------|------|
| **不用 `slow_mo`** | 改用 Playwright 内置等待，按需等 |
| **不用固定等待** | 用 `wait_for_selector` / `wait_for_url` 替代 `wait_for_timeout` |
| **选择器最多 2-3 个** | 选最可能命中的，`timeout=3000`，不要 5-6 个盲试 |
| **仅关键节点截图** | 最多：加载后、操作完成、出错时，共 3 张 |
| **`goto` 必设 `timeout`** | 防止内网不通卡 30 秒 |
| **禁止 `input()`** | 脚本在子进程中执行，stdin 不可用，`input()` 会导致永久阻塞 |

## 浏览器关闭策略

**默认行为**：每一步执行后要延迟 3s，例如点击、输入内容后，执行完成后延迟 5 秒自动关闭浏览器。

**例外**：仅当用户明确说了「不关闭浏览器」「保持浏览器打开」等字样时，才跳过关闭。

```python
# ✅ 默认：自动关闭
finally:
    print("⏳ 5秒后自动关闭浏览器...")
    time.sleep(5)
    context.close()  # 或 browser.close()
    print("✅ 浏览器已关闭")

# ✅ 仅当用户明确要求保持打开时
finally:
    print("🔍 浏览器保持打开，脚本退出")
    # 不调用 close()，浏览器窗口保留

# ❌ 禁止：使用 input() 等待用户输入
finally:
    input("按回车关闭...")  # 子进程无 stdin，会永久阻塞！
```

## 登录态持久化（需要登录的网站必用）

`launch()` 每次都是全新浏览器。**需要登录的网站必须用 `launch_persistent_context`**：

```python
from playwright.sync_api import sync_playwright

PROFILE = "/Users/shilei/.nanobot/browser_profiles/site_name"

with sync_playwright() as p:
    context = p.chromium.launch_persistent_context(
        user_data_dir=PROFILE, headless=False,
    )
    page = context.pages[0] if context.pages else context.new_page()
    page.goto("https://example.com", timeout=15000)

    if "login" in page.url.lower():
        print("⚠️ 需要登录，请手动完成...")
        page.wait_for_url("**/home**", timeout=120000)
        print("✅ 登录完成，状态已保存")

    # 后续自动化...
    context.close()
```

**首次运行**手动扫码 → 之后自动复用 Cookie。Profile 按网站命名：
- `~/.nanobot/browser_profiles/sankuai`
- `~/.nanobot/browser_profiles/bigmodel`

---

## 脚本模板

```python
#!/usr/bin/env python3
from playwright.sync_api import sync_playwright

def run():
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=False)
        page = browser.new_page()

        try:
            page.goto("https://example.com", wait_until="domcontentloaded", timeout=15000)
            page.screenshot(path="/tmp/step1_loaded.png")

            # Playwright 自动等待元素可操作，无需手动 wait
            page.get_by_role("button", name="登录").click()
            page.get_by_label("账号").fill("user")
            page.get_by_label("密码").fill("pass")
            page.get_by_role("button", name="登录").click()

            page.wait_for_url("**/dashboard**", timeout=10000)
            page.screenshot(path="/tmp/step2_done.png")
            print("✅ 完成")

        except Exception as e:
            page.screenshot(path="/tmp/error.png")
            print(f"❌ 出错: {e}")
            raise
        finally:
            print("⏳ 5秒后自动关闭浏览器...")
            import time; time.sleep(5)
            browser.close()
            print("✅ 浏览器已关闭")

if __name__ == "__main__":
    run()
```

## 选择器优先级

1. `get_by_role("button", name="xxx")` — 最稳定
2. `get_by_label("xxx")` — 表单字段首选
3. `get_by_text("xxx")` — 按文本定位
4. `get_by_placeholder("xxx")` — 输入框
5. `locator("css")` — 最后手段

## 等待策略

Playwright 的 `click` / `fill` 等操作**自动等待元素可操作**，大多数情况无需手动等待。

```python
# ✅ 等待特定元素（页面结构变化时用）
page.wait_for_selector(".chat-list", timeout=5000)

# ✅ 等待 URL 跳转（登录/提交后）
page.wait_for_url("**/home**", timeout=10000)

# ✅ 等待网络空闲（SPA 首次加载）
page.goto(url, wait_until="networkidle", timeout=15000)

# ⚠️ 固定等待仅用于无法检测的场景（动画），且不超过 1 秒
page.wait_for_timeout(1000)

# ❌ 禁止：time.sleep()
# ❌ 禁止：无条件 wait_for_timeout(3000) 散布在各处
```

## 新窗口 / Tab 处理（必须掌握）

链接可能在当前 tab 跳转，也可能 `target="_blank"` 打开新 tab。**必须用 `click_and_follow` 统一处理**，不要直接 `click()` 后假定还在原 page 上。

```python
from playwright.sync_api import TimeoutError as PwTimeout

def click_and_follow(context, page, selector, timeout=5000):
    """点击链接，自动跟踪目标页面。新 tab → 切过去；原 tab → 留在原 page。"""
    try:
        with context.expect_page(timeout=timeout) as new_page_info:
            page.locator(selector).first.click()
        new_page = new_page_info.value
        new_page.wait_for_load_state("domcontentloaded")
        print(f"  ↗ 新 tab 打开: {new_page.url}")
        return new_page
    except PwTimeout:
        return page
```

**使用方式**：

```python
# 点击「钱管家」— 可能新 tab 也可能原 tab
page = click_and_follow(context, page, "text=钱管家")
# 之后所有操作都在返回的 page 上继续，无需关心是哪个 tab
page.locator("text=去报销").click()
```

**与容错选择器结合**：

```python
def try_click_and_follow(context, page, selectors: list[str], timeout=5000):
    """容错选择器 + 新 tab 感知。返回 (成功?, 目标page)。"""
    for sel in selectors:
        try:
            el = page.locator(sel).first
            if not el.is_visible(timeout=3000):
                continue
            try:
                with context.expect_page(timeout=timeout) as new_page_info:
                    el.click()
                new_page = new_page_info.value
                new_page.wait_for_load_state("domcontentloaded")
                print(f"  ↗ 新 tab: {new_page.url}")
                return True, new_page
            except PwTimeout:
                return True, page
        except Exception:
            continue
    return False, page
```

**关键规则**：
- 每次点击链接后，**必须用返回值更新 `page` 变量**
- 不要在点击后直接用旧 `page` 操作，可能内容已经在新 tab 上
- `context.pages` 可随时查看所有打开的 tab

## 容错选择器（最多 2-3 个，timeout=3000）

```python
def try_click(page, selectors: list[str]) -> bool:
    """简单点击（确定不会开新 tab 时用）。涉及链接跳转请用 try_click_and_follow。"""
    for sel in selectors:
        try:
            el = page.locator(sel).first
            if el.is_visible(timeout=3000):
                el.click()
                return True
        except Exception:
            continue
    return False

# ✅ 只放 2-3 个最可能命中的选择器
clicked = try_click(page, [
    "button:has-text('账号登录')",
    "[data-type='account']",
])

# ❌ 不要放 5-6 个盲猜选择器，每个失败都要等 timeout
```

## 截图规范

仅在关键节点截图，不要每步都截：

```python
page.screenshot(path="/tmp/step1_loaded.png")   # 页面加载后
page.screenshot(path="/tmp/step2_done.png")      # 操作完成
page.screenshot(path="/tmp/error.png")           # 出错时
```
