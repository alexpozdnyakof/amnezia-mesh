[English](README.md) | [Русский](README.ru.md) | [中文](README.zh-CN.md) | [Español](README.es.md) | [فارسی](README.fa.md) | [العربية](README.ar.md) | [Português](README.pt-BR.md) | [日本語](README.ja.md) | [Deutsch](README.de.md) | **한국어** | [Français](README.fr.md) | [हिन्दी](README.hi.md) | [Bahasa Indonesia](README.id.md) | [Українська](README.uk.md)

_영문 README의 번역이며 원문보다 뒤처질 수 있습니다._

# amnezia-mesh

AmneziaWG 트래픽 난독화, MagicDNS, Tailscale 스타일의 exit/mesh 프로파일을
갖춘 자체 호스팅 WireGuard 메시 — 단일 VPS에서 ~10분이면 구축되며 Docker
이외의 의존성이 없습니다.

«나만의 Tailscale»이라고 생각하면 됩니다. 다만 모든 홉이 내 것인: 작은 서버
한 대, 기기의 공식 Amnezia 앱, 그리고 조정 서버도 계정도 제3자 릴레이도
없습니다.

## 특징

- **CGNAT 메시 네트워크** (`100.64.0.0/24`, RFC 6598) — 모든 기기에 고정 IP가
  부여되고, 기기 간 SSH/ping은 `tailscale ssh`처럼 허브를 통해 동작합니다.
- **AmneziaWG 3.1 난독화** — junk 패킷 핸드셰이크, 헤더 타입 치환, 헤더 보호
  키, 무작위 padding/trailer. 매개변수는 **배포할 때마다 무작위로** 생성되므로
  설치마다 DPI 핑거프린트가 다릅니다.
- **MagicDNS** — 허브의 dnsmasq가 `<기기>.<도메인>`(예: `laptop.awg`)에
  응답하고 나머지는 터널을 통해 업스트림 리졸버로 전달합니다.
- **기기별 exit + mesh 프로파일** — `exit`는 모든 트래픽을 VPS로 라우팅(검열
  우회), `mesh`는 CGNAT 서브넷만 라우팅하고 인터넷은 직접 연결. 두 프로파일이
  모든 기기에 생성됩니다.
- **공식 Amnezia 앱 네이티브 프로파일**(`vpn://`)과 모든 awg/wg 호환
  클라이언트용 일반 `.conf`.
- **버전에 무관한 설계** — AWG 이미지는 외부에서 교체 가능한 의존성이며 모든
  로직은 호스트에 있습니다(아래 *설계* 참조).
- **에이전트 친화적 CLI** — 모든 명령에 `--json` 출력, 환경 변수 오버라이드,
  비대화형 모드.

## 요구 사항

- 공인 IP가 있는 VPS, compose 플러그인이 있는 Docker, 그리고 `python3`
  (>= 3.8, 표준 라이브러리만 — `pip install` 불필요).
- VPS 방화벽에 열린 UDP 포트(권장: 443/udp — 일반 HTTPS/QUIC 트래픽에 섞여
  ISP가 셰이핑하기 가장 어렵습니다).

## AI 에이전트로 설치하기 (Claude Code, Kimi Code, Cursor, …)

CLI에는 자체 운영 스킬이 포함되어 있습니다. 설치, 자동화 프로토콜, 재시작
의미론, 진단 결정 트리를 다루는 간결한 런북입니다. 에이전트에게 넘기면 전체
흐름이 대화형이 됩니다:

```sh
# macOS cask: awg-mesh (CLI)와 awg-mesh-tui. Linux: Releases 참조.
brew tap alexpozdnyakof/tap
brew install --cask alexpozdnyakof/tap/awg-mesh
# 또는: 이 저장소를 git clone

awg-mesh-tui install --ssh root@YOUR_VPS --json
awg-mesh skill --install   # ~/.agents/skills/awg-mesh/SKILL.md
```

그 다음 그냥 요청하면 됩니다. 예: *"이 VPS(IP 203.0.113.7)에 VPN을 세팅하고,
내 노트북과 휴대폰을 추가한 뒤 자가 점검을 돌려줘"*. 에이전트는
`awg-mesh init` / `peer add` / `doctor --json`을 실행하고, 생성된 프로파일을
기기에 가져오고, 스킬의 결정 트리로 연결성을 진단합니다. 저장소 루트의
`AGENTS.md`는 체크아웃 안에서 작업하는 에이전트에게 같은 안내를 제공합니다.

## 빠른 시작 (사람)

```sh
git clone https://github.com/<you>/amnezia-mesh && cd amnezia-mesh

./bin/awg-mesh init --host YOUR_IP_OR_DOMAIN --port 443
./bin/awg-mesh peer add laptop
# → 출력: config/peers/laptop-exit.vpn, laptop-mesh.vpn 및 .conf 변형
# .vpn 링크를 기기의 Amnezia 앱으로 가져오기

./bin/awg-mesh peer add phone
./bin/awg-mesh doctor      # 설치 후 자가 점검
./bin/awg-mesh monitoring install   # 선택: cron 통계 + watchdog
```

기기에서: Amnezia 앱 → `vpn://` 링크 가져오기 → 연결. 이제 기기들이 서로 IP
(`100.64.0.x`) 또는 이름(`phone.awg`)으로 접근할 수 있습니다.

## 빠른 시작 (에이전트 / 자동화)

```sh
export AWG_MESH_NONINTERACTIVE=1
./bin/awg-mesh --json init --host 198.51.100.10 --port 443
./bin/awg-mesh --json peer add laptop
./bin/awg-mesh --json doctor        # 종료 코드 0 = 모든 점검 통과
```

출력은 명령당 단일 JSON 객체이며, 실패 시에는 0이 아닌 종료 코드와
`{"ok": false, "error": "..."}`를 반환합니다.

## 명령어

| 명령어 | 설명 |
|---|---|
| `awg-mesh init [--host H] [--port P] [--subnet CIDR] [--image IMG] [--domain D] [--rdp-reject]` | 키 + 무작위 난독화 생성, 설정 렌더링, 컨테이너 시작 |
| `awg-mesh peer add <name> [--type exit\|mesh\|both]` | 새 기기: 키, IP, 프로파일(`awg set` + dnsmasq SIGHUP으로 라이브 적용 — 재시작 없음, 기존 피어의 세션 유지) |
| `awg-mesh peer list` | 기기, IP, 생성 날짜 |
| `awg-mesh peer rename <name> <new-name> [pairs...]` | 기기 이름 바꾸기 — 이전/새 이름 쌍을 여러 개 전달해 adopt 이후 생성된 `peer-xxxx` 이름을 한 번에 정리( MagicDNS 이름도 따라감, dnsmasq SIGHUP만 — 재시작 없음, all-or-nothing 유효성 검사, 스왑 지원) |
| `awg-mesh peer rotate <name>` | 기기 키 재발급(IP 동일, 허브는 revoke처럼 재시작 — 기기가 프로파일을 다시 가져와야 하며 이전 `vpn://` 링크는 무효화) |
| `awg-mesh peer revoke <name>` | 기기 제거(awg + dns 컨테이너 재시작 — userspace 데몬에서 UAPI로 피어를 제거하면 새 핸드셰이크가 조용히 멈출 수 있음, 프로파일 삭제) |
| `awg-mesh doctor [--json]` | Docker, 컨테이너, 수신 포트, ip_forward, MagicDNS, 포트 게시 |
| `awg-mesh dns add <name> <ipv4>` / `dns remove <name>` / `dns list` | `<name>.<domain>` 위에 사용자 지정 MagicDNS 레코드(`nas.awg` → 임의 IPv4)를 `config/custom.hosts`에 추가 — dnsmasq의 두 번째 `--addn-hosts`, SIGHUP으로 다시 로드, 재시작 없음 |
| `awg-mesh monitoring install\|uninstall` | cron 통계(`/var/log/amnezia-mesh-stats.log`) + watchdog |
| `awg-mesh adopt (--container C \| --config F --image IMG) --host H [--port P] [--dns1 D] [--dns2 D] [--rdp-reject]` | 기존 AmneziaWG 서버를 awg-mesh 관리로 마이그레이션(아래 참조) |

## 원격 모드 (Mac에서 서버 관리)

```sh
awg-mesh --server my-vps peer list --json   # 또는: export AWG_MESH_SSH=my-vps
```

로컬 CLI는 시스템 ssh 클라이언트로 `ssh my-vps 'cd ~ && awg-mesh <args>'`를
실행하고(`~/.ssh/config`의 별칭과 키 사용) stdout/stderr/종료 코드를 그대로
전달합니다 — 로컬에서 로직이 중복되지 않습니다. 변경 명령(`init`, `adopt`,
`peer add|rename|revoke|rotate`) 이후에는 원격 `config/peers/`가 scp로
미러링되어 `.vpn` 프로파일이 로컬 체크아웃 옆에 놓입니다.
`AWG_MESH_REMOTE_ROOT`로 서버의 메시 루트를 설정(기본값 `~`). `skill`과
`--version`은 항상 로컬에서 실행됩니다.

## 기존 서버 가져오기 (adopt)

이미 AmneziaWG를 실행 중(컨테이너 또는 수동 배포)이고 `awg-mesh`의 관리 —
피어 관리, MagicDNS, doctor, 모니터링 — 를 원하지만 **클라이언트 프로파일을
하나도 다시 발급하지 않으려면**.

```sh
./bin/awg-mesh adopt --container amnezia-awg --host YOUR_IP --port 443
# 또는 호스트의 설정 파일에서:
./bin/awg-mesh adopt --config /root/awg0.conf --image amneziavpn/amneziawg-go:latest \
    --host YOUR_IP --port 443
```

**그대로** 이전되는 것(클라이언트가 아무것도 눈치채지 않도록):

| | adopt 후 |
|---|---|
| 서버 개인 키 | 동일 — 클라이언트가 보는 서버가 같음 |
| 난독화 프로파일(Jc/Jmin/Jmax/S/H, HeaderProtectionKey, 타이머) | 동일 — DPI 핑거프린트 변경 없음 |
| 피어 공개 키, PSK | 동일 |
| 피어 IP | 동일 — 각 피어의 `AllowedIPs`에서 가져옴 |
| 기기의 클라이언트 프로파일 | 계속 동작, 재발급 불필요 |

변경되는 것: 컨테이너가 `amnezia-mesh` compose 프로젝트 아래에서 다시
생성되고(`amnezia-mesh-awg`로 이름 변경, dnsmasq는 사이드카가 됨) 그 시점부터
배포는 `awg-mesh`가 관리합니다. `awg0.conf`로 표현할 수 없는 옵션은 플래그로
전달합니다: `--dns1/--dns2`(MagicDNS 전달용 업스트림 리졸버, 기본값 1.1.1.1),
`--rdp-reject`(RDP UDP/3389 reject 규칙), `--domain`(기본값 `awg`).

`adopt`의 단계:

1. `awg0.conf` 읽기 — 컨테이너 안에서(`--container`, 이미지 자동 감지) 또는
   파일에서(`--config`, `--image` 필수);
2. `[Interface]` + `[Peer]` 섹션을 `config/server.env` + `config/peers.db`로
   파싱 — 이해하지 못하는 키를 만나면 해당 키를 나열하며 **거부**하고 조용히
   버리지 않습니다;
3. `awg0.conf` / `dnsmasq.conf` / `start.sh`를 렌더링하고 스택 시작;
4. `--container`의 경우: 이전 컨테이너를 **중지**(절대 삭제하지 않음)하고
   `doctor` 실행. 실패하면 자동으로 롤백 — 이전 컨테이너가 다시 시작되고
   아무것도 삭제되지 않습니다.

안전 규칙:

- 이전 컨테이너는 중지될 뿐이며 롤백 플랜으로 호스트에 남습니다:
  `docker stop amnezia-mesh-awg amnezia-mesh-dns && docker start <이전>`
- 알 수 없는 `[Interface]` 키, 서버 `Address`가 서브넷의 첫 호스트가 아니거나,
  `PublicKey`/`PresharedKey`가 없는 피어가 있으면 adopt가 중단됩니다;
- 피어 이름은 `# name (added …)` 주석에서 가져오며, 이름 없는 피어는 생성된
  `peer-xxxxxx` 이름을 받고 충돌에는 `-2` 접미사가 붙습니다.

## 설계: AmneziaWG 버전 업데이트가 중요하지 않은 이유

1. **AWG 이미지는 일반 의존성입니다.** `docker-compose.yml`은
   `amneziavpn/amneziawg-go`를 참조하며(`--image` 또는 `AWG_MESH_IMAGE`로
   오버라이드) 포크나 패치가 없으므로 이미지 태그 교체에 프로젝트 변경이
   필요 없습니다.
2. **모든 로직은 호스트에 있습니다.** 서버 설정, dnsmasq 설정, 컨테이너
   엔트리포인트(iptables 부트스트랩: 포워딩, MASQUERADE, MSS 클램프, 선택적
   RDP-UDP reject)는 `config/`에 생성되어 마운트됩니다. 컨테이너 재생성이나
   업그레이드로 잃는 것이 없습니다.
3. **인터페이스는 안정적인 UAPI입니다.** `awg0.conf` 매개변수(Jc/S/H,
   HeaderProtectionKey, 타이머)는 AWG 프로토콜의 일부로 릴리스 간에
   바뀌지 않습니다. 실험적 매개변수 `I1`–`I5`(CPS)는 `init` 시에 프로브되고
   지원 여부를 기록하므로 어느 경우에도 호환성이 유지됩니다.
4. **프로파일은 앱의 네이티브 포맷입니다.** `vpn://` 프로파일은 공식 Amnezia
   앱이 내보내는 것과 바이트 호환입니다(`base64url(uint32_be(len) + zlib(json,
   9))`, 컴팩트 구분자 — 바이트 단위로 검증됨). 새 앱 릴리스도 계속
   가져옵니다.

## 구조

```
docker-compose.yml      awg 컨테이너 + dnsmasq 사이드카 (공유 netns)
bin/awg-mesh            CLI 진입점 (얇은 심, 체크아웃에서 바로 실행)
awg_mesh/               python 패키지: cli, envfile, peers, keygen, compose,
                        render, profile, doctor, adopt (stdlib만)
scripts/                선택적 모니터링 (stats, watchdog, cron)
tests/                  pytest 스위트: 렌더러 골든 파일, peers db + flock,
                        profile 코덱 roundtrip
config/                 생성된 비밀키와 상태 — gitignore되어 호스트에 유지
```

## 메시 작동 방식 (30초)

WireGuard는 암호화 키 라우팅입니다: 각 패킷은 피어의 공개 키로 암호화되고
`AllowedIPs`가 목적지 IP를 피어에 매핑합니다. `100.64.0.4`를 핑하는 폰은
**허브의** 키로 암호화하므로 맥북의 실제 주소를 절대 알지 못합니다. 허브가
복호화하고 맥북의 키로 다시 암호화하여 전달합니다. 이는 P2P가 아닌
허브-앤-스포크(라우팅형 메시)이므로, 홀 펀칭이 무의미한 통신사급 모바일
NAT를 포함해 어떤 NAT 뒤에서도 동작합니다. 양쪽의
`PersistentKeepalive=25`가 NAT 매핑을 유지해 기기들이 서로 도달 가능한
상태를 유지합니다.

## 보안 강화 참고

- `config/`에는 개인 키가 들어 있습니다 — gitignore되어 있고 모드 600이며
  서버를 절대 떠나지 않습니다. VPS를 다시 구성한다면 암호화된 백업을
  유지하세요.
- VPS 방화벽은 default-deny로 유지하고 SSH와 선택한 UDP 포트만
  허용하세요(443/udp가 일반 HTTPS/QUIC 트래픽에 가장 잘 섞입니다).
- 난독화는 DPI **핑거프린트**를 물리칠 뿐 트래픽 볼륨 분석은 물리치지
  못합니다. 전역 수동 공격자에 대해서는 Tor를 대체하지 않습니다.
- `--rdp-reject`는 터널을 통한 RDP에 도움이 됩니다(UDP 그래픽 채널의 즉시
  TCP 폴백 강제). 메시를 통한 RDP를 사용한다면 `init`에서 활성화하세요.

## 문제 해결

| 증상 | 확인 |
|---|---|
| 기기가 연결되지 않음 | `awg-mesh doctor`; VPS 방화벽이 UDP 포트를 허용하는지 |
| «connecting»이 길고 이후 «connected»지만 인터넷 없음 | 거의 언제나 기기의 잘못된/오래된 프로파일: 앱에서 활성 프로파일을 확인하고 오래된 것/테스트 것을 삭제 |
| 기기에서 도메인이 해석되지 않음 | `doctor`의 magicdns 점검; 기기 프로파일의 DNS는 허브여야 함(생성된 프로파일이 그렇게 됨) |
| 처리량 낮음 | MTU 1280은 의도적(padding 여유); 작은 VPS 플랜에서는 steal/CPU 확인 |
| `awg` CLI의 `Protocol not supported` | 단일 키 쿼리에서 amneziawg-tools의 알려진 특이 동작; 전체 `awg show` 사용 — 표시상의 문제뿐 |

## 테스트

```sh
python3 -m venv .venv && .venv/bin/pip install pytest
.venv/bin/python -m pytest tests/ -q
```

이 스위트는 Docker도 네트워크도 필요 없습니다: 서버 설정 렌더링은 원래
구현이 생성한 골든 파일과 바이트 단위로 비교되고, peers db는 `flock`
직렬화를 증명하기 위해 동시 작성자들에 의해 합격되며, `vpn://` 코덱은
roundtrip 테스트를 통과합니다.

## 라이선스

MIT
