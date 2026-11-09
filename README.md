# 剪贴板历史

自动记录你复制过的**文字**，保留 7 天，过期自动清掉。想用的时候点托盘图标翻出来，
选中哪条就放回剪贴板，你按 Ctrl+V 粘出来。

另外有一块**常用语**：自己存几条经常要粘的内容（地址、邮箱、固定话术），
它不受 7 天限制，永远不会被自动删掉。

![最近记录](docs/界面-最近记录.png)
![常用语](docs/界面-常用语.png)

---

## 怎么启动

双击 **`启动.vbs`**（推荐，不会闪黑框）。

也可以双击 `启动.bat`，效果一样，只是会闪一下黑框。

**开机自动启动**：本机已经把 `启动.vbs` 的快捷方式放进开机启动文件夹了，不用手动开。
换一台机器需要自己再放一次（见下面「怎么取消开机自启」里的路径）。

## 怎么关

在右下角托盘找到蓝色方块图标 → **右键** → **退出**。

⚠️ 点窗口右上角的 × 只是把窗口收起来，程序还在后台记录。这是故意的——
不然一关窗口就记不到东西了。

## 怎么用

- **点一下某条记录** = 复制它，然后去别的地方 Ctrl+V
- **右键某条记录** = 删除这条 / 编辑（常用语）
- **搜索框** = 打字就实时过滤，Esc 清空
- **页签** = 左边「最近记录」（7 天内的），右边「常用语」（永久的）
- **暂停记录** = 托盘右键勾上，那段时间复制的东西不记

## 数据存在哪

```
程序目录\data.db
```

一个 SQLite 文件，**明文**。里面有你的剪贴板内容，如果复制过密码之类的，
懂电脑的人打开这个文件能读到。目前没有加密。

## 怎么备份

复制 `data.db` 这一个文件就是完整备份。要恢复就把它放回去覆盖。

建议：先托盘退出，再复制，避免文件正被写入。

## 怎么取消开机自启

删掉这个文件就行：

```
%APPDATA%\Microsoft\Windows\Start Menu\Programs\Startup\剪贴板历史.vbs
```

## 出问题看哪里

```
程序目录\run.log
```

程序用 `pythonw` 跑，没有黑窗口，所以出错不会在屏幕上显示，全写在这个日志里。

常见情况：

| 症状 | 原因 | 怎么办 |
|---|---|---|
| 双击没反应，托盘也没图标 | 已经开着一份了（程序只允许一个实例） | 看右下角托盘，或者任务管理器里看有没有 pythonw.exe |
| 托盘图标不见了 | 可能被折叠进「^」里了 | 点任务栏的 ^ 展开看看 |
| 复制了东西但列表里没有 | 内容超过 10 万字 / 是图片 / 暂停记录了 | 图片和文件不记录，这是设计如此 |
| 窗口打开但列表是空的 | 刚启动，还没复制过东西 | 复制一段文字试试 |

## 文件说明

| 文件 | 作用 |
|---|---|
| `main.py` | 主程序：托盘、轮询剪贴板、定时清理 |
| `ui.py` | 窗口界面（深色主题） |
| `store.py` | 数据库读写，所有 SQL 都在这里 |
| `clipboard.py` | 调用 Windows API 读写剪贴板 |
| `tray.py` | 托盘图标和右键菜单 |
| `paths.py` | 统一给出"程序自己所在目录"，打包后才不会把数据写丢 |
| `plugins.py` | 插件加载器 |
| `plugins/` | 插件放这里，见下面「插件」一节 |
| `启动.vbs` / `启动.bat` | 启动器 |
| `自检.py` | 改完代码跑一下，全部检查通过才说明没改坏 |
| `data.db` | 你的数据 |
| `docs/spec/` | 开发时的需求文档和实施方案 |

## 环境要求

- Windows（用到 `ctypes` 调 Win32 剪贴板 API，只能在 Windows 上跑）
- Python 3.10+（本机用的是 3.14.6）
- 依赖只有两个：`pystray`（托盘图标）、`ttkbootstrap`（深色主题）

```bash
pip install pystray ttkbootstrap
```

## 从源码跑起来

首次运行不需要准备数据库——程序启动时如果没找到 `data.db` 会自己建表。

```
python main.py       # 前台跑，能看到日志输出
pythonw main.py      # 后台跑，没有黑窗口（启动.vbs 用的就是它）
```

## 改代码的话

程序不会热重载，改完 `.py` 要：托盘右键退出 → 重新双击 `启动.vbs`。

改完先跑一遍自检（用的是临时数据库，不会动你的真实记录）：

```
python 自检.py
```

看到「失败 0 项」再重启程序。

## 插件：加功能、修 bug 不用重新打包

程序目录下的 `plugins\` 文件夹里，丢一个 `.py` 进去就是插件，启动时自动加载。

一个插件就是普通 Python 文件，下面三样随便写哪几样都行：

| 写什么 | 什么时候被调用 |
|---|---|
| `NAME = "名字"` | 只是日志里显示的名字，可以不写 |
| `def on_copy(text): ...` | 每复制到一段新内容时调用。返回什么就存什么，返回 `None` 表示不改 |
| `def on_start(ctx): ...` | 启动时调一次。`ctx["window"]` 是主窗口，`ctx["store"]` 是数据库，`ctx["root"]` 是 tk 根窗口 |

**默认一个都不加载**。`plugins\` 里的两个示例文件名都以 `_` 开头，
你去掉开头那个下划线，重启程序它就生效了。

因为插件就是 Python，它还能直接改主程序的行为——这才是"修 bug 不用重新打包"的关键：

```python
import ui

_旧的 = ui.ClipboardWindow._delete_phrase

def _新的(self):
    ...你自己的实现...

ui.ClipboardWindow._delete_phrase = _新的
```

存成 `plugins\修删除.py`，重启就生效，不用碰 exe。

⚠️ 插件跑在主线程里，里面别写会卡住的操作（等网络、sleep），不然窗口会僵。

## 打包成单文件 exe

```bash
pip install pyinstaller

# 先画图标，跟托盘那个一样
python -c "import tray; tray.make_icon_image(256).save('build/app.ico', sizes=[(16,16),(32,32),(48,48),(256,256)])"

python -m PyInstaller --noconfirm --clean --onefile --windowed ^
  --name ClipboardHistory --icon build/app.ico ^
  --collect-data ttkbootstrap ^
  --hidden-import pystray._win32 --hidden-import PIL._tkinter_finder ^
  --exclude-module numpy ^
  --add-binary "%PY_BIN%/tiff.dll;." ^
  --add-binary "%PY_BIN%/jpeg8.dll;." ^
  --add-binary "%PY_BIN%/openjp2.dll;." ^
  --add-binary "%PY_BIN%/lcms2.dll;." ^
  --add-binary "%PY_BIN%/freetype.dll;." ^
  --distpath dist --workpath build/work main.py
```

`%PY_BIN%` 换成你这份 Python 的库目录。本机是 conda 式布局，所以是
`D:\pyhj\Library\bin`；用官网安装包一般是 `C:\Python3xx\DLLs`。

产出在 `dist\ClipboardHistory.exe`，改成 `剪贴板历史.exe` 也一样能跑。

五个必须注意的地方（每一个都真踩过）：

- **`--collect-data ttkbootstrap` 不能少**：主题是 json 数据文件，不带上会白屏
- **`--windowed` 不能少**：不加每次启动都会弹黑框
- **`--exclude-module numpy` 一定要加**：这台机器的 Python 里装了 numpy，
  打包器会顺着把 Intel MKL 那一堆数学 DLL 全拖进来，体积从 40MB 涨到 168MB。
  这个程序一个矩阵都不算，排掉毫无影响
- **PIL 的几个 DLL 得手动加**：`_imaging.pyd` 依赖 tiff / jpeg8 / openjp2 /
  lcms2 / freetype，conda 式布局下打包器找不到。少了就是启动即崩，报
  `ImportError: DLL load failed while importing _imaging`
- **数据要落在 exe 旁边**：单文件模式运行时会把代码解包到临时目录，
  `__file__` 就指向那儿，程序一退出就删。`paths.py` 专门处理这件事，
  千万别把 `data.db` 的路径改回 `__file__`，否则每次开机记录清零
