# HTTPS 和登录保护

生成的 Nginx 只监听 `127.0.0.1:8080`，所有允许的资源都继承 HTTP Basic 认证。
公网访问时不能简单改为 `listen 8080` 或将真实数据复制到一个公开静态站点。

## 使用已有 HTTPS 反向代理

在已有、证书有效的 HTTPS server 中转发到独立网页服务（示例域名请替换）：

```nginx
location / {
    proxy_pass http://127.0.0.1:8080;
    proxy_set_header Host $host;
    proxy_set_header X-Forwarded-Proto https;
    proxy_set_header Authorization $http_authorization;
}
```

上游 Nginx 会验证密码，未登录的页面与 JSON 都返回 401。不要用错误页面或静态 location
绕过 `/data/` 的认证。反向代理前有其他 HTTP 服务时使用独立域名/根路径；当前网页请求
`/data/...` 和根路径资源，不支持直接挂到某个子路径。

## 独立 HTTPS 入口

没有占用端口时，可以将生成配置中的 server 改为以下监听和证书指令，保留所有认证、
资源白名单、限流和响应头：

```nginx
listen 443 ssl;
server_name stats.example.com;
ssl_certificate /etc/v2ray-traffic-dashboard/tls/fullchain.pem;
ssl_certificate_key /etc/v2ray-traffic-dashboard/tls/privkey.pem;
ssl_protocols TLSv1.2 TLSv1.3;
```

证书私钥目录建议 0700、私钥 0600，仅 Nginx master 可读。证书由你选择的 ACME 客户端
单独申请、续期；成功续期后的 reload hook 使用
`systemctl reload v2ray-traffic-dashboard-web.service`，不重启 V2Ray。

没有域名时，可使用支持 IP 证书的 CA/ACME 客户端。Let's Encrypt 的 IP 证书属于短期证书，
必须使用兼容版本、正确 profile 并可靠自动续期；公网 IP 变化后需要重新申请。
参考 [Let's Encrypt IP 证书说明](https://letsencrypt.org/2026/01/15/6day-and-ip-general-availability)。
不要把服务器专用 ACME 账户目录或凭据放进仓库。acme.sh 是可选外部 GPL-3.0 程序，
本项目不捆绑、不代替它提供证书管理。

## 验证

- 浏览器正常验证 HTTPS，不出现证书错误。
- 未登录访问 `/`、`/app.js` 和 `/data/index.json` 返回 401；正确登录返回 200。
- 检查日/月数据、采样时间及实际代理连通性。
- 检查续期 timer/cron、下一次计划和 reload hook；首次检查成功不等于已经经历到期续签。
- Basic 认证信息可能在浏览器会话中缓存，共享设备使用后关闭会话或清除该站点认证状态。
