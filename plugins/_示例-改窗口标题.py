"""示例插件：程序启动时改动窗口，用来演示 on_start 能拿到什么。

怎么让它生效：把文件名开头的下划线去掉，重启程序，窗口标题后面会多一句话。

ctx 里能拿到的东西：
    ctx["root"]        tkinter 根窗口
    ctx["window"]      ClipboardWindow 实例（刷新列表、切页签都在它身上）
    ctx["icon"]        托盘图标对象
    ctx["store"]       数据库模块
    ctx["clipboard"]   剪贴板读写模块
    ctx["msg_queue"]   托盘往主线程传消息的队列
    ctx["state"]       {"paused": False}，勾上"暂停记录"会变 True

想修 bug 也能这么写，插件里是完整 Python，可以直接替换主程序的函数：

    import ui
    _旧的 = ui.ClipboardWindow._delete_phrase
    def _新的(self):
        ...你自己的实现...
    ui.ClipboardWindow._delete_phrase = _新的

改完重启程序就生效，不用重新打包 exe。
"""

NAME = "启动时改标题"


def on_start(ctx):
    root = ctx["root"]
    root.title(root.title() + "（插件已接管）")
