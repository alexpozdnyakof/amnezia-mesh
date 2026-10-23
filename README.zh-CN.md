[English](README.md) | [Русский](README.ru.md) | **中文** | [Español](README.es.md) | [فارسی](README.fa.md) | [العربية](README.ar.md) | [Português](README.pt-BR.md) | [日本語](README.ja.md) | [Deutsch](README.de.md)

_本文件是英文 README 的翻译，内容可能落后于原文。_

# amnezia-mesh

自托管的 WireGuard mesh 网络，带 AmneziaWG 流量混淆、MagicDNS，以及
Tailscale 风格的 exit/mesh 双配置——一台 VPS 即可，约 10 分钟搭建，除
Docker 外零依赖。

可以把它理解为「属于你自己的 Tailscale」，但每个环节都归你所有：一台
小服务器、设备上的官方 Amnezia 应用，没有协调服务器、没有账号、没有
第三方中继。

## 特性

- **CGNAT mesh 网络**（`100.64.0.0/24`，RFC 6598）——每台设备获得固定
  IP；设备之间的 SSH/ping 经 hub 转发，类似 `tailscale ssh`。
- **AmneziaWG 3.1 混淆**——junk 数据包握手、包头类型替换、包头保护密钥、
  随机填充/trailer。**每个部署随机生成参数**，不同安装之间的 DPI 指纹
  各不相同。
- **MagicDNS**——hub 上的 dnsmasq 应答 `<设备>.<域名>`（例如
  `laptop.awg`），其余查询经隧道转发到你的上游解析器。
- **每台设备同时生成 exit + mesh 配置**——`exit` 将全部流量经 VPS 转发
  （绕过封锁）；`mesh` 只路由 CGNAT 子网，互联网流量保持直连。
- **原生 Amnezia 应用配置**（`vpn://`），以及适用于任何 awg/wg 兼容
  客户端的 `.conf` 文件。
- **设计上与版本无关**——AWG 镜像是外部可替换的依赖，所有逻辑都在
  宿主机上（见下文「设计」）。
- **对 Agent 友好的 CLI**——每个命令都有 `--json` 输出、环境变量覆盖
  以及非交互模式。

## 环境要求

- 一台有公网 IP 的 VPS、带 compose 插件的 Docker，以及 `python3`
  （>= 3.8，仅标准库——无需 `pip install`）。
- 防火墙开放的 UDP 端口（推荐 443/udp——它混入常规 HTTPS/QUIC 流量，
  ISP 最难对其进行流量整形）。

## 快速上手（人工）

```sh
git clone https://github.com/<you>/amnezia-mesh && cd amnezia-mesh

./bin/awg-mesh init --host 你的IP或域名 --port 443
./bin/awg-mesh peer add laptop
# → 输出：config/peers/laptop-exit.vpn、laptop-mesh.vpn，以及 .conf 变体
# 在设备上的 Amnezia 应用中导入 .vpn 链接

./bin/awg-mesh peer add phone
./bin/awg-mesh doctor      # 安装后的自检
./bin/awg-mesh monitoring install   # 可选：cron 统计 + watchdog
```

在设备上：Amnezia 应用 → 导入 `vpn://` 链接 → 连接。此后设备间可以按
IP（`100.64.0.x`）或按名称（`phone.awg`）互相访问。

## 快速上手（Agent / 自动化）

```sh
export AWG_MESH_NONINTERACTIVE=1
./bin/awg-mesh --json init --host 198.51.100.10 --port 443
./bin/awg-mesh --json peer add laptop
./bin/awg-mesh --json doctor        # 退出码 0 = 全部检查通过
```

每个命令输出单个 JSON 对象；失败时退出码非零，并输出
`{"ok": false, "error": "..."}`。

## 命令

| 命令 | 说明 |
|---|---|
| `awg-mesh init [--host H] [--port P] [--subnet CIDR] [--image IMG] [--domain D] [--rdp-reject]` | 生成密钥 + 随机混淆参数，渲染配置，启动容器 |
| `awg-mesh peer add <name> [--type exit\|mesh\|both]` | 新设备：密钥、IP、配置文件（通过 `awg syncconf` 应用，随后重启 awg 容器——单独使用 syncconf 可能使 userspace 守护进程的后续握手静默失效） |
| `awg-mesh peer list` | 设备、IP、创建时间 |
| `awg-mesh peer rename <name> <new-name>` | 重命名设备（其 `<name>.<domain>` MagicDNS 记录随之更新） |
| `awg-mesh peer revoke <name>` | 移除设备（配置已应用，配置文件已删除） |
| `awg-mesh doctor [--json]` | Docker、容器、监听端口、ip_forward、MagicDNS、端口发布 |
| `awg-mesh monitoring install\|uninstall` | cron 统计（`/var/log/amnezia-mesh-stats.log`）+ watchdog |
| `awg-mesh adopt (--container C \| --config F --image IMG) --host H [--port P] [--dns1 D] [--dns2 D] [--rdp-reject]` | 将已有的 AmneziaWG 服务器迁移到 awg-mesh 管理之下（见下文） |

## 接管已有服务器（adopt）

你已经在运行 AmneziaWG（容器或手工部署），希望获得 `awg-mesh` 的
管理能力——peer 管理、MagicDNS、doctor、监控——并且**不需要重新签发
任何客户端配置**。

```sh
./bin/awg-mesh adopt --container amnezia-awg --host 你的IP --port 443
# 或从宿主机上的配置文件：
./bin/awg-mesh adopt --config /root/awg0.conf --image amneziavpn/amneziawg-go:latest \
    --host 你的IP --port 443
```

以下内容将**原样保留**（客户端无感知）：

| | adopt 之后 |
|---|---|
| 服务器私钥 | 相同——客户端看到的服务器不变 |
| 混淆参数（Jc/Jmin/Jmax/S/H、HeaderProtectionKey、计时器） | 相同——DPI 指纹不变 |
| peer 公钥、PSK | 相同 |
| peer IP | 相同——取自每个 peer 的 `AllowedIPs` |
| 设备上的客户端配置 | 继续可用，无需重新签发 |

变化的部分：容器在 `amnezia-mesh` compose 项目下重建（重命名为
`amnezia-mesh-awg`，dnsmasq 变为 sidecar），此后由 `awg-mesh` 管理。
`awg0.conf` 无法表达的选项通过命令行参数提供：`--dns1/--dns2`
（MagicDNS 转发的上游解析器，默认 1.1.1.1）、`--rdp-reject`（RDP
UDP/3389 reject 规则）、`--domain`（默认 `awg`）。

`adopt` 的执行步骤：

1. 读取 `awg0.conf`——从容器内读取（`--container`，自动检测镜像）或
   从文件读取（`--config`，必须提供 `--image`）；
2. 解析 `[Interface]` + `[Peer]` 段，写入 `config/server.env` +
   `config/peers.db`——遇到不理解的键时**拒绝继续**（并列出这些键），
   而不是悄悄丢弃；
3. 渲染 `awg0.conf` / `dnsmasq.conf` / `start.sh` 并启动整个栈；
4. 如果使用 `--container`：**停止**旧容器（绝不删除），随后运行
   `doctor`；若检查失败则自动回滚——旧容器重新启动，不删除任何内容。

安全规则：

- 旧容器仅被停止，并保留在宿主机上作为回滚方案：
  `docker stop amnezia-mesh-awg amnezia-mesh-dns && docker start <旧容器>`
- 出现以下情况 adopt 会中止：`[Interface]` 中存在未知键、服务器
  `Address` 不是子网的第一个主机、或 peer 缺少 `PublicKey`/`PresharedKey`；
- peer 名称来自 `# 名称 (added …)` 注释；无名称的 peer 会获得生成的
  `peer-xxxxxx` 名称，重名自动追加 `-2` 后缀。

## 设计：为什么 AmneziaWG 版本更新无关紧要

1. **AWG 镜像是普通依赖。** `docker-compose.yml` 引用
   `amneziavpn/amneziawg-go`（可通过 `--image` 或 `AWG_MESH_IMAGE`
   覆盖）。项目没有 fork 或 patch 任何东西；更换镜像 tag 无需改动项目。
2. **所有逻辑都在宿主机上。** 服务器配置、dnsmasq 配置和容器
   entrypoint（iptables 引导：转发、MASQUERADE、MSS clamp、可选的
   RDP-UDP reject）都生成到 `config/` 并 bind-mount 进容器。重建或升级
   容器不会丢失任何东西。
3. **接口是稳定的 UAPI。** `awg0.conf` 的参数（Jc/S/H、
   HeaderProtectionKey、计时器）是 AWG 协议的一部分，跨版本不变。
   实验性参数 `I1`–`I5`（CPS）在 `init` 时探测；无论支持与否，项目
   都会记录结果并保持兼容。
4. **配置文件是应用的原生格式。** `vpn://` 配置与官方 Amnezia 应用
   导出的格式字节级兼容（`base64url(uint32_be(len) + zlib(json, 9))`，
   紧凑分隔符——已验证字节级一致）。新版应用会持续兼容。

## 目录结构

```
docker-compose.yml      awg 容器 + dnsmasq sidecar（共享 netns）
bin/awg-mesh            CLI 入口（薄封装，直接从 checkout 运行）
awg_mesh/               python 包：cli、envfile、peers、keygen、compose、
                        render、profile、doctor、adopt（仅用标准库）
scripts/                可选监控（stats、watchdog、cron）
tests/                  pytest 测试集：render golden 文件、peers db + flock、
                        profile 编解码 roundtrip
config/                 生成的密钥与状态——已 gitignore，只留在宿主机
```

## mesh 工作原理（30 秒）

WireGuard 是加密密钥路由：每个数据包都使用目标 peer 的公钥加密，
`AllowedIPs` 将目标 IP 映射到 peer。手机 ping `100.64.0.4` 时，数据包
是加密给 **hub** 的——它永远不知道 macbook 的真实地址。hub 解密后，
再用 macbook 的公钥重新加密并转发。这是 hub-and-spoke（路由式 mesh），
而不是 P2P：它能在任意 NAT 之后工作，包括 hole punching 无效的
运营商级移动 NAT。双向 `PersistentKeepalive=25` 保持 NAT 映射活跃，
因此设备之间始终互相可达。

## 加固建议

- `config/` 包含私钥——已加入 gitignore、权限 600，且永远不会离开
  服务器。重装 VPS 时请加密备份。
- VPS 防火墙保持 default-deny，只放行 SSH 和你选定的 UDP 端口
  （443/udp 与普通 HTTPS/QUIC 流量混合得最好）。
- 混淆对抗的是 DPI **指纹**，而不是流量体积分析；面对全局被动监听者，
  它不能替代 Tor。
- `--rdp-reject` 对隧道内的 RDP 有帮助（强制 UDP 图形通道立即回退到
  TCP）。如果通过 mesh 使用 RDP，请在 `init` 时启用。

## 故障排查

| 症状 | 检查项 |
|---|---|
| 设备无法连接 | `awg-mesh doctor`；VPS 防火墙是否放行该 UDP 端口 |
| 长时间「connecting」，随后「connected」但无法上网 | 几乎都是设备上错误/过期的配置：检查应用中当前激活的配置，删除旧的/测试配置 |
| 设备上域名无法解析 | `doctor` 的 magicdns 检查；设备配置中的 DNS 必须指向 hub（生成的配置默认如此） |
| 吞吐量低 | MTU 1280 是有意为之（为 padding 预留空间）；低配 VPS 请检查 steal/CPU |
| `awg` CLI 返回 `Protocol not supported` | amneziawg-tools 在单键查询上的已知怪癖；请使用完整的 `awg show`——仅为表象 |

## 测试

```sh
python3 -m venv .venv && .venv/bin/pip install pytest
.venv/bin/python -m pytest tests/ -q
```

测试集不需要 Docker 和网络：服务器配置的渲染结果与原始实现生成的
golden 文件逐字节比对；peers db 被并发写入以验证 `flock` 串行化；
`vpn://` 编解码通过 roundtrip 测试。

## 许可

MIT
