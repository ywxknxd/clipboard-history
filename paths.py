"""统一回答一个问题：程序「自己所在的目录」在哪。

为什么不能直接用 __file__：
    用 PyInstaller 打成单文件 exe 后，__file__ 指向的是启动时临时解包出来的
    C:\\Users\\xxx\\AppData\\Local\\Temp\\_MEIxxxx\\ 目录，程序一退出就被删掉。
    把 data.db 和 run.log 放那儿，等于每次开机数据清零。

所以打包后（sys.frozen 为真）用 sys.executable 反推目录，源码跑才用 __file__。
"""

import os
import sys


def app_dir():
    if getattr(sys, "frozen", False):
        return os.path.dirname(os.path.abspath(sys.executable))
    return os.path.dirname(os.path.abspath(__file__))


def plugins_dir():
    return os.path.join(app_dir(), "plugins")
