# Claude Code 隔离环境（macOS 虚拟机版）

Apple Silicon Mac 上的 Claude Code 隔离方案：

```
Mac 宿主机（UTM + 代理 + pf）
  └─ UTM macOS 虚拟机（原生 Claude Code，无 Docker）
```

虚拟机默认拒绝一切出站，只允许访问宿主机网关的**代理、DNS、SSH、文件共享**端口；代理不可用时虚拟机断网（fail-closed）。

## 这套东西解决什么

- 把 Claude Code 的工作环境与日常 Mac 环境分开；
- 网络出口集中在宿主机：虚拟机只能走宿主代理；
- 不使用 Docker，避免 macOS 客户机不支持嵌套虚拟化的问题；
- 保留本地文件访问、SSH、rsync 和可选的 VirtioFS。

## 文件

| 文件 | 说明 |
|---|---|
| `Claude-Code-隔离环境-操作手册-macOS虚拟机版.md` | 主手册：架构、UTM 创建、客户机初始化、代理、pf 隔离、Claude Code、验收、排障、限制 |
| `AGENTS.md` | 交给另一个 agent 执行时的入口协议（阶段、验收门、禁止事项） |
| `pf-claude-vm.draft.conf` | pf 锚点规则草稿（`bridge100` / `192.168.64.0/24` 是示例实测值） |
| `claude-vm-proxy-relay.py` | 宿主侧 TCP 中转：只绑定虚拟机网桥地址，转发到 `127.0.0.1:10808` |
| `state.example.env` | 实测参数模板（复制为 `state.env`，不要提交） |
| `教程-视频总结.md` | 参考视频的总结 |
| `Claude-Code-隔离环境-操作手册.md` | Ubuntu + Docker 版参考手册（不是本方案的主路径） |

## 交给另一个 agent

1. 让 agent 先读 `AGENTS.md`，再读主手册的 **0.1 节**。
2. 或直接复制主手册 0.1 节的“交接提示词”发给它。
3. 明确告诉它哪些步骤需要你本人操作：UTM 新建虚拟机、Setup Assistant、macOS 安装、Claude Code 浏览器登录。

## 已验证环境

- 宿主机：Mac mini M4 / 16 GB / macOS 27.0.1
- UTM：5.0.8
- 客户机：macOS 27.2.1，4 CPU / 8 GB / 80 GB
- 宿主代理：v2rayN 7.25.6 + xray 26.10.10，`127.0.0.1:10808`
- Claude Code：2.1.330（native，darwin-arm64）
- 网络：`bridge100`，`192.168.64.0/24`，宿主网关 `192.168.64.1`，客户机 `192.168.64.2`
- 验收：客户机直连超时、走代理 HTTP 404、DNS/SSH/ping 正常、重启后规则仍生效、无旧 VPN 锚点

## 安全与合规

- 手册包含会修改 `/etc/pf.conf`、安装 LaunchDaemon、修改系统代理的命令；执行前备份并理解每一步。
- 网络参数是实测示例，**换机器、换 UTM 后端或系统重建后必须重新测量**，不要直接照抄。
- 不要在 UTM 运行时执行 `pfctl -f /etc/pf.conf`；UTM 的 `com.apple.internet-sharing` 是动态锚点，重载可能断网。
- 本方案只解决环境隔离和网络出口管理，不保证避免账号风控；请遵守 Anthropic/Claude 的服务条款。
- 这不是 Anthropic 或 UTM 的官方文档；命令按你的环境自行验证。

## 许可证

未指定开源许可证。
