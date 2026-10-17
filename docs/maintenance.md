# 维护、备份和升级

## 备份

停止的只是本项目 timer。timer 停止时已启动的 oneshot 仍可能继续，需要等待其结束：

```sh
sudo systemctl stop v2ray-traffic-dashboard.timer
while sudo systemctl is-active --quiet v2ray-traffic-dashboard.service; do sleep 1; done
sudo sh -c 'umask 077; mkdir -p /root/vtd-backup; cp -p /var/lib/v2ray-traffic-dashboard/traffic.sqlite3 /root/vtd-backup/; cp -a /etc/v2ray-traffic-dashboard /root/vtd-backup/'
sudo systemctl start v2ray-traffic-dashboard.timer
```

启用了域名清单时，还需停止 `v2ray-traffic-dashboard-domains.timer` 并等待其 service 结束，把独立 `domains.sqlite3` 一起备份，完成后重新启动原来启用的域名 timer。

备份是私有数据，不上传公开仓库。首次采样之前可能没有数据库；确认文件存在再备份。

## 恢复

停止采集 timer 并等待正在运行的 oneshot 结束，恢复数据库及配置到原目录，保留原来的
owner/mode，再运行 `export` 生成快照并重新启用 timer。若 V2Ray 进程发生变化，下次采样
会记录计数器重置事件；不能恢复上一次进程未采到的尾部流量。

## 升级

首版安装器拒绝覆盖已有安装，不提供自动原地升级。先备份，停止本项目服务、用旧版
卸载器移除本项目文件（保留数据），再安装新版并恢复经过核对的配置/密码/HTTPS设置。
不要恢复旧 `managed.json` 覆盖新版安装清单。最后验证 doctor、采集、登录与代理使用。
升级/卸载统计页不需要重启 V2Ray；只有另行更改代理分类配置才需要对应维护流程。

## 小时统计升级

新版 `connect_db` 通过 `CREATE TABLE IF NOT EXISTS hourly` 增加小时聚合，不覆盖已有日汇总；新版采样会将同一增量同时写入日表和小时表，失败时两者与游标一起回滚。导出器可只读打开尚未升级的旧数据库，并明确导出 `hourly_started_at: null`，网页提示未启用。小时数据使用相同保留天数自动清理。

升级前按上述步骤停止**统计采集 timer**、等待 oneshot 结束并用 SQLite 备份 API 或一致性复制备份数据库；备份源码、导出器、网页和 unit。更新新版后手动运行一次本项目 `collect` 并验证日总量增量与小时增量一致、旧日记录仍存在，再恢复 timer。只停止统计采集，不停止或重启 V2Ray。小时增量覆盖从升级前的最后一个有效采样时间开始，无法补录更早的时段。

回滚可恢复旧采集器/导出器/网页，新增小时表不影响旧脚本；**不要用旧数据库覆盖回去**，以免抹掉升级后已经采集的日统计和游标。回滚期间小时数据不会继续增加，网页需回到旧版本或明确提示更新延迟。备份和真实数据库均为私有数据，不上传源码仓库。

## 首次安装失败

程序会明确返回错误，但文件写入过程中遇到磁盘/权限故障可能留下部分文件。没有
`managed.json` 时不要使用卸载器猜测删除范围：依据安装预览检查本项目的目标目录与
unit，只清理确认属于失败安装的文件，不删除数据库或代理配置。重试前先解决错误原因。
