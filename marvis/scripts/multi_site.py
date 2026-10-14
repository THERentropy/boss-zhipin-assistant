#!/usr/bin/env python3
"""多站点统一入口 CLI

支持站点: zhaopin(智联) / liepin(猎聘) / 51job(前程无忧)

用法:
  # 1) 采集职位卡片（关键词从文件读取，避免 Windows 命令行中文乱码）
  python multi_site.py --site zhaopin --action collect --keyword-file kw.txt --out jobs_zhaopin.json

  # 2) 读取某职位的 JD（传详情页 URL 或 job_id）
  python multi_site.py --site zhaopin --action read --target "<url或id>" --out jd.json

  # 3) 投递（传详情页 URL 或 job_id）
  python multi_site.py --site zhaopin --action apply --target "<url或id>"

  # 4) 登录检查
  python multi_site.py --site zhaopin --action check
"""

import argparse
import json
import os
import sys
import time

SKILL_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if SKILL_DIR not in sys.path:
    sys.path.insert(0, SKILL_DIR)

from scripts.sites import get_adapter, list_sites
from scripts.webbridge_client import health_check, ensure_active_tab


def _read_keyword(path):
    if not path:
        return None
    with open(path, "r", encoding="utf-8") as f:
        return f.read().strip()


def main():
    ap = argparse.ArgumentParser(description="多站点统一入口（智联/猎聘/51job）")
    ap.add_argument("--site", required=True, help="站点: %s" % ",".join(list_sites()))
    ap.add_argument("--action", required=True,
                    choices=["check", "collect", "read", "apply", "load_more"])
    ap.add_argument("--keyword-file", default="", help="关键词文件（UTF-8，一行）")
    ap.add_argument("--target", default="", help="详情页 URL 或 job_id")
    ap.add_argument("--out", default="", help="输出 JSON 路径")
    ap.add_argument("--target-count", type=int, default=60, help="collect 目标卡片数")
    args = ap.parse_args()

    if not health_check():
        print("ERROR: WebBridge 不可达")
        sys.exit(1)
    ensure_active_tab(timeout_wait=10)

    ad = get_adapter(args.site)
    result = {"site": args.site, "action": args.action}

    # 关键: 启用焦点模拟。WebBridge 标签页在后台时，部分站点（如智联 vue-clamp）
    # 不会渲染文本，导致职位标题为空。
    result["focus_emulation"] = ad.enable_focus()

    if args.action == "check":
        if ad.home:
            ad.go(ad.home, wait=(7, 9))
        result["logged_in"] = ad.is_logged_in()
        result["url"] = ad.current_url()
        result["body_head"] = ad.page_text().replace("\n", " ")[:160]

    elif args.action == "collect":
        kw = _read_keyword(args.keyword_file)
        result["keyword"] = kw
        result["opened"] = ad.open_list(keyword=kw)
        before = ad.count_cards()
        after = ad.load_more(target=args.target_count) if hasattr(ad, "load_more") else before
        cards = ad.extract_cards()
        result["cards_before"] = before
        result["cards_after"] = after
        result["count"] = len(cards)
        result["cards"] = cards

    elif args.action == "read":
        # 智联等「同页双栏」站点需先打开列表页，才能点击卡片。
        # 但 target 为 zp-<index> 时说明页面已是刚采集的列表页，不能再刷新（否则索引错位）。
        t = str(args.target)
        if not t.startswith("http") and not t.startswith("zp-"):
            kw = _read_keyword(args.keyword_file)
            result["list_opened"] = ad.open_list(keyword=kw)
        ok = ad.open_job(args.target)
        jd = ad.read_jd() if ok else ""
        meta = ad.page_meta() if hasattr(ad, "page_meta") else {}
        result.update({"ok": ok, "jd": jd, "meta": meta})

    elif args.action == "apply":
        t = str(args.target)
        if not t.startswith("http") and not t.startswith("zp-"):
            kw = _read_keyword(args.keyword_file)
            result["list_opened"] = ad.open_list(keyword=kw)
        ok = ad.open_job(args.target)
        status, detail = ad.apply(args.target) if ok else ("fail", "无法打开职位详情")
        result.update({"opened": ok, "status": status, "detail": detail})

    elif args.action == "load_more":
        result["count"] = ad.load_more(target=args.target_count)

    print(json.dumps(result, ensure_ascii=False, indent=2)[:4000])

    if args.out:
        with open(args.out, "w", encoding="utf-8") as f:
            json.dump(result, f, ensure_ascii=False, indent=2)
        print("saved:", args.out)


if __name__ == "__main__":
    main()
