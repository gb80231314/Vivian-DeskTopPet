# -*- coding: utf-8 -*-
"""孵化动画截屏验证：启动宠物并按固定间隔抓取窗口区域画面。"""
import os
import subprocess
import sys
import time

from PIL import ImageGrab

ROOT = r"F:/AiWorkProject/2026-09-17-22-43-10"
OUT = os.path.join(ROOT, "pet-work", "hatch_shots")
os.makedirs(OUT, exist_ok=True)

# 窗口默认位于 (100,100)，孵化窗口约 230x250（scale=0.6 -> 115x125 * 2）
proc = subprocess.Popen(
    [r"D:/CodeTools/Mysoft/python314/python.exe", "qpet_app.py"],
    cwd=os.path.join(ROOT, "qpet-app"))

t0 = time.time()
i = 0
while time.time() - t0 < 7.0:
    time.sleep(0.3)
    try:
        im = ImageGrab.grab(bbox=(30, 25, 300, 305))
        im.save(os.path.join(OUT, f"s{i:02d}.png"))
    except Exception as e:
        print("grab fail:", e, flush=True)
    print(i, round(time.time() - t0, 2), flush=True)
    i += 1

proc.terminate()
print("DONE")
