# “其他域名”清单

点击统计表中的“其他域名”可展开目标域名、连接记录数、最近出现时间；日/月筛选、刷新、搜索与分页均可使用。一次网页访问可能产生多条连接，一条复用连接也可能承载多个请求。清单不提供 URL、网页内容、客户端 IP、每域名字节数或设备归属。

## 已有安装启用

先将新版代码与 `web/` 静态文件放入自己的安装路径，保留私有配置和数据库；不要用首次安装器覆盖已有目录。对照 `scripts/install.py` 新增独立 `v2ray-traffic-dashboard-domains.service/.timer`，并让已有受保护 Nginx JSON 白名单允许 `/data/domains-index.json` 和 `/data/domains-YYYY-MM.json`，例如：

```nginx
location ~ "^/data/(domains-)?(index|[0-9]{4}-[0-9]{2})\.json$" { try_files $uri =404; }
```

这些 location 必须继承同一登录保护。新增 unit 的 `ReadWritePaths` 只包含本项目私有状态目录及静态 data 目录；`CPUQuota=20%`、`MemoryMax=64M`、`Nice=19`、一次最多读取约 4MiB（完整记录边界最多额外 8KiB），避免与代理抢资源。timer 每两分钟运行，空闲无常驻进程。

首次安装器已生成这两个 unit，但不会启动域名 timer。编辑 `/etc/v2ray-traffic-dashboard/config.json` 的可选项：

```json
"domain_list": {
  "enabled": true,
  "access_log": "/var/log/v2ray/access.log",
  "tag": "usage-other",
  "log_timezone": "UTC"
}
```

`tag` 必须等于 `other` 分类的出站 tag。`log_timezone` 是日志时间的实际时区，不是网页展示时区；确认服务器进程的日志时区后填写，页面统一换算为北京时间。

支持原生 access log：

```text
2026/01/02 01:00:00 192.0.2.10:12345 accepted tcp:service.example.com:443 [usage-other]
2026/01/02 01:00:01 192.0.2.10:12345 accepted tcp:service.example.com:443 [loop -> usage-other]
```

只计算出站 tag 恰好匹配的这一层，避免 loopback 产生的其他层日志重复计数。IP 目标、非法域名和无匹配 tag 的日志不会收录；不保存原始日志、源地址、用户标识或完整 URL。若当前 V2Ray 未生成这类日志，先确认日志配置；本功能不会自动修改或重启代理。

```sh
sudo systemctl daemon-reload
sudo /opt/v2ray-traffic-dashboard/bin/v2ray-traffic-dashboard domains
sudo systemctl enable --now v2ray-traffic-dashboard-domains.timer
sudo systemctl status v2ray-traffic-dashboard-domains.service
```

Nginx 配置有修改时只校验并 reload 网页自己的服务，不重启 V2Ray。

## 范围与精度

- 首次从当前 access log 开始补录。此前轮转归档不主动导入；旧分类汇总无法还原域名。页面标出最早收录记录和最近采集时间，不声称整天历史完整。
- 记录和读取游标在独立 `domains.sqlite3` 同一事务中提交，重复采样不会重复计算；原有 `traffic.sqlite3` 不变。
- 轮转后通过文件标识和前缀指纹寻找上一代日志，继续读取未采集尾部，支持普通归档和 gzip。找不到保留归档时记录缺口。`copytruncate` 本身存在写入竞态，因此不能保证完全无遗漏。
- 每日最多收录 1000 个不同域名（已收录域名继续计数），默认保留 400 个自然日；静态页面每个日/月最多展示连接次数最多的 500 个，超限会显示提示。搜索范围是已展示的域名。
- 缺口、超长日志及上限事件会给出完整性提示；时间或 tag 不正确会导致漏收或错误日期，请核对后使用新的域名数据库，避免混合不同口径。
- 独立采集权限需要读取 access log 并写本项目状态/data 目录。日志可能包含私人信息，私有数据库保持 0600，状态目录保持 0700；公开端只提供经过登录保护的域名汇总。

## 停用、备份与回滚

```sh
sudo systemctl disable --now v2ray-traffic-dashboard-domains.timer
sudo systemctl stop v2ray-traffic-dashboard-domains.service
```

停用不影响分类流量与代理。若要同时关闭网页清单，移除受保护 data 目录内 `domains-*.json`（停用期间旧清单会提示更新延迟），保留私有数据库以便之后继续。备份 `domains.sqlite3` 前停止该 timer 并等待 service 结束；恢复同一数据库应同时保留其游标，日志换代过多可能产生缺口。回滚网页时保留旧静态资源并最后原子替换 HTML，避免已打开页面加载混用版本。
