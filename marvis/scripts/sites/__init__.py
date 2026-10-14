#!/usr/bin/env python3
"""多站点适配层

统一封装多家招聘网站的「列表采集 / JD 读取 / 投递」能力。

用法:
    from scripts.sites import get_adapter, list_sites

    print(list_sites())            # ['51job', 'liepin', 'zhaopin']
    ad = get_adapter("zhaopin")
    print(ad.is_logged_in())
    ad.open_list(keyword="物业管理")
    cards = ad.extract_cards()
"""

from scripts.sites.base import SiteAdapter, get_adapter, list_sites, ADAPTERS  # noqa: F401

__all__ = ["SiteAdapter", "get_adapter", "list_sites", "ADAPTERS"]
