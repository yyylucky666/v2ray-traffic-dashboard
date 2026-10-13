# 分类统计接入、备份和回滚

## 先确认适用范围

本项目通过 V2Ray `StatsService` 获取出站累积上下行计数。需要 `stats: {}`、
`policy.system.statsOutboundUplink/Downlink: true`、loopback API 入站及指向 API tag 的路由。

官方资料：[统计 API](https://www.v2fly.org/en_US/config/api.html)、
[出站统计策略](https://www.v2fly.org/en_US/config/policy.html)、
[Loopback](https://www.v2fly.org/en_US/config/protocols/loopback.html)。

候选生成器针对传统 JSON 配置与一个指定的 `freedom` 出站。它保留原来的 DNS、
现有代理入站和路由顺序，把该出站替换为内部 loopback；只有原路由允许进入该出站的连接
才进入第二轮分类。分类规则仅匹配内部 tag，最后一个兜底匹配 TCP/UDP，避免分类域名规则
在原来的阻断规则前放行流量。其他出站保持原行为，不计入本工具。

不支持 balancer。多文件配置只在参与改写的文件包含 `outbounds/routing/api` 等必需对象时
使用；其他文件仍须一起加入 `v2ray test`。若这些对象分散在多个文件、内部 tag 在其他文件
冲突、使用替代配置格式或复杂二次路由，请人工集成，不能直接套用候选生成器。

已有 API 时，生成器要求配置中的 API 端口对应显式 loopback 入站和正确 API 路由；
拒绝默认为公网监听的 API。它不修改 sniffing。代理客户端未传域名时，需自行评估是否配置
已有入站的 sniffing，否则可能进入未识别分类；不能把开启 sniffing 当成无影响改动。

## 生成并审阅候选

以下 `/etc/v2ray/config.json` 是常见示例，请换成实际路径：

```sh
sudo sh -c 'umask 077; cp -p /etc/v2ray/config.json /etc/v2ray/config.before-dashboard.json'
sudo /opt/v2ray-traffic-dashboard/bin/v2ray-traffic-dashboard prepare-config \
  --input /etc/v2ray/config.json \
  --output /etc/v2ray/config.dashboard-candidate.json \
  --direct-tag direct
sudo /usr/local/bin/v2ray test -c /etc/v2ray/config.dashboard-candidate.json
sudo diff -u /etc/v2ray/config.json /etc/v2ray/config.dashboard-candidate.json
```

候选输出使用独占创建、权限 0600，不覆盖任何已有文件；输入可能包含真实凭据，备份、
候选和 diff 都必须留在私有服务器上，**不能上传 GitHub**。多文件启动时，验证命令必须
包含实际的其他配置目录，例如 `-d /etc/v2ray/conf`，并核对 `systemctl cat v2ray` 的实际启动参数。

审阅重点：原入站/凭据、原拒绝规则、DNS、其他出站未变；内部 tag 没有跨文件冲突；
API 仅 loopback；分类克隆出站保留原 `freedom` 的设置。

## 人工启用与连通性验证

安排维护窗口。候选通过验证和审阅后，由操作者替换实际配置，保留原文件的 owner/mode，
按发行版需要恢复 SELinux context，然后重启 V2Ray。这里不提供会自动修改/重启代理的安装指令。

立即检查：`systemctl is-active v2ray`、现有客户端代理访问、原拒绝规则以及 TCP/UDP 使用场景。
验证后运行本工具 `doctor` 并启动采集 timer。doctor 不 reset 计数器，也不修改代理。

## 回滚

如果代理启动或实际使用异常，立即用先前的 `config.before-dashboard.json` 恢复实际配置，
保持 owner/mode/SELinux context，验证配置并重启 V2Ray；重新确认真实客户端能访问。
停止本项目的采集 timer，保留 SQLite 数据供排查。仅卸载网页不会自动撤销分类路由。
