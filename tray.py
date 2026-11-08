"""系统托盘图标。

线程约定（很重要）：pystray 的回调跑在它自己的线程里，**绝对不能碰 tkinter**。
所以这里所有动作都只是往队列丢一条消息，真正的处理在 main.py 的主线程里做。
"""

import pystray
from PIL import Image, ImageDraw


def make_icon_image(size=64, paused=False):
    """现画一个图标，省得带 .ico 文件。

    正常是蓝色圆角方块 + 三条横线（像剪贴板）；暂停时变灰。
    """
    img = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)

    bg = (128, 134, 144, 255) if paused else (58, 122, 246, 255)
    edge = size // 10
    draw.rounded_rectangle([edge, edge, size - edge, size - edge],
                           radius=size // 6, fill=bg)

    bar_h = max(2, size // 14)
    for i, top in enumerate((0.32, 0.46, 0.60)):
        x0 = int(size * 0.26)
        x1 = int(size * (0.74 if i < 2 else 0.58))
        y = int(size * top)
        draw.rounded_rectangle([x0, y, x1, y + bar_h],
                               radius=max(1, bar_h // 2),
                               fill=(255, 255, 255, 255))
    return img


def start(msg_queue, state):
    """启动托盘。state 是个 dict，目前只存 paused，用来给菜单显示勾选状态。

    返回 icon 对象，退出时要调 icon.stop()。
    """
    def on_open(icon, item):
        msg_queue.put(("show", None))

    def on_toggle_pause(icon, item):
        msg_queue.put(("toggle_pause", None))

    def on_clear(icon, item):
        msg_queue.put(("clear", None))

    def on_quit(icon, item):
        msg_queue.put(("quit", None))
        icon.stop()

    menu = pystray.Menu(
        pystray.MenuItem("打开", on_open, default=True),
        pystray.MenuItem("暂停记录", on_toggle_pause,
                         checked=lambda item: bool(state.get("paused"))),
        pystray.Menu.SEPARATOR,
        pystray.MenuItem("清空历史", on_clear),
        pystray.MenuItem("退出", on_quit),
    )

    icon = pystray.Icon("clipboard_history", make_icon_image(),
                        "剪贴板历史", menu)
    icon.run_detached()
    return icon


def set_paused(icon, paused):
    """换图标表示暂停状态。图标加载失败不能影响主流程，所以整段包起来。"""
    try:
        icon.icon = make_icon_image(paused=paused)
        icon.title = "剪贴板历史（已暂停）" if paused else "剪贴板历史"
    except Exception:
        pass
