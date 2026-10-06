#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
养老政策一站通 · 二维码生成
==================================================================
把一个网址转成二维码图片，方便放进 PPT 或打印出来。

用法：
    双击运行，或命令行执行 python 生成二维码.py

依赖：
    pip install qrcode[pil]

输出：
    同目录下的 qrcode.png（500 x 500，前景 #2D4A3E，背景白色，同名文件直接覆盖）
"""

import os
import sys

DEFAULT_URL = "http://127.0.0.1:8000/index.html"
OUTPUT_FILE = "qrcode.png"
SIZE = 500                    # 成品边长（像素）
FG_COLOR = "#2D4A3E"          # 前景色：墨绿
BG_COLOR = "#FFFFFF"          # 背景色：白色

if getattr(sys, "frozen", False):
    ROOT = os.path.dirname(os.path.abspath(sys.executable))
else:
    ROOT = os.path.dirname(os.path.abspath(__file__))


def main():
    show = print
    show("=" * 50)
    show("  养老政策一站通 · 二维码生成")
    show("=" * 50)

    try:
        import qrcode
    except ImportError:
        show("")
        show("未安装 qrcode 库，请先执行：")
        show("    pip install qrcode[pil]")
        show("")
        return 1

    try:
        text = input("请输入网址（直接回车用默认值 %s）：\n> " % DEFAULT_URL)
    except (EOFError, KeyboardInterrupt):
        text = ""
    text = text.strip().lstrip("\ufeff")        # 去掉首尾空白，以及粘贴带进来的 BOM
    url = text or DEFAULT_URL                    # 直接回车 / 只输入空白都用默认值
    if not url.lower().startswith(("http://", "https://")):
        url = "http://" + url

    qr = qrcode.QRCode(
        version=None,
        error_correction=qrcode.constants.ERROR_CORRECT_M,
        box_size=1,
        border=4,
    )
    qr.add_data(url)
    qr.make(fit=True)

    modules = len(qr.modules)                     # 含 4 模块静区的总模块数
    qr.box_size = max(1, SIZE // modules)         # 整数倍放大，二维码边缘才锐利

    path = os.path.join(ROOT, OUTPUT_FILE)
    size_text = "%d x %d" % (SIZE, SIZE)
    try:
        from PIL import Image
        image = qr.make_image(fill_color=FG_COLOR, back_color=BG_COLOR).convert("RGB")
        canvas = Image.new("RGB", (SIZE, SIZE), BG_COLOR)
        offset = (SIZE - image.size[0]) // 2
        canvas.paste(image, (offset, offset))     # 居中，四周白边补齐到 500x500
        canvas.save(path)                         # 已存在则直接覆盖
    except Exception:
        image = qr.make_image(fill_color=FG_COLOR, back_color=BG_COLOR)
        image.save(path)                          # 没装 pillow 时按整数倍尺寸保存
        size_text = "原始尺寸（未安装 pillow，未补齐到 %d x %d）" % (SIZE, SIZE)

    show("")
    show("网址：%s" % url)
    show("已生成：%s" % path)
    show("尺寸：%s（前景 %s，背景 %s）" % (size_text, FG_COLOR, BG_COLOR))
    return 0


if __name__ == "__main__":
    try:
        code = main()
    except Exception as error:
        print("生成失败：%s" % error)
        code = 1
    try:
        input("\n按回车键关闭…")
    except Exception:
        pass
    sys.exit(code)
