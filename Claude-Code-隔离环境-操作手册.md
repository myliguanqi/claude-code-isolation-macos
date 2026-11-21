# Claude Code 隔离工作环境 操作手册

> 对应视频：《Mac 上怎么用 Claude Code：UTM + Ubuntu + Docker 实录》
> 适用：Apple Silicon Mac（Intel 也可，命令基本一致）、macOS 13+
> 目标：在 Mac 上搭出「Mac 宿主机 → UTM Ubuntu 虚拟机 → Docker 容器」三层环境，Claude Code 只在容器里运行；网络出口由 Mac 统一控制，虚拟机直连公网被阻断（fail-closed）。
>
> **重要说明**：视频只讲了思路和架构，没有展示 UTM、防火墙、Docker 的具体参数。本手册给出了一套可执行的默认实现；凡标注「可选」「按你的环境修改」的地方，需要你按实际情况填写。

---

## 0. 最终形态

```
┌──────────────────────────────────────────────┐
│ Mac 宿主机                                    │
│  - UTM（虚拟化）                              │
│  - 代理客户端（mihomo / Clash / Surge 等）     │
│  - pf 防火墙：放行 VM↔Mac 本地流量，阻断其余出站 │
│                                              │
│   ┌────────────────────────────────────────┐ │
│   │ Ubuntu 虚拟机 192.168.64.10             │ │
│   │  - Docker                              │ │
│   │  ┌──────────────────────────────────┐  │ │
│   │  │ 容器 claude-code                  │  │ │
│   │  │  - Claude Code                    │  │ │
│   │  │  - 项目目录 /workspace            │  │ │
│   │  └──────────────────────────────────┘  │ │
│   └────────────────────────────────────────┘ │
└──────────────────────────────────────────────┘
```

### 三条设计原则

1. **分层隔离**：Mac 负责宿主与网络策略，Ubuntu 提供独立网络身份，Docker 提供可复刻的运行环境。
2. **策略集中在 Mac**：代理和出站规则配在 Mac 上，虚拟机与容器不各自维护一套网络策略。
3. **Fail-closed**：代理不可用时，虚拟机直接断网，而不是自动回退到直连。

### 先选一条网络路线

| | 路线 A：显式代理 + pf 白名单 | 路线 B：透明网关 |
|---|---|---|
| 做法 | Mac 开代理端口；pf 放行 VM↔Mac 本地流量、阻断其余出站；VM/容器设置一次代理地址 | Mac 作为透明网关，pf 把 VM 流量重定向到本机代理 |
| VM/容器里要配代理吗 | **要**（一次性的环境变量/Docker 配置） | **不要**（最接近视频） |
| 难度 | 低，最容易验证 | 中高，依赖额外组件 |
| 推荐 | **先用 A 跑通** | 跑通 A 后再升级 |

> 视频说「Ubuntu 和容器里都不用再配一遍代理」，对应的就是路线 B。但 macOS 上要做到全透明，需要 Surge 网关模式或 `trans_proxy` 这类组件；其中 `trans_proxy` 对 UTM 共享网络的 `bridge100` 没有官方验证。因此本手册把 A 作为默认、B 作为进阶。

### 合规提醒

视频作者的封号原因只是个人推测，视频中明确说「具体原因没确认」。本手册解决的是**环境隔离和网络出口管理**，不保证避免账号风控，也不建议用环境伪装去规避服务条款。请使用官方支持地区的合规账号，并以 Anthropic/Claude 的官方条款为准。

---

## 1. 准备清单

### 硬件与系统

- Apple Silicon Mac（M1 及以上），建议内存 ≥ 16 GB，可用磁盘 ≥ 60 GB。
- macOS 13 或更高版本（本文按 macOS 26/27 的命令写，旧版本基本通用）。

### 软件

| 软件 | 用途 | 安装方式 |
|---|---|---|
| UTM | 虚拟机 | `brew install --cask utm`（免费版） |
| Ubuntu Server 24.04 LTS ARM64 | 虚拟机系统 | 官网下载 ISO |
| Ghostty（可选） | 终端 | `brew install --cask ghostty` |
| 代理客户端 | 指定出口 | 你现有的 mihomo / Clash Verge / Surge 等 |
| Orca（可选） | Agent 编排 | `brew install --cask stablyai/orca/orca` |

### 参数表（建议先填好）

| 参数 | 本文默认值 | 你的值 |
|---|---|---|
| Mac 在 UTM 网络中的地址 | `192.168.64.1` | |
| VM 子网 | `192.168.64.0/24` | |
| VM 静态 IP | `192.168.64.10` | |
| VM 用户名 | `claude` | |
| Mac 代理端口 | `7890` | |
| 容器名 | `claude-code` | |
| VM 项目目录 | `~/work` | |
| 容器内项目目录 | `/workspace` | |
| Claude 配置目录 | `~/claude-config` | |

---

## 2. 第一步：创建 Ubuntu 虚拟机

### 2.1 安装 UTM

```bash
brew install --cask utm
```

也可以从 <https://mac.getutm.app/> 下载免费版。App Store 版本是付费版，功能基本一致。

### 2.2 新建虚拟机

1. 打开 UTM → **Create a New Virtual Machine**。
2. 选择 **Virtualize**（Apple Silicon 用虚拟化，速度快）→ **Linux**。
3. 选择 Ubuntu Server 24.04 LTS ARM64 的 ISO。
4. 配置：
   - Memory：**8192 MB**（最低 4096 MB）
   - CPU：**4 核**
   - Disk：**64 GB**
5. 网络：选择 **Shared Network**（共享网络）。
   - 该模式默认使用 `192.168.64.0/24`，Mac 的地址是 `192.168.64.1`。
   - **不要**勾选「Isolate Guest from Host」，否则 VM 无法访问 Mac 上的代理端口。
6. 名称填 `claude-vm`，保存并启动。

### 2.3 安装 Ubuntu

按向导安装，建议：

- 语言选 **English**（避免 VM 内 locale 影响命令输出；容器里的日语/时区在后面单独配）。
- 用户名：`claude`。
- 勾选 **Install OpenSSH server**。
- 不需要额外 snap 服务。

安装完成后重启，登录 VM。

### 2.4 确认网络与 SSH

在 UTM 窗口里登录 VM：

```bash
ip -br link                 # 确认网卡名，通常是 enp0s1
ip -4 addr show             # 记下当前 IP
ip route                    # 默认路由应指向 192.168.64.1
sudo systemctl status ssh   # 确认 SSH 已启动
```

在 Mac 上测试：

```bash
ssh claude@192.168.64.10    # 如果还是 DHCP，换成上一步看到的 IP
```

建议配置 SSH 密钥，避免每次输密码：

```bash
ssh-keygen -t ed25519 -C "claude-vm"    # 已有密钥可跳过
ssh-copy-id claude@192.168.64.10
```

### 2.5 固定 IP（推荐）

DHCP 地址变化会让后面的 pf 规则失效，建议给 VM 设静态 IP。

在 VM 里确认网卡名：

```bash
ip -br link
```

假设网卡是 `enp0s1`，创建 netplan 配置：

```bash
sudo tee /etc/netplan/99-claude-static.yaml >/dev/null <<'EOF'
network:
  version: 2
  ethernets:
    enp0s1:
      dhcp4: false
      dhcp6: false
      accept-ra: false
      addresses: [192.168.64.10/24]
      routes:
        - to: default
          via: 192.168.64.1
      nameservers:
        addresses: [1.1.1.1]
EOF
sudo chmod 600 /etc/netplan/99-claude-static.yaml
sudo netplan try     # 有 120 秒确认时间；确认没问题再按回车
sudo netplan apply
```

> 如果网卡名不是 `enp0s1`，把配置里的名字改掉。`dhcp6: false` / `accept-ra: false` 是为了禁用 IPv6，防止绕过后面的 IPv4 防火墙规则。

验证：

```bash
ip -4 addr show
ip route
ip -6 addr show          # 应该没有全局 IPv6 地址
```

> **注意**：后面的 pf 规则一旦启用，VM 就不能直接上公网了。所以先把下面所有「需要联网安装」的步骤做完，或者先不要启用 pf。

---

## 3. 第二步：网络隔离（核心）

### 3.1 路线 A：Mac 代理 + pf 白名单（推荐先跑通）

思路：Mac 上开一个代理端口（例如 `7890`），pf 允许 VM 与 Mac 之间的本地流量（代理、SSH、SSHFS、DNS），其余 VM 出站全部丢弃。VM 和容器通过这个代理上网。

#### 3.1.1 让 Mac 代理对 VM 可见

以 mihomo 为例，配置文件里至少要有：

```yaml
mixed-port: 7890
allow-lan: true
bind-address: '*'
mode: rule
```

如果用的是 Clash Verge / Stash / Surge 等 GUI 客户端：

- 打开「允许局域网连接 / Allow LAN」。
- 确认混合端口（HTTP/SOCKS）是 `7890`，或记下实际端口。
- 在客户端里选中你要用的「指定出口」节点。

验证 Mac 本机监听：

```bash
lsof -nP -iTCP:7890 -sTCP:LISTEN
```

应该能看到 `*:7890` 或 `0.0.0.0:7890`。再从 Mac 本机测试代理：

```bash
curl -x http://127.0.0.1:7890 -sS --max-time 15 https://api.anthropic.com/ -o /dev/null -w '%{http_code}\n'
```

返回任意 HTTP 状态码（200/401/403 都算通）说明代理可用。

> 安全提示：`bind-address: '*'` 会让代理监听所有网卡。下面的 pf 规则会阻止非 VM 来源访问 7890，但 **macOS 应用防火墙** 还可能弹窗询问是否允许 mihomo 接受传入连接，选择允许。不要把代理端口暴露到公网。

#### 3.1.2 写 pf 锚点

> 这里用的是 **pf（包过滤防火墙）**，不是「系统设置 → 网络 → 防火墙」里的应用防火墙。后者按 App 放行入站连接，做不到按来源网段控制虚拟机的出站流量。两者可以同时开启，互不替代。

macOS 的 `/etc/pf.conf` 已经包含 `anchor "com.apple/*"`，所以我们把规则加载到 `com.apple/100.claude-vm` 这个子锚点里，**不需要改 `/etc/pf.conf`**。

创建规则文件：

```bash
sudo tee /etc/pf.anchors/claude-vm >/dev/null <<'EOF'
# 1) 允许 VM 与 Mac 之间的本地流量（代理、SSH、SSHFS、DNS 等）
pass in quick inet from 192.168.64.0/24 to 192.168.64.1 keep state

# 2) 阻止其他设备访问 Mac 上的代理端口（VM 已被上一条放行）
block drop quick in inet proto tcp from any to 192.168.64.1 port 7890

# 3) 允许 DNS 到公共解析器（二选一，见 3.4）
#    注意用 in 方向：UTM 的 NAT 会在 out 方向把源地址改写成 Mac 的地址，
#    如果写 pass out from 192.168.64.0/24，NAT 之后可能匹配不到。
pass in quick inet proto { tcp, udp } from 192.168.64.0/24 to 1.1.1.1 port 53 keep state

# 4) 其余 VM 出站全部丢弃：在入方向、NAT 之前拦截
block drop quick in inet from 192.168.64.0/24 to any
EOF
```

加载并启用：

```bash
sudo pfctl -e 2>/dev/null || true
sudo pfctl -a com.apple/100.claude-vm -f /etc/pf.anchors/claude-vm
sudo pfctl -a com.apple/100.claude-vm -sr     # 能看到规则
sudo pfctl -s info | head -3                  # Status: Enabled
```

> 规则顺序很重要：`pass ... quick` 必须放在 `block ... quick` 前面，否则代理端口也会被拦。`quick` 表示匹配后立即停止后续规则。
>
> 第 1 条放行的是「VM → Mac 的所有本地端口」，这样 SSH、SSHFS、代理都能用。如果你不需要 VM 访问 Mac 的其他服务，可以把第 1 条收窄成只放行 `7890`、`22`、`53` 等具体端口；但收窄后要重新测试 SSH 和 SSHFS。

#### 3.1.3 开机自动加载

pf 锚点不会自动跨重启保留，用 LaunchDaemon 在开机时加载。

创建脚本：

```bash
sudo tee /usr/local/sbin/claude-vm-pf.sh >/dev/null <<'EOF'
#!/bin/sh
/sbin/pfctl -e >/dev/null 2>&1 || true
/sbin/pfctl -a com.apple/100.claude-vm -f /etc/pf.anchors/claude-vm
EOF
sudo chown root:wheel /usr/local/sbin/claude-vm-pf.sh
sudo chmod 755 /usr/local/sbin/claude-vm-pf.sh
```

创建 LaunchDaemon：

```bash
sudo tee /Library/LaunchDaemons/local.claude-vm-pf.plist >/dev/null <<'EOF'
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
  <key>Label</key>
  <string>local.claude-vm-pf</string>
  <key>ProgramArguments</key>
  <array>
    <string>/usr/local/sbin/claude-vm-pf.sh</string>
  </array>
  <key>RunAtLoad</key>
  <true/>
  <key>KeepAlive</key>
  <false/>
</dict>
</plist>
EOF
sudo chown root:wheel /Library/LaunchDaemons/local.claude-vm-pf.plist
sudo chmod 644 /Library/LaunchDaemons/local.claude-vm-pf.plist
sudo launchctl bootout system/local.claude-vm-pf 2>/dev/null || true
sudo launchctl bootstrap system /Library/LaunchDaemons/local.claude-vm-pf.plist
```

验证：

```bash
sudo launchctl print system/local.claude-vm-pf | head -20
sudo pfctl -a com.apple/100.claude-vm -sr
```

以后修改了 `/etc/pf.anchors/claude-vm`，需要手动重新加载一次；LaunchDaemon 只在开机时执行：

```bash
sudo pfctl -a com.apple/100.claude-vm -f /etc/pf.anchors/claude-vm
```

#### 3.1.4 VM 与容器设置代理

**VM 的 shell 环境**（写入 `~/.bashrc` 或 `~/.profile`）：

```bash
cat >> ~/.bashrc <<'EOF'
export HTTP_PROXY=http://192.168.64.1:7890
export HTTPS_PROXY=$HTTP_PROXY
export NO_PROXY=localhost,127.0.0.1,::1
EOF
source ~/.bashrc
```

**apt**（`sudo apt` 不会继承普通用户的环境变量）：

```bash
sudo tee /etc/apt/apt.conf.d/95proxy >/dev/null <<'EOF'
Acquire::http::Proxy "http://192.168.64.1:7890";
Acquire::https::Proxy "http://192.168.64.1:7890";
EOF
```

**Docker 守护进程**（用于 `docker pull`）：

```bash
sudo mkdir -p /etc/systemd/system/docker.service.d
sudo tee /etc/systemd/system/docker.service.d/http-proxy.conf >/dev/null <<'EOF'
[Service]
Environment="HTTP_PROXY=http://192.168.64.1:7890"
Environment="HTTPS_PROXY=http://192.168.64.1:7890"
Environment="NO_PROXY=localhost,127.0.0.1"
EOF
sudo systemctl daemon-reload
sudo systemctl restart docker
```

**容器**：在 `docker run` / compose 里传 `HTTP_PROXY`、`HTTPS_PROXY`（见第 4 节）。

> 注意：`HTTP_PROXY` 只影响 HTTP(S) 客户端。`git@github.com` 这类 SSH 协议不会走代理，会被 pf 阻断；克隆时优先用 HTTPS URL。如果必须用 SSH 形式的 git，需要额外给 SSH 配 `ProxyCommand`，这已经超出本手册的默认方案。

#### 3.1.5 验收（fail-closed）

在 VM 里执行：

```bash
# 直连应该失败（超时/拒绝）
# 注意：shell 里已经 export 了 HTTP_PROXY，curl 会自动走代理；
# 这里必须清掉代理变量，才是真正的“直连”测试
env -u HTTP_PROXY -u HTTPS_PROXY -u http_proxy -u https_proxy \
  curl --noproxy '*' -sS --max-time 5 https://api.anthropic.com/ \
  -o /dev/null -w '%{http_code}\n' || echo "BLOCKED"

# 走代理应该成功（返回任意 HTTP 状态码）
curl -x http://192.168.64.1:7890 -sS --max-time 15 https://api.anthropic.com/ -o /dev/null -w '%{http_code}\n'
```

预期：第一条失败或超时，第二条返回状态码。

再把 Mac 上的代理客户端停掉，重新执行第二条：应该失败。这说明是 fail-closed，而不是悄悄走了直连。

---

### 3.2 路线 B：全透明网关（贴近视频，进阶）

> 如果已经按路线 A 配过 pf，切到 B 之前先卸载 A 的锚点，避免两套规则互相干扰：
>
> ```bash
> sudo pfctl -a com.apple/100.claude-vm -F all
> sudo launchctl bootout system/local.claude-vm-pf 2>/dev/null || true
> ```
>
> 需要回到 A 时，再重新加载锚点并 bootstrap LaunchDaemon。

目标：VM 和容器里完全不写代理地址。

#### 方案 B1：Surge 网关模式（如果有 Surge 6+）

1. 在 Surge 中开启 **增强模式（Enhanced Mode）** 或 **VM 网关**。
2. UTM 的 Shared Network 已经让 VM 的网关指向 Mac（`192.168.64.1`），保持默认。
3. 把 VM 的 DNS 改为 Surge 的 Fake-IP DNS：`198.18.0.2`。
4. 在 Surge 的请求日志里确认能看到来自 `192.168.64.x` 的请求。

注意：Surge 官方文档提到 VM 网关模式不能和其他虚拟机软件的「桥接模式」同时使用；UTM 这里用的是 Shared Network，不是 Bridged，通常不冲突，但仍需实测。

#### 方案 B2：trans_proxy（免费，需自行验证）

`trans_proxy` 是 macOS/Linux 上的透明 TCP 代理，配合 pf 把客户端流量重定向到上游 HTTP/SOCKS5 代理。

```bash
# 从 release 下载 darwin-arm64 包，或：
git clone https://github.com/madeye/trans_proxy.git
cd trans_proxy
cargo build --release
sudo cp target/release/trans_proxy /usr/local/bin/
```

Mac 上已有代理（`127.0.0.1:7890`）的前提下：

```bash
# 先确认 UTM 共享网络对应的接口名（通常是 bridge100）
ifconfig | grep -B3 '192.168.64.1'

sudo /usr/local/bin/trans_proxy \
  --upstream-proxy 127.0.0.1:7890 \
  --dns \
  --interface bridge100 \
  --listen-addr 0.0.0.0:8443 \
  --daemon \
  --log-file /var/log/trans_proxy.log

sudo /usr/local/bin/trans_proxy \
  --upstream-proxy 127.0.0.1:7890 \
  --dns \
  --interface bridge100 \
  --setup-firewall
```

验证：

```bash
sudo pfctl -a trans_proxy -sr
dig @192.168.64.1 api.anthropic.com
# VM 内：
curl -sS --max-time 15 https://api.anthropic.com/ -o /dev/null -w '%{http_code}\n'
```

使用 B2 时：

- 把 VM 的默认网关设为 `192.168.64.1`，DNS 也设为 `192.168.64.1`（trans_proxy 的 `--dns` 会在 53 端口转发）。
- 确认 VM 的 shell、apt、Docker 里都**没有**残留 `HTTP_PROXY` / `HTTPS_PROXY`，否则仍然是显式代理而不是透明代理。

注意：

- `trans_proxy` 文档没有明确验证 UTM 的 `bridge100` / `192.168.64.0/24`，需要实测；如果 `DIOCNATLOOK failed` 或连接挂起，回到路线 A。
- 它的 pf 锚点主要做重定向，**不一定是默认拒绝**。要确认「非 80/443 端口」也被阻断，否则仍然存在绕过路径。可以在其锚点基础上补一条 `block drop quick inet from 192.168.64.0/24 to any`，但要注意锚点求值顺序，改完必须重新验收 3.1.5。
- 如果只想先跑通，不建议一上来就用 B2；先把 A 跑稳，再评估是否需要全透明。

---

### 3.3 DNS 与 IPv6

- 路线 A 中，VM 的 DNS 设为 `1.1.1.1`，pf 只放行到 `1.1.1.1:53` 的 DNS。这是唯一的直连例外；如果要求 DNS 也走代理，见下。
- 更严格的做法：在 Mac 上跑一个只监听 `192.168.64.1:53` 的 dnsmasq，VM 的 DNS 指向 `192.168.64.1`。3.1.2 的本地放行规则已经覆盖 53 端口，不需要额外加规则；同时可以把第 3 条「允许 DNS 到 1.1.1.1」删掉。
- VM 和 Docker 都关闭 IPv6（netplan 里 `dhcp6: false`、`accept-ra: false`；Docker 默认不启用 IPv6）。否则 IPv6 可能绕过只匹配 `inet` 的规则。
- 如果 DNS 解析失败但代理本身正常，优先检查 DNS 设置和 53 端口规则，而不是先怀疑 Claude Code。

---

## 4. 第三步：Docker + Claude Code

### 4.1 安装 Docker（在 VM 里，此时需要联网）

> 如果已经启用 3.1 的 pf 规则，先确认 3.1.4 的 apt 代理已配置好，否则 `apt update` 会失败。

```bash
sudo apt-get update
sudo apt-get install -y ca-certificates curl
sudo install -m 0755 -d /etc/apt/keyrings
# sudo 默认不继承普通用户的代理环境变量，这里显式传给 curl
sudo env https_proxy=http://192.168.64.1:7890 curl -fsSL https://download.docker.com/linux/ubuntu/gpg -o /etc/apt/keyrings/docker.asc
sudo chmod a+r /etc/apt/keyrings/docker.asc
echo "deb [arch=$(dpkg --print-architecture) signed-by=/etc/apt/keyrings/docker.asc] https://download.docker.com/linux/ubuntu $(. /etc/os-release && echo "${UBUNTU_CODENAME:-$VERSION_CODENAME}") stable" | sudo tee /etc/apt/sources.list.d/docker.list >/dev/null
sudo apt-get update
sudo apt-get install -y docker-ce docker-ce-cli containerd.io docker-buildx-plugin docker-compose-plugin
sudo usermod -aG docker "$USER"
```

退出 SSH 再重新登录，让 docker 组生效，然后：

```bash
docker run --rm hello-world
```

### 4.2 准备项目目录

在 VM 上：

```bash
mkdir -p ~/work ~/claude-config ~/claude-code
```

- `~/work`：放代码项目，后面挂到容器的 `/workspace`。
- `~/claude-config`：持久化 Claude Code 的登录状态和设置。
- `~/claude-code`：放 Dockerfile 和 compose 文件。

### 4.3 Dockerfile

创建 `~/claude-code/Dockerfile`：

```dockerfile
FROM ubuntu:24.04

ENV DEBIAN_FRONTEND=noninteractive
ARG HTTP_PROXY
ARG HTTPS_PROXY

RUN apt-get update && apt-get install -y --no-install-recommends \
      ca-certificates curl git openssh-client ripgrep less jq \
      locales tzdata sudo \
    && sed -i 's/^# *ja_JP.UTF-8/ja_JP.UTF-8/' /etc/locale.gen \
    && locale-gen \
    && ln -snf /usr/share/zoneinfo/Asia/Tokyo /etc/localtime \
    && echo "Asia/Tokyo" > /etc/timezone \
    && rm -rf /var/lib/apt/lists/*

RUN useradd -m -s /bin/bash claude \
    && echo 'claude ALL=(ALL) NOPASSWD:ALL' > /etc/sudoers.d/claude \
    && chmod 0440 /etc/sudoers.d/claude

USER claude
WORKDIR /home/claude
ENV HOME=/home/claude

ENV LANG=ja_JP.UTF-8 \
    LANGUAGE=ja_JP:ja \
    LC_ALL=ja_JP.UTF-8 \
    TZ=Asia/Tokyo \
    PATH=/home/claude/.local/bin:/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin

# 安装 Claude Code 原生版本
RUN curl -fsSL https://claude.ai/install.sh | bash

WORKDIR /workspace
CMD ["sleep", "infinity"]
```

说明：

- 这里把时区设为 `Asia/Tokyo`、语言设为日语，是为了复刻视频里的容器环境。**这不会改变网络出口，也不会改变账号地区**；只是容器内的 locale 配置。
- 非 root 用户 `claude` 是必须的：Claude Code 以 root 运行时，某些参数（例如 `--dangerously-skip-permissions`）会被拒绝。
- 容器内给了 `NOPASSWD` sudo，方便装依赖；只在一次性容器里这样做，不要把这种镜像用于多租户环境。

### 4.4 docker-compose.yml

创建 `~/claude-code/docker-compose.yml`：

```yaml
services:
  claude:
    build:
      context: .
      args:
        HTTP_PROXY: http://192.168.64.1:7890
        HTTPS_PROXY: http://192.168.64.1:7890
    image: claude-code:local
    container_name: ${CONTAINER_NAME:-claude-code}
    restart: unless-stopped
    working_dir: /workspace
    volumes:
      - /home/claude/work:/workspace
      - /home/claude/claude-config:/home/claude/.claude
    environment:
      CLAUDE_CONFIG_DIR: /home/claude/.claude
      TZ: Asia/Tokyo
      LANG: ja_JP.UTF-8
      LC_ALL: ja_JP.UTF-8
      HTTP_PROXY: http://192.168.64.1:7890
      HTTPS_PROXY: http://192.168.64.1:7890
      NO_PROXY: localhost,127.0.0.1
    env_file:
      - /home/claude/.claude-container.env
    command: sleep infinity
```

创建 env 文件（先留空，登录方式见 4.6）：

```bash
touch ~/.claude-container.env
chmod 600 ~/.claude-container.env
```

> 如果走路线 B（全透明），把 compose 里的 `HTTP_PROXY` / `HTTPS_PROXY` 删掉，build args 也删掉。

### 4.5 构建并启动

```bash
cd ~/claude-code
docker compose build
docker compose up -d
docker ps                      # 确认 claude-code 是 Up
docker exec -it claude-code bash
```

进入容器后：

```bash
claude --version
claude doctor
```

### 4.6 登录 Claude Code

两种方式，任选其一。

**方式一：容器内交互登录（推荐先试）**

```bash
docker exec -it claude-code bash
claude
```

首次运行会显示登录 URL。因为容器里没有浏览器：

1. 在 Mac 浏览器打开终端里显示的 URL；
2. 登录后如果页面显示一段 code，把它粘贴回容器的 `Paste code here if prompted`；
3. 看到 `Login successful` 即可。

凭据会保存在 `~/.claude/.credentials.json`，而 `~/.claude` 已挂载到 VM 的 `~/claude-config`，重启容器不会丢。

**方式二：在 Mac 上生成长期 token**

如果不想每次在容器里走浏览器流程，可以在 Mac 上安装 Claude Code 后生成一年期 token：

```bash
# Mac 上
brew install --cask claude-code
claude setup-token
```

把输出的 token 写进 VM 的 `~/.claude-container.env`：

```bash
CLAUDE_CODE_OAUTH_TOKEN=粘贴你的token
```

然后重启容器：

```bash
docker compose up -d --force-recreate
docker exec -it claude-code bash -lc 'claude --version'
```

> `CLAUDE_CODE_OAUTH_TOKEN` 只能用于模型请求，不能建立 Remote Control 会话或拉取 claude.ai 连接器；本地 MCP 仍可用。token 等同密码，不要提交到 git，env 文件权限保持 `600`。

### 4.7 验收

```bash
# 容器内
date                    # 应该显示 JST
locale                  # 应该包含 ja_JP.UTF-8
claude --version
claude doctor
```

```bash
# 容器内直连应失败（路线 A 的 pf 规则）
# 容器里同样有 HTTP_PROXY 环境变量，必须清掉才算直连
env -u HTTP_PROXY -u HTTPS_PROXY -u http_proxy -u https_proxy \
  curl --noproxy '*' -sS --max-time 5 https://api.anthropic.com/ \
  -o /dev/null -w '%{http_code}\n' || echo "BLOCKED"

# 走代理应成功
curl -x http://192.168.64.1:7890 -sS --max-time 15 https://api.anthropic.com/ -o /dev/null -w '%{http_code}\n'
```

---

## 5. 日常使用

### 5.1 SSH 别名

在 Mac 的 `~/.ssh/config` 加：

```sshconfig
Host claude-vm
  HostName 192.168.64.10
  User claude
  IdentityFile ~/.ssh/id_ed25519

Host claude-code-fresh
  HostName 192.168.64.10
  User claude
  IdentityFile ~/.ssh/id_ed25519
  RequestTTY yes
  RemoteCommand /home/claude/bin/claude-shell
```

在 VM 上创建 `/home/claude/bin/claude-shell`：

```bash
mkdir -p ~/bin
cat > ~/bin/claude-shell <<'EOF'
#!/bin/bash
docker start claude-code >/dev/null 2>&1
exec docker exec -it claude-code bash
EOF
chmod +x ~/bin/claude-shell
```

之后在 Mac 的 Ghostty（或任意终端）里：

```bash
ssh claude-code-fresh
claude
```

### 5.2 启动/停止顺序

**启动**：

1. 打开 UTM，启动 `claude-vm`。
2. 启动 Mac 上的代理客户端，确认 `7890` 在监听、指定出口节点已选中。
3. `ssh claude-code-fresh`（脚本会自动启动容器）。
4. `claude`。

**停止**：

```bash
exit                    # 退出容器
exit                    # 退出 SSH
```

VM 和代理可以保持运行；不需要时再关 UTM 和代理客户端。注意：代理一关，VM 就断网，这是预期行为。

### 5.3 项目文件放哪里

推荐把代码放在 VM 的 `~/work`，容器挂载为 `/workspace`：

```bash
# VM 上
cd ~/work
git clone <你的仓库>
```

好处：文件在 VM 本地磁盘，Docker 读写快；不依赖 Mac 的文件共享。

### 5.4 偶尔访问 Mac 上的文件

视频里用 Orca 做这件事，但官方文档没有给出「容器调用 Mac 文件/工具」的通用桥。更可控的替代方案是 SSHFS 或同步：

**SSHFS（VM 挂载 Mac 目录）**

1. Mac：系统设置 → 通用 → 共享 → 打开「远程登录」。
2. 3.1.2 的 pf 规则已经放行 VM 与 Mac 之间的本地流量，其中包含 22 端口，无需额外加规则。
3. VM：

```bash
sudo apt install -y sshfs
mkdir -p ~/mac
# 注意：这里用的是 Mac 的登录用户名，不是 VM 里的 claude
sshfs 你的Mac用户名@192.168.64.1:/Users/你的Mac用户名 ~/mac
```

用完卸载：

```bash
fusermount -u ~/mac
```

**rsync / scp**：临时拷贝一两个文件更简单：

```bash
scp 本地文件 claude@192.168.64.10:~/work/
```

**调用 Mac 上的命令**：容器里可以通过 SSH 执行 Mac 上的工具（需要先把 Mac 的公钥配好）：

```bash
ssh 你的Mac用户名@192.168.64.1 'say "任务完成"'
```

> 开启 Mac 远程登录会增加攻击面。建议只允许密钥登录、不要开密码登录；不需要时关掉「远程登录」。

### 5.5 Orca（可选）

Orca 是 Stably 的 Agent 编排桌面端，支持 SSH 远程 worktree。按官方文档：

1. Mac 安装：`brew install --cask stablyai/orca/orca`。
2. Orca → **Settings → SSH → Add Target**，填 `192.168.64.10`、用户 `claude`、私钥。
3. 新建 worktree 时选择这个 SSH target，agent 会在 VM 上运行。

注意事项：

- Orca 官方文档只说明「agent 在 SSH 主机上运行」，**没有说明容器内运行**。如果一定要让 agent 在容器里，需要给容器装 sshd 并映射端口，或在 Orca 里用终端手动 `docker exec`。
- Orca 的 managed server 需要 VM 上有可下载的 Node.js 运行时。
- 有社区资料指出 Orca 默认会给 Claude 传 `--dangerously-skip-permissions`，等价于跳过确认。只应在一次性容器里使用，并在 Orca 设置里检查权限模式；不要在 Mac 宿主机上这样跑。
- 视频里「通过 Orca 调 Mac 文件/工具」的具体机制没有公开细节，不建议把它当成唯一的文件通道；上面的 SSHFS/rsync 更可验证。

### 5.6 更新、备份、重建

**更新 Claude Code**：

```bash
docker exec -it claude-code bash -lc 'claude update'
```

或者重建镜像（更可控）：

```bash
cd ~/claude-code
docker compose build --no-cache
docker compose up -d --force-recreate
```

**备份**：

```bash
# VM 上
tar czf ~/claude-backup-$(date +%F).tgz ~/claude-config ~/work
```

**重建容器**（配置不丢，因为 `~/claude-config` 是挂载卷）：

```bash
docker compose down
docker compose up -d
```

**换一套配置试**：

```bash
cd ~/claude-code
CONTAINER_NAME=claude-test docker compose -p claude-test up -d --build
```

`container_name` 用的是 `${CONTAINER_NAME:-claude-code}`，所以测试容器会叫 `claude-test`，不会和原来的 `claude-code` 冲突；原来的容器继续可用，验证没问题再切换。

> 测试容器和主容器默认挂载同一个 `~/claude-config` 和 `~/work`。如果要完全隔离，复制一份 compose，把 volumes 改成 `~/claude-config-test` 和 `~/work-test` 再启动。

---

## 6. 一次性验收清单

全部打勾再开始日常使用：

- [ ] Mac 能 `ssh claude-vm` 登录。
- [ ] VM 的默认路由是 `192.168.64.1`。
- [ ] VM 没有全局 IPv6 地址。
- [ ] VM 直连 `https://api.anthropic.com/` 失败或超时。
- [ ] VM 走 `http://192.168.64.1:7890` 能拿到 HTTP 状态码。
- [ ] 关掉 Mac 代理后，VM 走代理也失败（fail-closed）。
- [ ] `pfctl -a com.apple/100.claude-vm -sr` 能看到 5 条规则。
- [ ] 重启 Mac 后，上述 pf 规则仍然存在。
- [ ] 容器内直连失败、走代理成功。
- [ ] `claude --version` 和 `claude doctor` 正常。
- [ ] 容器内 `date` 是 JST，`locale` 是 `ja_JP.UTF-8`（如果启用了视频同款配置）。
- [ ] 重启容器后不需要重新登录（`~/claude-config` 持久化生效）。
- [ ] 已备份 `~/claude-config` 和 `~/work`。

---

## 7. 故障排查

| 现象 | 可能原因 | 处理 |
|---|---|---|
| 开启 macOS 防火墙后 UTM 共享网络不通 | 应用防火墙拦住了虚拟化进程 | 把虚拟化 XPC 加入例外：`sudo /usr/libexec/ApplicationFirewall/socketfilterfw --add /System/Library/Frameworks/Virtualization.framework/Versions/A/XPCServices/com.apple.Virtualization.VirtualMachine.xpc/Contents/MacOS/com.apple.VirtualizationVirtualMachine`，然后重启 |
| `pfctl: anchor ... not found` | 锚点未加载 | 重新执行 `pfctl -a com.apple/100.claude-vm -f ...`；确认 `/etc/pf.conf` 里有 `anchor "com.apple/*"` |
| pf 规则加载了但 VM 还能直连 | pf 未启用，或规则顺序不对 | `pfctl -s info | head -3` 看 Status；确认 `pass ... quick` 在 `block ... quick` 前面 |
| Mac 上代理正常，VM 不行 | 代理只监听 `127.0.0.1` | 开 `allow-lan`，`bind-address: '*'`；`lsof -nP -iTCP:7890 -sTCP:LISTEN` 确认监听地址 |
| VM 能走代理，容器不能 | 容器没传代理环境变量 | `docker exec claude-code env | grep -i proxy`；检查 compose 的 `environment` |
| `docker pull` 失败 | Docker 守护进程没配代理 | `systemctl show docker --property=Environment`；重配 `docker.service.d/http-proxy.conf` 后 `systemctl restart docker` |
| 容器里登录一直循环 | 时钟不对 / 配置目录权限不对 / 旧凭据 | `date` 检查时间；`ls -la ~/.claude`；用 `claude setup-token` 方式；`claude doctor` |
| 容器写不了 `~/.claude` | VM 上的 `~/claude-config` 属主 UID 和容器里的 `claude` 不一致 | 在 VM 上执行 `sudo chown -R 1000:1000 ~/claude-config`（容器里 `id claude` 确认 UID） |
| 日语 locale 不生效 | 镜像里没有生成 locale | 确认 Dockerfile 有 `locales`、`locale-gen`；`locale -a | grep ja_JP` |
| SSH 别名进入后立刻退出 | 容器没启动，或 RemoteCommand 失败 | 先 `ssh claude-vm` 登录 VM，手动 `docker ps -a`、`docker start claude-code`，再执行 `~/bin/claude-shell` 看报错 |
| DNS 解析失败 | VM 的 DNS 不可达，或 pf 拦了 53 | `dig @1.1.1.1 api.anthropic.com`；确认 3.1.2 第 4 条规则；或改用 Mac 上的 dnsmasq |
| 重启后规则丢失 | LaunchDaemon 没生效 | `launchctl print system/local.claude-vm-pf`；检查脚本权限和 plist 路径 |
| Orca SSH 连不上 | VM 缺 Node 运行时，或容器没有 sshd | 先确认 `ssh claude-vm` 正常；查看 Orca 日志；容器内运行 agent 需要额外配 sshd |

---

## 8. 与视频的对应关系

| 视频里的说法 | 本手册的实现 | 说明 |
|---|---|---|
| Mac → Ubuntu 虚拟机 → Docker 容器 | 第 2、4 节 | 一致 |
| 虚拟机有独立虚拟网卡和内网地址 | UTM Shared Network，`192.168.64.0/24` | 一致 |
| 网络环境配在 Mac 上 | 路线 A 的 pf 白名单 + Mac 代理；路线 B 的透明网关 | 路线 A 需要在 VM/容器里写一次代理地址；路线 B 才做到「完全不用配」 |
| 指定出口不可用时拦截公网流量 | 路线 A 的 `block drop quick ...` | 路线 B 需要额外确认默认拒绝规则 |
| SSH 走本地虚拟网络 | UTM 共享网络 + `ssh claude-code-fresh` | 一致 |
| Docker 里设东京时区、日语 | 第 4.3 节 Dockerfile | 仅容器内生效；不改变网络出口或账号地区 |
| Ghostty 里 `ssh claude-code-fresh` → `claude` | 第 5.1 节 | 一致 |
| 偶尔通过 Orca 调 Mac 文件/工具 | 第 5.5 节（可选） | 官方未说明容器内运行；更推荐 SSHFS/rsync |
| 不租 VPS：性能、价格、传文件 | 本手册的本机方案 | 一致 |
| 封号原因 | 视频未确认 | 本手册不承诺避免风控；请遵守服务条款 |

### 已知限制

- 视频没有展示任何实际配置命令，本手册的 UTM 参数、防火墙规则、Dockerfile 都是按视频思路补全的默认实现；不同 macOS/UTM 版本可能有差异。
- `trans_proxy` 对 UTM `bridge100` 的兼容性没有官方说明，属于「需要实测」的进阶方案；路线 A 是更稳的起点。
- Orca 官方文档只覆盖 SSH 主机，没有覆盖「agent 在容器内运行」；本手册的 Orca 部分是可选工作流，不是必需组件。
- 时区/语言设置只影响容器内的格式和 locale，不改变网络出口、IP 归属或账号地区。
- 账号封禁是服务方风控行为，原因和判定标准不公开；隔离环境只能降低环境混杂，不能保证避免封禁。

---

## 附录：参考链接

- UTM 网络模式文档：<https://docs.getutm.app/settings-qemu/devices/network/network/>
- Claude Code 安装与登录：<https://code.claude.com/docs/en/setup>、<https://code.claude.com/docs/en/authentication>
- Claude Code 网络配置：<https://code.claude.com/docs/en/network-config>
- Docker Ubuntu 安装：<https://docs.docker.com/engine/install/ubuntu/>
- Orca SSH worktree：<https://orca.dev/docs/ssh>
- trans_proxy：<https://madeye.github.io/trans_proxy/index_zh.html>
- Surge 网关模式：<https://kb.nssurge.com/surge-knowledge-base/zh/guidelines/gateway>
- macOS pf.conf：`man pf.conf`、`man pfctl`

---

## 附：最短路径（赶时间版）

1. UTM 装 Ubuntu Server 24.04，Shared Network，静态 IP `192.168.64.10`，开 SSH。
2. Mac 代理开 `7890` + Allow LAN；写 pf 锚点放行 VM↔Mac 本地流量，其余 VM 出站丢弃。
3. VM 里配 apt / Docker 代理，安装 Docker。
4. 用第 4.3 的 Dockerfile 构建镜像，挂载 `~/work` 和 `~/claude-config`，启动容器。
5. `docker exec -it claude-code bash` → `claude` → 完成登录。
6. Mac 上 `ssh claude-code-fresh` → `claude`。
7. 跑一遍第 6 节验收清单。
