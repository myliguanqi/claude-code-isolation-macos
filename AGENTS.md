# AGENTS.md — 执行协议

你是一个在 Apple Silicon Mac 上搭建 Claude Code 隔离环境的执行 agent。先读本文件，再读 `Claude-Code-隔离环境-操作手册-macOS虚拟机版.md` 的 0.1 节和全文。

## 目标

复现：Mac 宿主机 → UTM macOS 虚拟机 → 原生 Claude Code；虚拟机只能通过宿主代理上网，代理不可用时 fail-closed。

最终验收：

1. 客户机直连 `https://api.anthropic.com/` 超时或被拒绝。
2. 客户机走 `http://<gateway>:10808` 返回任意 HTTP 状态码。
3. 客户机 DNS、宿主 SSH、宿主 ping 正常。
4. 宿主重启后规则仍生效。
5. `claude --version` / `claude doctor` 正常。

## 硬性规则

- **不要使用 Docker**。macOS 客户机不支持嵌套虚拟化，Docker Desktop 起不来。
- **不要启用 v2rayN AllowLAN**。用只绑定虚拟机网桥的 TCP 中转。
- **不要在 UTM 运行时执行 `pfctl -f /etc/pf.conf`**。UTM 的 `com.apple.internet-sharing` 是动态锚点，重载可能断掉虚拟机网络。
- **不要修改第三方 VPN/EDR 的锚点或文件**。如果目标机器上有这类软件，先只读检查 `pf.conf`，必要时暂停询问用户。
- **不要在未确认前执行**：`sudo`、创建/删除 VM、修改 `/etc/pf.conf`、安装 LaunchDaemon、安装/卸载软件、重启宿主。
- **不要在文件、仓库或聊天里写密码/token/私钥**。需要 sudo 时让用户在终端输入。
- **不要自动上传/发布**任何内容。

## 执行前：只读探测

先输出并保存到 `state.env`（不要提交）：

```bash
sw_vers
uname -m
sysctl -n hw.memsize
df -h /System/Volumes/Data
ls -d /Applications/UTM.app 2>/dev/null || echo "UTM not installed"
ifconfig | grep -E '^(bridge|vmenet|vmnet)[0-9]*:|inet '
lsof -nP -iTCP:10808 -sTCP:LISTEN
scutil --proxy
sudo pfctl -s info
sudo pfctl -s Anchors
```

如果 `sudo` 无法非交互执行，让用户在终端运行并读取输出，不要索要密码。

## 阶段与验收门

| 阶段 | 动作 | 验收 | 需要用户操作 |
|---|---|---|---|
| 0 | 只读探测，填写 `state.env` | 输出完整现状 | 可能：输入管理员密码 |
| 1 | 安装 UTM（DMG 或用户自行安装） | `CFBundleShortVersionString` | 是：拖入 Applications/首次启动 |
| 2 | UTM 新建 macOS VM：Virtualization → macOS 12+；4 CPU / 8192 MB / 80 GB；Shared Network；不要 Isolate Guest from Host | UTM 状态 `started`，客户机拿到 IP | **是**：向导、macOS 安装、Setup Assistant |
| 3 | 客户机：创建用户 `claude`；开启 Remote Login；写 SSH 公钥；设置 `zh-Hant-TW` / `zh_TW` / `Asia/Taipei`；关闭 IPv6 | `ssh ... whoami`；`defaults read -g AppleLocale` = `zh_TW`；`ifconfig en0` 无全局 IPv6 | 部分：Setup Assistant |
| 4 | 宿主安装 TCP 中转，监听 `<gateway>:10808` → `127.0.0.1:10808`；客户机设置系统代理 + shell 代理 | 客户机 `curl -x http://<gateway>:10808 ...` 返回状态码 | 是：输入管理员密码 |
| 5 | 安装 pf 锚点 `com.apple/100.claude-vm`：放行代理/DNS/SSH/文件共享/DHCP，其余 `block drop in quick`；写 `pf.conf` 锚点；安装 LaunchDaemon | 直连超时；代理成功；DNS/SSH/ping 正常 | 是：输入管理员密码 |
| 6 | 客户机安装 Claude Code；加 PATH；登录 | `claude --version`；`claude doctor` | 是：浏览器登录或 token |
| 7 | 重启宿主；启动 UTM/VM；复验 | 锚点仍在；直连仍失败；代理仍成功 | 是：重启、启动 VM |

每个阶段结束后停下来汇报：做了什么、验收命令、实际输出、下一步。**验收失败不要继续。**

## 关键实现细节

- pf 语法：macOS 27 不接受 `block drop quick in ...`，必须写 `block drop in quick ...`。
- 锚点求值顺序：`com.apple/100.claude-vm` 必须在 `com.apple.internet-sharing` 之前；主规则集里用 `anchor "com.apple/100.claude-vm" all` + `load anchor ...`。
- 宿主 → 虚拟机方向必须有一条 `pass out quick on <bridge> inet from <gateway> to <subnet> keep state`，否则 SSH/ping 的回包会被后面的 block 拦截。
- DHCP 续租：放行 UDP 68 → 67，否则租约到期断网。
- 代理中转只监听 `<gateway>:10808`，不要监听 `0.0.0.0`；否则会与 xray 的 `127.0.0.1:10808` 冲突，或暴露到热点。
- 客户机 DNS 用 `<gateway>:53`；不要依赖 `1.1.1.1:53`（实测可能超时）。
- 客户机 IPv6 关闭；pf 仍加 `block drop in quick inet6 all` 兜底。

## 遇到这些情况停下来

- UTM 恢复保存状态失败（`无效的自变量`）：改用 `start ... without saving`，不要反复重试恢复。
- 中转日志反复 `can't assign requested address`：`bridge100` 还没出现或网关变了；不要改监听为 `0.0.0.0`，先测量新网关。
- 直连仍能通：先检查 `pfctl -s Anchors` 和 `pfctl -a com.apple/100.claude-vm -sr`，不要盲目重载 `pf.conf`。
- UTM 网络断了：不要继续改 pf；恢复 `/etc/pf.conf.before-*` 备份并重启宿主。
- 客户机 `claude doctor` 报 Keychain 不可写：改在虚拟机桌面的 Terminal 登录，或用 token；不要在 SSH 里反复尝试。

## 最终报告格式

1. 环境：宿主 macOS、UTM、客户机 macOS、CPU/内存/磁盘。
2. 实测网络：接口、网段、网关、客户机 IP、代理端口。
3. 每阶段验收结果（通过/失败 + 实际输出）。
4. 文件清单：pf 锚点、中转、LaunchDaemon、日志、备份。
5. 未完成项和风险。
6. 不包含密码/token/私钥。

## 可直接复制的交接提示词

```
你是执行 agent。请在 Apple Silicon Mac 上按《Claude-Code-隔离环境-操作手册-macOS虚拟机版》搭建 Claude Code 隔离环境。

先做只读探测并汇报；涉及 sudo、创建/删除 VM、修改 pf.conf、安装 LaunchDaemon 或软件前，先说明并征得用户确认。UTM GUI、Setup Assistant、Claude 登录等步骤暂停让用户操作。每阶段按手册的验收门检查，失败则停止并按故障排查报告，不要跳过。不要使用 Docker；不要启用 v2rayN AllowLAN；不要在 UTM 运行时执行 pfctl -f；不要修改第三方 VPN/EDR 锚点；不要把密码/token 写进文件或聊天记录。
```
