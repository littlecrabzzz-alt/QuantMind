# 可选 Windows 通达信桥

此目录包含 Windows 侧桥程序、`setup.ps1`、keepalive 与打包脚本，不是已在线交易服务的证明。当前旧内网桥已下线；重新接入时先确认实际 Windows 主机、账号权限、网络及平台配置，不能复用历史 SMB 地址或凭据。

源码示例配置为同目录 [config.yaml](config.yaml)：认证由 `BRIDGE_AUTH_TOKEN` 环境变量注入，共享目录由 `SHARED_DIR` 注入。安装后带真实地址、凭据和状态的私有配置留在运行主机，不提交 `dist/config.yaml` 或其他发行目录中的实例配置。

部署、安全配置和只读检查统一见 [通达信桥接说明](../../docs/integrations/tdx-bridge.md)。不要依赖旧指南关于“实盘总会弹确认框”的保证；真实下单可能直接提交，健康检查不应使用下单接口。
