' 双击本文件启动剪贴板历史（不会弹出黑框）
Option Explicit
Dim shell
Set shell = CreateObject("WScript.Shell")
shell.CurrentDirectory = "D:\剪贴板历史"
shell.Run """D:\pyhj\pythonw.exe"" ""D:\剪贴板历史\main.py""", 0, False
