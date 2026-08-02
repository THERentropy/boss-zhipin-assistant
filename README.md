# BOSS Smart Assistant 

这是一款基于智能关键词匹配与系统推荐页的求职辅助 skill。本工具拒绝粗暴的海投策略，而是利用AI精准识别语义分析，结合用户过往工作经验自动化实现精准、高效的岗位投递。旨在解放双手，提高效率。

## ⚠️ 运行必读 (避坑指南)

为了确保脚本能够顺利运行，请务必仔细阅读以下环境要求：

1. **测试环境限制**：本 SKILL 目前属于**测试版**，仅在 **Windows 11** 系统下的 `workbuddy` 智能体中测试运行稳定。不保证在其他 Agent 框架中也能完美兼容或稳定运行。但相信以目前AI的能力，稍微提示一下它自行修改匹配一下即可适应您的使用环境。
2. **浏览器要求**：运行必须基于 **Chrome 浏览器**，并且请务必在运行脚本前，**提前手动登录好你的 BOSS 直聘账号**。
3. **前置插件**：必须在 Chrome 中安装 `Kimi WebBridge` 浏览器扩展插件。
   - 📥 插件下载地址：[https://www.kimi.com/zh-cn/features/webbridge](https://www.kimi.com/zh-cn/features/webbridge)
4. **智能体配置**：必须在你的智能体（Agent）中提前安装好 `Kimi WebBridge` 的 SKILL。
5. **数据配置**：根目录下的 `user_profile.json` 和 `boss_applied.json` 为空数据模板，通过与agent的对话不断更新丰富规则，越投越准。所以再次强调，不要海投，投几个它汇报结果后您再微调效率会更高。

---

## ☕ 支持与打赏

如果这个小工具帮你节省了海量的时间，或者助你顺利拿到了心仪的 Offer，欢迎给作者打赏一杯咖啡！你的支持是我持续维护和优化的最大动力。

<div align="center">
  <img src="assets/tip_wechat.jpg" width="280" alt="微信打赏"/>
  &nbsp;&nbsp;&nbsp;&nbsp;
  <img src="assets/tip_alipay.jpg" width="280" alt="支付宝打赏"/>
</div>
