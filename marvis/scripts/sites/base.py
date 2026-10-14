#!/usr/bin/env python3
"""多站点适配层 — 统一接口基类

支持站点: 智联招聘(zhaopin) / 猎聘(liepin) / 前程无忧(51job) / BOSS直聘(boss)

设计原则:
  - 每个站点一个 adapter，实现同名接口
  - 上层（采集/筛选/投递）与具体站点解耦
  - 所有浏览器操作统一走 scripts/webbridge_client

统一接口:
    adapter.is_logged_in() -> bool
    adapter.open_list(keyword=None, city="") -> bool      # 打开职位列表/搜索页
    adapter.extract_cards() -> list[dict]                  # 提取职位卡片
    adapter.open_job(job_id) -> bool                       # 展开某职位详情
    adapter.read_jd() -> str                               # 读取当前详情 JD 文本
    adapter.apply(job_id) -> (status, detail)              # 投递

卡片字段约定:
    {"job_id", "title", "salary", "company", "location", "tags", "url", "raw"}
"""

import json
import os
import re
import sys
import time

SKILL_DIR = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
if SKILL_DIR not in sys.path:
    sys.path.insert(0, SKILL_DIR)

from scripts.webbridge_client import api, evaluate, navigate, scroll_page, SESSION


# ══════════════ 地址黑名单 ══════════════
# 与 user_profile.json 的「地址黑名单」保持一致，供各站点在采集/读 JD 阶段统一过滤。
# 说明: 福田区信息枢纽大厦聚集电话客服外包与中介招聘，用户明确要求不投。
ADDRESS_BLACKLIST = [
    "信息枢纽大厦",
]

# 通勤过远的区域（罗湖出发约 50 分钟以上）
DISTRICT_BLACKLIST = [
    "宝安", "光明", "坪山", "大鹏", "葵涌", "深汕",
]


def is_blacklisted_address(address):
    """地址是否命中黑名单（地址黑名单 or 远郊区域）"""
    if not address:
        return False
    addr = str(address)
    for kw in ADDRESS_BLACKLIST:
        if kw in addr:
            return True
    return False


def is_far_district(address):
    """地址是否位于通勤过远的区域"""
    if not address:
        return False
    addr = str(address)
    for kw in DISTRICT_BLACKLIST:
        if kw in addr:
            return True
    return False


class SiteAdapter(object):
    """站点适配器基类"""

    name = "base"
    display = "base"
    home = ""

    # 子类可覆盖；默认使用模块级黑名单
    address_blacklist = ADDRESS_BLACKLIST
    district_blacklist = DISTRICT_BLACKLIST

    def __init__(self, session=SESSION):
        self.session = session

    # ══════════════ 基础设施 ══════════════

    def js(self, code):
        return evaluate(code, session=self.session)

    # ══════════════ 焦点模拟（关键） ══════════════
    # WebBridge 操作的标签页处于后台，部分站点（如智联的 vue-clamp）
    # 在视口不可见时不渲染文本，导致标题为空。启用焦点模拟可解决。

    def enable_focus(self):
        try:
            r = api("cdp", {"method": "Emulation.setFocusEmulationEnabled",
                            "params": {"enabled": True}}, session=self.session)
            return bool(r.get("ok"))
        except Exception:
            return False

    def disable_focus(self):
        try:
            r = api("cdp", {"method": "Emulation.setFocusEmulationEnabled",
                            "params": {"enabled": False}}, session=self.session)
            return bool(r.get("ok"))
        except Exception:
            return False

    def go(self, url, wait=(6, 8)):
        return navigate(url, wait_range=wait, session=self.session)

    def current_url(self):
        return self.js("window.location.href") or ""

    def page_text(self):
        raw = self.js("document.body ? document.body.innerText : ''") or ""
        return raw

    @staticmethod
    def norm(text):
        if text is None:
            return ""
        return re.sub(r"\s+", " ", str(text)).strip()

    def body_has(self, keyword):
        return keyword in self.page_text()

    def scroll_until(self, count_js, target, max_rounds=12, wait=2.0):
        """滚动加载直到数量达标或稳定（返回最终数量）"""
        last = -1
        stable = 0
        for _ in range(max_rounds):
            raw = self.js(count_js) or "0"
            try:
                cur = int(str(raw).split(".")[0])
            except Exception:
                cur = 0
            if cur >= target:
                return cur
            if cur == last:
                stable += 1
                if stable >= 3:
                    return cur
            else:
                stable = 0
            last = cur
            scroll_page(session=self.session)
            time.sleep(wait)
        return last if last > 0 else 0

    def click_text(self, text, tag_scope="button, a, div, span"):
        """按可见文本点击（返回 'clicked:tag.class' 或 'not_found'）"""
        code = r"""
        (function(){
          var want = %s;
          var els = document.querySelectorAll(%s);
          for (var i=0;i<els.length;i++){
            var el = els[i];
            if (el.children.length > 0) continue;
            var t = (el.textContent||'').trim();
            if (t !== want) continue;
            var r = el.getBoundingClientRect();
            if (r.width <= 0 || r.height <= 0) continue;
            el.scrollIntoView({block:'center'});
            el.click();
            return 'clicked:' + el.tagName + '.' + (typeof el.className === 'string' ? el.className.slice(0,40) : '');
          }
          return 'not_found';
        })()
        """ % (json.dumps(text), tag_scope)
        return self.js(code) or "not_found"

    # ══════════════ 需子类实现 ══════════════

    def is_logged_in(self):
        raise NotImplementedError

    def open_list(self, keyword=None, city=""):
        raise NotImplementedError

    def extract_cards(self):
        raise NotImplementedError

    def open_job(self, job_id):
        raise NotImplementedError

    def read_jd(self):
        raise NotImplementedError

    def apply(self, job_id):
        raise NotImplementedError


ADAPTERS = {}


def register(cls):
    ADAPTERS[cls.name] = cls
    return cls


def get_adapter(name):
    """按名称获取适配器实例（会自动加载全部站点模块）"""
    from scripts.sites import site_zhaopin  # noqa: F401
    from scripts.sites import site_liepin   # noqa: F401
    from scripts.sites import site_51job    # noqa: F401

    if name not in ADAPTERS:
        raise KeyError("unknown site '%s'; available: %s" % (name, sorted(ADAPTERS.keys())))
    return ADAPTERS[name]()


def list_sites():
    from scripts.sites import site_zhaopin  # noqa: F401
    from scripts.sites import site_liepin   # noqa: F401
    from scripts.sites import site_51job    # noqa: F401
    return sorted(ADAPTERS.keys())
