# Claude Code 隔离环境操作手册（macOS 虚拟机版）

> 适用：Apple Silicon Mac（本机为 Mac mini M4 / 16 GB）
> 目标：Mac 宿主机 → UTM macOS 虚拟机 → 原生 Claude Code；虚拟机只能通过宿主代理上网，代理不可用时 fail-closed。
> 本手册基于 2026-11-17 至 2026-11-21 在本机的实际搭建与验收，所有参数均为实测值；未验证的内容会明确标注「未验证」。
> **不使用 Docker**。macOS 客户机不支持嵌套虚拟化，Docker Desktop 在客户机里起不来，这不是配置问题。

---

## 0.1 给执行 Agent 的说明（人类可跳过）

如果你把本手册交给另一个 agent 执行，先让它读完本节和全文，再开始。

**目标**：在 Apple Silicon Mac 上复现本手册的隔离环境；最终验收是客户机直连失败、走代理成功、重启后规则仍在、Claude Code 可用。

**执行规则**

1. 先只读探测，汇报现状；不要直接开始改系统。
2. 涉及 `sudo`、创建/删除虚拟机、修改 `/etc/pf.conf`、安装 LaunchDaemon、安装软件前，先说明将做什么并征得用户确认。
3. UTM 新建虚拟机、Setup Assistant、macOS 安装、Claude Code 浏览器登录是 GUI 步骤；agent 无法点击时，暂停并让用户操作。
4. 每个阶段结束必须跑该阶段的验收命令；失败就停止，按故障排查处理，不要跳过。
5. 不要使用 Docker；不要启用 v2rayN AllowLAN；不要在 UTM 运行时执行 `pfctl -f /etc/pf.conf`；不要修改第三方 VPN/EDR 的锚点。
6. 不要把密码、token、密钥写进文档、仓库或聊天记录；需要 sudo 时让用户在终端输入。
7. 不要自动上传/发布任何内容；需要时先征得用户确认。
8. 实测参数（接口、网段、网关、IP）写入 `state.env`（不要提交到公开仓库），后续命令用变量，不要硬编码。

**阶段与验收门**

| 阶段 | 内容 | 验收 |
|---|---|---|
| 0 | 只读探测 | 输出 `sw_vers`、`uname -m`、UTM、接口、代理端口、pf、磁盘/内存 |
| 1 | 安装 UTM | `CFBundleShortVersionString` 正确 |
| 2 | 创建 macOS VM | UTM 状态 `started`，客户机拿到 IP |
| 3 | 客户机 SSH / locale / IPv6 | `ssh ... whoami` 成功；`defaults read -g AppleLocale` 为 `zh_TW`；`ifconfig en0` 无全局 IPv6 |
| 4 | 代理中转 | 客户机 `curl -x http://<gateway>:10808 ...` 返回任意 HTTP 状态码 |
| 5 | pf 隔离 | 客户机直连超时；代理成功；DNS/SSH/ping 正常 |
| 6 | Claude Code | `claude --version`、`claude doctor` 通过 |
| 7 | 重启验收 | 锚点仍生效；直连仍失败；代理仍成功；两个 LaunchDaemon 正常 |

**交接提示词（可直接复制给另一个 agent）**

```
你是执行 agent。请在 Apple Silicon Mac 上按《Claude-Code-隔离环境-操作手册-macOS虚拟机版》搭建 Claude Code 隔离环境。

先做只读探测并汇报；涉及 sudo、创建/删除 VM、修改 pf.conf、安装 LaunchDaemon 或软件前，先说明并征得用户确认。UTM GUI、Setup Assistant、Claude 登录等步骤暂停让用户操作。每阶段按手册的验收门检查，失败则停止并按故障排查报告，不要跳过。不要使用 Docker；不要启用 v2rayN AllowLAN；不要在 UTM 运行时执行 pfctl -f；不要修改第三方 VPN/EDR 锚点；不要把密码/token 写进文件或聊天记录。
```

---

## 0. 最终形态（实测）

```
┌──────────────────────────────────────────────────────────────┐
│ Mac 宿主机（macOS 27.0.1，Mac mini M4，16 GB）                │
│  - UTM 5.0.8                                                 │
│  - v2rayN 7.25.6 + xray 26.10.10                             │
│      xray mixed inbound: 127.0.0.1:10808                     │
│  - 中转 local.claude-vm-proxy-relay                           │
│      192.168.64.1:10808 -> 127.0.0.1:10808                    │
│  - pf 锚点 com.apple/100.claude-vm                            │
│                                                              │
│   ┌────────────────────────────────────────────────────────┐ │
│   │ UTM macOS 虚拟机（macOS 27.2.1，4 CPU / 8 GB）          │ │
│   │  IP 192.168.64.2/24，网关 192.168.64.1                  │ │
│   │  - Claude Code 2.1.330（native，~/.local/bin/claude）   │ │
│   │  - 系统代理 + shell 代理均指向 192.168.64.1:10808       │ │
│   └────────────────────────────────────────────────────────┘ │
└──────────────────────────────────────────────────────────────┘
```

实测网络参数（**不要照抄成 192.168.64.0/24 就当永远不变**，换机器/换后端要重新测）：

| 参数 | 实测值 |
|---|---|
| 宿主侧接口 | `bridge100` |
| 宿主地址 / 虚拟机网关 | `192.168.64.1/24` |
| 虚拟机子网 | `192.168.64.0/24` |
| 虚拟机 IP（DHCP） | `192.168.64.2` |
| 宿主代理（xray） | `127.0.0.1:10808` |
| 虚拟机使用的代理入口 | `192.168.64.1:10808`（中转） |
| 虚拟机 DNS | `192.168.64.1:53`（宿主 mDNSResponder） |

### 三条设计原则

1. **隔离在网络层**：虚拟机默认拒绝一切出站，只允许到宿主网关的代理、DNS、SSH、文件共享端口。
2. **策略集中在 Mac**：代理、中转、pf 规则都在宿主机；虚拟机里只写一次代理地址。
3. **Fail-closed**：代理不可用时虚拟机直接断网，不会自动回退到直连。

### 与视频方案的关系

| 视频 | 本手册 |
|---|---|
| Mac → Ubuntu VM → Docker 容器 | Mac → macOS VM → 原生 Claude Code（无 Docker） |
| Ubuntu 里跑 Claude Code | macOS 客户机里原生运行 |
| 网络策略配在 Mac | 同样配在 Mac，但 pf 参数按 macOS 客户机实测生成 |
| 容器内日语/东京 | 虚拟机内繁體中文（台灣）/ Asia/Taipei（仅 locale，不改变网络出口） |

---

## 1. 前置条件

### 硬件与系统

- Apple Silicon Mac；本机 Mac mini M4，10 核，16 GB 内存。
- 宿主机 macOS 12+；本机 **macOS 27.0.1**。
- 可用磁盘：本机搭建前约 181 GB，虚拟机磁盘 80 GB（稀疏，实际占用随使用增长）。
- 虚拟机内存 8 GB 后，宿主剩约 8 GB；如果同时开很多 Mac 应用，可降到 6 GB。

### 软件

| 软件 | 版本/用途 | 说明 |
|---|---|---|
| UTM | 5.0.8 | 从官方 GitHub release 下载 DMG；无需 Homebrew |
| macOS IPSW | 由 UTM 自动下载 | 本次得到 macOS 27.2.1（最新兼容版本） |
| v2rayN / xray | 7.25.6 / 26.10.10 | 本机已有；xray 监听 `127.0.0.1:10808` |
| Claude Code | 2.1.330 | 客户机原生安装 |

### 网络现状（搭建时）

- 搭建时宿主机通过手机热点上网；IPSW 约 14–16 GB，下载前确认流量和稳定性。
- 宿主代理只监听 `127.0.0.1:10808`，**没有开 AllowLAN**；虚拟机通过 `192.168.64.1:10808` 的中转访问。

---

## 2. 创建 macOS 虚拟机（UTM）

### 2.1 安装 UTM

从官方 release 下载 `UTM.dmg`（本次 v5.0.8），拖入 `/Applications`。也可以从 <https://mac.getutm.app/> 下载。

验证：

```bash
defaults read /Applications/UTM.app/Contents/Info.plist CFBundleShortVersionString
# 5.0.8
```

> 本机 UTM 的签名是 `Developer ID Application: Turing Software, LLC (WDNLXAD4W8)`；`spctl` 显示未公证，但 DMG 来自官方 GitHub HTTPS，且无 quarantine。若你的环境被 Gatekeeper 拦截，按系统提示在「隐私与安全性」里允许。

### 2.2 新建虚拟机

1. 打开 UTM → **Create a New Virtual Machine**。
2. 选择 **Virtualization** → **macOS 12+**。
3. **macOS 版本/IPSW**：UTM 5 的向导默认自动下载“最新兼容 IPSW”，没有单独的版本选择页。若想指定版本，需要先自行下载 IPSW，再在向导里选择/浏览（**具体按钮标签未验证**）。
4. 资源（本次实测配置）：
   - Name：`macOS`（UTM 默认名；本手册后续都用这个名字）
   - CPU Cores：**4**
   - Memory：**8192 MB**
   - Disk Size：**80 GB**（客户机内显示 75 GiB）
   - 字段标签以向导实际显示为准。
5. 网络：**Shared Network**；不要勾选 **Isolate Guest from Host**。
6. 保存并启动，等待 IPSW 下载和 macOS 安装完成。

> 本次 IPSW 下载约 2.6 GB 时速度约 23 MB/s；完整下载后 UTM 自动进入安装。安装期间不要退出 UTM。

### 2.3 安装 macOS

- 语言/地区：在 Setup Assistant 里选 **繁體中文**、**台灣**（本次安装后实际 locale 为 `zh_TW` / `zh-Hant-TW`）。
- 不登录 Apple ID；不启用 FileVault。
- 创建管理员账号：用户名 **`claude`**。
- 进入桌面后：**系統設定 → 一般 → 共享 → 遠端登入**，允许 `claude` 用户（或所有使用者）。
- 记录 IP：**系統設定 → 網路 → 乙太網路 → 詳細資料**，或终端 `ipconfig getifaddr en0`。

### 2.4 启动时的一个坑（已实测）

宿主重启后，UTM 可能尝试恢复虚拟机的“保存状态”，报：

```
恢复虚拟机时发生错误。虚拟机未能恢复，错误为“无效的自变量”。 (-2700)
```

解决：**不恢复状态，直接从磁盘启动**。已验证的 AppleScript：

```bash
osascript -e 'tell application "UTM" to start virtual machine named "macOS" without saving'
```

GUI 里如果有 “Start without saving” 选项，也可以用它（**标签未验证**）。日常建议在重启宿主前，先在虚拟机里正常关机，避免保存状态。

---

## 3. 客户机初始化

### 3.1 SSH 免密登录

宿主机生成专用密钥（不要覆盖已有 GitHub 密钥）：

```bash
ssh-keygen -t ed25519 -f ~/.ssh/id_ed25519_claude_vm -N '' -C 'claude-macos-vm'
```

把公钥装进客户机（会提示输入虚拟机里 `claude` 的密码）：

```bash
ssh-copy-id -i ~/.ssh/id_ed25519_claude_vm.pub claude@192.168.64.2
```

> 如果 `ssh-copy-id` 因密码/用户名失败，可在虚拟机的终端里手动写入：
>
> ```bash
> whoami
> mkdir -p ~/.ssh && chmod 700 ~/.ssh
> echo 'ssh-ed25519 AAAA... claude-macos-vm' >> ~/.ssh/authorized_keys
> chmod 600 ~/.ssh/authorized_keys
> ```

验证：

```bash
ssh -i ~/.ssh/id_ed25519_claude_vm -o BatchMode=yes claude@192.168.64.2 'whoami; sw_vers'
```

### 3.2 台灣 locale / 時區

在客户机里执行（`sudo` 会提示输入虚拟机密码）：

```bash
sudo languagesetup -langspec zh-Hant
sudo defaults write /Library/Preferences/.GlobalPreferences AppleLocale -string zh_TW
sudo defaults write /Library/Preferences/.GlobalPreferences AppleLanguages -array zh-Hant-TW zh-Hant en-US
sudo systemsetup -settimezone Asia/Taipei
defaults write -g AppleLocale -string zh_TW
defaults write -g AppleLanguages -array zh-Hant-TW zh-Hant en-US
```

注销/重启后界面生效。实测结果：

```bash
defaults read -g AppleLocale       # zh_TW
defaults read -g AppleLanguages    # zh-Hant-TW, ...
```

> 这些设置只影响界面语言、格式和时区，**不改变网络出口、IP 归属或 Claude 账号地区**。Claude Code 的回答语言也不由 macOS locale 决定。

### 3.3 关闭 IPv6

```bash
sudo networksetup -setv6off "Ethernet"
```

验证：

```bash
ifconfig en0 | grep inet6 || echo "no inet6"
scutil --dns | grep nameserver
# 应该只剩 192.168.64.1
```

> 关闭 IPv6 有两个目的：避免 DNS 优先走 `fe80::` 的链路本地地址；让 pf 的 IPv4 规则没有绕过路径。pf 里仍然加了 `block ... inet6` 作为兜底。

### 3.4 确认 DNS

客户机 DNS 由 DHCP 指向宿主网关 `192.168.64.1`。实测宿主 mDNSResponder 监听 `*:53`，客户机解析正常：

```bash
dscacheutil -q host -a name api.anthropic.com
# ip_address: 160.79.104.10
```

> 直连公共 DNS `1.1.1.1:53` 在本机实测超时；不要依赖它。pf 只放行到网关的 DNS。

---

## 4. 代理：宿主中转，而不是 AllowLAN

### 4.1 为什么不用 v2rayN AllowLAN

v2rayN 的 xray 入站默认监听 `127.0.0.1:10808`。如果打开 AllowLAN：

- xray 会监听所有网卡，热点上的其他设备也可能访问；
- 还需要额外的 pf/防火墙规则来限制来源。

本手册改用一个**只绑定在虚拟机网桥地址**的中转：

```
虚拟机 192.168.64.2
   → 192.168.64.1:10808（中转，只监听 bridge100）
      → 127.0.0.1:10808（xray mixed inbound）
         → 代理节点 → api.anthropic.com
```

热点/LAN 无法路由到 `192.168.64.1`，所以代理不会暴露到虚拟机网络之外。

### 4.2 中转脚本

源码：`~/Projects/我的项目/claude-vm-proxy-relay.py`
安装位置：`/usr/local/sbin/claude-vm-proxy-relay.py`

核心逻辑（Python asyncio，纯 TCP 转发，支持并发连接）：

```python
LISTEN_HOST = "192.168.64.1"
LISTEN_PORT = 10808
UPSTREAM_HOST = "127.0.0.1"
UPSTREAM_PORT = 10808
```

脚本在网桥尚未出现时会每 5 秒重试绑定，因此可以在开机时先启动、等 UTM 把 `bridge100` 建起来后自动绑定。

LaunchDaemon：`/Library/LaunchDaemons/local.claude-vm-proxy-relay.plist`

```xml
<key>Label</key><string>local.claude-vm-proxy-relay</string>
<key>ProgramArguments</key>
<array>
  <string>/usr/bin/python3</string>
  <string>/usr/local/sbin/claude-vm-proxy-relay.py</string>
</array>
<key>RunAtLoad</key><true/>
<key>KeepAlive</key><true/>
<key>StandardOutPath</key><string>/var/log/claude-vm-proxy-relay.log</string>
<key>StandardErrorPath</key><string>/var/log/claude-vm-proxy-relay.log</string>
```

日志：

```bash
tail -20 /var/log/claude-vm-proxy-relay.log
# relay listening on 192.168.64.1:10808 -> 127.0.0.1:10808
```

> 如果宿主的网桥 IP 变了（例如变成 `192.168.65.1`），改脚本里的 `LISTEN_HOST`，重新安装并执行：
>
> ```bash
> sudo launchctl kickstart -k system/local.claude-vm-proxy-relay
> ```
>
> 同时虚拟机里的系统代理和 shell 变量也要改成新网关。

### 4.3 客户机系统代理

在客户机里（`sudo` 需要虚拟机密码）：

```bash
sudo networksetup -setwebproxy "Ethernet" 192.168.64.1 10808
sudo networksetup -setsecurewebproxy "Ethernet" 192.168.64.1 10808
sudo networksetup -setwebproxystate "Ethernet" on
sudo networksetup -setsecurewebproxystate "Ethernet" on
```

验证：

```bash
scutil --proxy | grep -E 'HTTPEnable|HTTPProxy|HTTPPort'
# HTTPEnable : 1
# HTTPProxy : 192.168.64.1
# HTTPPort : 10808
```

> 系统代理只覆盖 Safari/CFNetwork 等应用；**Claude Code CLI 不读 macOS 系统代理**，所以还要配环境变量。

### 4.4 客户机 shell 代理

写入 `~/.zshrc` 和 `~/.zprofile`：

```bash
# CLAUDE_VM_PROXY
export HTTP_PROXY=http://192.168.64.1:10808
export HTTPS_PROXY=http://192.168.64.1:10808
export ALL_PROXY=socks5://192.168.64.1:10808
export NO_PROXY=localhost,127.0.0.1,::1,192.168.64.1
export http_proxy=$HTTP_PROXY
export https_proxy=$HTTPS_PROXY
export all_proxy=$ALL_PROXY
export no_proxy=$NO_PROXY
```

xray 的 mixed inbound 同时支持 HTTP 和 SOCKS，所以 `ALL_PROXY=socks5://...` 可用。

验证：

```bash
curl -x http://192.168.64.1:10808 -sS --max-time 15 https://api.anthropic.com/ \
  -o /dev/null -w '%{http_code}\n'
# 404（任意 HTTP 状态码都算链路通）
```

---

## 5. pf 隔离（核心）

### 5.1 本机的特殊背景（必读）

搭建前这台机器安装了 **某第三方 VPN/零信任客户端**，它修改过 `/etc/pf.conf`：

- 把 Apple 默认的 `anchor "com.apple/*"` 整段注释掉；
- 加入 20 个它自己的锚点；
- UTM 的 `com.apple.internet-sharing` 是**运行时动态锚点**，不在 `/etc/pf.conf` 里，由 `pfd` 维护 NAT/放行规则。

因此：

1. **不能直接照抄 Ubuntu 手册的 `pfctl -f /etc/pf.conf`**：会冲掉主规则集，可能把 UTM 的 Internet Sharing 锚点/NAT 弄丢，直接断虚拟机网络。
2. 本次最终方案是：把正式锚点写进 `pf.conf`，**重启宿主**由系统加载；运行中不重载主规则集。
3. 该 VPN 客户端已经卸载（2026-11-21），其 pf 段和锚点也已删除。如果以后重新安装类似的 VPN/零信任软件，需要重新检查 `pf.conf` 和锚点顺序。

### 5.2 一个 macOS pf 语法坑（已实测）

现有 Ubuntu 手册里的写法：

```
block drop quick in inet from ... to any     # macOS 27 报 syntax error
```

在本机 `pfctl -n -f` 下报错。正确写法是把方向放在 `drop` 后面：

```
block drop in quick inet from ... to any     # 通过语法检查
```

本手册所有规则都用后者。

### 5.3 最终锚点规则

文件：`/etc/pf.anchors/claude-vm`
源文件：`~/Projects/我的项目/pf-claude-vm.draft.conf`（两份内容一致）

```
# Host -> VM management traffic (SSH, file sharing, ping).
# The state lets the VM's replies back in without being caught by the block.
pass out quick on bridge100 inet from 192.168.64.1 to 192.168.64.0/24 keep state

# DHCP from the VM (initial request and renewals).
pass in quick on bridge100 inet proto udp from any port 68 to any port 67 keep state

# Loopback is trusted (the host itself uses 127.0.0.1:10808).
pass in quick on lo0 all

# VM -> host gateway: proxy, SSH, file sharing, screen sharing.
pass in quick on bridge100 inet proto tcp from 192.168.64.0/24 to 192.168.64.1 \
  port { 10808, 22, 445, 548, 5900 } keep state

# VM -> host gateway DNS (UDP and TCP).
pass in quick on bridge100 inet proto { tcp, udp } from 192.168.64.0/24 to 192.168.64.1 \
  port 53 keep state

# Fail-closed: block every other IPv4 packet from the VM, in the in
# direction, before the vmnet NAT rewrites it.
block drop in quick on bridge100 inet from 192.168.64.0/24 to any

# Fail-closed for IPv6 as well (the guest's IPv6 is disabled separately).
block drop in quick on bridge100 inet6 all

# Do not expose the host proxy port to other LAN clients.
block drop in quick inet proto tcp from any to any port 10808
```

逐条说明：

| 规则 | 作用 |
|---|---|
| `pass out ... 192.168.64.1 → 192.168.64.0/24` | 宿主主动连虚拟机（SSH、ping、文件共享）时建立状态，保证回包不被后面的 block 拦截 |
| DHCP 68 → 67 | 允许虚拟机续租，否则租约到期后断网 |
| `pass in on lo0` | 宿主自己用 `127.0.0.1:10808` 时不受全局 10808 阻断影响 |
| VM → 网关 10808/22/445/548/5900 | 代理、SSH、SMB、AFP、屏幕共享 |
| VM → 网关 53 | DNS |
| `block drop in quick ... 192.168.64.0/24 to any` | 其余 IPv4 出站全部丢弃，在 `in` 方向、NAT 之前 |
| `block drop in quick ... inet6 all` | IPv6 兜底 |
| `block drop in quick ... port 10808` | 防止热点/LAN 其他设备访问宿主代理端口 |

### 5.4 让锚点被主规则集引用

`/etc/pf.conf` 末尾追加（已安装，备份见 5.8）：

```
# Claude VM isolation (managed by local.claude-vm-pf)
anchor "com.apple/100.claude-vm"
load anchor "com.apple/100.claude-vm" from "/etc/pf.anchors/claude-vm"
```

重启后的主规则集实测：

```
scrub-anchor "com.apple.internet-sharing" all fragment reassemble
anchor "com.apple/100.claude-vm" all
anchor "com.apple.internet-sharing" all
```

关键点：**我们的锚点排在 Internet Sharing 之前**，所以 `block quick` 会先于 UTM 的放行规则生效。

> `load anchor` 在 pf.conf 解析时把规则读进锚点；`anchor` 才是求值点。两者都要有。

### 5.5 开机 LoadDaemon

脚本：`/usr/local/sbin/claude-vm-pf.sh`

```sh
#!/bin/sh
LOG=/var/log/claude-vm-pf.log
{
  echo "=== $(date) ==="
  ANCHORS=$(/sbin/pfctl -s Anchors 2>/dev/null)
  if ! echo "$ANCHORS" | grep -q 'com.apple/100.claude-vm'; then
    if echo "$ANCHORS" | grep -q 'com.apple.internet-sharing'; then
      echo "WARN: claude-vm anchor point missing; Internet Sharing active; not reloading"
    else
      /sbin/pfctl -f /etc/pf.conf
    fi
  fi
  /sbin/pfctl -e >/dev/null 2>&1 || true
  /sbin/pfctl -a com.apple/100.claude-vm -f /etc/pf.anchors/claude-vm
  echo "--- rules ---"
  /sbin/pfctl -a com.apple/100.claude-vm -sr
} >> "$LOG" 2>&1
```

LaunchDaemon：`/Library/LaunchDaemons/local.claude-vm-pf.plist`

```xml
<key>Label</key><string>local.claude-vm-pf</string>
<key>ProgramArguments</key>
<array><string>/usr/local/sbin/claude-vm-pf.sh</string></array>
<key>RunAtLoad</key><true/>
<key>KeepAlive</key><false/>
```

日志：

```bash
tail -30 /var/log/claude-vm-pf.log
```

> 脚本在“锚点已存在”时不会重载主规则集；只有在开机早期、Internet Sharing 还没出现时才执行 `pfctl -f /etc/pf.conf`。这样避免运行中重载打断 UTM 网络。

### 5.6 验收结果（2026-11-21，重启后）

| 测试 | 结果 |
|---|---|
| 客户机直连 `https://api.anthropic.com/`（清空代理变量 + `--noproxy '*'`） | **超时 / BLOCKED** |
| 客户机 `curl -x http://192.168.64.1:10808 ...` | **HTTP 404**（链路通） |
| 客户机 DNS `dscacheutil` | `160.79.104.10` |
| 宿主 `ssh claude@192.168.64.2` | 正常 |
| 宿主 `ping 192.168.64.2` | 正常 |
| 宿主 `curl -x http://127.0.0.1:10808 ...` | HTTP 404 |
| `pfctl -s Anchors` | `com.apple`、`com.apple.internet-sharing`，**无旧 VPN 锚点** |
| 主规则集顺序 | `com.apple/100.claude-vm` 在 `com.apple.internet-sharing` 之前 |
| pf LaunchDaemon | `runs=1`，`last exit code=0` |
| 重启宿主后 | 上述结果保持不变 |

### 5.7 修改 / 重新生成

如果 UTM 的网络后端、子网或接口名变了，必须重新生成，不能继续用旧值。先测：

```bash
# 宿主
ifconfig bridge100 | grep 'inet '
route -n get default

# 客户机
ipconfig getifaddr en0
route -n get default
scutil --dns | grep nameserver
```

然后：

1. 编辑 `~/Projects/我的项目/pf-claude-vm.draft.conf`，替换接口/网段/网关。
2. 语法检查：
   ```bash
   pfctl -n -f ~/Projects/我的项目/pf-claude-vm.draft.conf
   ```
3. 安装并重载锚点（**不需要重载主规则集**）：
   ```bash
   sudo install -m 644 -o root -g wheel \
     ~/Projects/我的项目/pf-claude-vm.draft.conf \
     /etc/pf.anchors/claude-vm
   sudo pfctl -a com.apple/100.claude-vm -f /etc/pf.anchors/claude-vm
   ```
4. 同步修改中转脚本的 `LISTEN_HOST` 和客户机代理地址。

### 5.8 回滚

```bash
# 1) 停用并删除 pf LaunchDaemon
sudo launchctl bootout system/local.claude-vm-pf 2>/dev/null || true
sudo rm -f /Library/LaunchDaemons/local.claude-vm-pf.plist /usr/local/sbin/claude-vm-pf.sh

# 2) 清空并删除锚点
sudo pfctl -a com.apple/100.claude-vm -F all 2>/dev/null || true
sudo rm -f /etc/pf.anchors/claude-vm

# 3) 恢复 pf.conf（二选一）
sudo cp -p /etc/pf.conf.before-claude-vm-20261121-222527 /etc/pf.conf
# 或者手动删掉末尾的 claude-vm 三行

# 4) 不要在用 UTM 时 pfctl -f；重启宿主最稳
```

备份文件：

- `/etc/pf.conf.before-claude-vm-20261121-222527`
- `/etc/pf.conf.before-vpn-removal-<date>`
- 本机卸载记录（未随仓库上传）

---

## 6. Claude Code

### 6.1 安装

在客户机里（走代理）：

```bash
export HTTP_PROXY=http://192.168.64.1:10808
export HTTPS_PROXY=$HTTP_PROXY
curl -fsSL https://claude.ai/install.sh | bash
```

本次下载的二进制是 `claude-2.1.330-darwin-arm64`（约 347 MB），安装到：

```
~/.local/bin/claude -> ~/.local/share/claude/versions/2.1.330
```

安装器不会自动改 PATH，需要手动加：

```bash
# CLAUDE_VM_PATH
export PATH="$HOME/.local/bin:$PATH"
```

写入 `~/.zshrc` 和 `~/.zprofile`。验证：

```bash
zsh -lc 'which claude; claude --version'
# /Users/claude/.local/bin/claude
# 2.1.330 (Claude Code)
```

### 6.2 `claude doctor`

```bash
zsh -lc 'claude doctor'
```

实测通过：`native (2.1.330)`、`darwin-arm64`、auto-updates enabled。

唯一警告：

```
macOS Keychain is not writable ... Console login will fail to save your API key.
```

原因是通过 SSH 运行 `claude doctor`，没有 GUI 登录上下文。**在虚拟机桌面里的 Terminal 登录不会出现这个问题**。也可以通过 token 方式绕开（见 6.3）。

### 6.3 登录（二选一）

**方式 A：虚拟机桌面交互登录（推荐）**

1. 在 UTM 窗口里进入虚拟机桌面。
2. 打开 Terminal。
3. 运行 `claude`。
4. 按提示打开登录 URL（Safari 已配置系统代理，能访问）。
5. 如果显示 code，粘贴回 Terminal。
6. 看到登录成功后，运行 `claude doctor` 确认。

**方式 B：宿主机生成 token**

宿主机已安装 Claude Code，可以：

```bash
claude setup-token
```

把输出的 token 写入客户机 `~/.zshrc`（文件权限保持 600）：

```bash
export CLAUDE_CODE_OAUTH_TOKEN='粘贴 token'
```

然后：

```bash
source ~/.zshrc
claude --version
claude doctor
```

> `CLAUDE_CODE_OAUTH_TOKEN` 可用于模型请求，但不能建立 Remote Control 会话或拉取 claude.ai 连接器；本地 MCP 仍可用。token 等同密码，不要提交到 git。

**当前状态（2026-11-21）**：已安装 2.1.330，**尚未登录**（`claude auth status` 显示 `loggedIn: false`）。登录这一步需要你在虚拟机桌面里完成，或在宿主机生成 token。

### 6.4 更新与持久化

- 自动更新已启用（doctor 显示 `Auto-updates: enabled`）。
- 手动更新：`claude update`。
- 配置/登录状态在 `~/.claude`，虚拟机磁盘持久化；不会因为关虚拟机丢失。
- 备份：
  ```bash
  tar czf ~/claude-backup-$(date +%F).tgz ~/.claude
  ```

---

## 7. 文件共享（可选）

### 7.1 VirtioFS（推荐，需双方 macOS 13+）

UTM 官方文档：VirtioFS 需要宿主和客户机都 macOS 13+；在 UTM 虚拟机设置里添加共享目录，然后在客户机挂载。

1. UTM 选中虚拟机 → Settings → Sharing → 添加要共享的 Mac 目录。
2. 客户机：

```bash
sudo mkdir -m 777 -p /Users/claude/mac
sudo mount_virtiofs share /Users/claude/mac
```

> 官方文档的挂载名是 `share`；如果你的 UTM 设置里共享名不同，替换掉。**本机尚未实际配置/验证**。

卸载：

```bash
umount /Users/claude/mac
```

### 7.2 SSH / rsync（已验证可用）

从宿主机推文件：

```bash
scp -i ~/.ssh/id_ed25519_claude_vm 本地文件 claude@192.168.64.2:~/work/
```

同步目录：

```bash
rsync -av -e "ssh -i ~/.ssh/id_ed25519_claude_vm" \
  本地目录/ claude@192.168.64.2:~/work/
```

### 7.3 Orca（可选，未验证）

Orca 官方只支持 SSH 主机；本方案没有容器。理论上：

- Settings → SSH → Add Target
- Host：`192.168.64.2`
- User：`claude`
- Key：`~/.ssh/id_ed25519_claude_vm`

**未在本机验证**，且 Orca 默认可能给 Claude 传 `--dangerously-skip-permissions`，不建议在宿主机这样跑；在隔离虚拟机里也要自行评估。

---

## 8. 日常使用

### 8.1 启动顺序

1. 启动宿主机代理客户端（v2rayN），确认 xray 在 `127.0.0.1:10808` 监听。
2. 打开 UTM，选中 `macOS`，点播放按钮。
   - 如果提示“恢复虚拟机时发生错误”，改用：
     ```bash
     osascript -e 'tell application "UTM" to start virtual machine named "macOS" without saving'
     ```
3. 等虚拟机启动，确认 `bridge100` 出现、中转绑定：
   ```bash
   ifconfig bridge100 | grep 'inet '
   tail -5 /var/log/claude-vm-proxy-relay.log
   ```
4. 从宿主机 SSH：

```bash
ssh -i ~/.ssh/id_ed25519_claude_vm claude@192.168.64.2
```

可选 SSH 别名（写入 `~/.ssh/config`）：

```sshconfig
Host claude-macos
  HostName 192.168.64.2
  User claude
  IdentityFile ~/.ssh/id_ed25519_claude_vm
```

之后 `ssh claude-macos` 即可。注意 IP 是 DHCP，变化时要改。

### 8.2 获取虚拟机 IP

```bash
osascript -e 'tell application "UTM" to query ip of virtual machine named "macOS"'
```

或在虚拟机里：

```bash
ipconfig getifaddr en0
```

### 8.3 关机

- 虚拟机内：Apple 菜单 → 关机。
- 或 UTM 工具栏停止按钮。
- 不建议依赖“保存状态”：本机实测宿主重启后恢复保存状态失败，需要 `start ... without saving`。

### 8.4 代理故障时的表现

- 关闭 v2rayN/xray：虚拟机走代理会失败，直连被 pf 阻断 → **完全断网**，这是预期的 fail-closed。
- 重新启动 v2rayN 后，中转不需要重启（它只转发 TCP；xray 恢复后新连接即可用）。
- 检查：
  ```bash
  launchctl print system/local.claude-vm-proxy-relay | grep -E 'state|pid'
  tail -20 /var/log/claude-vm-proxy-relay.log
  ```

---

## 9. 验收清单

搭建完成后逐项打勾（本机 2026-11-21 实测结果）：

- [x] UTM 5.0.8 已安装，虚拟机 `macOS` 能启动
- [x] 客户机 macOS 27.2.1，4 CPU / 8 GB / 75 GiB
- [x] 客户机 IP `192.168.64.2`，网关 `192.168.64.1`，接口 `bridge100`
- [x] 宿主 → 客户机免密 SSH
- [x] 客户机 locale `zh_TW` / `zh-Hant-TW`，时区 `Asia/Taipei`
- [x] 客户机 IPv6 已关闭，DNS 只走 `192.168.64.1:53`
- [x] 客户机系统代理 + shell 代理指向 `192.168.64.1:10808`
- [x] 客户机直连 `api.anthropic.com` 超时（fail-closed）
- [x] 客户机走代理返回 HTTP 404（链路通）
- [x] 宿主 `127.0.0.1:10808` 代理正常
- [x] 宿主 SSH / ping 客户机正常
- [x] `com.apple/100.claude-vm` 锚点在主规则集中，排在 `com.apple.internet-sharing` 之前
- [x] 旧 VPN 锚点已从运行规则集中消失
- [x] 重启宿主后规则仍生效
- [x] 中转 LaunchDaemon 开机自启，网桥出现后自动绑定
- [x] Claude Code 2.1.330 安装，`claude doctor` 通过
- [ ] Claude Code 登录（待完成）
- [ ] VirtioFS 文件共享（可选，未配置）
- [ ] 修改虚拟机默认密码（建议）

---

## 10. 故障排查

| 现象 | 可能原因 | 处理 |
|---|---|---|
| 虚拟机没有 IP / `bridge100` 不存在 | UTM 里的虚拟机没启动 | 打开 UTM 启动 `macOS`；检查 `ifconfig bridge100` |
| 启动报“恢复虚拟机时发生错误 / 无效的自变量” | 宿主重启后保存状态不兼容 | `osascript ... start ... without saving`，或 GUI 选不恢复状态启动 |
| SSH `Connection refused` | 客户机 Remote Login 没开 | 客户机：系統設定 → 一般 → 共享 → 遠端登入；允许 `claude` 或所有使用者 |
| SSH 密码/公钥都失败 | 用户名不是 `claude` 或密码错 | 在客户机终端 `whoami`；重新 `ssh-copy-id` 或手动写 `authorized_keys` |
| 虚拟机仍能直连公网 | pf 锚点没生效 | `sudo pfctl -s Anchors` 看 `com.apple/100.claude-vm`；`sudo pfctl -a com.apple/100.claude-vm -sr` 看规则；确认 `/etc/pf.conf` 里有 `anchor` 和 `load anchor` |
| 直连失败但代理也不通 | xray 没启动 / 中转没绑定 / 客户机代理配错 | 宿主 `lsof -nP -iTCP:10808`；`tail /var/log/claude-vm-proxy-relay.log`；客户机 `scutil --proxy`、`env | grep -i proxy` |
| 中转日志反复 `can't assign requested address` | `bridge100` 还没出现，或 IP 变了 | 启动虚拟机；若 IP 变了，改 `LISTEN_HOST` 并 `launchctl kickstart -k system/local.claude-vm-proxy-relay` |
| 中转日志 `Address already in use` | 旧的临时中转还在 | `sudo pkill -f claude-vm-proxy-relay.py`，LaunchDaemon 会自动重启 |
| `pfctl: anchor ... not found` | 锚点文件或 pf.conf 引用缺失 | 重新安装锚点；确认 `pfctl -s Anchors` 有 `com.apple/100.claude-vm` |
| 加了 pf 规则后 UTM 网络断了 | 重载主规则集冲掉了 Internet Sharing 锚点 | 不要在用 UTM 时 `pfctl -f`；重启宿主；恢复 `/etc/pf.conf.before-*` 备份 |
| `block drop quick in ...` 语法错误 | macOS pf 解析器要求方向在 `drop` 后 | 改成 `block drop in quick ...` |
| 客户机 DNS 失败 | 网关 DNS 不可达 / IPv6 优先 | `scutil --dns`；`sudo networksetup -setv6off Ethernet`；确认 pf 放行 53 |
| `claude doctor` 报 Keychain 不可写 | 通过 SSH 运行，没有 GUI 上下文 | 在虚拟机桌面 Terminal 登录；或使用 `CLAUDE_CODE_OAUTH_TOKEN` |
| Claude Code 命令找不到 | `~/.local/bin` 不在 PATH | 在 `.zshrc` 和 `.zprofile` 加 `export PATH="$HOME/.local/bin:$PATH"` |
| 语言/时区没变 | 需要注销/重启 | `defaults read -g AppleLocale`；注销后重新登录 |
| 虚拟机时间漂移 | pf 阻断了 NTP（UDP 123） | 虚拟机通常由 Virtualization 同步时间；若漂移明显，可在宿主跑本地 NTP 并放行 UDP 123（未实现） |
| 重启后旧 VPN 锚点又出现 | 该 VPN 客户端被重新安装 | 按 5.1 重新检查 `pf.conf` 和锚点顺序；必要时重做卸载 |

---

## 11. 与视频的对应关系

| 视频里的说法 | 本手册的实现 | 说明 |
|---|---|---|
| Mac → Ubuntu VM → Docker 容器 | Mac → UTM macOS VM → 原生 Claude Code | 明确不用 Docker |
| 虚拟机有独立虚拟网卡和内网地址 | UTM Shared Network，`192.168.64.0/24` | 实测 |
| 网络环境配在 Mac 上 | pf 锚点 + 宿主中转 + 网关 DNS | 虚拟机只写一次代理地址 |
| 指定出口不可用时拦截公网流量 | `block drop in quick ...` | fail-closed，已验收 |
| SSH 走本地虚拟网络 | 宿主 → `192.168.64.2:22` | 已验收 |
| 容器里设东京时区、日语 | 虚拟机里设台灣繁體/Asia/Taipei | 仅 locale，不改变网络出口 |
| Ghostty 里 `ssh claude-code-fresh` → `claude` | 宿主 `ssh claude-macos` → `claude` | 本机无容器，直接进虚拟机 |
| 偶尔通过 Orca 调 Mac 文件/工具 | 可选；本手册推荐 SSH/rsync/VirtioFS | Orca 未验证 |
| 不租 VPS：性能、价格、传文件 | 本机方案 | 一致 |
| 封号原因 | 视频未确认 | 本手册不承诺避免风控；请遵守服务条款 |

---

## 12. 已知限制

1. **硬编码实测值**：`bridge100`、`192.168.64.0/24`、`192.168.64.1`、`192.168.64.2` 都是本机实测。换机器、换 UTM 后端、或系统重建后可能变化，必须重新测量并改 pf/中转/客户机代理。
2. **中转脚本硬编码 `LISTEN_HOST`**：网桥 IP 变化时中转会绑定失败并每 5 秒重试；日志会提示，需手动改脚本。
3. **pf 主规则集的动态锚点**：UTM/Internet Sharing 的锚点是运行时的，不能用 `pfctl -f /etc/pf.conf` 随便重载；本方案靠重启加载。若你以后加了别的网络共享/VPN，先检查锚点顺序。
4. **macOS 客户机不支持嵌套虚拟化**：不要在客户机里装 Docker Desktop/Parallels/VMware；这不是配置问题。
5. **Claude Code 登录**：通过 SSH 运行 `claude doctor` 会看到 Keychain 警告；登录请在虚拟机桌面完成，或用 token。
6. **Apple 服务**：pf 只放行代理/DNS/SSH/文件共享，iCloud、APNs、NTP 等直连会被阻断；虚拟机不登录 Apple ID 即可。
7. **locale 不等于网络出口**：繁體中文/台灣时区不会改变 IP 归属或账号地区；封号风险不由本方案解决。
8. **文件共享未配置**：VirtioFS 的挂载命令来自官方文档，本机未实际验证；SSH/rsync 已验证。
9. **UTM/虚拟机不会自动启动**：需要手动打开 UTM 并启动 `macOS`；可以自行加登录项，但本手册未配置。
10. **虚拟机密码较弱**：搭建时使用了简单密码，建议在客户机「系統設定 → 使用者與群組」里改强；本手册不记录密码。
11. **中转以 root 运行**：代码很短（纯 TCP 转发），但仍建议你自行审阅 `/usr/local/sbin/claude-vm-proxy-relay.py`；它只监听 `192.168.64.1:10808`，不暴露到热点/LAN。
12. **未验证项**：UTM 向导的具体字段标签、VirtioFS 挂载、Orca SSH target、`claude setup-token` 流程、macOS 12/13/15 客户机行为。

---

## 附录 A：关键文件清单

| 路径 | 用途 |
|---|---|
| `/Applications/UTM.app` | UTM 5.0.8 |
| `~/Library/Containers/com.utmapp.UTM/Data/Documents/macOS.utm` | 虚拟机包（沙盒，勿手改） |
| `~/.ssh/id_ed25519_claude_vm` | 宿主 → 虚拟机专用密钥 |
| `~/Projects/我的项目/claude-vm-proxy-relay.py` | 中转源码 |
| `/usr/local/sbin/claude-vm-proxy-relay.py` | 中转安装位置 |
| `/Library/LaunchDaemons/local.claude-vm-proxy-relay.plist` | 中转 LaunchDaemon |
| `/var/log/claude-vm-proxy-relay.log` | 中转日志 |
| `~/Projects/我的项目/pf-claude-vm.draft.conf` | pf 锚点源文件 |
| `/etc/pf.anchors/claude-vm` | pf 锚点安装位置 |
| `/usr/local/sbin/claude-vm-pf.sh` | pf 开机脚本 |
| `/Library/LaunchDaemons/local.claude-vm-pf.plist` | pf LaunchDaemon |
| `/var/log/claude-vm-pf.log` | pf 日志 |
| `/etc/pf.conf` | 主规则集（末尾有 claude-vm 锚点） |
| `/etc/pf.conf.before-claude-vm-20261121-222527` | 加锚点前备份 |
| `/etc/pf.conf.before-vpn-removal-<date>` | 删旧 VPN 前备份（本机文件名） |
| 本机卸载记录 | 未随仓库上传 |
| 客户机 `~/.local/bin/claude` | Claude Code 2.1.330 |
| 客户机 `~/.claude` | Claude Code 配置/登录状态 |
| 客户机 `~/.zshrc` / `~/.zprofile` | 代理环境变量 + PATH |

## 附录 B：参考链接

- UTM macOS guest：<https://docs.getutm.app/guest-support/macos/>
- UTM Apple 网络设置：<https://docs.getutm.app/settings-apple/devices/network/>
- UTM Apple 共享：<https://docs.getutm.app/settings-apple/sharing/>
- UTM 脚本（`query ip`、`start vm without saving`）：<https://docs.getutm.app/scripting/cheat-sheet/>
- Claude Code 安装与登录：<https://code.claude.com/docs/en/setup>、<https://code.claude.com/docs/en/authentication>
- Claude Code 网络配置：<https://code.claude.com/docs/en/network-config>
- macOS pf：`man pf.conf`、`man pfctl`
- 本机项目内参考：`教程-视频总结.md`、`Claude-Code-隔离环境-操作手册.md`（Ubuntu + Docker 版）

---

## 附录 C：最短路径（照抄版）

1. UTM 5.0.8 → Virtualization → macOS 12+ → 自动下载 IPSW → 4 CPU / 8192 MB / 80 GB → Shared Network。
2. Setup Assistant：繁體中文/台灣，用户 `claude`，不登录 Apple ID，不开 FileVault；开启遠端登入。
3. 宿主 `ssh-copy-id -i ~/.ssh/id_ed25519_claude_vm.pub claude@192.168.64.2`。
4. 客户机：`networksetup -setv6off Ethernet`；设置 web/secure proxy `192.168.64.1:10808`；把代理变量写进 `.zshrc`/`.zprofile`。
5. 宿主安装中转 `local.claude-vm-proxy-relay`（监听 `192.168.64.1:10808`）。
6. 宿主安装 pf 锚点 `com.apple/100.claude-vm`（放行 10808/22/445/548/5900/53/DHCP，其余 `block drop in quick`）。
7. 重启宿主；启动 UTM 和 `macOS`；验收直连失败、代理成功、DNS/SSH 正常。
8. 客户机安装 Claude Code，加 PATH，桌面登录或注入 token。
