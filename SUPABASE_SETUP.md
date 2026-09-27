# Supabase 接入

代码已经支持把收藏、人工提交和个人资料同步到 Supabase。没有配置项目时，页面继续使用浏览器本地缓存，不会中断。

## 一次性配置

1. 在 Supabase 新建项目。
2. 在 SQL Editor 执行 `supabase/migrations/20260927010000_personal_cloud.sql`。
3. 在 Authentication 设置中启用 **Allow anonymous sign-ins**。匿名账户用于无门槛试用；准备跨设备或收费时，再启用邮件登录。
4. 在 Project Settings → API 复制 Project URL 和 **publishable key**，填入 `supabase-config.js`：

```js
window.SCU_RADAR_SUPABASE = {
  url: 'https://你的项目.supabase.co',
  publishableKey: '你的 publishable key',
  anonymousSignIn: true
};
```

`publishable key` 可以放在浏览器；`service_role` 可以绕过行级权限，绝对不能写进网页、Git 或前端配置。

## 数据边界

- `profiles`：个人显示名、目标院校、兴趣方向和备注。
- `bookmarks`：收藏的公开信息 ID。
- `submissions`：用户手工补录的公开线索。
- 三张表都启用了 RLS。用户只能读取、写入和删除 `auth.uid()` 等于自身 `user_id` 的行。
- 公共抓取数据仍由 `radar-data.js` 提供；用户表不会获得写入公共来源库的权限。

## 从本地迁移

首次成功连接云端时，页面会把当前浏览器的收藏和人工补录与云端记录合并，然后同步。完成同步后，本地仅保留离线副本，用于断网降级。

## 上线前

- 匿名登录应配 Turnstile/CAPTCHA 和定期清理策略，避免匿名账户被滥用。
- 收费前应启用邮件或 OAuth 登录；匿名账户清除浏览器数据后无法恢复。
- 部署到正式域名后，把该域名加入 Supabase Auth 的 Redirect URLs。
