#!/usr/bin/env python3
"""猎聘 (liepin.com) 适配器

已验证结构（2026-10）:
  推荐页     : https://c.liepin.com/
  搜索页     : https://www.liepin.com/zhaopin/?key=<kw>
  卡片       : .jobCardPcContainer (外层 .job-list-item)
    标题     : [class*=jobTitle] / .jobDetailBox a
    公司     : .jobDetailCompanyBox
  详情页     : https://www.liepin.com/job/{jobId}.shtml
  JD 容器    : .job-intro-container
  登录标志   : 页面出现 "你好，<用户名>" / "简历优化"
"""

import json
import time
from urllib.parse import quote

from scripts.sites.base import SiteAdapter, register


@register
class LiepinAdapter(SiteAdapter):
    name = "liepin"
    display = "猎聘"
    home = "https://c.liepin.com/"

    CARD = ".jobCardPcContainer"
    CARD_FALLBACK = ".job-list-item"
    JD_SEL = ".job-intro-container"

    # ══════════════ 登录 ══════════════

    def is_logged_in(self):
        txt = self.page_text()
        if "登录/注册" in txt or "请登录" in txt:
            return False
        return ("你好，" in txt) or ("简历优化" in txt and "我要招人" in txt)

    # ══════════════ 列表 ══════════════

    def open_list(self, keyword=None, city="深圳"):
        if keyword:
            url = "https://www.liepin.com/zhaopin/?key=%s" % quote(keyword)
        else:
            url = self.home
        self.go(url, wait=(8, 10))
        time.sleep(2)
        return self.count_cards() > 0

    def count_cards(self):
        for sel in (self.CARD, self.CARD_FALLBACK):
            raw = self.js("document.querySelectorAll('%s').length" % sel) or "0"
            try:
                n = int(str(raw).split(".")[0])
            except Exception:
                n = 0
            if n > 0:
                return n
        return 0

    def load_more(self, target=40, max_rounds=10):
        return self.scroll_until(
            "document.querySelectorAll('%s').length" % self.CARD,
            target, max_rounds=max_rounds, wait=2.0,
        )

    def extract_cards(self):
        js = r"""
        (function(){
          var out = [];
          var cards = document.querySelectorAll('.jobCardPcContainer, .job-list-item');
          var seen = {};
          for (var i = 0; i < cards.length; i++) {
            var c = cards[i];
            var a = c.querySelector("a[href*='/job/']");
            var href = a ? (a.getAttribute('href') || '') : '';
            var m = href.match(/\/job\/(\d+)\.shtml/);
            var jid = m ? m[1] : ('lp-' + i);
            if (seen[jid]) continue;
            seen[jid] = 1;
            var txt = (c.innerText || '').replace(/\s+/g, ' ').trim();
            var titleEl = c.querySelector("[class*=jobTitle]");
            var compEl = c.querySelector('.jobDetailCompanyBox, [class*=company]');
            out.push({
              job_id: jid,
              title: titleEl ? titleEl.innerText.trim().replace(/\s+/g, ' ') : txt.slice(0, 40),
              salary: ((txt.match(/[\d.]+-[\d.]+k/i) || [''])[0]),
              company: compEl ? compEl.innerText.trim().replace(/\s+/g, ' ').slice(0, 40) : '',
              location: ((txt.match(/【\s*([^】]+)\s*】/) || ['', ''])[1]),
              tags: txt.slice(0, 200),
              url: href.indexOf('http') === 0 ? href : ('https://www.liepin.com' + href),
              raw: txt.slice(0, 240)
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
        u = str(job_id)
        if u.startswith("http"):
            url = u
        else:
            url = "https://www.liepin.com/job/%s.shtml" % u
        self.go(url, wait=(8, 10))
        time.sleep(1.5)
        return "liepin.com/job/" in self.current_url()

    def read_jd(self):
        js = r"""
        (function(){
          var e = document.querySelector('.job-intro-container');
          if (e && (e.innerText || '').trim().length > 40) {
            return (e.innerText || '').replace(/\n{3,}/g, '\n\n').slice(0, 4000);
          }
          var sels = ['[class*=job-intro]', '.paragraph', '[class*=job-description]'];
          for (var i = 0; i < sels.length; i++) {
            var x = document.querySelector(sels[i]);
            if (x && (x.innerText || '').trim().length > 40) {
              return (x.innerText || '').replace(/\n{3,}/g, '\n\n').slice(0, 4000);
            }
          }
          return (document.body ? document.body.innerText : '').replace(/\n{3,}/g, '\n\n').slice(0, 2500);
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
        txt = self.page_text()
        if "已投递" in txt:
            return "skip", "页面显示已投递"

        r = self.js(r"""
        (function(){
          var cands = [];
          var kw = /投递简历|立即投递|投个简历|申请职位|立即沟通|聊一聊/;
          var all = document.querySelectorAll('button,a,div,span');
          for (var i = 0; i < all.length; i++) {
            var el = all[i];
            var t = (el.textContent || '').trim();
            if (!t || t.length > 12) continue;
            if (!kw.test(t)) continue;
            var rc = el.getBoundingClientRect();
            if (rc.width <= 0 || rc.height <= 0) continue;
            cands.push(el);
          }
          if (!cands.length) return 'no_button';
          // 优先最短文本（通常是按钮本体）
          cands.sort(function(a, b){ return a.textContent.length - b.textContent.length; });
          var b = cands[0];
          b.scrollIntoView({block: 'center'});
          b.click();
          return 'clicked:' + (b.textContent || '').trim() + ':' + b.tagName;
        })()
        """) or "no_button"

        if r == "no_button":
            return "fail", "未找到投递/沟通按钮"
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
            if (t === '确定' || t === '确认' || t === '继续投递' || t === '确认投递') {
              var rc = el.getBoundingClientRect();
              if (rc.width > 0 && rc.height > 0) { el.click(); return 'confirmed:' + t; }
            }
          }
          return 'no_confirm';
        })()
        """) or "no_confirm"

        time.sleep(1.5)

        # 实测：猎聘「聊一聊」成功后会弹出聊天窗口(class 含 ant-im-modal)，
        # 页面按钮变为「继续聊」，并出现"打招呼"/消息记录。
        chat = self.js(
            "(function(){var m=document.querySelector('.ant-im-modal, [class*=ant-im-modal], [class*=im-ui-chat]');"
            "return m ? 'chat_open' : '';})()"
        ) or ""
        btn_after = self.js(
            "(function(){var a=document.querySelector('.apply-box');"
            "return a?(a.innerText||'').trim():'';})()"
        ) or ""
        txt2 = self.page_text()

        if chat or ("继续聊" in btn_after) or ("继续聊" in txt2):
            return "success", "已发起沟通(聊天窗=%s; 按钮=%s)" % (chat or "-", btn_after or "-")

        if ("投递成功" in txt2) or ("已投递" in txt2) or confirm.startswith("confirmed:"):
            return "success", "投递成功 (%s / %s)" % (r, confirm)
        return "unknown", "未检测到成功标志 (%s / %s)" % (r, confirm)
