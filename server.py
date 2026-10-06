#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
养老政策一站通 · 局域网访问服务
==================================================================
在本机起一个静态 HTTP 服务，让同一个 Wi-Fi / 热点下的手机也能打开网站。

用法：
    python server.py            # 默认监听 0.0.0.0:8000
    python server.py 8001       # 临时换端口

打包成 exe（打包后把 exe 放到 index.html 同目录即可）：
    pyinstaller --onefile --noconsole --name 启动局域网服务 server.py

说明：
    * 只用 Python 标准库（http.server + socketserver），不需要装任何第三方库
    * 服务根目录 = 本脚本所在目录（打包后 = exe 所在目录）
    * 端口被占用时，把下面 PORT 改成 8001，或命令行传一个端口号
"""

import os
import socket
import socketserver
import sys
from http.server import HTTPServer, SimpleHTTPRequestHandler

# ---------------------------------------------------------------------------
# 配置
# ---------------------------------------------------------------------------
PORT = 8000                      # 默认端口，被占用时可改成 8001
HOST = "0.0.0.0"                 # 0.0.0.0 = 允许局域网内其他设备访问

# 打包成 exe 后 __file__ 不可靠，改用 exe 自身所在目录
if getattr(sys, "frozen", False):
    ROOT = os.path.dirname(os.path.abspath(sys.executable))
else:
    ROOT = os.path.dirname(os.path.abspath(__file__))


def show(message):
    """打印提示；打包成无窗口程序时标准输出可能不存在，这里静默跳过。"""
    try:
        if sys.stdout is not None:
            print(message, flush=True)
    except Exception:
        pass


def get_lan_ip():
    """获取本机局域网 IP：先连一个不可达地址，让系统选出出口网卡。"""
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        sock.connect(("10.255.255.255", 1))      # 不会真的发包，只用于选路
        ip = sock.getsockname()[0]
        if ip and not ip.startswith("127."):
            return ip
    except Exception:
        pass
    finally:
        try:
            sock.close()
        except Exception:
            pass
    try:                                          # 退路：遍历本机 IPv4 地址
        for info in socket.getaddrinfo(socket.gethostname(), None, socket.AF_INET):
            ip = info[4][0]
            if ip and not ip.startswith("127."):
                return ip
    except Exception:
        pass
    return "127.0.0.1"


class QuietHandler(SimpleHTTPRequestHandler):
    """静态文件服务：不打印每条访问日志，避免命令行刷屏。"""

    def log_message(self, fmt, *args):
        pass


class ThreadedServer(socketserver.ThreadingMixIn, HTTPServer):
    """每个请求一个线程，关窗口时能立刻退出。"""

    daemon_threads = True
    allow_reuse_address = True


def main():
    port = PORT
    if len(sys.argv) > 1:                         # 允许命令行临时指定端口
        try:
            port = int(sys.argv[1])
        except ValueError:
            pass

    if not os.path.isfile(os.path.join(ROOT, "index.html")):
        show("[警告] 当前目录下没有找到 index.html：%s" % ROOT)

    handler = lambda *args, **kwargs: QuietHandler(*args, directory=ROOT, **kwargs)
    try:
        httpd = ThreadedServer((HOST, port), handler)
    except OSError as exc:
        show("[错误] 无法监听端口 %d：%s" % (port, exc))
        show("       端口可能被占用，请把本文件顶部的 PORT 改成 8001 后重试。")
        return 1

    ip = get_lan_ip()
    show("服务目录：%s" % ROOT)
    show("本机访问 http://127.0.0.1:%d/index.html" % port)
    show("手机访问 http://%s:%d/index.html" % (ip, port))
    show("提示：手机需与电脑连接同一个 Wi-Fi 或热点")
    show("按 Ctrl+C 停止服务")

    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        show("\n正在停止服务…")
    finally:
        try:
            httpd.server_close()
        except Exception:
            pass
    return 0


if __name__ == "__main__":
    sys.exit(main())
