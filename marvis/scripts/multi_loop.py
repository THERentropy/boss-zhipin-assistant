#!/usr/bin/env python3
"""多站点自动投递 — 三层循环主控制器

外层 (站点级): zhaopin(智联) → liepin(猎聘) → 51job(前程无忧)
中层 (关键词级): 每个站点按关键词采集一批职位
内层 (岗位级): 逐条读 JD → AI 决策 → 投递 → 检查每日目标

命令体系:
    --step init                                 环境检查 + 登录检测 + 启用焦点模拟
    --step collect [--site X] [--keyword-file f] 采集一批职位到 pending
    --step read --index N                       读取第 N 条的 JD → current_jd.json
    --step apply --index N                      按 decision.json 执行投递
    --step status                               查看三层进度
    --step next-keyword                         切换关键词并采集下一批
    --step next-site                            切换到下一站点
    --step finish                               生成投递汇总报告

信号文件 (位于 WORK_DIR):
    multi_state.json   — 三层循环状态
    current_jd.json    — 当前 JD（供 AI 阅读）
    decision.json      — AI 决策 {"decision":"APPROVE"/"REJECT","reason":"..."}
"""

import argparse
import json
import os
import sys
import time
from datetime import datetime

SKILL_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if SKILL_DIR not in sys.path:
    sys.path.insert(0, SKILL_DIR)

from scripts.profile_loader import WORK_DIR
from scripts.sites import get_adapter, list_sites
from scripts.webbridge_client import health_check, ensure_active_tab

STATE_FILE = os.path.join(WORK_DIR, "multi_state.json")
CURRENT_JD = os.path.join(WORK_DIR, "current_jd.json")
DECISION_FILE = os.path.join(WORK_DIR, "decision.json")
REPORT_FILE = os.path.join(WORK_DIR, "多站投递汇总.html")

DEFAULT_SITES = ["zhaopin", "liepin", "51job"]

DEFAULT_KEYWORDS = [
    "物业管理", "物业客服", "物业管家", "行政助理", "文员",
    "资料员", "前台", "客服", "电工", "综合维修",
]


# ═══════════════════════════════════════════════════════════
# 状态管理
# ═══════════════════════════════════════════════════════════

def _default_state():
    return {
        "sites": list(DEFAULT_SITES),
        "site_index": 0,
        "keyword_index": 0,
        "keywords": list(DEFAULT_KEYWORDS),
        "tried": {},            # {site: [keyword, ...]}
        "pending": [],          # 当前批次待处理岗位
        "cursor": 0,            # pending 游标（下一条待读）
        "processed": [],        # 已决策岗位 [{index, job_id, title, decision, status}]
        "delivered": [],        # 成功投递 [{site, title, company, salary, url, city}]
        "daily_target": 30,
        "started_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
    }


def load_state():
    if os.path.exists(STATE_FILE):
        try:
            with open(STATE_FILE, "r", encoding="utf-8") as f:
                s = json.load(f)
            base = _default_state()
            base.update(s)
            return base
        except Exception:
            pass
    return _default_state()


def save_state(state):
    with open(STATE_FILE, "w", encoding="utf-8") as f:
        json.dump(state, f, ensure_ascii=False, indent=2)


def cur_site(state):
    return state["sites"][state["site_index"]]


def cur_keyword(state):
    kws = state["keywords"]
    return kws[state["keyword_index"]] if state["keyword_index"] < len(kws) else None


def _write_json(path, data):
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


def _read_json(path):
    if not os.path.exists(path):
        return None
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return None


# ═══════════════════════════════════════════════════════════
# 步骤 0: 环境检查
# ═══════════════════════════════════════════════════════════

def step_init(sites=None):
    print("[初始化] ═══ 多站点自动投递启动 ═══")
    if not health_check():
        print("[初始化] ERROR: WebBridge 不可达，请先启动 kimi-webbridge")
        return False
    if not ensure_active_tab():
        print("[初始化] ERROR: 无法建立标签页")
        return False
    print("[初始化] WebBridge 环境正常")

    state = load_state()
    if sites:
        state["sites"] = sites
    state["site_index"] = 0
    state["keyword_index"] = 0
    state["pending"] = []
    state["cursor"] = 0
    state["started_at"] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    save_state(state)

    # 逐站点登录检测（必须逐个导航到站点首页，否则读到的是上一个站点的页面）
    for name in state["sites"]:
        try:
            ad = get_adapter(name)
            ad.enable_focus()
            if ad.home:
                ad.go(ad.home, wait=(7, 9))
            ok = ad.is_logged_in()
            print("[初始化] %-10s 登录: %s" % (ad.display, "是" if ok else "否 ← 需手动登录"))
        except Exception as e:
            print("[初始化] %-10s 检测异常: %s" % (name, e))

    print("[初始化] ★ 待处理站点: %s" % ", ".join(state["sites"]))
    print("[初始化] ★ 下一步: python multi_loop.py --step collect")
    return True


# ═══════════════════════════════════════════════════════════
# 中层: 采集一批
# ═══════════════════════════════════════════════════════════

def step_collect(site=None, keyword=None):
    state = load_state()
    if site:
        if site not in state["sites"]:
            state["sites"].append(site)
        state["site_index"] = state["sites"].index(site)
    site = cur_site(state)
    kw = keyword or cur_keyword(state)

    ad = get_adapter(site)
    ad.enable_focus()
    print("[采集] 站点=%s 关键词=%s" % (ad.display, kw or "(推荐页)"))

    # 先导航到该站点，再判断登录（顺序不能反，否则读到的是上一个站点的页面）
    opened = ad.open_list(keyword=kw)
    if not ad.is_logged_in():
        print("[采集] ERROR: %s 未登录，请先在浏览器登录" % ad.display)
        return False
    if not opened:
        print("[采集] 警告: 列表页可能未正确加载")
    before = ad.count_cards()
    after = ad.load_more(target=30) if hasattr(ad, "load_more") else before
    cards = ad.extract_cards()
    print("[采集] 卡片: 初始 %s → 加载后 %s，提取 %s 条" % (before, after, len(cards)))

    # 记录已尝试关键词
    if kw:
        tried = state["tried"].setdefault(site, [])
        if kw not in tried:
            tried.append(kw)

    # 去重（同站点+job_id 已在 processed/delivered 中的跳过）
    done_ids = set()
    for p in state["processed"]:
        done_ids.add((p.get("site"), p.get("job_id")))
    for d in state["delivered"]:
        done_ids.add((d.get("site"), d.get("job_id")))

    pending = []
    for c in cards:
        jid = c.get("job_id")
        if (site, jid) in done_ids:
            continue
        c["site"] = site
        c["status"] = "pending"
        pending.append(c)

    state["pending"] = pending
    state["cursor"] = 0
    save_state(state)
    _write_json(CURRENT_JD, None)

    print("[采集] 去重后待处理: %d 条" % len(pending))
    for i, c in enumerate(pending[:15]):
        print("  [%2d] %-30s %-14s %-20s %s" % (
            i, (c.get("title") or "")[:28], (c.get("salary") or "")[:12],
            (c.get("company") or "")[:18], (c.get("location") or "")[:14]))
    if len(pending) > 15:
        print("  ... 共 %d 条" % len(pending))

    print("\n[采集] ★ 下一步: python multi_loop.py --step read --index 0")
    return len(pending) > 0


# ═══════════════════════════════════════════════════════════
# 内层: 读 JD / 投递
# ═══════════════════════════════════════════════════════════

def step_read(index):
    state = load_state()
    pending = state["pending"]
    if not pending:
        print("ERROR: pending 为空，请先 --step collect")
        return False
    if index < 0 or index >= len(pending):
        print("ERROR: index 超出范围 0~%d" % (len(pending) - 1))
        return False

    job = pending[index]
    site = job.get("site") or cur_site(state)
    ad = get_adapter(site)
    ad.enable_focus()

    print("[读取] [%d/%d] %s | %s | %s" % (
        index, len(pending), job.get("title"), job.get("salary"), job.get("company")))

    # 智联为同页双栏：若当前不在列表页需重新打开
    target = job.get("job_id")
    if not str(target).startswith("http") and not str(target).startswith("zp-"):
        ad.open_list(keyword=None)

    ok = ad.open_job(target)
    if not ok:
        print("[读取] 打开职位失败")
        return False

    jd = ad.read_jd()
    meta = ad.page_meta() if hasattr(ad, "page_meta") else {}
    if not jd:
        print("[读取] WARN: JD 为空")
        jd = ""

    _write_json(CURRENT_JD, {
        "site": site,
        "index": index,
        "job_id": target,
        "title": job.get("title"),
        "salary": job.get("salary"),
        "company": job.get("company"),
        "location": job.get("location"),
        "url": job.get("url"),
        "tags": job.get("tags"),
        "jd_text": jd[:4000],
        "page_title": (meta or {}).get("title", ""),
    })
    # 清理上一轮决策
    if os.path.exists(DECISION_FILE):
        _write_json(DECISION_FILE, None)

    print("[读取] JD 已写入 current_jd.json (%d 字)" % len(jd))
    print("[读取] ★ 等待 AI 阅读并写入 decision.json:")
    print('       {"decision": "APPROVE"|"REJECT", "reason": "..."}')
    return True


def step_apply(index):
    state = load_state()
    pending = state["pending"]
    if index < 0 or index >= len(pending):
        print("ERROR: index 超出范围")
        return False
    job = pending[index]
    site = job.get("site") or cur_site(state)

    dec = _read_json(DECISION_FILE) or {}
    decision = (dec.get("decision") or "").upper()
    reason = dec.get("reason", "")
    if decision not in ("APPROVE", "REJECT"):
        print("ERROR: decision.json 无效（需要 APPROVE 或 REJECT）")
        return False

    entry = {
        "index": index, "site": site, "job_id": job.get("job_id"),
        "title": job.get("title"), "company": job.get("company"),
        "salary": job.get("salary"), "location": job.get("location"),
        "decision": decision, "reason": reason,
    }

    if decision == "REJECT":
        entry["status"] = "skipped"
        state["processed"].append(entry)
        save_state(state)
        _write_json(DECISION_FILE, None)
        print("[投递] 跳过: %s (%s)" % (job.get("title"), reason))
        _print_next_step(state, index)
        return True

    # APPROVE → 投递
    ad = get_adapter(site)
    ad.enable_focus()

    # 人机验证拦截检测：若被拦截则等待真人完成（默认最长 5 分钟），
    # 通过后流程自动继续，无需重跑。
    try:
        from scripts.verify_watch import ensure_no_verify, human_delay
        if not ensure_no_verify(timeout=300, adapter_name=site):
            print("[投递] 已暂停：人机验证未完成，请完成后重跑本步")
            return False
    except Exception as _e:
        print("[投递] 验证检测跳过: %s" % _e)
        human_delay = None

    target = job.get("job_id")
    if not str(target).startswith("http") and not str(target).startswith("zp-"):
        ad.open_list(keyword=None)

    opened = ad.open_job(target)
    if not opened:
        entry["status"] = "fail"
        entry["detail"] = "无法打开职位"
        state["processed"].append(entry)
        save_state(state)
        print("[投递] 失败: 无法打开职位")
        return False

    status, detail = ad.apply(target)
    entry["status"] = status
    entry["detail"] = detail
    state["processed"].append(entry)

    # 拟人化节奏：随机间隔，降低触发平台风控/验证的概率
    try:
        if human_delay:
            human_delay(2.5, 6.5)
    except Exception:
        pass

    if status == "success":
        state["delivered"].append({
            "site": site, "job_id": target, "title": job.get("title"),
            "company": job.get("company"), "salary": job.get("salary"),
            "location": job.get("location"), "url": job.get("url"),
            "time": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        })
    save_state(state)
    _write_json(DECISION_FILE, None)

    print("[投递] %s | %s" % (status.upper(), detail))
    print("[投递] 累计成功: %d/%d" % (len(state["delivered"]), state["daily_target"]))

    if len(state["delivered"]) >= state["daily_target"]:
        print("\n[投递] ★★★ 已达每日目标 %d 份，建议 --step finish ★★★" % state["daily_target"])
        return True

    _print_next_step(state, index)
    return status == "success"


def _print_next_step(state, index):
    nxt = index + 1
    if nxt < len(state["pending"]):
        print("[下一步] python multi_loop.py --step read --index %d" % nxt)
    else:
        nxt_site = state["site_index"] + 1
        nxt_kw = state["keyword_index"] + 1
        if nxt_kw < len(state["keywords"]):
            print("[下一步] 本批已处理完 → 换关键词:")
            print("         python multi_loop.py --step next-keyword")
        elif nxt_site < len(state["sites"]):
            print("[下一步] 本站点关键词已穷尽 → 换站点:")
            print("         python multi_loop.py --step next-site")
        else:
            print("[下一步] 全部站点完成 → python multi_loop.py --step finish")


def step_next_keyword():
    state = load_state()
    state["keyword_index"] += 1
    if state["keyword_index"] >= len(state["keywords"]):
        print("[循环] 本站点关键词已用完 → 请切换站点: --step next-site")
        return False
    kw = cur_keyword(state)
    print("[循环] 切换到关键词: %s" % kw)
    save_state(state)
    return step_collect()


def step_next_site():
    state = load_state()
    state["site_index"] += 1
    state["keyword_index"] = 0
    if state["site_index"] >= len(state["sites"]):
        print("[循环] 所有站点已完成 → python multi_loop.py --step finish")
        return False
    site = cur_site(state)
    print("[循环] 切换到站点: %s" % site)
    save_state(state)
    return step_collect()


# ═══════════════════════════════════════════════════════════
# 状态 / 收尾
# ═══════════════════════════════════════════════════════════

def step_status():
    state = load_state()
    site = cur_site(state)
    kw = cur_keyword(state)
    pending = state["pending"]
    idx = state["cursor"]
    delivered = state["delivered"]
    processed = state["processed"]

    approved = [p for p in processed if p.get("decision") == "APPROVE"]
    rejected = [p for p in processed if p.get("decision") == "REJECT"]
    failed = [p for p in approved if p.get("status") not in ("success",)]

    print("=" * 58)
    print("多站点投递进度")
    print("=" * 58)
    print("外层(站点)  当前: %s (%d/%d)  关键词: %s (%d/%d)" % (
        site, state["site_index"] + 1, len(state["sites"]),
        kw, state["keyword_index"] + 1, len(state["keywords"])))
    print("中层(批次)  pending: %d 条，游标: %d" % (len(pending), idx))
    print("内层(岗位)  已处理: %d  APPROVE: %d  REJECT: %d  投递失败: %d" % (
        len(processed), len(approved), len(rejected), len(failed)))
    print("目标        成功投递: %d / %d" % (len(delivered), state["daily_target"]))
    print("-" * 58)
    print("已尝试关键词:")
    for s, kws in state["tried"].items():
        print("  %-10s %s" % (s, ", ".join(kws) if kws else "(无)"))
    if delivered:
        print("-" * 58)
        print("最近投递:")
        for d in delivered[-5:]:
            print("  [%s] %s | %s | %s" % (d.get("site"), d.get("title"), d.get("company"), d.get("salary")))
    print("=" * 58)
    _print_next_step(state, idx - 1 if idx > 0 else -1)


def step_finish():
    from scripts.multi_report import build_multi_report
    state = load_state()
    out = build_multi_report(state, REPORT_FILE)
    if out:
        print("\n[完成] ★ 多站投递汇总已生成: %s" % out)
        print("[完成] 成功投递 %d 份（目标 %d）" % (len(state["delivered"]), state["daily_target"]))
        by_site = {}
        for d in state["delivered"]:
            by_site[d.get("site")] = by_site.get(d.get("site"), 0) + 1
        for s, n in by_site.items():
            print("       %-10s %d 份" % (s, n))
    else:
        print("[完成] ERROR: 报告生成失败")
    return bool(out)


# ═══════════════════════════════════════════════════════════
# CLI
# ═══════════════════════════════════════════════════════════

def main():
    ap = argparse.ArgumentParser(description="多站点自动投递 — 三层循环主控制器")
    ap.add_argument("--step", required=True,
                    choices=["init", "collect", "read", "apply", "status",
                             "next-keyword", "next-site", "finish"])
    ap.add_argument("--site", default="", help="站点: %s" % ",".join(list_sites()))
    ap.add_argument("--index", type=int, default=-1, help="岗位索引（read/apply）")
    ap.add_argument("--keyword-file", default="", help="关键词文件（UTF-8，一行）")
    ap.add_argument("--sites", default="", help="初始化时指定站点(逗号分隔)")
    args = ap.parse_args()

    if args.step == "init":
        sites = [s.strip() for s in args.sites.split(",") if s.strip()] if args.sites else None
        step_init(sites)

    elif args.step == "collect":
        kw = None
        if args.keyword_file:
            with open(args.keyword_file, "r", encoding="utf-8") as f:
                kw = f.read().strip()
        step_collect(site=args.site or None, keyword=kw)

    elif args.step == "read":
        if args.index < 0:
            print("ERROR: --index 必须 >= 0")
            sys.exit(1)
        step_read(args.index)

    elif args.step == "apply":
        if args.index < 0:
            print("ERROR: --index 必须 >= 0")
            sys.exit(1)
        step_apply(args.index)

    elif args.step == "status":
        step_status()

    elif args.step == "next-keyword":
        step_next_keyword()

    elif args.step == "next-site":
        step_next_site()

    elif args.step == "finish":
        step_finish()


if __name__ == "__main__":
    main()
