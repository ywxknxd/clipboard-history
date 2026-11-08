"""按 SPEC 验收清单跑一遍。能自动验的全在这里，点击类操作用真实控件方法模拟。

用法：D:\\pyhj\\python.exe _acceptance.py
"""

import os
import sqlite3
import sys
import time

sys.stdout.reconfigure(encoding="utf-8")
sys.path.insert(0, r"D:\剪贴板历史")

TMP = os.path.join(os.environ["TEMP"], "acceptance.db")
if os.path.exists(TMP):
    os.remove(TMP)

import clipboard
import store
import ttkbootstrap as tb
import ui

store.init_db(TMP)

PASS, FAIL = [], []


def check(cond, label):
    (PASS if cond else FAIL).append(label)
    print(("  [OK]   " if cond else "  [FAIL] ") + label)


# ---------------------------------------------------------------- 准备窗口
root = tb.Window(themename="darkly")
win = ui.ClipboardWindow(root)
root.update()

print("== 1. 复制文字后能出现在列表最上面 ==")
clipboard.set_text("第一段：会议纪要草稿")
store.add_history(clipboard.get_text())
win.refresh()
rows = win.hist_tree.get_children()
check(len(rows) == 1, "列表出现 1 条")
check(win.hist_tree.item(rows[0], "values")[0].startswith("第一段"), "内容对得上")

print("== 2. 再复制一段，新的在上面 ==")
clipboard.set_text("第二段：https://example.com/x")
store.add_history(clipboard.get_text())
win.refresh()
rows = win.hist_tree.get_children()
check(len(rows) == 2, "两条都在")
check(win.hist_tree.item(rows[0], "values")[0].startswith("第二段"), "新的排在最上面")

print("== 3. 反复复制同一段 5 次只留 1 条 ==")
before = len(store.list_history())
for _ in range(5):
    store.add_history("第一段：会议纪要草稿")
after = len(store.list_history())
check(before == after == 2, "总数没变（%d → %d）" % (before, after))
top = win.hist_tree.get_children()
win.refresh()
top = win.hist_tree.get_children()
check(win.hist_tree.item(top[0], "values")[0].startswith("第一段"), "重复的那条跳到最上面")

print("== 4. 点一条 = 复制回剪贴板 ==")
clipboard.set_text("先把剪贴板占掉")
target = win.hist_tree.get_children()[1]
win.hist_tree.selection_set(target)
win._copy_history()
time.sleep(0.2)
got = clipboard.get_text()
check("第二段" in got or "第一段" in got, "剪贴板内容被替换成了选中的那条：%r" % got[:20])

print("== 5. 搜索过滤 ==")
win.search.delete(0, "end")
win.search.insert(0, "会议")
win._ph_on = False          # 搜索框里已有真内容，别让占位符逻辑干扰
win.refresh()
rows = win.hist_tree.get_children()
check(len(rows) == 1, "只剩 1 条")
check("会议" in win.hist_tree.item(rows[0], "values")[0], "命中的是含关键字那条")
win.search.delete(0, "end")
win.refresh()

print("== 6. 空剪贴板 / 图片不记录 ==")
clipboard.set_text("")
empty = clipboard.get_text()
check(empty == "", "空剪贴板读出来是空字符串（不会写入垃圾）")
check(store.add_history(empty) is False, "空内容不落库")

print("== 7. 删除单条 ==")
n0 = len(store.list_history())
first_id = store.list_history()[0]["id"]
store.delete_history(first_id)
check(len(store.list_history()) == n0 - 1, "删掉一条后少了一条")

print("== 8. 常用语：添加 / 编辑 / 删除 ==")
pid = store.add_phrase("wzx@example.com")
store.add_phrase("北京市朝阳区望京SOHO T1 2001室")
win.refresh()
prows = win.phrase_tree.get_children()
check(len(prows) == 2, "常用语列表出现 2 条")
check("wzx@example.com" in win.phrase_tree.item(prows[0], "values")[0], "列表里直接显示内容")

win.phrase_tree.selection_set(prows[0])
clipboard.set_text("占位")
win._copy_phrase()
time.sleep(0.2)
check("wzx@example.com" in clipboard.get_text(), "点常用语能复制出内容")

store.update_phrase(pid, "wzx@newmail.com")
check(store.get_phrase(pid)["content"] == "wzx@newmail.com", "编辑生效")
store.delete_phrase(pid)
check(len(store.list_phrases()) == 1, "删除生效")

print("== 8b. 常用语对话框：保存按钮不拉窗口也能看见 ==")
dlg = ui.PhraseDialog(root, on_saved=lambda: None)
root.update()
dlg.update()
btn_bottom = dlg.btn_save.winfo_rooty() + dlg.btn_save.winfo_height()
win_bottom = dlg.winfo_rooty() + dlg.winfo_height()
check(dlg.btn_save.winfo_ismapped(), "保存按钮已绘制出来")
check(btn_bottom <= win_bottom,
      "按钮底部 %d 在窗口底部 %d 之内" % (btn_bottom, win_bottom))
check(not hasattr(dlg, "title_entry"), "对话框里没有标题输入框了")
dlg.destroy()
root.update()

print("== 9. 7 天过期清理（历史清、常用语不清） ==")
conn = sqlite3.connect(TMP)
conn.execute("UPDATE history SET updated_at = ?", (int(time.time()) - 8 * 86400,))
conn.execute("UPDATE phrases SET created_at = ?, updated_at = ?",
             (int(time.time()) - 30 * 86400, int(time.time()) - 30 * 86400))
conn.commit()
conn.close()
removed = store.purge_expired(7)
check(removed > 0, "清掉了 %d 条过期历史" % removed)
check(len(store.list_history()) == 0, "历史清空")
check(len(store.list_phrases()) == 1, "30 天前的常用语仍在")

print("== 10. 窗口隐藏后程序仍活着（× 不退出） ==")
win.hide()
root.update()
check(root.state() == "withdrawn", "窗口变成隐藏状态而非销毁")
win.show()
root.update()
check(root.state() == "normal", "能再次显示出来")

root.destroy()
store.close()
os.remove(TMP)

print("\n" + "=" * 46)
print("通过 %d 项，失败 %d 项" % (len(PASS), len(FAIL)))
if FAIL:
    for f in FAIL:
        print("  失败：" + f)
    sys.exit(1)
