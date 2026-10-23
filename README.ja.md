[English](README.md) | [Русский](README.ru.md) | [中文](README.zh-CN.md) | [Español](README.es.md) | [فارسی](README.fa.md) | [العربية](README.ar.md) | [Português](README.pt-BR.md) | **日本語** | [Deutsch](README.de.md)

_英語版 README の翻訳です。原文より遅れる場合があります。_

# amnezia-mesh

AmneziaWG によるトラフィック難読化、MagicDNS、Tailscale 風の exit/mesh
プロファイルを備えたセルフホスト型 WireGuard メッシュ — 1 台の VPS で約
10 分、Docker 以外の依存は一切なし。

「自分専用の Tailscale」とでも思ってください。ただしすべてのホップが
あなたのもの。小さなサーバー 1 台、各デバイスの公式 Amnezia アプリ、
そして調整サーバー・アカウント・サードパーティリレーはありません。

## 特徴

- **CGNAT メッシュネットワーク**（`100.64.0.0/24`, RFC 6598）— 各
  デバイスに固定 IP。デバイス間の SSH/ping は hub 経由で動作
  （`tailscale ssh` 相当）。
- **AmneziaWG 3.1 難読化** — ジャンクパケットハンドシェイク、ヘッダー
  タイプの置き換え、ヘッダー保護キー、ランダム padding/trailer。
  パラメータは**デプロイごとにランダム生成**されるため、DPI
  フィンガープリントはインストールごとに異なります。
- **MagicDNS** — hub 上の dnsmasq が `<デバイス>.<ドメイン>`（例:
  `laptop.awg`）に応答し、それ以外をトンネル経由でアップストリーム
  リゾルバへ転送します。
- **デバイスごとの exit + mesh プロファイル** — `exit` は全トラフィックを
  VPS 経由（検閲回避）。`mesh` は CGNAT サブネットのみをルーティングし、
  インターネットは直結のまま。どちらも全デバイスに生成されます。
- **公式 Amnezia アプリのネイティブプロファイル**（`vpn://`）に加え、
  任意の awg/wg 互換クライアント向けの素の `.conf`。
- **バージョン非依存の設計** — AWG イメージは外部の差し替え可能な
  依存。ロジックはすべてホスト側に存在（「設計」を参照）。
- **エージェントフレンドリな CLI** — 全コマンドに `--json` 出力、環境
  変数による上書き、非インタラクティブモード。

## 必要環境

- パブリック IP を持つ VPS、compose プラグイン付き Docker、そして
  `python3`（>= 3.8、標準ライブラリのみ — `pip install` は不要）。
- VPS ファイアウォールで開いた UDP ポート（推奨は 443/udp — 通常の
  HTTPS/QUIC トラフィックに紛れ、ISP がシェイピングしにくい）。

## クイックスタート（人間向け）

```sh
git clone https://github.com/<you>/amnezia-mesh && cd amnezia-mesh

./bin/awg-mesh init --host あなたのIPまたはドメイン --port 443
./bin/awg-mesh peer add laptop
# → config/peers/laptop-exit.vpn, laptop-mesh.vpn と .conf 版が出力される
# デバイス上の Amnezia アプリに .vpn リンクをインポート

./bin/awg-mesh peer add phone
./bin/awg-mesh doctor      # インストール後の自己チェック
./bin/awg-mesh monitoring install   # オプション: cron 統計 + watchdog
```

デバイス側: Amnezia アプリ → `vpn://` リンクをインポート → 接続。これで
デバイス同士は IP（`100.64.0.x`）または名前（`phone.awg`）で相互に
アクセスできます。

## クイックスタート（エージェント / 自動化）

```sh
export AWG_MESH_NONINTERACTIVE=1
./bin/awg-mesh --json init --host 198.51.100.10 --port 443
./bin/awg-mesh --json peer add laptop
./bin/awg-mesh --json doctor        # 終了コード 0 = 全チェック合格
```

出力はコマンドごとに 1 つの JSON オブジェクト。失敗時は終了コードが非
ゼロで `{"ok": false, "error": "..."}` が出ます。

## コマンド

| コマンド | 説明 |
|---|---|
| `awg-mesh init [--host H] [--port P] [--subnet CIDR] [--image IMG] [--domain D] [--rdp-reject]` | 鍵 + ランダム難読化パラメータの生成、設定のレンダリング、コンテナ起動 |
| `awg-mesh peer add <name> [--type exit\|mesh\|both]` | 新規デバイス: 鍵、IP、プロファイル（`awg syncconf` で適用後、awg コンテナを再起動 — syncconf だけだと userspace デーモンが新規ハンドシェイクを静かに失敗することがある） |
| `awg-mesh peer list` | デバイス、IP、作成日時 |
| `awg-mesh peer rename <name> <new-name>` | デバイスの改名（MagicDNS の `<name>.<domain>` レコードも追随） |
| `awg-mesh peer revoke <name>` | デバイスの削除（設定適用済み、プロファイルは削除） |
| `awg-mesh doctor [--json]` | Docker、コンテナ、リッスンポート、ip_forward、MagicDNS、ポート公開 |
| `awg-mesh monitoring install\|uninstall` | cron 統計（`/var/log/amnezia-mesh-stats.log`）+ watchdog |
| `awg-mesh adopt (--container C \| --config F --image IMG) --host H [--port P] [--dns1 D] [--dns2 D] [--rdp-reject]` | 既存の AmneziaWG サーバーを awg-mesh 管理へ移行（下記参照） |

## 既存サーバーの移行（adopt）

AmneziaWG がすでに動いていて（コンテナでも手作りデプロイでも）、peer
管理・MagicDNS・doctor・モニタリングといった `awg-mesh` の管理下に置き
たい — **しかもクライアントプロファイルを 1 枚も再発行せずに**。

```sh
./bin/awg-mesh adopt --container amnezia-awg --host あなたのIP --port 443
# または、ホスト上の設定ファイルから:
./bin/awg-mesh adopt --config /root/awg0.conf --image amneziavpn/amneziawg-go:latest \
    --host あなたのIP --port 443
```

**そのまま**引き継がれるもの（クライアントは気づかない）:

| | adopt 後 |
|---|---|
| サーバーの秘密鍵 | 同一 — クライアントから見えるサーバーは同じ |
| 難読化プロファイル（Jc/Jmin/Jmax/S/H, HeaderProtectionKey, タイマー） | 同一 — DPI フィンガープリントは変わらない |
| peer の公開鍵、PSK | 同一 |
| peer の IP | 同一 — 各 peer の `AllowedIPs` から取得 |
| デバイス上のクライアントプロファイル | そのまま動く。再発行不要 |

変わるもの: コンテナが `amnezia-mesh` という compose プロジェクトの下に
再作成され（`amnezia-mesh-awg` に改名、dnsmasq は sidecar 化）、以降の
デプロイは `awg-mesh` が管理する。`awg0.conf` が表現できないオプションは
フラグで渡す: `--dns1/--dns2`（MagicDNS 転送先のアップストリーム
リゾルバ、デフォルト 1.1.1.1）、`--rdp-reject`（RDP UDP/3389 リジェクト
ルール）、`--domain`（デフォルト `awg`）。

`adopt` の手順:

1. `awg0.conf` を読む — コンテナ内から（`--container`、イメージは自動
   検出）またはファイルから（`--config`、`--image` 必須）；
2. `[Interface]` + `[Peer]` セクションを `config/server.env` +
   `config/peers.db` に変換 — 理解できないキーを見つけたら**拒否して**
   （該当キーを列挙）、黙って捨てたりしない；
3. `awg0.conf` / `dnsmasq.conf` / `start.sh` をレンダリングしてスタックを
   起動；
4. `--container` の場合: 旧コンテナを**停止**（決して削除しない）して
   `doctor` を実行。失敗時は自動でロールバック — 旧コンテナが再起動し、
   何も削除されない。

安全ルール:

- 旧コンテナは停止されるだけで、ロールバック用としてホストに残る:
  `docker stop amnezia-mesh-awg amnezia-mesh-dns && docker start <旧>`
- 未知の `[Interface]` キー、サーバー `Address` がサブネットの先頭ホストで
  ない場合、peer に `PublicKey`/`PresharedKey` がない場合は adopt が中断；
- peer 名は `# 名前 (added …)` コメントから取得。名前のない peer には
  生成名 `peer-xxxxxx` が付き、重複には `-2` サフィックス。

## 設計: AmneziaWG のバージョンアップが問題にならない理由

1. **AWG イメージは単なる依存。** `docker-compose.yml` は
   `amneziavpn/amneziawg-go` を参照（`--image` または `AWG_MESH_IMAGE` で
   上書き可）。フォークもパッチもなく、イメージタグの差し替えでプロジェクト
   の変更は一切不要。
2. **ロジックはすべてホスト側。** サーバー設定、dnsmasq 設定、コンテナの
   エントリーポイント（iptables ブートストラップ: フォワーディング、
   MASQUERADE、MSS クランプ、オプションの RDP-UDP リジェクト）は `config/`
   に生成されてマウントされる。コンテナの再作成やアップグレードで失うものは
   何もない。
3. **インターフェースは安定した UAPI。** `awg0.conf` のパラメータ
   （Jc/S/H、HeaderProtectionKey、タイマー）は AWG プロトコルの一部で
   リリース間で変わらない。実験的パラメータ `I1`–`I5`（CPS）は `init` 時に
   プローブされ、サポート有無を記録してどちらの場合も互換性を維持。
4. **プロファイルはアプリのネイティブフォーマット。** `vpn://` プロファイルは
   公式 Amnezia アプリのエクスポートとバイト互換
   （`base64url(uint32_be(len) + zlib(json, 9))`、コンパクト区切り — バイト
   一致を検証済み）。新しいアプリのリリースでもインポートは継続される。

## 構成

```
docker-compose.yml      awg コンテナ + dnsmasq sidecar（netns 共有）
bin/awg-mesh            CLI エントリポイント（checkout から直接動く薄い shim）
awg_mesh/               python パッケージ: cli, envfile, peers, keygen,
                        compose, render, profile, doctor, adopt（stdlib のみ）
scripts/                オプションのモニタリング（stats, watchdog, cron）
tests/                  pytest スイート: レンダラ golden ファイル、peers db +
                        flock、profile コーデック roundtrip
config/                 生成される秘密鍵と状態 — gitignore 済み。ホスト内に留まる
```

## メッシュの動作原理（30 秒）

WireGuard は暗号鍵ルーティングです。各パケットは peer の公開鍵で暗号化され、
`AllowedIPs` が宛先 IP を peer にマッピングします。`100.64.0.4` に ping する
電話は **hub の鍵**で暗号化する — macbook の実アドレスを知ることはありません。
hub が復号し、macbook の鍵で再暗号化して転送します。これは hub-and-spoke
（ルーティング型メッシュ）であって P2P ではないため、hole punching が
無意味なキャリアグレードのモバイル NAT の内側でも含め、どんな NAT の背後でも
動作します。両方向の `PersistentKeepalive=25` が NAT マッピングを維持し、
デバイスが常に相互に到達可能な状態を保ちます。

## 堅牢化の注意

- `config/` には秘密鍵が入っている — gitignore 済み、モード 600、サーバー
  から一切持ち出さない。VPS を作り直す場合は暗号化バックアップを。
- VPS ファイアウォールは default-deny のまま、SSH と選んだ UDP ポートだけを
  許可（443/udp が通常の HTTPS/QUIC トラフィックに最も溶け込む）。
- 難読化が倒すのは DPI の**フィンガープリント**であり、トラフィック量の
  解析ではない。グローバルな受動的攻撃者に対する Tor の代わりにはならない。
- `--rdp-reject` はトンネル越しの RDP を助ける（UDP グラフィックス
  チャネルの即時 TCP フォールバックを強制）。メッシュ越しに RDP を使う
  なら `init` で有効化を。

## トラブルシューティング

| 症状 | 確認すること |
|---|---|
| デバイスが接続しない | `awg-mesh doctor`；VPS ファイアウォールが UDP ポートを許可しているか |
| 長い「connecting」の後「connected」になるがインターネットがない | ほぼ確実にデバイス上のプロファイルが古い/誤り: アプリで現在有効なプロファイルを確認し、旧物・テスト用を削除 |
| デバイス上でドメインが解決されない | `doctor` の magicdns チェック；デバイスプロファイルの DNS は hub でなければならない（生成プロファイルはそのようになっている） |
| スループットが低い | MTU 1280 は意図的（padding 用の余白）。小さい VPS プランでは steal/CPU を確認 |
| `awg` CLI が `Protocol not supported` | 単一キークエリにおける amneziawg-tools の既知の癖。完全な `awg show` を使うこと — 表示上の問題のみ |

## テスト

```sh
python3 -m venv .venv && .venv/bin/pip install pytest
.venv/bin/python -m pytest tests/ -q
```

このスイートは Docker もネットワークも不要です。サーバー設定のレンダリングは
オリジナル実装が生成した golden ファイルとバイト単位で比較され、peers db は
複数の同時書き込みで叩かれて `flock` の直列化を証明し、`vpn://` コーデックは
roundtrip テストをパスします。

## ライセンス

MIT
