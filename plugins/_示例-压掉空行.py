"""示例插件：复制进来的内容里，把连续的空行压成一个。

怎么让它生效：把文件名开头的下划线去掉（改成「示例-压掉空行.py」），重启程序。

on_copy 收到剪贴板原文，返回什么就存什么。
返回 None 表示"我不改"，交给下一个插件。
"""

NAME = "压掉多余空行"


def on_copy(text):
    out = []
    blank = 0
    for line in text.split("\n"):
        if line.strip() == "":
            blank += 1
            if blank > 1:        # 第二个及以后的空行丢掉
                continue
        else:
            blank = 0
        out.append(line)
    return "\n".join(out)
