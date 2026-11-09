"""剪贴板历史 —— 主程序。

启动顺序：查单实例 → 开数据库 → 建窗口（先藏着）→ 起托盘 → 挂三个定时器 → 进事件循环。

两种线程：
  - 主线程跑 tkinter，所有 UI 操作只能在这里
  - pystray 的托盘图标在自己的线程里，只往 msg_queue 丢消息

pythonw 启动时没有控制台，出错会"静默消失"，所以异常一律写进 run.log。
"""

import ctypes
import logging
import os
import queue
import time

import ttkbootstrap as tb

import clipboard
import paths
import plugins
import store
import tray
import ui

LOG_PATH = os.path.join(paths.app_dir(), "run.log")

POLL_MS = 400                 # 剪贴板轮询间隔
QUEUE_MS = 120                # 托盘消息处理间隔，太快没必要，太慢点了没反应
PURGE_MS = 60 * 60 * 1000     # 每小时清一次过期记录

# 允许用环境变量换互斥体名：调试版要和正在用的正式版同时开着时用得上
MUTEX_NAME = os.environ.get("CLIP_MUTEX_NAME", "Local\\ClipboardHistory_9f3a")


def setup_log():
    """日志超过 200KB 就重开一份，避免无限长。"""
    try:
        if os.path.exists(LOG_PATH) and os.path.getsize(LOG_PATH) > 200 * 1024:
            os.replace(LOG_PATH, LOG_PATH + ".old")
    except OSError:
        pass
    logging.basicConfig(
        filename=LOG_PATH,
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(message)s",
        encoding="utf-8",
    )


def claim_single_instance():
    """同名互斥体已存在就说明已经开着一份了。

    直接开两个会重复记录、抢剪贴板，所以第二个静默退出。
    返回的 handle 必须一直拿着，被回收了互斥体就没了。
    """
    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    handle = kernel32.CreateMutexW(None, False, MUTEX_NAME)
    return ctypes.get_last_error() != 183, handle


def main():
    setup_log()
    logging.info("启动")

    ok, mutex = claim_single_instance()
    if not ok:
        logging.info("已有实例在运行，本次退出")
        return

    store.init_db()
    removed = store.purge_expired()
    if removed:
        logging.info("启动时清掉 %d 条过期记录", removed)

    # 插件要在建窗口之前加载：插件能改 ui/store 里的函数（修 bug 用），
    # 得让改动赶在对象创建之前生效。
    loaded = plugins.load_all()
    if loaded:
        logging.info("共加载 %d 个插件：%s", len(loaded), "、".join(loaded))

    root = tb.Window(themename="darkly")
    root.withdraw()
    window = ui.ClipboardWindow(root)

    msg_queue = queue.Queue()
    state = {"paused": False}
    stopping = {"flag": False}

    icon = tray.start(msg_queue, state)
    logging.info("托盘已启动")

    # 窗口和托盘都就位了，才把 ctx 交给插件的 on_start
    plugins.CTX.update({
        "root": root,
        "window": window,
        "icon": icon,
        "store": store,
        "clipboard": clipboard,
        "tray": tray,
        "msg_queue": msg_queue,
        "state": state,
    })
    plugins.start_all()

    # 启动那一刻剪贴板里已有的内容不入库：那是上次复制留下的，
    # 记进来只会让每次开机都莫名其妙多一条。以它为基线，之后变了才记。
    last = {"text": clipboard.get_text()}

    def poll():
        try:
            if not state["paused"]:
                text = clipboard.get_text()
                if text and text != last["text"]:
                    # 比较用的还是剪贴板原文，插件改过的内容只影响入库，
                    # 否则插件每次把内容改一遍，"有没有变化"就永远判不准。
                    last["text"] = text
                    text = plugins.process(text)
                    if store.add_history(text):
                        window.refresh()
        except Exception:
            logging.exception("轮询剪贴板出错")
        root.after(POLL_MS, poll)

    def quit_app():
        if stopping["flag"]:
            return
        stopping["flag"] = True
        logging.info("退出")
        try:
            icon.stop()
        except Exception:
            pass
        try:
            store.close()
        except Exception:
            pass
        root.destroy()

    def drain():
        try:
            while True:
                try:
                    kind, _ = msg_queue.get_nowait()
                except queue.Empty:
                    break

                if kind == "show":
                    window.show()
                elif kind == "toggle_pause":
                    state["paused"] = not state["paused"]
                    tray.set_paused(icon, state["paused"])
                    logging.info("暂停记录：%s", state["paused"])
                elif kind == "clear":
                    # 清空要二次确认，所以走窗口里那个带对话框的方法
                    window.show()
                    window._clear_history()
                elif kind == "quit":
                    quit_app()
                    return
        except Exception:
            logging.exception("处理托盘消息出错")
        root.after(QUEUE_MS, drain)

    def purge():
        try:
            n = store.purge_expired()
            if n:
                logging.info("清掉 %d 条过期记录", n)
                window.refresh()
        except Exception:
            logging.exception("清理过期出错")
        root.after(PURGE_MS, purge)

    root.after(POLL_MS, poll)
    root.after(QUEUE_MS, drain)
    root.after(PURGE_MS, purge)

    try:
        root.mainloop()
    finally:
        logging.info("主循环结束")
        try:
            if not stopping["flag"]:
                icon.stop()
        except Exception:
            pass
        store.close()


if __name__ == "__main__":
    try:
        main()
    except Exception:
        logging.exception("启动失败")
        raise
