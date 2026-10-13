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

## 首次安装失败

程序会明确返回错误，但文件写入过程中遇到磁盘/权限故障可能留下部分文件。没有
`managed.json` 时不要使用卸载器猜测删除范围：依据安装预览检查本项目的目标目录与
unit，只清理确认属于失败安装的文件，不删除数据库或代理配置。重试前先解决错误原因。
