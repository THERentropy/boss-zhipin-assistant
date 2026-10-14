#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""验证拦截监测助手 —— 检测人机验证 / 等待真人完成后自动续跑

背景：
    招聘平台高频操作后会弹出「滑动验证」等人机验证。这类验证的设计目的
    就是区分真人与自动化，因此必须由真人完成；本工具**不**模拟拖动、
    不识别验证码，只负责把「等待 - 检测」这一段自动化，让人工干预
    只花几秒钟（拖一下滑块），流程不必重跑。

用法：
    python verify_watch.py                    # 检测一次，若被拦截则等待通过
    python verify_watch.py --timeout 300      # 最长等待秒数（默认 300）
    python verify_watch.py --interval 3       # 轮询间隔秒数（默认 3）
    python verify_watch.py --shot             # 被拦截时保存页面截图

退出码：
    0 = 当前没有验证拦截（可继续流程）
    2 = 曾出现验证且已通过（可继续流程）
    3 = 等待超时（验证仍未通过，需人工处理）
"""

import argparse
import os
import sys
import time
from datetime import datetime

SKILL_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if SKILL_DIR not in sys.path:
    sys.path.insert(0, SKILL_DIR)

from scripts.profile_loader import WORK_DIR
from scripts.sites import get_adapter
from scripts.webbridge_client import api, health_check

# 常见验证页特征（页面标题 / 正文关键词）
VERIFY_TITLE_KEYS = ["滑动验证", "访问验证", "安全验证", "验证页面", "人机验证", "验证中心"]
VERIFY_BODY_KEYS = [
    "请按住滑块", "拖动到最右边", "拖动滑块", "请完成验证",
    "访问验证", "为了更好的访问体验，请进行验证", "安全验证",
]

DETECT_JS = r"""
(function(){
  var title = document.title || '';
  var body = (document.body ? document.body.innerText : '') || '';
  body = body.replace(/\s+/g, ' ').slice(0, 600);
  var hasWidget = 0;
  var sels = ['[class*=captcha]', '[class*=slide]', '[class*=verify]',
              '#nc_1_wrapper', '.nc_container', '[id*=captcha]'];
  for (var i = 0; i < sels.length; i++) {
    try { if (document.querySelectorAll(sels[i]).length > 0) hasWidget = 1; } catch(e) {}
  }
  return JSON.stringify({title: title, body: body, widget: hasWidget, url: location.href});
})()
"""


def is_verify_page(meta):
    """判断当前页是否为验证拦截页"""
    if not meta:
        return False, "无法读取页面"
    title = meta.get("title") or ""
    body = meta.get("body") or ""
    for k in VERIFY_TITLE_KEYS:
        if k in title:
            return True, "标题命中「%s」" % k
    for k in VERIFY_BODY_KEYS:
        if k in body:
            return True, "正文命中「%s」" % k
    if meta.get("widget"):
        return True, "检测到验证组件 DOM"
    return False, "无验证特征"


def take_shot(tag="verify"):
    """截图保存（失败不中断）"""
    try:
        shot = api("screenshot", {}, timeout=15)
        data = shot.get("data", {}) if isinstance(shot, dict) else {}
        b64 = data.get("data") or data.get("base64") or ""
        if not b64:
            return None
        import base64
        fn = os.path.join(WORK_DIR, "%s_%s.png" % (
            tag, datetime.now().strftime("%H%M%S")))
        with open(fn, "wb") as f:
            f.write(base64.b64decode(b64.split(",")[-1]))
        return fn
    except Exception:
        return None


def _eval(code):
    """执行 JS 并取回值（WebBridge 返回 {"ok":true,"data":{"type":..,"value":..}}）"""
    try:
        r = api("evaluate", {"code": code.replace("\n", " ")}, timeout=10)
    except Exception:
        return None
    if not isinstance(r, dict) or not r.get("ok"):
        return None
    d = r.get("data") or {}
    return d.get("value") if isinstance(d, dict) else None


def detect(adapter_name=None):
    """检测当前标签页"""
    raw = None
    if adapter_name:
        try:
            ad = get_adapter(adapter_name)
            raw = ad.js(DETECT_JS)
        except Exception:
            raw = None
    if not raw:
        raw = _eval(DETECT_JS)
    import json
    try:
        return json.loads(raw) if isinstance(raw, str) else (raw or {})
    except Exception:
        return {}


def ensure_no_verify(timeout=300, interval=3, adapter_name=None, verbose=True):
    """供投递脚本调用：检测到人机验证时等待真人完成，通过后返回 True。

    Returns:
        True  = 当前无验证（可继续投递）
        False = 等待超时（验证仍未完成，应暂停流程）
    """
    meta = detect(adapter_name)
    hit, why = is_verify_page(meta)
    if not hit:
        return True
    if verbose:
        print("\n" + "=" * 60)
        print("  ⚠ 检测到人机验证（%s）" % why)
        print("  请在浏览器中拖动滑块完成验证，完成后流程会自动继续…")
        print("=" * 60)
    t0 = time.time()
    while time.time() - t0 < timeout:
        time.sleep(interval)
        meta = detect(adapter_name)
        hit, _ = is_verify_page(meta)
        if not hit:
            if verbose:
                print("[验证监测] ✓ 验证已通过（等待 %d 秒），继续投递" % int(time.time() - t0))
            return True
    if verbose:
        print("[验证监测] ✗ 等待超时，请手动完成验证后重跑")
    return False


def human_delay(lo=2.5, hi=6.0):
    """拟人化随机间隔（降低触发风控/验证的概率）"""
    import random
    time.sleep(random.uniform(lo, hi))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--timeout", type=int, default=300)
    ap.add_argument("--interval", type=int, default=3)
    ap.add_argument("--shot", action="store_true")
    ap.add_argument("--site", default="")
    args = ap.parse_args()

    if not health_check():
        print("[验证监测] ERROR: WebBridge 不可达")
        return 1

    meta = detect(args.site or None)
    hit, why = is_verify_page(meta)
    print("[验证监测] 当前页: %s" % (meta.get("url") or "")[:110])
    print("[验证监测] 判定: %s" % why)

    if not hit:
        print("[验证监测] ✓ 无验证拦截，可直接继续")
        return 0

    print("")
    print("=" * 60)
    print("  ⚠ 检测到人机验证，需要你手动完成")
    print("  ─────────────────────────────────────────")
    print("  请在浏览器中打开该标签页，按提示拖动滑块。")
    print("  完成后无需通知我，本工具会自动检测到并继续。")
    print("  （人机验证须真人完成，程序不代做）")
    print("=" * 60)

    if args.shot:
        fn = take_shot()
        if fn:
            print("  已保存验证页截图: %s" % fn)

    t0 = time.time()
    n = 0
    while time.time() - t0 < args.timeout:
        time.sleep(args.interval)
        n += 1
        meta = detect(args.site or None)
        hit, why = is_verify_page(meta)
        el = int(time.time() - t0)
        if not hit:
            print("\n[验证监测] ✓ 验证已通过（等待 %d 秒）— 可以继续流程" % el)
            return 2
        if n % 5 == 0:
            print("  ... 仍在等待验证（已等 %d 秒 / 上限 %d 秒） 当前: %s" % (
                el, args.timeout, why))

    print("\n[验证监测] ✗ 等待超时（%d 秒），验证仍未通过" % args.timeout)
    print("           请确认浏览器是否已打开验证标签页并完成拖动")
    return 3


if __name__ == "__main__":
    sys.exit(main())
