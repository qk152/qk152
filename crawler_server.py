#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
养老政策一站通 · 本地 HTTP 服务 + 政策爬虫
=========================================
完全基于 Python 标准库（http.server / urllib），不需要 pip install。

用法：
    python crawler_server.py                启动服务并自动打开网页（默认）
    python crawler_server.py --no-browser   只启动服务，不打开浏览器
    python crawler_server.py --crawl        只执行一次爬虫，打印结果后退出
    python crawler_server.py --port 8765    指定端口

接口：
    GET /policies   返回 data/policies.json（文件不存在时先落盘种子数据，并后台补一次爬虫）
    GET /crawl      手动触发一次爬虫，返回是否更新
    GET /health     返回 {"ok": true}
    GET /<其他>     返回网站目录下的静态文件（便于用 http:// 方式访问）

设计要点：
    * 所有响应都带 Access-Control-Allow-Origin: *，file:// 页面可直接跨域读取。
    * 单次爬虫总耗时被硬性限制在 CRAWL_BUDGET 秒内，超时返回旧数据。
    * /policies 最多等待正在运行的爬虫 AWAIT_MAX 秒（网页的 fetch 超时是 2500ms）。
    * 任何网络 / 解析 / 文件异常都被捕获，只写日志，绝不让接口 500。
"""

import argparse
import json
import os
import re
import socket
import sys
import threading
import time
import webbrowser
from datetime import datetime
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib import request as urlrequest
from urllib.parse import quote, urljoin, urlparse

# ==========================================================================
# 1. 路径与常量
# ==========================================================================
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DATA_DIR = os.path.join(BASE_DIR, "data")
DATA_FILE = os.path.join(DATA_DIR, "policies.json")
LOG_FILE = os.path.join(DATA_DIR, "server.log")
INDEX_FILE = os.path.join(BASE_DIR, "index.html")

HOST = "127.0.0.1"
DEFAULT_PORT = 8765

CRAWL_BUDGET = 8.0        # 单次爬虫总耗时上限（秒）
HTTP_TIMEOUT = 1.8        # 单个来源的请求超时；4 个来源 <= 7.2s，稳定落在预算内
AWAIT_MAX = 1.6           # /policies 等待后台爬虫的最长时间（网页超时预算 2500ms）
STALE_SECONDS = 600       # 距上次爬虫超过 10 分钟，访问 /policies 时后台补爬一次
REFRESH_INTERVAL = 1800   # 后台定时爬虫间隔（秒）
ADD_LIMIT = 20            # 单次爬虫最多写入多少条新政策
MAX_BYTES = 2 * 1024 * 1024
LOG_MAX = 512 * 1024

UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/124.0 Safari/537.36")

# ==========================================================================
# 2. 内嵌种子数据（data/policies.json 不存在时用它落盘，保证网页永远有数据）
# ==========================================================================
SEED_JSON = r'''{
  "version": "2026-10-06T14:30:00",
  "updated_at": "2026年10月6日 14:30",
  "source": "民政部 / 财政部 / 中国政府网",
  "policies": [
    {
      "id": "失能补贴-2025-49",
      "category": "失能补贴",
      "tag": "每月最高 800 元",
      "title": "民政部办公厅 财政部办公厅关于全面启动实施向中度以上失能老年人发放养老服务消费补贴项目的通知",
      "doc_no": "民办函〔2025〕49号",
      "issuer": "民政部办公厅、财政部办公厅",
      "date": "2025-12-26",
      "url": "https://www.gov.cn/zhengce/zhengceku/202601/content_7055775.htm",
      "summary": "从2026年1月1日起在全国实施，每月最高800元。",
      "detail": {
        "who": [
          {
            "label": "年龄",
            "value": "60周岁及以上"
          },
          {
            "label": "失能等级",
            "value": "经评估为中度、重度、完全失能"
          },
          {
            "label": "户籍",
            "value": "不限户籍，以居住地申请（部分地区要求本地居住满 6 个月）"
          },
          {
            "label": "排除",
            "value": "已享受同类特困供养、集中照护补贴的，不重复享受"
          }
        ],
        "how_much": [
          {
            "label": "最高额度",
            "value": "每月最高 800 元"
          },
          {
            "label": "发放形式",
            "value": "电子消费券，按月发放，当月有效"
          },
          {
            "label": "资金渠道",
            "value": "中央财政补助 + 地方财政配套"
          },
          {
            "label": "抵扣比例",
            "value": "服务费用的 40%—50% 由补贴抵扣"
          }
        ],
        "how_to": [
          "准备材料：身份证正反面照片、正面照、侧面照、生活照",
          "在民政通小程序提交评估申请",
          "等待街道（乡镇）组织老年人能力评估，一般 5—15 个工作日",
          "评估结果公示无异议后，补贴按月发放至个人账户",
          "选择定点养老服务机构消费，扫码即可抵扣"
        ],
        "coverage": [
          {
            "label": "居家服务",
            "value": "助餐、助浴、助洁、助行、助急、助医"
          },
          {
            "label": "社区服务",
            "value": "日间照料、康复训练、喘息服务"
          },
          {
            "label": "机构服务",
            "value": "入住养老机构的长期照护费用"
          },
          {
            "label": "不可抵扣",
            "value": "现金提现、非定点机构消费、购买实物商品"
          }
        ]
      }
    },
    {
      "id": "适老化改造-2026-03",
      "category": "适老化改造",
      "tag": "每户最高补贴 3000 元",
      "title": "民政部办公厅 财政部办公厅关于持续推进特殊困难老年人家庭适老化改造工作的通知",
      "doc_no": "民办函〔2026〕3号",
      "issuer": "民政部办公厅、财政部办公厅",
      "date": "2026-01-15",
      "url": "https://www.mca.gov.cn/",
      "summary": "面向特殊困难老年人家庭，按“一户一策”实施地面防滑、扶手加装、卫浴无障碍等改造，中央财政按户给予补助。",
      "detail": {
        "who": [
          {
            "label": "对象",
            "value": "分散供养特困人员、低保及低保边缘家庭中的老年人"
          },
          {
            "label": "优先",
            "value": "高龄、失能、残疾、独居空巢老年人优先安排"
          },
          {
            "label": "房屋",
            "value": "自有产权或长期居住的房屋，且 5 年内无拆迁计划"
          },
          {
            "label": "次数",
            "value": "同一家庭原则上只享受一次改造补贴"
          }
        ],
        "how_much": [
          {
            "label": "参考标准",
            "value": "每户最高补贴 3000 元"
          },
          {
            "label": "地方配套",
            "value": "多数省份按 1:1 配套，部分城市提高到每户 5000 元"
          },
          {
            "label": "自费部分",
            "value": "超出补贴标准的改造内容由家庭自付"
          }
        ],
        "how_to": [
          "向户籍所在地社区（村）提出申请，填写改造申请表",
          "街道（乡镇）初审，县级民政部门复核并公示",
          "委托第三方评估机构入户评估，出具一户一策改造方案",
          "确定施工单位，按方案施工，一般 15—30 天完成",
          "验收合格后补贴直接拨付至家庭账户或抵扣施工费用"
        ],
        "coverage": [
          {
            "label": "地面",
            "value": "防滑处理、高差消除、门槛坡化"
          },
          {
            "label": "卫浴",
            "value": "淋浴椅、防滑垫、L 型扶手、坐便器加高"
          },
          {
            "label": "卧室",
            "value": "床边扶手、感应夜灯、护理床位改造"
          },
          {
            "label": "智能设备",
            "value": "紧急呼叫、燃气报警、智能水表（部分试点）"
          }
        ]
      }
    },
    {
      "id": "高龄津贴-2025-18",
      "category": "高龄津贴",
      "tag": "80 周岁起领",
      "title": "民政部关于进一步做好高龄津贴发放工作的通知",
      "doc_no": "民办函〔2025〕18号",
      "issuer": "民政部养老服务司",
      "date": "2025-06-18",
      "url": "https://www.mca.gov.cn/",
      "summary": "年满 80 周岁及以上的本地户籍老年人可按月领取高龄津贴，多数地区 80—89 周岁每月 50—200 元。",
      "detail": {
        "who": [
          {
            "label": "年龄",
            "value": "80 周岁及以上（部分地区 70 周岁起）"
          },
          {
            "label": "户籍",
            "value": "一般要求本地户籍，异地居住需提供居住证明"
          },
          {
            "label": "认证",
            "value": "每年需完成一次生存认证（人脸识别或上门核验）"
          }
        ],
        "how_much": [
          {
            "label": "80—89 周岁",
            "value": "每月 50—200 元（各地标准不同）"
          },
          {
            "label": "90—99 周岁",
            "value": "每月 100—500 元"
          },
          {
            "label": "100 周岁及以上",
            "value": "每月不低于 300 元，部分地区另有一次性慰问金"
          }
        ],
        "how_to": [
          "携带身份证、户口簿、本人银行卡到社区（村）登记",
          "已实现“免申即享”的地区由系统自动识别发放，无需申请",
          "每年按时完成资格认证，逾期未认证的次月暂停发放",
          "补认证后，停发期间的津贴予以补发"
        ],
        "coverage": [
          {
            "label": "现金津贴",
            "value": "按月发放至本人社保卡或银行卡"
          },
          {
            "label": "叠加福利",
            "value": "部分地区叠加节日慰问、免费体检、居家服务时长"
          },
          {
            "label": "不计入",
            "value": "高龄津贴多数地区不计入低保家庭收入核算"
          }
        ]
      }
    }
  ]
}'''

# ==========================================================================
# 3. 日志（控制台 + data/server.log，控制台不可用时不报错）
# ==========================================================================
_log_lock = threading.Lock()


def log(msg):
    line = "[%s] %s" % (datetime.now().strftime("%Y-%m-%d %H:%M:%S"), msg)
    with _log_lock:
        try:
            if sys.stdout is not None:
                print(line, flush=True)
        except Exception:
            pass
        try:
            os.makedirs(DATA_DIR, exist_ok=True)
            if os.path.isfile(LOG_FILE) and os.path.getsize(LOG_FILE) > LOG_MAX:
                os.remove(LOG_FILE)
            with open(LOG_FILE, "a", encoding="utf-8") as fp:
                fp.write(line + "\n")
        except Exception:
            pass


# ==========================================================================
# 4. 数据读写（原子写，避免半截文件）
# ==========================================================================
def seed_data():
    try:
        data = json.loads(SEED_JSON)
    except Exception as exc:
        log("内嵌种子数据解析失败：%s" % exc)
        data = {"version": "", "updated_at": "", "source": "", "policies": []}
    return data


def load_data():
    """读取 data/policies.json；不存在或格式错误时返回 None。"""
    try:
        with open(DATA_FILE, "r", encoding="utf-8") as fp:
            data = json.load(fp)
        if not isinstance(data, dict) or not isinstance(data.get("policies"), list):
            raise ValueError("顶层结构不符合预期")
        return data
    except FileNotFoundError:
        return None
    except Exception as exc:
        log("读取 %s 失败（已忽略）：%s" % (DATA_FILE, exc))
        return None


def save_data(data):
    try:
        os.makedirs(DATA_DIR, exist_ok=True)
        tmp = DATA_FILE + ".tmp"
        with open(tmp, "w", encoding="utf-8") as fp:
            json.dump(data, fp, ensure_ascii=False, indent=2)
            fp.write("\n")
        os.replace(tmp, DATA_FILE)
        return True
    except Exception as exc:
        log("写入 %s 失败（已忽略）：%s" % (DATA_FILE, exc))
        return False


def ensure_data():
    """保证 data/policies.json 存在；返回 (数据, 是否新建)。"""
    data = load_data()
    if data is None:
        data = seed_data()
        save_data(data)
        return data, True
    return data, False


def zh_now():
    now = datetime.now()
    return "%d年%d月%d日 %02d:%02d" % (now.year, now.month, now.day, now.hour, now.minute)


# ==========================================================================
# 5. 爬虫：抓取 -> 解析 -> 去重 -> 合并
# ==========================================================================
SOURCES = (
    {
        "name": "中国政府网·政策文件库（养老服务消费补贴）",
        "url": ("https://sousuo.www.gov.cn/search-gov/data?t=zhengcelibrary_bm&q="
                + quote("养老服务消费补贴")
                + "&p=1&n=10&sort=score&sortType=1&searchfield=title:content&type=gwyzcwjk"),
        "kind": "json",
    },
    {
        "name": "中国政府网·政策文件库（适老化改造补贴）",
        "url": ("https://sousuo.www.gov.cn/search-gov/data?t=zhengcelibrary_bm&q="
                + quote("适老化改造补贴")
                + "&p=1&n=10&sort=score&sortType=1&searchfield=title:content&type=gwyzcwjk"),
        "kind": "json",
    },
    {
        "name": "中国政府网·政策文件库（高龄津贴）",
        "url": ("https://sousuo.www.gov.cn/search-gov/data?t=zhengcelibrary_bm&q="
                + quote("高龄津贴")
                + "&p=1&n=10&sort=score&sortType=1&searchfield=title:content&type=gwyzcwjk"),
        "kind": "json",
    },
    {
        "name": "民政部官网（养老服务司公告）",
        "url": "https://www.mca.gov.cn/",
        "kind": "html",
    },
)

CATEGORY_RULES = (
    ("失能补贴", ("失能", "失智", "护理补贴", "消费补贴", "照护服务", "养老服务补贴")),
    ("适老化改造", ("适老化", "无障碍改造", "家庭改造", "居家改造")),
    ("高龄津贴", ("高龄津贴", "高龄老人", "长寿补贴", "敬老金", "高龄")),
)

KEEP_KEYS = ("养老", "老年", "失能", "失智", "适老化", "高龄", "津贴", "补贴",
             "护理", "照护", "民政", "改造")
DROP_KEYS = ("登录", "注册", "无障碍浏览", "网站地图", "联系我们", "更多", "搜索",
             "首页", "客户端", "微博", "微信", "设为首页", "加入收藏")

TITLE_KEYS = ("title", "TITLE", "docTitle", "name", "subtitle", "contentTitle")
URL_KEYS = ("url", "URL", "link", "href", "docUrl", "urlLink")
DATE_KEYS = ("pubtimeStr", "pubtime", "publishTime", "pubDate", "publishDate",
             "date", "time", "ptime", "updateTime")
ISSUER_KEYS = ("puborg", "publisher", "source", "author", "deptName", "orgName")

RE_DATE = re.compile(r"(20\d{2})[-/年.](\d{1,2})[-/月.](\d{1,2})")
RE_DOCNO = re.compile(r"([\u4e00-\u9fa5]{1,8}〔\d{4}〕\s*\d{1,4}\s*号)")
RE_TAG = re.compile(r"<[^>]+>")
RE_ANCHOR = re.compile(r"""<a\b[^>]*href=["']([^"']+)["'][^>]*>(.*?)</a>""", re.S | re.I)
RE_SCRIPT = re.compile(r"<(script|style)\b.*?</\1>", re.S | re.I)

ISSUER_HINTS = ("民政部", "财政部", "国务院", "人力资源社会保障部", "国家卫生健康委",
                "国家发展改革委", "住房城乡建设部", "中国残联", "国家医保局")

TAG_BY_CATEGORY = {
    "失能补贴": "最新发布",
    "适老化改造": "最新发布",
    "高龄津贴": "最新发布",
    "其他": "政策动态",
}


def clean_text(text):
    if text is None:
        return ""
    s = str(text)
    s = RE_TAG.sub("", s)
    s = s.replace("\xa0", " ").replace("\u3000", " ").replace("&nbsp;", " ")
    s = s.replace("&amp;", "&").replace("&lt;", "<").replace("&gt;", ">").replace("&quot;", '"')
    s = re.sub(r"\s+", " ", s)
    return s.strip()


def first_value(node, keys):
    for key in keys:
        if key in node:
            val = node.get(key)
            if isinstance(val, str) and val.strip():
                return val.strip()
            if isinstance(val, (int, float)):
                return str(val)
    return ""


def normalize_date(text):
    if not text:
        return ""
    m = RE_DATE.search(str(text))
    if not m:
        return ""
    year, month, day = m.group(1), int(m.group(2)), int(m.group(3))
    if not (1 <= month <= 12 and 1 <= day <= 31):
        return ""
    return "%s-%02d-%02d" % (year, month, day)


def extract_doc_no(text):
    m = RE_DOCNO.search(text or "")
    if not m:
        return ""
    return m.group(1).replace(" ", "")


def classify(title):
    for category, keys in CATEGORY_RULES:
        for key in keys:
            if key in title:
                return category
    return "其他"


def guess_issuer(title):
    hits = [name for name in ISSUER_HINTS if name in title]
    if hits:
        return "、".join(hits[:3])
    return "官方发布"


def norm_title(title):
    s = clean_text(title)
    s = re.sub(r"[\s　]+", "", s)
    s = re.sub(r'''[《》【】\[\]（）()·\-—_、,，。.：:；;！!？?"'“”‘’]''', "", s)
    return s


def is_policy_title(title):
    if not title or len(title) < 10 or len(title) > 120:
        return False
    if any(key in title for key in DROP_KEYS):
        return False
    return any(key in title for key in KEEP_KEYS)


def make_id(category, date, title):
    acc = 0
    for ch in title:
        acc = (acc * 131 + ord(ch)) & 0xFFFFFFFF
    return "%s-%s-%04X" % (category, date or "0000-00-00", acc % 0xFFFF)


def build_policy(rec):
    title = clean_text(rec.get("title", ""))
    category = classify(title)
    date = normalize_date(rec.get("date", "")) or ""
    issuer = clean_text(rec.get("issuer", "")) or guess_issuer(title)
    doc_no = extract_doc_no(title)
    return {
        "id": make_id(category, date, title),
        "category": category,
        "tag": TAG_BY_CATEGORY.get(category, "最新发布"),
        "title": title,
        "doc_no": doc_no,
        "issuer": issuer,
        "date": date,
        "url": rec.get("url", "") or "",
        "summary": ("该条目由爬虫自动收录，摘要待人工补充。发布机构：%s；发布日期：%s。"
                    % (issuer, date or "以官方发布为准")),
        "detail": {"who": [], "how_much": [], "how_to": [], "coverage": []},
    }


def extract_records(payload):
    """在任意嵌套的 JSON 中寻找“像政策条目”的字典。"""
    out = []

    def walk(node, depth):
        if depth > 6 or len(out) > 200:
            return
        if isinstance(node, dict):
            title = clean_text(first_value(node, TITLE_KEYS))
            if len(title) >= 10:
                out.append({
                    "title": title,
                    "url": first_value(node, URL_KEYS),
                    "date": first_value(node, DATE_KEYS),
                    "issuer": clean_text(first_value(node, ISSUER_KEYS)),
                })
            for value in node.values():
                walk(value, depth + 1)
        elif isinstance(node, list):
            for value in node:
                walk(value, depth + 1)

    walk(payload, 0)
    return out


def parse_html_records(html, base_url):
    """从 HTML 里抽取像政策标题的链接，并尝试在附近找日期。"""
    out = []
    if not html:
        return out
    body = RE_SCRIPT.sub(" ", html)
    for match in RE_ANCHOR.finditer(body):
        href = match.group(1) or ""
        text = clean_text(match.group(2))
        if not is_policy_title(text):
            continue
        url = urljoin(base_url, href)
        if not url.startswith("http"):
            continue
        window = body[max(0, match.start() - 240): match.end() + 240]
        out.append({
            "title": text,
            "url": url,
            "date": normalize_date(window),
            "issuer": "",
        })
        if len(out) >= 80:
            break
    return out


def http_get(url, timeout):
    req = urlrequest.Request(url, headers={
        "User-Agent": UA,
        "Accept": "application/json, text/html;q=0.9, */*;q=0.8",
        "Accept-Language": "zh-CN,zh;q=0.9",
        "Connection": "close",
    })
    with urlrequest.urlopen(req, timeout=timeout) as resp:
        raw = resp.read(MAX_BYTES)
        charset = resp.headers.get_content_charset() or ""
    for enc in (charset, "utf-8", "gb18030"):
        if not enc:
            continue
        try:
            return raw.decode(enc), charset
        except Exception:
            continue
    return raw.decode("utf-8", "ignore"), charset


def merge_records(data, records):
    existing = set()
    for item in data.get("policies", []):
        if isinstance(item, dict):
            existing.add(norm_title(item.get("title", "")))
    added = []
    for rec in records:
        title = clean_text(rec.get("title", ""))
        if not is_policy_title(title):
            continue
        key = norm_title(title)
        if not key or key in existing:
            continue
        existing.add(key)
        added.append(build_policy(rec))
        if len(added) >= ADD_LIMIT:
            break
    if added:
        data["policies"] = added + list(data.get("policies", []))
        data["version"] = datetime.now().strftime("%Y-%m-%dT%H:%M:%S")
        data["updated_at"] = zh_now()
        save_data(data)
        log("写入 %d 条新政策，版本更新为 %s" % (len(added), data["version"]))
    else:
        log("未发现新政策，版本保持不变")
    return added


_crawl_lock = threading.Lock()
_crawl_state = {"running": False, "last_start": 0.0, "last_end": 0.0, "last_result": None}


def crawl_once(budget=CRAWL_BUDGET):
    """执行一次爬虫；无论成功失败都在 budget 秒内返回。"""
    started = time.time()
    deadline = started + budget
    records = []

    for source in SOURCES:
        remaining = deadline - time.time()
        if remaining <= 0.4:
            log("爬虫时间预算用尽，跳过剩余来源")
            break
        try:
            text, charset = http_get(source["url"], timeout=min(HTTP_TIMEOUT, remaining))
            if not text:
                continue
            looks_json = (source.get("kind") == "json"
                          or "json" in (charset or "").lower()
                          or text.lstrip()[:1] in ("{", "["))
            got = []
            if looks_json:
                payload = None
                try:
                    payload = json.loads(text)
                except Exception:
                    payload = None
                got = extract_records(payload) if payload is not None else parse_html_records(text, source["url"])
            else:
                got = parse_html_records(text, source["url"])
            records.extend(got)
            log("来源 %s：解析到 %d 条候选" % (source["name"], len(got)))
        except Exception as exc:
            log("来源 %s 抓取失败（已忽略）：%s" % (source["name"], exc))

    data = load_data() or seed_data()
    added = merge_records(data, records)
    result = {
        "ok": True,
        "updated": bool(added),
        "added": len(added),
        "total": len(data.get("policies", [])),
        "version": data.get("version", ""),
        "updated_at": data.get("updated_at", ""),
        "elapsed": round(time.time() - started, 2),
    }
    _crawl_state["last_result"] = result
    return result


def crawl_once_guarded():
    """带上锁的爬虫入口，避免并发重复抓取。"""
    if not _crawl_lock.acquire(blocking=False):
        return {"ok": True, "updated": False, "added": 0, "busy": True,
                "message": "爬虫正在运行，请稍后再试"}
    _crawl_state["running"] = True
    _crawl_state["last_start"] = time.time()
    try:
        return crawl_once()
    except Exception as exc:
        log("爬虫执行异常（已忽略）：%s" % exc)
        data = load_data() or seed_data()
        return {"ok": True, "updated": False, "added": 0,
                "total": len(data.get("policies", [])),
                "version": data.get("version", ""), "error": str(exc)}
    finally:
        _crawl_state["running"] = False
        _crawl_state["last_end"] = time.time()
        _crawl_lock.release()


def schedule_crawl():
    """后台补一次爬虫，不阻塞当前请求。"""
    if _crawl_state["running"]:
        return False
    threading.Thread(target=crawl_once_guarded, name="crawl", daemon=True).start()
    return True


def crawl_is_stale():
    last = _crawl_state["last_end"] or _crawl_state["last_start"]
    if not last:
        return True
    return (time.time() - last) > STALE_SECONDS


def await_crawl(max_wait=AWAIT_MAX):
    """若爬虫正在运行，最多等待 max_wait 秒，尽量让本次请求拿到新数据。"""
    end = time.time() + max_wait
    while time.time() < end and _crawl_state["running"]:
        time.sleep(0.05)


def periodic_crawl():
    while True:
        time.sleep(REFRESH_INTERVAL)
        try:
            crawl_once_guarded()
        except Exception as exc:
            log("后台定时爬虫异常（已忽略）：%s" % exc)


# ==========================================================================
# 6. HTTP 服务
# ==========================================================================
CONTENT_TYPES = {
    ".html": "text/html; charset=utf-8",
    ".json": "application/json; charset=utf-8",
    ".css": "text/css; charset=utf-8",
    ".js": "application/javascript; charset=utf-8",
    ".txt": "text/plain; charset=utf-8",
    ".svg": "image/svg+xml",
    ".png": "image/png",
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".gif": "image/gif",
    ".webp": "image/webp",
    ".ico": "image/x-icon",
}


class Handler(BaseHTTPRequestHandler):
    server_version = "YanglaoPolicy/1.0"
    protocol_version = "HTTP/1.1"

    # 精简日志，写进控制台与 data/server.log
    def log_message(self, fmt, *args):
        try:
            log("HTTP " + (fmt % args))
        except Exception:
            pass

    # ---------- 基础工具 ----------
    def _cors(self):
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, HEAD, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "*")
        self.send_header("Access-Control-Max-Age", "600")

    def _send(self, code, body, ctype, cache="no-store"):
        try:
            self.send_response(code)
            self.send_header("Content-Type", ctype)
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", cache)
            self._cors()
            self.end_headers()
            if self.command != "HEAD":
                self.wfile.write(body)
        except (BrokenPipeError, ConnectionAbortedError, ConnectionResetError):
            pass
        except Exception as exc:
            log("响应写出失败（已忽略）：%s" % exc)

    def _json(self, obj, code=200):
        body = json.dumps(obj, ensure_ascii=False).encode("utf-8")
        self._send(code, body, "application/json; charset=utf-8")

    # ---------- 路由 ----------
    def do_OPTIONS(self):
        self._send(204, b"", "text/plain; charset=utf-8")

    def do_HEAD(self):
        self.do_GET()

    def do_GET(self):
        try:
            path = urlparse(self.path).path
            route = path.rstrip("/") or "/"
            if route == "/policies":
                return self.handle_policies()
            if route == "/crawl":
                return self.handle_crawl()
            if route == "/health":
                return self._json({"ok": True})
            return self.handle_static(path)
        except Exception as exc:
            log("请求处理异常（已忽略）：%s" % exc)
            try:
                self._json({"ok": False, "error": "internal"}, 200)
            except Exception:
                pass

    def handle_policies(self):
        data = load_data()
        if data is None:
            # 文件不存在（或损坏）：立刻落盘种子数据并返回，绝不让网页等待
            data, created = ensure_data()
            if created:
                log("data/policies.json 不存在，已写入初始种子数据")
            schedule_crawl()
        elif crawl_is_stale():
            # 数据可能过期：后台补一次爬虫，并给它 AWAIT_MAX 秒争取本轮就返回新数据
            schedule_crawl()
            await_crawl()
            data = load_data() or data
        self._json(data)

    def handle_crawl(self):
        result = crawl_once_guarded()
        self._json(result)

    def handle_static(self, path):
        if path in ("/", "", "/index.html"):
            target = INDEX_FILE
        else:
            target = os.path.realpath(os.path.join(BASE_DIR, path.lstrip("/")))
        root = os.path.realpath(BASE_DIR)
        if not target.startswith(root) or not os.path.isfile(target):
            self._json({"ok": False, "error": "not found", "path": path}, 404)
            return
        try:
            with open(target, "rb") as fp:
                body = fp.read()
        except Exception as exc:
            log("读取静态文件失败（已忽略）：%s" % exc)
            self._json({"ok": False, "error": "read failed"}, 404)
            return
        ext = os.path.splitext(target)[1].lower()
        self._send(200, body, CONTENT_TYPES.get(ext, "application/octet-stream"))


# ==========================================================================
# 7. 启动
# ==========================================================================
def port_in_use(port):
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    sock.settimeout(0.4)
    try:
        sock.connect((HOST, port))
        return True
    except Exception:
        return False
    finally:
        try:
            sock.close()
        except Exception:
            pass


def open_browser(port):
    """由 Python 自己打开网页，bat 不重复打开。"""
    try:
        if os.path.isfile(INDEX_FILE):
            webbrowser.open(_file_uri(INDEX_FILE))
        else:
            webbrowser.open("http://%s:%d/" % (HOST, port))
    except Exception as exc:
        log("打开浏览器失败（已忽略）：%s" % exc)


def _file_uri(path):
    try:
        from pathlib import Path
        return Path(path).as_uri()
    except Exception:
        return "file:///" + path.replace("\\", "/")


def main(argv=None):
    parser = argparse.ArgumentParser(description="养老政策一站通 · 本地服务 + 爬虫")
    parser.add_argument("--port", type=int, default=DEFAULT_PORT, help="监听端口，默认 8765")
    parser.add_argument("--no-browser", action="store_true", help="启动后不打开浏览器")
    parser.add_argument("--crawl", action="store_true", help="只执行一次爬虫后退出")
    args = parser.parse_args(argv)

    os.makedirs(DATA_DIR, exist_ok=True)
    data, created = ensure_data()
    log("数据文件：%s（%d 条政策，版本 %s）"
        % (DATA_FILE, len(data.get("policies", [])), data.get("version", "")))

    if args.crawl:
        result = crawl_once_guarded()
        text = json.dumps(result, ensure_ascii=False, indent=2)
        try:
            if sys.stdout is not None:
                print(text)
        except Exception:
            pass
        return 0

    if port_in_use(args.port):
        log("端口 %d 已有服务在运行，直接打开网页" % args.port)
        if not args.no_browser:
            open_browser(args.port)
        return 0

    try:
        httpd = ThreadingHTTPServer((HOST, args.port), Handler)
    except OSError as exc:
        log("无法监听 %s:%d（%s）" % (HOST, args.port, exc))
        return 1
    httpd.daemon_threads = True

    log("服务已启动：http://%s:%d/health" % (HOST, args.port))
    log("接口：/policies  /crawl  /health")

    # 后台定时刷新 + 启动时的首次抓取
    threading.Thread(target=periodic_crawl, name="periodic", daemon=True).start()
    schedule_crawl()

    if not args.no_browser:
        threading.Timer(0.6, open_browser, args=(args.port,)).start()

    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        log("收到中断信号，正在退出")
    finally:
        try:
            httpd.server_close()
        except Exception:
            pass
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except Exception as exc:
        log("启动失败：%s" % exc)
        sys.exit(1)
