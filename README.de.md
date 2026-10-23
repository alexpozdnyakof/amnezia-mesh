[English](README.md) | [Русский](README.ru.md) | [中文](README.zh-CN.md) | [Español](README.es.md) | [فارسی](README.fa.md) | [العربية](README.ar.md) | [Português](README.pt-BR.md) | [日本語](README.ja.md) | **Deutsch**

_Übersetzung des englischen READMEs; kann dem Original hinterherhinken._

# amnezia-mesh

Selbst-gehostetes WireGuard-Mesh mit AmneziaWG-Traffic-Obfuskation, MagicDNS
und Tailscale-artigen exit/mesh-Profilen — auf einem einzigen VPS, in ~10
Minuten, ohne Abhängigkeiten außer Docker.

Stell es dir vor wie «dein eigenes Tailscale», aber jeder Hop gehört dir: ein
kleiner Server, die offizielle Amnezia-App auf deinen Geräten, und keine
Koordinierungsserver, keine Accounts, keine Third-Party-Relays.

## Features

- **CGNAT-Mesh-Netz** (`100.64.0.0/24`, RFC 6598) — jedes Gerät bekommt eine
  stabile IP; SSH/ping zwischen Geräten läuft über den Hub, wie `tailscale ssh`.
- **AmneziaWG-3.1-Obfuskation** — Handshakes mit Junk-Paketen, Ersetzung von
  Header-Typen, Header-Protection-Key, zufälliges Padding/Trailer. Die
  Parameter werden **pro Installation randomisiert**, sodass sich DPI-Fingerprints
  zwischen Installs unterscheiden.
- **MagicDNS** — dnsmasq auf dem Hub antwortet auf `<gerät>.<domain>` (z. B.
  `laptop.awg`) und leitet alles andere durch den Tunnel an deinen Upstream-Resolver.
- **Exit- + Mesh-Profile pro Gerät** — `exit` routet den gesamten Traffic über
  den VPS (Zensur-Umgehung); `mesh` routet nur das CGNAT-Subnetz und lässt das
  Internet direkt. Beide werden für jedes Gerät erzeugt.
- **Native Amnezia-App-Profile** (`vpn://`) plus einfache `.conf` für jeden
  awg/wg-kompatiblen Client.
- **Versionsagnostisch by Design** — das AWG-Image ist eine externe,
  austauschbare Abhängigkeit; die gesamte Logik lebt auf dem Host (siehe *Design*).
- **Agentenfreundliche CLI** — jedes Kommando hat `--json`-Ausgabe, Overrides
  per Umgebungsvariable und einen Nicht-interaktiv-Modus.

## Voraussetzungen

- Ein VPS mit öffentlicher IP, Docker mit Compose-Plugin und `python3`
  (>= 3.8, nur Standardbibliothek — kein `pip install`).
- Ein offener UDP-Port in der VPS-Firewall (empfohlen: 443/udp — er mischt sich
  unter normalen HTTPS/QUIC-Traffic und ist für ISPs am schwersten zu shapen).

## Schnellstart (menschlich)

```sh
git clone https://github.com/<you>/amnezia-mesh && cd amnezia-mesh

./bin/awg-mesh init --host DEINE_IP_ODER_DOMAIN --port 443
./bin/awg-mesh peer add laptop
# → gibt aus: config/peers/laptop-exit.vpn, laptop-mesh.vpn sowie .conf-Varianten
# den .vpn-Link in der Amnezia-App auf dem Gerät importieren

./bin/awg-mesh peer add phone
./bin/awg-mesh doctor      # Selbsttests nach der Installation
./bin/awg-mesh monitoring install   # optional: Cron-Statistiken + Watchdog
```

Auf dem Gerät: Amnezia-App → `vpn://`-Link importieren → verbinden. Geräte
erreichen sich jetzt per IP (`100.64.0.x`) oder per Name (`phone.awg`).

## Schnellstart (Agent / Automatisierung)

```sh
export AWG_MESH_NONINTERACTIVE=1
./bin/awg-mesh --json init --host 198.51.100.10 --port 443
./bin/awg-mesh --json peer add laptop
./bin/awg-mesh --json doctor        # Exit-Code 0 = alle Checks grün
```

Die Ausgabe ist ein einzelnes JSON-Objekt pro Kommando; bei Fehlern ist der
Exit-Code ungleich null und es kommt `{"ok": false, "error": "..."}`.

## Kommandos

| Kommando | Beschreibung |
|---|---|
| `awg-mesh init [--host H] [--port P] [--subnet CIDR] [--image IMG] [--domain D] [--rdp-reject]` | Schlüssel + zufällige Obfuskation erzeugen, Configs rendern, Container starten |
| `awg-mesh peer add <name> [--type exit\|mesh\|both]` | Neues Gerät: Schlüssel, IP, Profile (wird via `awg syncconf` angewendet, danach wird der awg-Container neu gestartet — syncconf allein kann frische Handshakes im Userspace-Daemon still kaputt machen) |
| `awg-mesh peer list` | Geräte, IPs, Erstellungsdaten |
| `awg-mesh peer rename <name> <new-name>` | Gerät umbenennen (der `<name>.<domain>`-MagicDNS-Eintrag folgt dem Namen) |
| `awg-mesh peer revoke <name>` | Gerät entfernen (Config angewendet, Profile gelöscht) |
| `awg-mesh doctor [--json]` | Docker, Container, Listen-Port, ip_forward, MagicDNS, Port-Veröffentlichung |
| `awg-mesh monitoring install\|uninstall` | Cron-Statistiken (`/var/log/amnezia-mesh-stats.log`) + Watchdog |
| `awg-mesh adopt (--container C \| --config F --image IMG) --host H [--port P] [--dns1 D] [--dns2 D] [--rdp-reject]` | Einen bestehenden AmneziaWG-Server unter awg-mesh-Verwaltung migrieren (siehe unten) |

## Einen bestehenden Server übernehmen (adopt)

Du betreibst bereits AmneziaWG (Container oder Hand-Deployment) und willst die
Verwaltung durch `awg-mesh` — Peer-Verwaltung, MagicDNS, Doctor, Monitoring —
**ohne auch nur ein einziges Client-Profil neu auszustellen**.

```sh
./bin/awg-mesh adopt --container amnezia-awg --host DEINE_IP --port 443
# oder aus einer Config-Datei auf dem Host:
./bin/awg-mesh adopt --config /root/awg0.conf --image amneziavpn/amneziawg-go:latest \
    --host DEINE_IP --port 443
```

Was **wörtlich** übernommen wird (damit Clients nichts merken):

| | nach adopt |
|---|---|
| privater Serverschlüssel | derselbe — Clients sehen denselben Server |
| Obfuskationsprofil (Jc/Jmin/Jmax/S/H, HeaderProtectionKey, Timer) | dasselbe — DPI-Fingerprint unverändert |
| öffentliche Peer-Schlüssel, PSKs | dieselben |
| Peer-IPs | dieselben — aus dem jeweiligen `AllowedIPs` übernommen |
| Client-Profile auf den Geräten | funktionieren weiter, kein Neu-Ausstellen |

Was sich ändert: Der Container wird unter dem Compose-Projekt `amnezia-mesh`
neu erstellt (umbenannt in `amnezia-mesh-awg`, dnsmasq wird ein Sidecar) und das
Deployment wird von da an von `awg-mesh` verwaltet. Optionen, die ein
`awg0.conf` nicht ausdrücken kann, sind Flags: `--dns1/--dns2` (Upstream-Resolver
für das MagicDNS-Forwarding, Standard 1.1.1.1), `--rdp-reject` (Reject-Regel für
RDP UDP/3389), `--domain` (Standard `awg`).

Schritt für Schritt macht `adopt`:

1. liest `awg0.conf` — aus dem Container (`--container`, Image wird automatisch
   erkannt) oder aus einer Datei (`--config`, `--image` erforderlich);
2. parst die Abschnitte `[Interface]` + `[Peer]` nach `config/server.env` +
   `config/peers.db` — bei unbekannten Schlüsseln **bricht es ab** (und nennt
   sie), statt sie still zu verwerfen;
3. rendert `awg0.conf` / `dnsmasq.conf` / `start.sh` und startet den Stack;
4. bei `--container`: **stoppt** den alten Container (entfernt ihn nie) und läuft
   `doctor`; bei Fehlern rollt es automatisch zurück — der alte Container wird
   wieder gestartet, nichts wird gelöscht.

Sicherheitsregeln:

- der alte Container wird nur gestoppt und bleibt auf dem Host als Rollback-Plan:
  `docker stop amnezia-mesh-awg amnezia-mesh-dns && docker start <alt>`
- adopt bricht ab bei unbekannten `[Interface]`-Schlüsseln, einer Server-`Address`,
  die nicht der erste Host des Subnetzes ist, oder Peers ohne
  `PublicKey`/`PresharedKey`;
- Peer-Namen kommen aus `# name (added …)`-Kommentaren; namenlose Peers bekommen
  einen generierten Namen `peer-xxxxxx`, Kollisionen einen `-2`-Suffix.

## Design: warum AmneziaWG-Versionsupdates egal sind

1. **Das AWG-Image ist eine gewöhnliche Abhängigkeit.** `docker-compose.yml`
   referenziert `amneziavpn/amneziawg-go` (überschreibbar via `--image` oder
   `AWG_MESH_IMAGE`). Nichts ist geforkt oder gepatcht; das Wechseln des
   Image-Tags erfordert keine Projektänderungen.
2. **Die gesamte Logik lebt auf dem Host.** Server-Config, dnsmasq-Config und
   der Container-Entrypoint (iptables-Bootstrap: Forwarding, MASQUERADE,
   MSS-Clamp, optionaler RDP-UDP-Reject) werden nach `config/` gerendert und
   gemountet. Neuerstellen oder Upgraden des Containers verliert nichts.
3. **Die Schnittstelle ist das stabile UAPI.** Die `awg0.conf`-Parameter
   (Jc/S/H, HeaderProtectionKey, Timer) sind Teil des AWG-Protokolls und ändern
   sich nicht zwischen Releases. Experimentelle `I1`–`I5`-Parameter (CPS) werden
   beim `init` erprobt; die Unterstützung wird protokolliert und die
   Kompatibilität bleibt auf jeden Fall erhalten.
4. **Profile sind das natives App-Format.** `vpn://`-Profile sind
   byte-kompatibel mit dem, was die offizielle Amnezia-App exportiert
   (`base64url(uint32_be(len) + zlib(json, 9))`, kompakte Trenner —
   byte-identisch verifiziert). Neue App-Releases importieren sie weiter.

## Struktur

```
docker-compose.yml      awg-Container + dnsmasq-Sidecar (geteilter Netns)
bin/awg-mesh            CLI-Einstieg (dünner Shim, läuft direkt aus dem Checkout)
awg_mesh/               Python-Paket: cli, envfile, peers, keygen, compose,
                        render, profile, doctor, adopt (nur Stdlib)
scripts/                optionales Monitoring (Stats, Watchdog, Cron)
tests/                  pytest-Suite: Render-Golden-Files, peers db +
                        flock, Profile-Codec-Roundtrip
config/                 erzeugte Secrets und Zustand — gitignored, bleibt auf dem Host
```

## Wie das Mesh funktioniert (30 Sekunden)

WireGuard ist Cryptokey-Routing: Jedes Paket wird mit dem Public Key des Peers
verschlüsselt, und `AllowedIPs` bildet Ziel-IPs auf Peers ab. Ein Telefon, das
`100.64.0.4` anpingt, verschlüsselt mit dem Schlüssel des **Hubs** — es erfährt
nie die echte Adresse des MacBooks. Der Hub entschlüsselt, verschlüsselt neu mit
dem Schlüssel des MacBooks und leitet weiter. Das ist Hub-and-Spoke (geroutetes
Mesh), nicht P2P: Es funktioniert hinter jedem NAT, inklusive Carrier-Grade-
Mobilfunk-NATs, bei denen Hole Punching nutzlos ist. `PersistentKeepalive=25`
auf beiden Seiten hält die NAT-Mappings aktiv, damit Geräte sich gegenseitig
erreichen.

## Härtungshinweise

- `config/` enthält private Schlüssel — es ist gitignored, hat Modus 600 und
  verlässt den Server nie. Sichere es verschlüsselt, wenn du den VPS neu
  aufsetzt.
- Halte die VPS-Firewall auf default-deny; erlaube nur SSH und deinen gewählten
  UDP-Port (443/udp mischt sich am besten unter normalen HTTPS/QUIC-Traffic).
- Obfuskation besiegt DPI-**Fingerprints**, nicht Traffic-Volumen-Analyse. Sie
  ersetzt Tor nicht gegen einen global passiven Angreifer.
- `--rdp-reject` hilft RDP über den Tunnel (erzwingt sofortiges TCP-Fallback des
  UDP-Grafikkanals). Aktiviere es im `init`, wenn du RDP durchs Mesh nutzt.

## Fehlersuche

| Symptom | Prüfen |
|---|---|
| Gerät verbindet nicht | `awg-mesh doctor`; VPS-Firewall lässt UDP-Port zu |
| Langes «connecting», dann «connected», aber kein Internet | Fast immer das falsche/alte Profil auf dem Gerät: prüfe, welches Profil in der App aktiv ist, und lösche alte/Test-Profile |
| Domains lösen auf dem Gerät nicht auf | magicdns-Check im `doctor`; das Profil des Geräts muss den Hub als DNS nutzen (generierte Profile tun das) |
| Durchsatz niedrig | MTU 1280 ist Absicht (Puffer für Padding); prüfe steal/CPU bei kleinen VPS-Tarifen |
| `Protocol not supported` vom `awg`-CLI | bekannte Macke von amneziawg-tools bei Einzel-Key-Abfragen; nutze das volle `awg show` — nur kosmetisch |

## Tests

```sh
python3 -m venv .venv && .venv/bin/pip install pytest
.venv/bin/python -m pytest tests/ -q
```

Die Suite braucht weder Docker noch Netz: Das Rendern der Server-Config wird
Byte für Byte mit Golden-Files der Original-Implementierung verglichen, die
peers db wird von konkurrierenden Schreibern gequält, um die `flock`-
Serialisierung zu beweisen, und der `vpn://`-Codec durchläuft Roundtrip-Tests.

## Lizenz

MIT
