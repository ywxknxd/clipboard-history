# 剪贴板历史 实施方案

版本：v1（2026-11-08）    对应：SPEC.md v2

## 总体设计

```
D:\剪贴板历史\
├── 启动.bat          双击就开（用 pythonw，不弹黑框）
├── main.py           入口：把下面几块拼起来，跑轮询
├── store.py          数据：历史 + 常用语，全部 SQL 操作集中在这
├── clipboard.py      读写剪贴板（ctypes 调 Win32，不装任何包）
├── ui.py             窗口：搜索框 + 两个页签（常用语 / 最近记录）
├── tray.py           托盘图标和右键菜单
├── data.db           运行时自动生成，别提交、别手动改
├── README.md         怎么用、怎么关、怎么备份
└── docs/spec/        SPEC.md / IMPL.md
```

**分层原则**：`store.py` 只管数据，`clipboard.py` 只管系统接口，`ui.py` 只管画和点，
`main.py` 只做粘合。这样哪块坏了替换哪块，不影响其它。

**关键约束**：tkinter 只能在**主线程**操作；`pystray` 的菜单回调在**别的线程**。
两者之间只能用「队列 + `root.after` 轮询」通信，不能直接调 —— 这是本项目最容易出错的地方。

---

## T1 验证 pystray 能在 Python 3.14 上跑（先做，失败就换方案）

**涉及文件**：`spike_tray.py`（验证完删除）

**步骤**

1. 装包
   ```
   D:\pyhj\python.exe -m pip install pystray
   ```
   验证：`python -c "import pystray; print(pystray.__version__)"` 有版本号

2. 写最小托盘：`pystray.Icon` + 一张 64×64 的图（Pillow 画个方块）+ 两个菜单项（打开 / 退出）

3. 起 `icon.run()`，观察右下角是否出现图标、右键是否有菜单、点退出是否真的退出

**验收**：托盘图标真实出现，菜单能点，退出后进程消失（`tasklist` 里没有）

**如果失败**（图标不出现 / 报 `_tkinter` 冲突 / 3.14 不兼容）：
切换到 **ctypes 手写托盘**方案：`Shell_NotifyIconW` + 隐藏窗口 + `RegisterClassW`，
代码约 +100 行。此时新开一个任务 T1b，重写 `tray.py` 的实现方式，其它任务不受影响。

**回滚**：删 `spike_tray.py`；如需卸包 `pip uninstall pystray`

---

## T2 存储层 `store.py`

**涉及文件**：`store.py`（新建）

**表结构**（`data.db`，首次运行自动建）

```sql
CREATE TABLE IF NOT EXISTS history (
  id         INTEGER PRIMARY KEY AUTOINCREMENT,
  content    TEXT    NOT NULL,
  hash       TEXT    NOT NULL UNIQUE,   -- sha256(content)
  created_at INTEGER NOT NULL,          -- unix 秒
  updated_at INTEGER NOT NULL           -- 最后一次被复制的时间
);
CREATE INDEX IF NOT EXISTS idx_hist_updated ON history(updated_at DESC);

CREATE TABLE IF NOT EXISTS phrases (
  id         INTEGER PRIMARY KEY AUTOINCREMENT,
  title      TEXT    NOT NULL,
  content    TEXT    NOT NULL,
  created_at INTEGER NOT NULL,
  updated_at INTEGER NOT NULL
);
```

**对外函数**（全部返回简单类型，别抛异常给 UI）

| 函数 | 作用 | 要点 |
|---|---|---|
| `init_db()` | 建表建索引 | 幂等，每次启动都调 |
| `add_history(text)` | 记一条 | `INSERT ... ON CONFLICT(hash) DO UPDATE SET updated_at=?`；**返回 True 表示是新内容** |
| `list_history(keyword=None, limit=300)` | 列表 | 按 `updated_at DESC`；keyword 走 `LIKE %kw%` |
| `delete_history(id)` | 删一条 | |
| `clear_history()` | 清空历史 | **不动常用语** |
| `purge_expired(days=7)` | 删过期 | `DELETE WHERE updated_at < now - days*86400`；返回删除条数 |
| `add_phrase(title, content)` | 加常用语 | |
| `list_phrases(keyword=None)` | 常用语列表 | 按 `created_at ASC` |
| `update_phrase(id, title, content)` | 改 | |
| `delete_phrase(id)` | 删 | |

**关键决策**

- 过期用 `updated_at` 判断：**7 天没再复制过才删**，反复在用的内容不会被清掉
- 去重用 `hash` 唯一索引：同一段复制 5 次，库里只有 1 行，`updated_at` 刷新、位置置顶
- 单条超过 10 万字符直接拒绝（返回 False），不写库
- 空字符串/纯空白不记录

**验收**：写个临时脚本跑一遍 —— 插 3 条、重复插 1 条、查列表、按关键字搜、删 1 条、把一条时间改成 8 天前再 `purge_expired()` 看是否只剩该留的。

---

## T3 剪贴板读写 `clipboard.py`

**涉及文件**：`clipboard.py`（新建）

**对外函数**

| 函数 | 作用 |
|---|---|
| `get_text() -> str` | 读当前剪贴板文字，读不到返回 `""` |
| `set_text(s)` | 写入剪贴板 |

**实现要点（ctypes）**

- 读：`OpenClipboard(None)` → `GetClipboardData(CF_UNICODETEXT=13)` → `GlobalLock` → `ctypes.wstring_at` → `GlobalUnlock` → **`CloseClipboard()`**
- 写：`OpenClipboard` → `EmptyClipboard()` → `GlobalAlloc(GMEM_MOVEABLE)` → `memmove` → `SetClipboardData` → `CloseClipboard`
- **`CloseClipboard` 必须放在 `finally` 里** —— 漏掉会让整个系统的复制粘贴卡死，这是最危险的坑
- 打开失败（别的程序正占用）就返回 `""`，下次轮询再来，不要重试死等
- 读到的内容如果含 `\x00` 截断；纯文本格式之外的（图片/文件）天然读不到，直接返回 `""`

**验收**：`set_text("测试123")` → 手动在记事本 Ctrl+V，内容一致；再手动复制别的文字 → `get_text()` 能读到。

---

## T4 主窗口 `ui.py`

**涉及文件**：`ui.py`（新建）

**结构**

```
┌─────────────────────────────────────┐
│ [搜索框.....................] [×]   │
├─────────────────────────────────────┤
│ ┏ 常用语 ┓ 最近记录                  │  ← ttk.Notebook 两个页签
│ ┌─────────────────────────────────┐ │
│ │ 公司地址          ← 标题加粗     │ │
│ │ 北京市朝阳区...   ← 内容灰字截断 │ │
│ └─────────────────────────────────┘ │
│ [＋ 添加常用语]     [清空历史]      │
└─────────────────────────────────────┘
```

**要点**

- `ClipboardWindow` 类，`root` 由 `main.py` 创建并传入，本文件不 `mainloop()`
- 窗口 `withdraw()` 起步（默认隐藏），由托盘唤起；点 `×` 只 `withdraw()` 不销毁
- 列表用 `ttk.Treeview`，两列：`内容`（宽）/ `时间`（窄，显示"3分钟前"这种人话）
- 单条内容预览截断到 80 字，换行替换成空格，避免撑破行高
- **单击选中就复制**（不用双击，也不用右键菜单找"复制"）→ `set_text()` + 状态栏提示「已复制」
- 常用语页签顶部按钮 `＋ 添加常用语` → `Toplevel` 小窗：标题输入框 + 多行内容框 + 保存/取消
- 右键菜单：历史 → 复制 / 删除；常用语 → 复制 / 编辑 / 删除
- 搜索框 `bind('<KeyRelease>')` 实时过滤，同时过滤当前页签
- 底部状态栏：显示「已复制」/「共 N 条」/「已清理 N 条过期」

**线程约束**：本文件所有函数都只在主线程被调用。托盘要唤起窗口时，
不是直接调 `window.show()`，而是往 `main.py` 的队列里塞一个 `("show", None)`。

**验收**：手工走一遍 SPEC 验收标准里界面相关的 8 条。

---

## T4b 常用语（在 T4 里一起做）

**涉及文件**：`ui.py`、`store.py`

**要点**

- 常用语页签独立于历史，**搜索时也一起过滤**
- 添加/编辑用同一个 `Toplevel`，靠传不传 `phrase_id` 区分新建还是修改
- 标题最长 40 字，内容不限（但 >10 万字符拒绝）
- 删除要 `askyesno` 确认
- 空标题或空内容不允许保存，按钮置灰或弹提示

**验收**：加一条 → 改标题 → 删掉；把某条常用语 `created_at` 改到 30 天前 → `purge_expired()` → **它还在**。

---

## T5 托盘 `tray.py`

**涉及文件**：`tray.py`（新建）

**要点**

- `pystray.Icon(name, image, title, menu)`，`image` 用 Pillow 现画（64×64，画个圆角方块 + 两条横线表示"剪贴板"）
- 菜单项：**打开** / **暂停记录**（勾选态）/ **清空历史** / **退出**
- 左键单击图标 = 打开窗口（`default=True` 给"打开"这一项）
- 所有回调**只往队列塞消息**，不碰任何 tkinter 对象：
  ```python
  def on_open(icon, item): queue.put(("show", None))
  def on_quit(icon, item): queue.put(("quit", None))
  ```
- `icon.run_detached()` 而不是 `run()`，避免阻塞主线程

**验收**：托盘出现、右键菜单四项都在、点"打开"窗口弹出、点"退出"进程结束。

---

## T6 主程序 `main.py`

**涉及文件**：`main.py`（新建）

**职责**：创建 `root`、初始化数据库、启动托盘、跑两个定时器。

**流程**

```
store.init_db()
root = tk.Tk(); root.withdraw()
window = ClipboardWindow(root)
tray.start(queue)              # 托盘在别的线程
root.after(300, poll)          # 剪贴板轮询
root.after(1000, drain_queue)  # 处理托盘消息
root.after(60*60*1000, purge)  # 每小时清过期
root.mainloop()
```

**`poll()` 逻辑（每 400ms）**

```
if paused: return
text = clipboard.get_text()
if text and text != last_text:
    last_text = text
    if store.add_history(text):
        window.refresh()      # 有新增才刷新，避免每 0.4 秒重画
root.after(400, poll)
```

**`drain_queue()`**：从队列取消息，`show` → `window.show()`，`quit` → 停托盘、`root.destroy()`；然后 `root.after(1000, drain_queue)`

**启动时**：先 `purge_expired()` 一次，把上次运行期间过期的清掉。

**验收**：跑起来后完整走一遍 SPEC 全部验收标准。

---

## T7 启动与自启

**涉及文件**：`启动.bat`、`README.md`

**`启动.bat`**（纯 ASCII，避免 GBK 乱码）

```bat
@echo off
cd /d "%~dp0"
start "" "D:\pyhj\pythonw.exe" "%~dp0main.py"
```

**开机自启**：在
`%APPDATA%\Microsoft\Windows\Start Menu\Programs\Startup\`
放一个指向 `启动.bat` 的快捷方式（用 PowerShell 的 `WScript.Shell` 创建，
不要用 `reg.exe` —— 本机安全策略拦它）。

**README.md** 必须包含：怎么启动、怎么关（托盘右键退出，不是点 ×）、
数据存在哪（`data.db`）、怎么备份（复制这个文件）、怎么取消自启（删启动文件夹里的快捷方式）、
出问题看哪里（如果加了 `run.log` 就写这里）。

**验收**：双击 `启动.bat` 无黑框、托盘出现；重启电脑后托盘自动出现。

---

## 全局纪律

- 每完成一个任务，立即跑该任务的验收，**不过不进下一个**
- 改动前对已有文件留 `.bak-日期`（本项目的文件都是新建，`store.py` 起才有覆盖风险）
- 所有面向用户的文字（提示、按钮、报错）用中文
- 代码注释只写"为什么"，不写"这行是干什么的" —— 函数名本身要说清楚
