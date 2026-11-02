[English](README.md) | [Русский](README.ru.md) | [中文](README.zh-CN.md) | [Español](README.es.md) | [فارسی](README.fa.md) | [العربية](README.ar.md) | [Português](README.pt-BR.md) | [日本語](README.ja.md) | [Deutsch](README.de.md) | [한국어](README.ko.md) | [Français](README.fr.md) | [हिन्दी](README.hi.md) | **Bahasa Indonesia** | [Українська](README.uk.md)

_Terjemahan dari README bahasa Inggris; bisa tertinggal dari aslinya._

# amnezia-mesh

Mesh WireGuard self-hosted dengan ofuskasi trafik AmneziaWG, MagicDNS, dan
profil exit/mesh gaya Tailscale — di satu VPS, dalam ~10 menit, tanpa
dependensi selain Docker.

Anggap saja «Tailscale milikmu sendiri», tapi setiap hop milikmu: satu server
kecil, aplikasi resmi Amnezia di perangkatmu, dan tanpa server koordinasi,
tanpa akun, tanpa relay pihak ketiga.

## Fitur

- **Jaringan mesh CGNAT** (`100.64.0.0/24`, RFC 6598) — setiap perangkat
  mendapat IP stabil; SSH/ping antar perangkat berjalan melalui hub, seperti
  `tailscale ssh`.
- **Ofuskasi AmneziaWG 3.1** — handshake dengan paket junk, substitusi tipe
  header, kunci proteksi header, padding/trailer acak. Parameter
  **diacak setiap deployment**, sehingga sidik jari DPI berbeda antar
  instalasi.
- **MagicDNS** — dnsmasq di hub menjawab `<perangkat>.<domain>` (mis.
  `laptop.awg`) dan meneruskan sisanya ke resolver upstream-mu lewat tunnel.
- **Profil exit + mesh per perangkat** — `exit` mengarahkan semua trafik via
  VPS (penyiasatan sensor); `mesh` hanya mengarahkan subnet CGNAT dan
  internet tetap langsung. Keduanya dibuat untuk setiap perangkat.
- **Profil asli aplikasi Amnezia** (`vpn://`) ditambah `.conf` polos untuk
  klien awg/wg mana pun.
- **Agnostik versi secara desain** — image AWG adalah dependensi eksternal yang
  bisa diganti; seluruh logika hidup di host (lihat *Desain*).
- **CLI yang ramah agen** — setiap perintah punya keluaran `--json`, override
  via variabel lingkungan, dan mode non-interaktif.

## Persyaratan

- VPS dengan IP publik, Docker dengan plugin compose, dan `python3`
  (>= 3.8, hanya pustaka standar — tanpa `pip install`).
- Port UDP terbuka di firewall VPS (disarankan 443/udp — bercampur dengan
  trafik HTTPS/QUIC normal dan paling sulit di-shape oleh ISP).

## Penyiapan dengan agen AI (Claude Code, Kimi Code, Cursor, …)

CLI membawa skill operatornya sendiri — runbook ringkas yang mencakup
instalasi, protokol otomatisasi, semantik restart, dan pohon keputusan
diagnostik. Serahkan ke agenmu dan seluruh alurnya menjadi percakapan:

```sh
# cask macOS: awg-mesh (CLI) dan awg-mesh-tui. Linux: lihat Releases.
brew tap alexpozdnyakof/tap
brew install --cask alexpozdnyakof/tap/awg-mesh
# atau: git clone repo ini

awg-mesh-tui install --ssh root@VPS_KAMU --json
awg-mesh skill --install   # ~/.agents/skills/awg-mesh/SKILL.md
```

Lalu cukup minta, mis. *«pasang VPN di VPS ini (IP 203.0.113.7), tambahkan
laptop dan ponselku, lalu jalankan pemeriksaan mandiri»*. Agen menjalankan
`awg-mesh init` / `peer add` / `doctor --json`, mengimpor profil yang dibuat
ke perangkatmu, dan mendiagnosis konektivitas dengan pohon keputusan skill.
`AGENTS.md` di root repo melakukan orientasi yang sama untuk agen yang
bekerja di dalam checkout.

## Mulai cepat (manusia)

```sh
git clone https://github.com/<you>/amnezia-mesh && cd amnezia-mesh

./bin/awg-mesh init --host IP_ATAU_DOMAIN_KAMU --port 443
./bin/awg-mesh peer add laptop
# → mencetak: config/peers/laptop-exit.vpn, laptop-mesh.vpn, plus varian .conf
# impor tautan .vpn ke aplikasi Amnezia di perangkat

./bin/awg-mesh peer add phone
./bin/awg-mesh doctor      # pemeriksaan mandiri pasca-instalasi
./bin/awg-mesh monitoring install   # opsional: statistik cron + watchdog
```

Di perangkat: aplikasi Amnezia → impor tautan `vpn://` → sambung. Perangkat
 kini saling terjangkau lewat IP (`100.64.0.x`) atau nama (`phone.awg`).

## Mulai cepat (agen / otomatisasi)

```sh
export AWG_MESH_NONINTERACTIVE=1
./bin/awg-mesh --json init --host 198.51.100.10 --port 443
./bin/awg-mesh --json peer add laptop
./bin/awg-mesh --json doctor        # kode keluar 0 = semua pemeriksaan hijau
```

Keluaran adalah satu objek JSON per perintah; kegagalan memberi kode keluar
non-nol dan `{"ok": false, "error": "..."}`.

## Perintah

| Perintah | Deskripsi |
|---|---|
| `awg-mesh init [--host H] [--port P] [--subnet CIDR] [--image IMG] [--domain D] [--rdp-reject]` | Membuat kunci + ofuskasi acak, me-render konfigurasi, menjalankan kontainer |
| `awg-mesh peer add <name> [--type exit\|mesh\|both]` | Perangkat baru: kunci, IP, profil (diterapkan langsung via `awg set` + SIGHUP dnsmasq — tanpa restart; peer yang ada mempertahankan sesinya) |
| `awg-mesh peer list` | Perangkat, IP, tanggal pembuatan |
| `awg-mesh peer rename <name> <new-name> [pairs...]` | Mengganti nama perangkat — terima beberapa pasangan lama/baru untuk membersihkan sekaligus nama `peer-xxxx` yang dibuat setelah adopt (nama MagicDNS mengikuti; hanya SIGHUP dnsmasq — tanpa restart; validasi all-or-nothing, swap didukung) |
| `awg-mesh peer rotate <name>` | Menerbitkan ulang kunci perangkat (IP sama; hub di-restart seperti pada revoke — perangkat harus mengimpor ulang profilnya, tautan `vpn://` lama mati) |
| `awg-mesh peer revoke <name>` | Menghapus perangkat (kontainer awg + dns di-restart — menghapus peer dari daemon userspace via UAPI bisa diam-diam menjegal handshake baru; profil terhapus) |
| `awg-mesh doctor [--json]` | Docker, kontainer, port pendengar, ip_forward, MagicDNS, publikasi port |
| `awg-mesh dns add <name> <ipv4>` / `dns remove <name>` / `dns list` | Catatan MagicDNS kustom di atas `<name>.<domain>` (`nas.awg` → IPv4 apa pun) di `config/custom.hosts` — `--addn-hosts` kedua untuk dnsmasq, dimuat ulang via SIGHUP, tanpa restart |
| `awg-mesh monitoring install\|uninstall` | Statistik cron (`/var/log/amnezia-mesh-stats.log`) + watchdog |
| `awg-mesh adopt (--container C \| --config F --image IMG) --host H [--port P] [--dns1 D] [--dns2 D] [--rdp-reject]` | Memigrasikan server AmneziaWG yang ada ke bawah kelolaan awg-mesh (lihat di bawah) |

## Mode jarak jauh (kelola server dari Mac-mu)

```sh
awg-mesh --server my-vps peer list --json   # atau: export AWG_MESH_SSH=my-vps
```

CLI lokal menjalankan `ssh my-vps 'cd ~ && awg-mesh <args>'` dengan klien ssh
sistem (alias dan kunci dari `~/.ssh/config`) dan meneruskan stdout/stderr/kode
keluar — tidak ada logika yang diduplikasi secara lokal. Setelah perintah yang
mengubah state (`init`, `adopt`, `peer add|rename|revoke|rotate`),
`config/peers/` jarak jauh dicerminkan balik via scp, sehingga profil `.vpn`
berakhir di samping checkout lokalmu. `AWG_MESH_REMOTE_ROOT` mengatur root
mesh di server (bawaan `~`). `skill` dan `--version` selalu berjalan lokal.

## Mengadopsi server yang ada

Kamu sudah menjalankan AmneziaWG (kontainer atau deployment buatan tangan) dan
mau kelolaan `awg-mesh` — manajemen peer, MagicDNS, doctor, monitoring —
**tanpa menerbitkan ulang satu pun profil klien**.

```sh
./bin/awg-mesh adopt --container amnezia-awg --host IP_KAMU --port 443
# atau, dari berkas konfigurasi di host:
./bin/awg-mesh adopt --config /root/awg0.conf --image amneziavpn/amneziawg-go:latest \
    --host IP_KAMU --port 443
```

Yang dibawa **apa adanya** (agar klien tidak menyadari apa pun):

| | setelah adopt |
|---|---|
| kunci privat server | sama — klien melihat server yang sama |
| profil ofuskasi (Jc/Jmin/Jmax/S/H, HeaderProtectionKey, timer) | sama — sidik jari DPI tak berubah |
| kunci publik dan PSK peer | sama |
| IP peer | sama — diambil dari `AllowedIPs` masing-masing peer |
| profil klien di perangkat | terus berfungsi, tanpa penerbitan ulang |

Yang berubah: kontainer dibuat ulang di bawah proyek compose `amnezia-mesh`
(diubah namanya menjadi `amnezia-mesh-awg`, dnsmasq menjadi sidecar) dan
deployment dikelola oleh `awg-mesh` sejak saat itu. Opsi yang tidak bisa
dinyatakan `awg0.conf` menjadi flag: `--dns1/--dns2` (resolver upstream untuk
forwarding MagicDNS, bawaan 1.1.1.1), `--rdp-reject` (aturan reject RDP
UDP/3389), `--domain` (bawaan `awg`).

Langkah demi langkah, `adopt`:

1. membaca `awg0.conf` — dari dalam kontainer (`--container`, image terdeteksi
   otomatis) atau dari berkas (`--config`, wajib `--image`);
2. menguraikan bagian `[Interface]` + `[Peer]` ke `config/server.env` +
   `config/peers.db` — menghadapi kunci yang tidak dikenal, ia **menolak**
   (dengan menyebutkannya), bukan membuangnya diam-diam;
3. me-render `awg0.conf` / `dnsmasq.conf` / `start.sh` dan menjalankan stack;
4. dengan `--container`: **menghentikan** kontainer lama (tidak pernah
   menghapusnya) dan menjalankan `doctor`; bila gagal ia otomatis memutar balik
   — kontainer lama berjalan lagi, tidak ada yang terhapus.

Aturan keamanan:

- kontainer lama hanya dihentikan dan tetap ada di host sebagai rencana
  rollback: `docker stop amnezia-mesh-awg amnezia-mesh-dns && docker start <lama>`
- adopt berhenti pada kunci `[Interface]` yang tidak dikenal, `Address` server
  yang bukan host pertama subnet, atau peer tanpa
  `PublicKey`/`PresharedKey`;
- nama peer diambil dari komentar `# nama (added …)`; peer tanpa nama
  mendapat nama buatan `peer-xxxxxx`, dan tabrakan mendapat akhiran `-2`.

## Desain: kenapa pembaruan versi AmneziaWG tidak masalah

1. **Image AWG adalah dependensi biasa.** `docker-compose.yml` mereferensikan
   `amneziavpn/amneziawg-go` (ditimpa via `--image` atau `AWG_MESH_IMAGE`).
   Tidak ada yang di-fork atau di-patch; mengganti tag image tidak butuh
   perubahan proyek.
2. **Seluruh logika hidup di host.** Konfigurasi server, konfigurasi dnsmasq,
   dan entrypoint kontainer (bootstrap iptables: forwarding, MASQUERADE, MSS
   clamp, reject RDP-UDP opsional) dibuat ke `config/` dan di-mount. Membuat
   ulang atau meningkatkan kontainer tidak kehilangan apa pun.
3. **Antarmukanya adalah UAPI yang stabil.** Parameter `awg0.conf` (Jc/S/H,
   HeaderProtectionKey, timer) adalah bagian dari protokol AWG dan tidak
   berubah antar rilis. Parameter eksperimental `I1`–`I5` (CPS) diuji saat
   `init`; dukungan dicatat dan kompatibilitas terjaga dalam kedua kasus.
4. **Profil adalah format asli aplikasi.** Profil `vpn://` kompatibel byte
   dengan yang diekspor aplikasi resmi Amnezia
   (`base64url(uint32_be(len) + zlib(json, 9))`, pemisah ringkas — terverifikasi
   byte demi byte). Rilis aplikasi baru terus mengimpornya.

## Struktur

```
docker-compose.yml      kontainer awg + sidecar dnsmasq (netns bersama)
bin/awg-mesh            titik masuk CLI (shim tipis, berjalan dari checkout)
awg_mesh/               paket python: cli, envfile, peers, keygen, compose,
                        render, profile, doctor, adopt (hanya stdlib)
scripts/                monitoring opsional (stats, watchdog, cron)
tests/                  rangkaian pytest: golden file render, peers db +
                        flock, roundtrip codec profile
config/                 rahasia dan state yang dibuat — di gitignore, tetap di host
```

## Cara kerja mesh (30 detik)

WireGuard adalah routing berbasis kriptokunci: setiap paket dienkripsi dengan
kunci publik peer, dan `AllowedIPs` memetakan IP tujuan ke peer. Ponsel yang
melakukan ping ke `100.64.0.4` mengenkripsi dengan kunci **hub** — ia tidak
pernah mengetahui alamat asli macbook. Hub mendekripsi, mengenkripsi ulang
dengan kunci macbook, dan meneruskan. Ini hub-and-spoke (mesh ter-routing),
bukan P2P: bekerja di belakang NAT apa pun, termasuk NAT seluler carrier-grade
yang membuat hole punching percuma. `PersistentKeepalive=25` di kedua sisi
menjaga pemetaan NAT tetap hidup sehingga perangkat saling terjangkau.

## Catatan pengerasan

- `config/` memuat kunci privat — sudah di gitignore, ber-mode 600, dan tidak
  pernah meninggalkan server. Buat cadangan terenkripsi bila kamu membangun
  ulang VPS.
- Jaga firewall VPS dalam default-deny; hanya izinkan SSH dan port UDP pilihanmu
  (443/udp paling menyatu dengan trafik HTTPS/QUIC normal).
- Ofuskasi mengalahkan **sidik jari** DPI, bukan analisis volume trafik. Ia
  bukan pengganti Tor menghadapi musuh pasif global.
- `--rdp-reject` membantu RDP lewat tunnel (memaksa fallback TCP seketika
  untuk kanal grafis UDP). Aktifkan di `init` bila kamu memakai RDP melalui
  mesh.

## Penyelesaian masalah

| Gejala | Periksa |
|---|---|
| Perangkat tidak tersambung | `awg-mesh doctor`; firewall VPS membolehkan port UDP |
| «connecting» lama, lalu «connected» tapi tidak ada internet | Hampir selalu profil salah/usang di perangkat: periksa profil yang aktif di aplikasi dan hapus yang lama/uji coba |
| Domain tidak ter-resolve di perangkat | pemeriksaan magicdns di `doctor`; DNS pada profil perangkat harus hub (profil yang dibuat memang begitu) |
| Throughput rendah | MTU 1280 disengaja (ruang untuk padding); periksa steal/CPU di paket VPS kecil |
| `Protocol not supported` dari CLI `awg` | kejanggalan umum amneziawg-tools pada kueri kunci tunggal; gunakan `awg show` lengkap — murni kosmetik |

## Uji

```sh
python3 -m venv .venv && .venv/bin/pip install pytest
.venv/bin/python -m pytest tests/ -q
```

Rangkaian ini tidak butuh Docker maupun jaringan: render konfigurasi server
dibandingkan byte demi byte dengan golden file dari implementasi asli, peers db
dihajar oleh banyak penulis bersamaan untuk membuktikan serialisasi `flock`,
dan codec `vpn://` melewati uji roundtrip.

## Lisensi

MIT
