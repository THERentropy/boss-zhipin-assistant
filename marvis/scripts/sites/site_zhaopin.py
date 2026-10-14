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
        """打开职位列表。

        注意: 智联的 `jl` 城市参数不稳定（实测会返回全国职位），
        因此这里做「城市校验 + 自动回退」: 若搜索结果不含目标城市，
        则回退到推荐页（推荐页基于账号求职期望，已限定罗湖/深圳）。
        """
        if keyword:
            url = "https://www.zhaopin.com/jobs/?kw=%s" % quote(keyword)
            self.go(url, wait=(8, 10))
            probe = self.extract_cards()[:6]
            locs = [(c.get("location") or "").replace(" ", "") for c in probe]
            hit = sum(1 for l in locs if city and city in l)
            if locs and hit * 2 < len(locs):
                print("  [智联] 关键词结果仅 %d/%d 条在%s，回退推荐页" % (hit, len(locs), city))
                self.go(self.home, wait=(8, 10))
        else:
            self.go(self.home, wait=(8, 10))
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
        """点击「立即投递」→ 等待结果弹窗 → 点击「留在此页」

        实测（2026-10-14）成功文案:
          弹窗 "已向对方发送简历和打招呼语"，按钮由「立即投递」变为「继续沟通」
        """
        # 已是沟通/已投递状态
        btn = self.js(
            "(function(){var b=document.querySelector('.job-detail-summary__apply');"
            "return b?b.innerText.trim():'';})()"
        ) or ""
        if ("继续沟通" in btn) or ("已投递" in btn) or ("已申请" in btn):
            return "skip", "当前已是「%s」状态" % btn

        r = self.js(r"""
        (function(){
          var b = document.querySelector('.job-detail-summary__apply');
          if (!b) return 'no_button';
          b.scrollIntoView({block: 'center'});
          b.click();
          return 'clicked:' + (b.innerText || '').trim();
        })()
        """) or "no_button"

        if r == "no_button":
            return "fail", "未找到「立即投递」按钮"
        if not r.startswith("clicked:"):
            return "unknown", "点击返回: %s" % r

        time.sleep(2.5)

        # 检测投递结果弹窗（智联文案：已向对方发送简历和打招呼语）
        sent = self.js(r"""
        (function(){
          var t = document.body ? document.body.innerText : '';
          if (t.indexOf('已向对方发送简历') >= 0) return 'sent_popup';
          if (t.indexOf('发送简历') >= 0 && t.indexOf('打招呼') >= 0) return 'sent_text';
          if (t.indexOf('投递成功') >= 0) return 'sent_success';
          return '';
        })()
        """) or ""

        # 点击「留在此页」——绝不可点「继续沟通」（会跳转聊天页）
        stay = self.click_text("留在此页", "button, a, div, span")
        time.sleep(1.0)

        # 复核按钮状态
        btn2 = self.js(
            "(function(){var b=document.querySelector('.job-detail-summary__apply');"
            "return b?b.innerText.trim():'';})()"
        ) or ""

        if sent:
            return "success", "投递成功(%s; 按钮→%s; %s)" % (sent, btn2 or "?", stay)
        if "继续沟通" in btn2:
            return "success", "投递成功(按钮已变为继续沟通; %s)" % stay
        return "unknown", "点击后未检测到成功标志 (btn=%s; stay=%s)" % (btn2 or "?", stay)
