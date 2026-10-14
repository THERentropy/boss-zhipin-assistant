#!/usr/bin/env python3
"""前程无忧 (51job.com) 适配器

已验证结构（2026-10）:
  首页推荐卡 : .card.specialCard      （内含 a[href*='jobs.51job.com/.../{id}.html']）
  详情页     : https://jobs.51job.com/{area}/{jobId}.html
  投放按钮   : .apply-btn-new   ("立即投递")   备用: 文本"立即投递"的 div
  登录标志   : 页面出现 "Hi，用户名" / "在线简历"
  搜索结果页 : https://we.51job.com/pc/search?keyword=<kw>
"""

import json
import time
from urllib.parse import quote

from scripts.sites.base import SiteAdapter, register


@register
class Job51Adapter(SiteAdapter):
    name = "51job"
    display = "前程无忧"
    home = "https://www.51job.com/"

    CARD_SEL = ".card.specialCard, .joblist-item, .j_joblist .e"
    APPLY_SEL = ".apply-btn-new"

    # ══════════════ 登录 ══════════════

    def is_logged_in(self):
        txt = self.page_text()
        if "登录/注册" in txt or "请登录" in txt:
            return False
        return ("在线简历" in txt) or ("我的投递" in txt) or ("Hi，" in txt)

    # ══════════════ 列表 ══════════════

    def open_list(self, keyword=None, city="深圳"):
        if keyword:
            url = "https://we.51job.com/pc/search?keyword=%s" % quote(keyword)
        else:
            url = self.home
        self.go(url, wait=(8, 10))
        return True

    def count_cards(self):
        raw = self.js("document.querySelectorAll(\"a[href*='jobs.51job.com']\").length") or "0"
        try:
            return int(str(raw).split(".")[0])
        except Exception:
            return 0

    def extract_cards(self):
        """从首页推荐位或搜索页提取职位卡片"""
        js = r"""
        (function(){
          var out = [];
          var seen = {};
          var cards = document.querySelectorAll('.card, .joblist-item, .j_joblist .e, [class*=joblist] li');
          var push = function(el){
            var a = el.querySelector("a[href*='jobs.51job.com']");
            if (!a) return;
            var href = a.getAttribute('href') || '';
            var m = href.match(/\/(\d{6,})\.html/);
            if (!m) return;
            var jid = m[1];
            if (seen[jid]) return;
            seen[jid] = 1;
            var txt = (el.innerText || '').replace(/\s+/g, ' ').trim();
            out.push({
              job_id: jid,
              title: (el.querySelector('.jobName, [class*=jobName], .jname, h3') || {}).innerText || txt.slice(0, 40),
              salary: ((txt.match(/[\d.]+-[\d.]+[万千元·薪]*/) || [''])[0]),
              company: ((el.querySelector('.cname, [class*=company], .t2') || {}).innerText || '').trim(),
              location: '',
              tags: txt.slice(0, 220),
              url: href.indexOf('http') === 0 ? href : ('https:' + href),
              raw: txt.slice(0, 240)
            });
          };
          for (var i = 0; i < cards.length; i++) push(cards[i]);
          if (!out.length) {
            var as = document.querySelectorAll("a[href*='jobs.51job.com']");
            for (var j = 0; j < as.length; j++) push(as[j].closest('div,li') || as[j]);
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

    def open_job(self, url_or_id):
        """51job 详情为独立页面：直接打开"""
        u = str(url_or_id)
        if u.startswith("http"):
            url = u
        else:
            url = "https://jobs.51job.com/%s.html" % u
        self.go(url, wait=(8, 10))
        return "jobs.51job.com" in self.current_url()

    def read_jd(self):
        js = r"""
        (function(){
          var sels = ['.job-detail-section', '.tCompany_main', '[class*=job-detail]', '.bmsg.job_msg', '.job_msg'];
          for (var i = 0; i < sels.length; i++) {
            var e = document.querySelector(sels[i]);
            if (e && (e.innerText || '').trim().length > 80) {
              return (e.innerText || '').replace(/\n{3,}/g, '\n\n').slice(0, 4000);
            }
          }
          var body = document.body ? document.body.innerText : '';
          return body.replace(/\n{3,}/g, '\n\n').slice(0, 2500);
        })()
        """
        return self.js(js) or ""

    def page_meta(self):
        js = r"""
        (function(){
          return JSON.stringify({
            title: document.title,
            url: window.location.href,
            body_head: (document.body ? document.body.innerText : '').replace(/\s+/g, ' ').slice(0, 300)
          });
        })()
        """
        raw = self.js(js)
        try:
            return json.loads(raw) if raw else {}
        except Exception:
            return {}

    # ══════════════ 投递 ══════════════

    def apply(self, job_id=None):
        """点击「立即投递」"""
        txt = self.page_text()
        if "已投递" in txt or "已申请" in txt:
            return "skip", "页面显示已投递"

        r = self.js(r"""
        (function(){
          var b = document.querySelector('.apply-btn-new');
          if (!b) {
            var all = document.querySelectorAll('div,a,button,span');
            for (var i = 0; i < all.length; i++) {
              var el = all[i];
              if (el.children.length > 0) continue;
              if ((el.textContent || '').trim() === '立即投递') { b = el; break; }
            }
          }
          if (!b) return 'no_button';
          var t = (b.innerText || '').trim();
          b.scrollIntoView({block: 'center'});
          b.click();
          return 'clicked:' + t;
        })()
        """) or "no_button"

        if r == "no_button":
            return "fail", "未找到「立即投递」按钮"
        if not r.startswith("clicked:"):
            return "unknown", "点击返回: %s" % r

        time.sleep(2.5)

        confirm = self.js(r"""
        (function(){
          var all = document.querySelectorAll('button,a,div,span');
          for (var i = 0; i < all.length; i++) {
            var el = all[i];
            if (el.children.length > 0) continue;
            var t = (el.textContent || '').trim();
            if (t === '确认' || t === '确定' || t === '确认投递' || t === '继续投递') {
              var r = el.getBoundingClientRect();
              if (r.width > 0 && r.height > 0) { el.click(); return 'confirmed:' + t; }
            }
          }
          return 'no_confirm';
        })()
        """) or "no_confirm"

        time.sleep(1.5)

        # 实测：51job 投递成功后会跳转到 applysuccess.php?jobid=xxx
        url = self.current_url()
        if "applysuccess" in url:
            return "success", "投递成功(跳转至 %s)" % url.split("?")[0]

        txt2 = self.page_text()
        if ("投递成功" in txt2) or ("申请成功" in txt2) or ("简历已发送" in txt2) or confirm.startswith("confirmed:"):
            return "success", "投递成功 (%s / %s)" % (r, confirm)
        return "unknown", "未检测到成功标志 (%s / %s)" % (r, confirm)
