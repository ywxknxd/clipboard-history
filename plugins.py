"""插件：程序目录下的 plugins/*.py 会在启动时自动加载。

为什么要有这个：打成单文件 exe 之后，改一行代码就得重新打包一个几十 MB 的
文件。有了插件，加功能、改小毛病只要丢一个 .py 进去，重启程序就生效。

一个插件就是一个普通 .py 文件，可以写下面任意几样：

    NAME = "名字"                  # 可选，日志和报错里显示用

    def on_copy(text):             # 可选，每次复制到新内容时调用
        return text.strip()        # 返回值会存进库里；返回 None 表示不改

    def on_start(ctx):             # 可选，启动时调用一次
        win = ctx["window"]        # 能拿到窗口、托盘、数据库、剪贴板

因为插件本身就是普通 Python，所以它也能直接改主程序的行为（修 bug 用）：

    import ui
    ui.ClipboardWindow._delete_phrase = 你自己写的函数

同样不用重新打包。文件名以 _ 开头的不会被加载——示例文件就是这么放着的。
"""

import importlib.util
import logging
import os
import sys

import paths

_hooks = []        # [(名字, on_copy 函数), ...]

CTX = {}           # 启动后填进去，插件在 on_start 里从这里拿东西


def load_all():
    """扫描并加载。单个插件出错只记日志，绝不让主程序起不来。"""
    # 重复调用等于重新扫一遍，别让钩子越叠越多
    del _hooks[:]

    folder = paths.plugins_dir()
    if not os.path.isdir(folder):
        return []

    loaded = []
    files = sorted(f for f in os.listdir(folder)
                   if f.endswith(".py") and not f.startswith("_"))

    for idx, filename in enumerate(files):
        path = os.path.join(folder, filename)
        # 模块名只用序号，不掺文件名：中文、空格、减号都可能出现在文件名里，
        # 拼进模块名容易出意外，反正我们也从不 import 它。
        mod_name = "clip_plugin_%d" % idx
        try:
            spec = importlib.util.spec_from_file_location(mod_name, path)
            if spec is None or spec.loader is None:
                logging.warning("插件 %s 无法解析，跳过", filename)
                continue
            mod = importlib.util.module_from_spec(spec)
            sys.modules[mod_name] = mod
            spec.loader.exec_module(mod)
        except Exception:
            logging.exception("插件 %s 加载失败，已跳过", filename)
            continue

        label = str(getattr(mod, "NAME", filename[:-3]))
        loaded.append(label)
        logging.info("插件已加载：%s", label)

        hook = getattr(mod, "on_copy", None)
        if callable(hook):
            _hooks.append((label, hook))

    return loaded


def start_all():
    """加载完之后调一次，让插件有机会做启动初始化。"""
    folder = paths.plugins_dir()
    if not os.path.isdir(folder):
        return
    for mod_name, mod in list(sys.modules.items()):
        if not mod_name.startswith("clip_plugin_"):
            continue
        hook = getattr(mod, "on_start", None)
        if not callable(hook):
            continue
        label = str(getattr(mod, "NAME", mod_name))
        try:
            hook(CTX)
        except Exception:
            logging.exception("插件 %s 的 on_start 出错", label)


def process(text):
    """让所有插件依次处理一遍内容。谁出错就跳过谁，不影响别人。"""
    for label, hook in _hooks:
        try:
            out = hook(text)
        except Exception:
            logging.exception("插件 %s 处理内容时出错", label)
            continue
        if out is None:
            continue
        if not isinstance(out, str):
            logging.warning("插件 %s 返回的不是字符串，已忽略", label)
            continue
        text = out
    return text
