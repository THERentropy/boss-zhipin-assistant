#!/usr/bin/env python3
"""多站点投递汇总报告生成

输入: multi_state.json（由 multi_loop.py 维护）
输出: HTML 报告（可离线打开）

用法:
    python multi_report.py [--state multi_state.json] [--out 多站投递汇总.html]
"""

import argparse
import json
import os
import sys
from datetime import datetime

SKILL_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if SKILL_DIR not in sys.path:
    sys.path.insert(0, SKILL_DIR)

from scripts.profile_loader import WORK_DIR

SITE_LABEL = {
    "zhaopin": "智联招聘",
    "liepin": "猎聘",
    "51job": "前程无忧",
    "boss": "BOSS直聘",
}


def _esc(s):
    if s is None:
        return ""
    return (str(s).replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;"))


def build_multi_report(state, output_path):
    delivered = state.get("delivered", [])
    processed = state.get("processed", [])
    target = state.get("daily_target", 0)

    by_site = {}
    for d in delivered:
        by_site[d.get("site", "?")] = by_site.get(d.get("site", "?"), 0) + 1

    approved = [p for p in processed if p.get("decision") == "APPROVE"]
    rejected = [p for p in processed if p.get("decision") == "REJECT"]
    failed = [p for p in approved if p.get("status") not in ("success",)]

    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    rows = []
    for i, d in enumerate(delivered, 1):
        site = SITE_LABEL.get(d.get("site"), d.get("site", ""))
        url = d.get("url") or ""
        title = _esc(d.get("title"))
        if url:
            title = '<a href="%s" target="_blank">%s</a>' % (_esc(url), title)
        rows.append(
            "<tr><td class='num'>%d</td><td>%s</td><td>%s</td><td>%s</td>"
            "<td>%s</td><td>%s</td><td class='time'>%s</td></tr>" % (
                i, site, title, _esc(d.get("company")), _esc(d.get("salary")),
                _esc(d.get("location")), _esc((d.get("time") or "")[5:16])))
    if not rows:
        rows.append("<tr><td colspan='7' class='empty'>暂无投递记录</td></tr>")

    site_cards = "".join(
        "<div class='card'><div class='num-big'>%d</div><div class='lbl'>%s</div></div>" % (
            n, SITE_LABEL.get(s, s)) for s, n in sorted(by_site.items(), key=lambda x: -x[1]))
    if not site_cards:
        site_cards = "<div class='card'><div class='num-big'>0</div><div class='lbl'>暂无</div></div>"

    html = """<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="utf-8">
<title>多站投递汇总</title>
<style>
  * { box-sizing: border-box; }
  body { font-family: -apple-system, "Segoe UI", "Microsoft YaHei", sans-serif;
         background: #f5f6f8; margin: 0; padding: 28px 20px; color: #222; }
  .wrap { max-width: 1080px; margin: 0 auto; }
  h1 { font-size: 24px; margin: 0 0 6px; }
  .sub { color: #888; font-size: 13px; margin-bottom: 22px; }
  .stats { display: flex; gap: 12px; flex-wrap: wrap; margin-bottom: 24px; }
  .stat { background: #fff; border-radius: 10px; padding: 16px 22px; flex: 1 1 150px;
          box-shadow: 0 1px 4px rgba(0,0,0,.06); }
  .stat .n { font-size: 26px; font-weight: 700; color: #1a73e8; }
  .stat .t { font-size: 12px; color: #888; margin-top: 4px; }
  .cards { display: flex; gap: 12px; flex-wrap: wrap; margin-bottom: 26px; }
  .card { background: #fff; border-radius: 10px; padding: 14px 20px; min-width: 130px;
          box-shadow: 0 1px 4px rgba(0,0,0,.06); text-align: center; }
  .num-big { font-size: 22px; font-weight: 700; color: #0b8043; }
  .lbl { font-size: 12px; color: #666; margin-top: 4px; }
  table { width: 100%; border-collapse: collapse; background: #fff; border-radius: 10px;
          overflow: hidden; box-shadow: 0 1px 4px rgba(0,0,0,.06); }
  th { background: #fafafa; font-size: 12px; color: #666; font-weight: 600;
       text-align: left; padding: 11px 14px; border-bottom: 1px solid #eee; }
  td { padding: 11px 14px; font-size: 13px; border-bottom: 1px solid #f2f2f2; }
  tr:last-child td { border-bottom: none; }
  td.num { color: #aaa; width: 42px; }
  td.time { color: #999; font-size: 12px; white-space: nowrap; }
  td.empty { text-align: center; color: #aaa; padding: 40px; }
  a { color: #1a73e8; text-decoration: none; }
  a:hover { text-decoration: underline; }
  .foot { margin-top: 26px; color: #aaa; font-size: 12px; text-align: center; }
</style>
</head>
<body>
<div class="wrap">
  <h1>多站投递汇总</h1>
  <div class="sub">生成时间: {{now}} &nbsp;|&nbsp; 开始时间: {{started}}</div>

  <div class="stats">
    <div class="stat"><div class="n">{{n_delivered}}</div><div class="t">成功投递</div></div>
    <div class="stat"><div class="n">{{target}}</div><div class="t">当日目标</div></div>
    <div class="stat"><div class="n">{{n_approved}}</div><div class="t">AI 通过</div></div>
    <div class="stat"><div class="n">{{n_rejected}}</div><div class="t">AI 拒绝</div></div>
    <div class="stat"><div class="n">{{n_failed}}</div><div class="t">投递失败</div></div>
  </div>

  <div class="cards">{{site_cards}}</div>

  <table>
    <thead>
      <tr><th>#</th><th>站点</th><th>岗位</th><th>公司</th><th>薪资</th><th>地点</th><th>时间</th></tr>
    </thead>
    <tbody>
      {{rows}}
    </tbody>
  </table>

  <div class="foot">由 boss-zhipin-assistant · 多站点适配层生成</div>
</div>
</body>
</html>
"""

    # 用占位符替换（避免 CSS 中的 % 与字符串格式化冲突）
    values = {
        "{{now}}": now,
        "{{started}}": str(state.get("started_at", "-")),
        "{{n_delivered}}": str(len(delivered)),
        "{{target}}": str(target),
        "{{n_approved}}": str(len(approved)),
        "{{n_rejected}}": str(len(rejected)),
        "{{n_failed}}": str(len(failed)),
        "{{site_cards}}": site_cards,
        "{{rows}}": "\n      ".join(rows),
    }
    for k, v in values.items():
        html = html.replace(k, v)

    with open(output_path, "w", encoding="utf-8") as f:
        f.write(html)
    return output_path


def main():
    ap = argparse.ArgumentParser(description="多站点投递汇总报告")
    ap.add_argument("--state", default=os.path.join(WORK_DIR, "multi_state.json"))
    ap.add_argument("--out", default=os.path.join(WORK_DIR, "多站投递汇总.html"))
    args = ap.parse_args()

    if not os.path.exists(args.state):
        print("ERROR: 状态文件不存在: %s" % args.state)
        sys.exit(1)
    with open(args.state, "r", encoding="utf-8") as f:
        state = json.load(f)

    out = build_multi_report(state, args.out)
    print("报告已生成:", out)
    print("  成功投递: %d 份" % len(state.get("delivered", [])))


if __name__ == "__main__":
    main()
