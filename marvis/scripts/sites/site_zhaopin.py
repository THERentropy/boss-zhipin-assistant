#!/usr/bin/env python3
"""智联招聘 (zhaopin.com) 适配器

已验证结构（2026-10）:
  列表页   : https://www.zhaopin.com/jobs/?kw=<kw>&jl=489     (jl=489 深圳)
  卡片     : .job-card          （激活态 .job-card--active）
    标题   : .job-card__title-main
    薪资   : .job-card__salary
    公司   : .job-card__company-name
    地点   : .job-card__location
    标签   : .job-card__skill-tags
  详情面板 : .job-detail-card   （同页右侧，点卡片即切换）
  投递按钮 : .job-detail-summary__apply  ("立即投递")
  登录标志 : 页面出现 "编辑期望" / "吴先生"
"""

import json
import time
from urllib.parse import quote

from scripts.sites.base import SiteAdapter, register


def _js_json(code):
    return (code or "[]").strip()


@register
class ZhaoPinAdapter(SiteAdapter):
    name = "zhaopin"
    display = "智联招聘"
    home = "https://www.zhaopin.com/jobs/?pageMode=recommend"

    CARD = ".job-card"
    CARD_ACTIVE = ".job-card--active"
    DETAIL = ".job-detail-card"
    APPLY_SEL = ".job-detail-summary__apply"

    CITY_JL = {"深圳": "489"}

    # ══════════════ 登录 ══════════════

    def is_logged_in(self):
        txt = self.page_text()
        if "登录/注册" in txt or "请先登录" in txt:
            return False
        return ("编辑期望" in txt) or ("我的简历" in txt)

    # ══════════════ 列表 ══════════════

    def open_list(self, keyword=None, city="深圳"):
        jl = self.CITY_JL.get(city, "489")
        if keyword:
            url = "https://www.zhaopin.com/jobs/?kw=%s&jl=%s" % (quote(keyword), jl)
        else:
            url = self.home
        self.go(url, wait=(8, 10))
        return self.count_cards() > 0

    def count_cards(self):
        raw = self.js("document.querySelectorAll('%s').length" % self.CARD) or "0"
        try:
            return int(str(raw).split(".")[0])
        except Exception:
            return 0

    def load_more(self, target=60, max_rounds=12):
        """滚动加载更多卡片"""
        return self.scroll_until(
            "document.querySelectorAll('%s').length" % self.CARD,
            target, max_rounds=max_rounds, wait=2.0,
        )

    def extract_cards(self):
        js = r"""
        (function(){
          var out = [];
          var cards = document.querySelectorAll('.job-card');
          var q = function(scope, sel){
            var e = scope.querySelector(sel);
            return e ? (e.textContent || '').replace(/\s+/g, ' ').trim() : '';
          };
          for (var i = 0; i < cards.length; i++) {
            var c = cards[i];
            // 智联卡片无独立职位 ID（链接指向公司页），统一用索引标识
            var a = c.querySelector("a[href*='job'], a[href*='position']");
            var href = a ? (a.getAttribute('href') || '') : '';
            var jid = 'zp-' + i;
            var title = q(c, '.job-card__title-main') || q(c, '.job-card__title');
            out.push({
              job_id: jid,
              title: title,
              salary: q(c, '.job-card__salary'),
              company: q(c, '.job-card__company-name'),
              location: q(c, '.job-card__location'),
              tags: q(c, '.job-card__skill-tags'),
              url: href,
              raw: (c.innerText || '').replace(/\s+/g, ' ').slice(0, 240)
            });
          }
          return JSON.stringify(out);
        })()
        """
        raw = self.js(js)
        try:
            return json.loads(raw) if raw else []
        except Exception:
            return []

    # ══════════════ 详情 ══════════════

    def open_job(self, job_id):
        """点击列表中第 index 张卡片，展开右侧详情（智联为同页双栏）

        job_id 约定为 'zp-<index>'；若传入纯数字则视为索引。
        """
        s = str(job_id)
        if s.startswith("zp-"):
            s = s.split("-", 1)[1]
        try:
            idx = int(s)
        except Exception:
            return False

        r = self.js(
            "(function(){var c=document.querySelectorAll('.job-card')[%d];"
            "if(!c)return 'not_found';c.scrollIntoView({block:'center'});c.click();return 'clicked';})()" % idx
        )
        if r == "clicked":
            time.sleep(2.5)
            return True
        return False

    def read_jd(self):
        js = r"""
        (function(){
          var d = document.querySelector('.job-detail-card');
          if (!d) return '';
          var t = (d.innerText || '');
          return t.replace(/\n{3,}/g, '\n\n').slice(0, 4000);
        })()
        """
        return self.js(js) or ""

    def detail_summary(self):
        js = r"""
        (function(){
          var d = document.querySelector('.job-detail-card');
          if (!d) return '{}';
          var q = function(sel){
            var e = d.querySelector(sel);
            return e ? (e.innerText || '').trim() : '';
          };
          return JSON.stringify({
            title: q('.job-detail-card__title') || q('h3') || q('.job-detail-summary__title'),
            body: (d.innerText || '').replace(/\s+/g, ' ').slice(0, 400)
          });
        })()
        """
        raw = self.js(js)
        try:
            return json.loads(raw) if raw else {}
        except Exception:
            return {}

    # ══════════════ 投递 ══════════════

    def has_applied(self):
        txt = self.page_text()
        return ("已投递" in txt) or ("已申请" in txt)

    def apply(self, job_id=None):
        """点击「立即投递」；返回 (status, detail)"""
        # 检查是否已投递
        if self.has_applied():
            return "skip", "页面显示已投递"

        r = self.js(r"""
        (function(){
          var b = document.querySelector('.job-detail-summary__apply');
          if (!b) return 'no_button';
          var t = (b.innerText || '').trim();
          if (t.indexOf('已投递') >= 0 || t.indexOf('已申请') >= 0) return 'already:' + t;
          b.scrollIntoView({block: 'center'});
          b.click();
          return 'clicked:' + t;
        })()
        """) or "no_button"

        if r.startswith("already:"):
            return "skip", r
        if r == "no_button":
            return "fail", "未找到立即投递按钮"
        if not r.startswith("clicked:"):
            return "unknown", "点击返回: %s" % r

        time.sleep(2.5)

        # 处理可能的确认弹窗
        confirm = self.js(r"""
        (function(){
          var btns = document.querySelectorAll('button, a, div[class*=btn], span[class*=btn]');
          for (var i = 0; i < btns.length; i++) {
            var el = btns[i];
            if (el.children.length > 0) continue;
            var t = (el.textContent || '').trim();
            if (t === '确认投递' || t === '确定' || t === '确认' || t === '继续投递') {
              var r = el.getBoundingClientRect();
              if (r.width > 0 && r.height > 0) { el.click(); return 'confirmed:' + t; }
            }
          }
          return 'no_confirm';
        })()
        """) or "no_confirm"

        time.sleep(1.5)
        txt = self.page_text()
        if "投递成功" in txt or "已投递" in txt or "已申请" in txt or confirm.startswith("confirmed:"):
            return "success", "投递成功 (%s / %s)" % (r, confirm)
        return "unknown", "点击后未检测到成功标志 (%s / %s)" % (r, confirm)
