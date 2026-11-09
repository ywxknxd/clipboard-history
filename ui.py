"""主窗口。全部界面逻辑都在这里，不碰数据库细节，也不碰托盘。

线程约定：本文件所有方法只在主线程被调用。托盘线程想弹窗，必须走 main.py 的队列。
"""

import ctypes
import time
import tkinter as tk

import ttkbootstrap as tb

import clipboard
import store

FONT = ("Microsoft YaHei UI", 10)
FONT_SMALL = ("Microsoft YaHei UI", 9)
FONT_TITLE = ("Microsoft YaHei UI", 9, "bold")

PLACEHOLDER = "搜索内容…"
PLACEHOLDER_FG = "#6d7480"

PREVIEW_LEN = 70
STATUS_FG = "#9aa7b4"


def human_time(ts):
    """把时间戳说成人话。列表里全是 2026-11-08 21:03:45 这种没人愿意细看。"""
    delta = int(time.time()) - int(ts)
    if delta < 60:
        return "刚刚"
    if delta < 3600:
        return "%d 分钟前" % (delta // 60)
    if delta < 86400:
        return "%d 小时前" % (delta // 3600)
    if delta < 86400 * 2:
        return "昨天"
    return "%d 天前" % (delta // 86400)


def preview(text, n=PREVIEW_LEN):
    """压成一行并截断。剪贴板里经常是带换行的长段落，不压平会把行高撑爆。"""
    flat = " ".join(str(text).split())
    return flat[:n] + ("…" if len(flat) > n else "")


def _enable_dark_title_bar(root):
    """让系统标题栏跟着变深色，否则深色窗口顶着一根白条，很出戏。"""
    try:
        hwnd = ctypes.windll.user32.GetParent(root.winfo_id())
        value = ctypes.c_int(1)
        # 20 = DWMWA_USE_IMMERSIVE_DARK_MODE，Win10 1809 之后才有
        ctypes.windll.dwmapi.DwmSetWindowAttribute(hwnd, 20, ctypes.byref(value), 4)
    except Exception:
        pass


def make_icon_image(size=64):
    """托盘和窗口共用一个画出来的图标，省得带一个 .ico 文件。"""
    from PIL import Image, ImageDraw

    img = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    d.rounded_rectangle([3, 3, size - 3, size - 3], radius=size // 5,
                        fill=(59, 130, 246, 255))
    for i, w in enumerate((0.58, 0.58, 0.36)):
        y = int(size * (0.32 + i * 0.17))
        d.rounded_rectangle(
            [int(size * 0.24), y, int(size * (0.24 + w)), y + max(2, size // 15)],
            radius=size // 30, fill=(255, 255, 255, 240),
        )
    return img


class PhraseDialog(tb.Toplevel):
    """新增 / 编辑常用语。传 phrase 就是编辑，不传就是新增。

    只有一块内容框：常用语本来就是「一句话点一下就用」，多一个标题栏只会
    在保存前多一道必填，没有任何收益。
    """

    def __init__(self, master, on_saved, phrase=None):
        super().__init__(master)
        self.on_saved = on_saved
        self.phrase = phrase

        self.title("编辑常用语" if phrase else "添加常用语")
        self.minsize(420, 300)
        self.resizable(True, True)
        self._place(460, 380)

        # 按钮必须第一个 pack 到 side=bottom。之前放最后，结果 Text 一 expand
        # 就把它们顶到窗口外面去了，得把窗口拉大才看得到「保存」。
        row = tb.Frame(self)
        row.pack(side="bottom", fill="x", padx=16, pady=(8, 14))

        # 用原生 tk.Label：ttkbootstrap 的 Label 会用主题色盖掉 foreground，
        # 在深色背景上就是一片看不清的深灰（用户实际反馈过）。
        tk.Label(self, text="内容", font=FONT_SMALL, fg=STATUS_FG,
                 bg=tb.Style().colors.bg).pack(anchor="w", padx=16, pady=(16, 6))

        self.text = tb.Text(self, height=8, font=FONT, wrap="word",
                            relief="flat", borderwidth=6)
        self.text.pack(fill="both", expand=True, padx=16)
        if phrase:
            self.text.insert("1.0", phrase["content"])

        self.btn_cancel = tb.Button(row, text="取消", bootstyle="secondary-outline",
                                    command=self.destroy, width=8)
        self.btn_cancel.pack(side="right")
        self.btn_save = tb.Button(row, text="保存", bootstyle="primary",
                                  command=self._save, width=8)
        self.btn_save.pack(side="right", padx=(0, 8))

        self.bind("<Escape>", lambda e: self.destroy())
        self.bind("<Control-Return>", lambda e: self._save())
        self.after(100, self.text.focus_set)
        self.grab_set()

    def _place(self, w, h):
        self.update_idletasks()
        sw, sh = self.winfo_screenwidth(), self.winfo_screenheight()
        self.geometry("%dx%d+%d+%d" % (w, h, (sw - w) // 2, (sh - h) // 3))

    def _save(self):
        content = self.text.get("1.0", "end").strip()
        if not content:
            self._warn("内容不能为空")
            return
        if len(content) > store.MAX_LEN:
            self._warn("内容太长（上限 %d 字）" % store.MAX_LEN)
            return

        if self.phrase:
            store.update_phrase(self.phrase["id"], content)
        else:
            store.add_phrase(content)

        self.on_saved()
        self.destroy()

    def _warn(self, msg):
        from tkinter import messagebox
        messagebox.showwarning("提示", msg, parent=self)


class ClipboardWindow:
    def __init__(self, root):
        self.root = root
        self._refreshing = False
        self._flash_job = None
        self._resize_job = None
        self._last_width = 0
        self._ph_on = True

        from tkinter import font as tkfont
        self._measure = tkfont.Font(font=FONT)

        root.title("剪贴板历史")
        root.minsize(460, 420)
        self._center(root, 580, 640)
        root.protocol("WM_DELETE_WINDOW", self.hide)

        self._apply_icon()
        _enable_dark_title_bar(root)

        self._build()
        self.refresh()
        root.withdraw()

    # ------------------------------------------------------------ 布局

    def _apply_icon(self):
        try:
            from PIL import ImageTk
            self._icon_img = ImageTk.PhotoImage(make_icon_image(64))
            self.root.iconphoto(True, self._icon_img)
        except Exception:
            pass

    @staticmethod
    def _center(win, w, h):
        win.update_idletasks()
        sw = win.winfo_screenwidth()
        sh = win.winfo_screenheight()
        win.geometry("%dx%d+%d+%d" % (w, h, (sw - w) // 2, (sh - h) // 3))

    def _build(self):
        style = tb.Style()
        style.configure("Treeview", rowheight=46, font=FONT, borderwidth=0)
        style.configure("Treeview.Heading", font=FONT_TITLE)

        outer = tb.Frame(self.root, padding=(16, 14, 16, 12))
        outer.pack(fill="both", expand=True)

        # 底部必须先 pack 并钉在底部，否则会被上面 expand=True 的列表吃掉
        bottom = tb.Frame(outer)
        bottom.pack(side="bottom", fill="x", pady=(12, 0))

        self.search = tb.Entry(outer, font=FONT)
        self.search.pack(side="top", fill="x", pady=(0, 12), ipady=4)
        self.search.insert(0, PLACEHOLDER)
        self.search.configure(foreground=PLACEHOLDER_FG)
        self.search.bind("<FocusIn>", self._search_focus_in)
        self.search.bind("<FocusOut>", self._search_focus_out)
        self.search.bind("<KeyRelease>", lambda e: self.refresh())
        self.search.bind("<Escape>", lambda e: self._clear_search())

        self.tabs = tb.Notebook(outer)
        self.tabs.pack(side="top", fill="both", expand=True)

        self._build_history_tab()
        self._build_phrases_tab()

        self.btn_add = tb.Button(bottom, text="＋ 添加常用语",
                                 bootstyle="primary", padding=(16, 8),
                                 command=self._add_phrase)
        self.btn_add.pack(side="left")

        self.btn_clear = tb.Button(bottom, text="清空历史",
                                   bootstyle="secondary", padding=(16, 8),
                                   command=self._clear_history)
        self.btn_clear.pack(side="left", padx=(10, 0))

        self.status = tb.Label(bottom, text="", font=FONT_SMALL, foreground=STATUS_FG)
        self.status.pack(side="right", padx=(14, 2))

        self.root.bind("<Escape>", self._on_escape)

        # 常用语更多是"点一下就走"，所以默认停在历史页
        self.tabs.select(0)

        # 拉伸窗口或换页签后，列宽变了，预览长度得重算，否则文字始终那么短。
        # 用 after(80) 而不是 after_idle：刚切过去的页签还没完成布局，
        # idle 时刻拿到的宽度仍是 1（实测 phrase_tree 要等下个事件循环才是 510）。
        self.tabs.bind("<<NotebookTabChanged>>",
                       lambda e: self.root.after(80, self.refresh))
        self.root.bind("<Configure>", self._on_resize)

    def _fit(self, text, tree, col="content"):
        """按列的真实像素宽度截断。

        固定字符数（比如 70）在中文和英文下宽度差一倍，总会有一边长出来被
        Treeview 直接硬切，尾巴上连省略号都没有。这里用字体实测宽度二分。
        """
        flat = " ".join(str(text).split())
        if not flat:
            return ""
        # tree.column("width") 拿到的是配置值（320），不是拉伸后的真实宽度，
        # 直接用它会让每行右半截空着。用控件实际宽度推算可用像素。
        avail = tree.winfo_width()
        if avail <= 1:                       # 窗口还没绘制出来，退回配置值
            limit = max(80, tree.column(col, "width") - 16)
        else:
            if len(tree["columns"]) > 1:     # 预留时间列
                avail -= 80
            limit = max(80, avail - 16)
        if self._measure.measure(flat) <= limit:
            return flat
        lo, hi = 0, len(flat)
        while lo < hi:
            mid = (lo + hi + 1) // 2
            if self._measure.measure(flat[:mid] + "…") <= limit:
                lo = mid
            else:
                hi = mid - 1
        return (flat[:lo] + "…") if lo else "…"

    def _make_tree(self, parent, with_time=True):
        wrap = tb.Frame(parent, padding=(12, 12, 8, 8))
        wrap.pack(fill="both", expand=True)

        cols = ("content", "time") if with_time else ("content",)
        tree = tb.Treeview(wrap, columns=cols, show="headings", selectmode="browse")
        tree.heading("content", text="内容", anchor="w")
        tree.column("content", width=320, anchor="w", stretch=True, minwidth=160)

        if with_time:
            tree.heading("time", text="时间", anchor="e")
            tree.column("time", width=76, anchor="e", stretch=False)

        # 不指定 bootstyle 的话滚动条槽是浅灰的，在深色窗口边上像贴了条白胶布
        bar = tb.Scrollbar(wrap, orient="vertical", command=tree.yview,
                           bootstyle="secondary-round")
        tree.configure(yscrollcommand=bar.set)
        bar.pack(side="right", fill="y")
        tree.pack(side="left", fill="both", expand=True)

        empty = tb.Label(wrap, text="", font=FONT_SMALL, bootstyle="secondary")
        return tree, empty

    def _build_history_tab(self):
        page = tb.Frame(self.tabs)
        self.tabs.add(page, text="  最近记录  ")
        self.hist_tree, self.hist_empty = self._make_tree(page)
        self.hist_tree.bind("<ButtonRelease-1>", self._copy_history)
        self._attach_menu(self.hist_tree, "history")

    def _build_phrases_tab(self):
        page = tb.Frame(self.tabs)
        self.tabs.add(page, text="  常用语  ")
        self.phrase_tree, self.phrase_empty = self._make_tree(page, with_time=False)
        self.phrase_tree.bind("<ButtonRelease-1>", self._copy_phrase)
        self.phrase_tree.bind("<Double-1>", lambda e: self._edit_phrase())
        self._attach_menu(self.phrase_tree, "phrase")

    def _attach_menu(self, tree, kind):
        menu = tb.Menu(tree, tearoff=False)
        if kind == "history":
            menu.add_command(label="复制", command=self._copy_history)
            menu.add_command(label="删除这条", command=self._delete_history)
        else:
            menu.add_command(label="复制", command=self._copy_phrase)
            menu.add_command(label="编辑", command=self._edit_phrase)
            menu.add_separator()
            menu.add_command(label="删除", command=self._delete_phrase)
        tree.bind("<Button-3>", lambda e: self._popup(e, tree, menu))

    @staticmethod
    def _popup(event, tree, menu):
        row = tree.identify_row(event.y)
        if row:
            tree.selection_set(row)
            menu.tk_popup(event.x_root, event.y_root)

    # ------------------------------------------------------------ 搜索框占位

    def _search_focus_in(self, _event=None):
        if self._ph_on:
            self.search.delete(0, "end")
            self.search.configure(foreground="")
            self._ph_on = False

    def _search_focus_out(self, _event=None):
        if not self.search.get().strip():
            self._ph_on = True
            self.search.delete(0, "end")
            self.search.insert(0, PLACEHOLDER)
            self.search.configure(foreground=PLACEHOLDER_FG)

    def _clear_search(self):
        self._ph_on = True
        self.search.delete(0, "end")
        self.search.insert(0, PLACEHOLDER)
        self.search.configure(foreground=PLACEHOLDER_FG)
        self.root.focus_set()
        self.refresh()

    def _keyword(self):
        if self._ph_on:
            return None
        return self.search.get().strip() or None

    def _on_escape(self, _event=None):
        if not self._ph_on and self.search.get().strip():
            self._clear_search()
        else:
            self.hide()

    # ------------------------------------------------------------ 数据刷新

    def refresh(self):
        if self._refreshing:
            return
        self._refreshing = True
        try:
            kw = self._keyword()

            self.hist_tree.delete(*self.hist_tree.get_children())
            for row in store.list_history(keyword=kw):
                self.hist_tree.insert(
                    "", "end", iid="h%d" % row["id"],
                    values=(self._fit(row["content"], self.hist_tree),
                            human_time(row["updated_at"])),
                )

            self.phrase_tree.delete(*self.phrase_tree.get_children())
            for row in store.list_phrases(keyword=kw):
                self.phrase_tree.insert(
                    "", "end", iid="p%d" % row["id"],
                    values=(self._fit(row["content"], self.phrase_tree),),
                )

            self._update_empty_states(kw)
            self._set_count()
        finally:
            self._refreshing = False

    def _update_empty_states(self, kw):
        if self.hist_tree.get_children():
            self.hist_empty.pack_forget()
        else:
            self.hist_empty.configure(
                text=("没找到匹配的记录" if kw else
                      "还没有记录。复制点什么试试，它会自动出现在这里。"))
            self.hist_empty.pack(pady=24)

        if self.phrase_tree.get_children():
            self.phrase_empty.pack_forget()
        else:
            self.phrase_empty.configure(
                text=("没找到匹配的常用语" if kw else
                      "还没有常用语。点左下角「＋ 添加常用语」存一条。"))
            self.phrase_empty.pack(pady=24)

    def _set_count(self):
        s = store.stats()
        # 不显示数据库体积：底部这一行同时塞两个按钮和统计，多几个字符就会被窗口
        # 右边切掉（KB 的 B 真的被切过）。库多大不是用户要的信息。
        self.status.configure(text="历史 %d · 常用语 %d" % (
            s["history"], s["phrases"]))

    def _flash(self, msg):
        self.status.configure(text=msg)
        if self._flash_job:
            self.root.after_cancel(self._flash_job)
        # 2.5 秒后恢复统计，别让提示永远挂在那儿
        self._flash_job = self.root.after(2500, self._set_count)

    # ------------------------------------------------------------ 操作

    def _selected(self, tree, prefix):
        sel = tree.selection()
        if not sel:
            return None
        iid = sel[0]
        if not iid.startswith(prefix):
            return None
        try:
            return int(iid[1:])
        except ValueError:
            return None

    def _copy_history(self, event=None):
        item_id = self._selected(self.hist_tree, "h")
        if item_id is None:
            return
        content = store.get_history_content(item_id)
        if content and clipboard.set_text(content):
            self._flash("已复制：%s" % preview(content, 24))

    def _copy_phrase(self, event=None):
        item_id = self._selected(self.phrase_tree, "p")
        if item_id is None:
            return
        row = store.get_phrase(item_id)
        if row and clipboard.set_text(row["content"]):
            self._flash("已复制：%s" % preview(row["content"], 24))

    def _delete_history(self):
        item_id = self._selected(self.hist_tree, "h")
        if item_id is None:
            return
        from tkinter import messagebox
        if messagebox.askyesno("删除", "删掉这一条记录？", parent=self.root):
            store.delete_history(item_id)
            self.refresh()

    def _delete_phrase(self):
        item_id = self._selected(self.phrase_tree, "p")
        if item_id is None:
            return
        row = store.get_phrase(item_id)
        if not row:
            return
        from tkinter import messagebox
        # 表里早就没有 title 了（常用语只留内容），这里必须读 content，
        # 而且要截断——常用语可能是整段话，原样塞进对话框会撑得很宽。
        text = preview(row["content"], 40)
        if messagebox.askyesno("删除", "删掉这条常用语？\n\n%s" % text, parent=self.root):
            store.delete_phrase(item_id)
            self.refresh()

    def _add_phrase(self):
        PhraseDialog(self.root, on_saved=self._after_phrase_change)

    def _edit_phrase(self):
        item_id = self._selected(self.phrase_tree, "p")
        if item_id is None:
            return
        row = store.get_phrase(item_id)
        if row:
            PhraseDialog(self.root, on_saved=self._after_phrase_change, phrase=row)

    def _after_phrase_change(self):
        self.refresh()
        self.tabs.select(1)

    def _clear_history(self):
        from tkinter import messagebox
        if messagebox.askyesno("清空历史", "清空全部历史记录？\n常用语不受影响。",
                               parent=self.root):
            n = store.clear_history()
            self.refresh()
            self._flash("已清空 %d 条历史" % n)

    # ------------------------------------------------------------ 显示控制

    def _on_resize(self, event):
        """窗口宽度真变了才重算列表。

        只认宽度：高度变化（比如滚动条出现）也会触发 Configure，
        不加这层判断会自己把自己刷进死循环。
        """
        if event.widget is not self.root:
            return
        width = self.root.winfo_width()
        if width == self._last_width:
            return
        self._last_width = width
        if self._resize_job:
            self.root.after_cancel(self._resize_job)
        self._resize_job = self.root.after(180, self.refresh)

    def show(self, tab=None):
        if tab == "phrase":
            self.tabs.select(1)
        self.root.deiconify()
        self.root.update_idletasks()   # 先让窗口算出真实尺寸，否则截断按旧宽度算
        self.root.lift()
        self.root.attributes("-topmost", True)
        # 立刻取消置顶，否则会盖住其它所有窗口
        self.root.after(150, lambda: self.root.attributes("-topmost", False))
        self.refresh()

    def hide(self):
        self.root.withdraw()
