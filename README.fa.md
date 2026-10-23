[English](README.md) | [Русский](README.ru.md) | [中文](README.zh-CN.md) | [Español](README.es.md) | **فارسی** | [العربية](README.ar.md) | [Português](README.pt-BR.md) | [日本語](README.ja.md) | [Deutsch](README.de.md)

_ترجمه‌ای از README انگلیسی است و ممکن است از متن اصلی عقب‌تر باشد._

# amnezia-mesh

مش WireGuard خودمیزبان با مبهم‌سازی ترافیک AmneziaWG، MagicDNS و پروفایل‌های
exit/mesh به سبک Tailscale — روی یک VPS، در حدود ۱۰ دقیقه، و بدون هیچ وابستگی
جز Docker.

آن را «Tailscale خودتان» تصور کنید، با این تفاوت که هر hop متعلق به خود شماست:
یک سرور کوچک، اپ رسمی Amnezia روی دستگاه‌هایتان، و بدون هیچ سرور هماهنگی،
حساب کاربری یا رله شخص ثالث.

## ویژگی‌ها

- **شبکه مش CGNAT** (`100.64.0.0/24`, RFC 6598) — هر دستگاه یک IP پایدار
  می‌گیرد؛ SSH/ping بین دستگاه‌ها از طریق هاب کار می‌کند، مانند `tailscale ssh`.
- **مبهم‌سازی AmneziaWG 3.1** — دست‌دادن با بسته‌های junk، جایگزینی نوع
  هدر، کلید محافظ هدر، و padding/trailer تصادفی. پارامترها در **هر نصب به‌صورت
  تصادفی** تولید می‌شوند، بنابراین اثر انگشت DPI بین نصب‌ها متفاوت است.
- **MagicDNS** — dnsmasq روی هاب به `<دستگاه>.<دامنه>` (مثلاً `laptop.awg`)
  پاسخ می‌دهد و بقیه را از طریق تونل به resolver بالادستی شما فوروارد می‌کند.
- **پروفایل exit + mesh برای هر دستگاه** — `exit` کل ترافیک را از VPS
  عبور می‌دهد (دور زدن سانسور)؛ `mesh` فقط زیرشبکه CGNAT را روت می‌کند و
  اینترنت مستقیم می‌ماند. هر دو برای هر دستگاه تولید می‌شوند.
- **پروفایل‌های بومی اپ Amnezia** (`vpn://`) به‌علاوه `.conf` ساده برای هر
  کلاینت سازگار با awg/wg.
- **طراحی مستقل از نسخه** — ایمیج AWG یک وابستگی خارجی و قابل تعویض است؛
  تمام منطق روی هاست اجرا می‌شود (به بخش «طراحی» نگاه کنید).
- **CLI دوستانه برای agentها** — هر دستور خروجی `--json`، بازتعریف با
  متغیرهای محیطی و حالت غیرتعاملی دارد.

## پیش‌نیازها

- یک VPS با IP عمومی، Docker با پلاگین compose و `python3`
  (‏>= 3.8، فقط کتابخانه استاندارد — بدون `pip install`).
- یک پورت UDP باز در فایروال VPS (‏443/udp توصیه می‌شود — با ترافیک معمولی
  HTTPS/QUIC قاطی می‌شود و برای ISP شکل‌دادن به آن سخت‌ترین است).

## شروع سریع (انسان)

```sh
git clone https://github.com/<you>/amnezia-mesh && cd amnezia-mesh

./bin/awg-mesh init --host YOUR_IP_OR_DOMAIN --port 443
./bin/awg-mesh peer add laptop
# → چاپ می‌کند: config/peers/laptop-exit.vpn, laptop-mesh.vpn و نسخه‌های .conf
# لینک .vpn را در اپ Amnezia روی دستگاه ایمپورت کنید

./bin/awg-mesh peer add phone
./bin/awg-mesh doctor      # خودآزمایی پس از نصب
./bin/awg-mesh monitoring install   # اختیاری: آمار cron + watchdog
```

روی دستگاه: اپ Amnezia → ایمپورت لینک `vpn://` → اتصال. دستگاه‌ها از این پس
به‌صورت IP (`100.64.0.x`) یا نام (`phone.awg`) به هم دسترسی دارند.

## شروع سریع (agent / اتوماسیون)

```sh
export AWG_MESH_NONINTERACTIVE=1
./bin/awg-mesh --json init --host 198.51.100.10 --port 443
./bin/awg-mesh --json peer add laptop
./bin/awg-mesh --json doctor        # کد خروجی 0 = همه چک‌ها سبز
```

خروجی یک شیء JSON برای هر دستور است؛ در خطا کد خروجی غیرصفر و
`{"ok": false, "error": "..."}` برمی‌گردد.

## دستورات

| دستور | توضیح |
|---|---|
| `awg-mesh init [--host H] [--port P] [--subnet CIDR] [--image IMG] [--domain D] [--rdp-reject]` | تولید کلیدها + مبهم‌سازی تصادفی، رندر کانفیگ‌ها، اجرای کانتینرها |
| `awg-mesh peer add <name> [--type exit\|mesh\|both]` | دستگاه جدید: کلیدها، IP، پروفایل‌ها (با `awg syncconf` اعمال می‌شود، سپس کانتینر awg ری‌استارت می‌شود — syncconf به‌تنهایی می‌تواند دست‌دادن‌های تازه را در دیمون userspace بی‌صدا خراب کند) |
| `awg-mesh peer list` | دستگاه‌ها، IPها، تاریخ‌های ساخت |
| `awg-mesh peer rename <name> <new-name>` | تغییر نام دستگاه (رکورد MagicDNS `<name>.<domain>` دنبال نام می‌آید) |
| `awg-mesh peer revoke <name>` | حذف دستگاه (کانفیگ اعمال می‌شود، پروفایل‌ها پاک می‌شوند) |
| `awg-mesh doctor [--json]` | Docker، کانتینرها، پورت گوش‌دادن، ip_forward، MagicDNS، انتشار پورت |
| `awg-mesh monitoring install\|uninstall` | آمار cron (`/var/log/amnezia-mesh-stats.log`) + watchdog |
| `awg-mesh adopt (--container C \| --config F --image IMG) --host H [--port P] [--dns1 D] [--dns2 D] [--rdp-reject]` | مهاجرت یک سرور AmneziaWG موجود به مدیریت awg-mesh (پایین را ببینید) |

## اتخاذ سرور موجود (adopt)

از قبل AmneziaWG اجرا دارید (یک کانتینر یا یک دیپلوی دست‌ساز) و مدیریت
`awg-mesh` را می‌خواهید — مدیریت peerها، MagicDNS، doctor، مانیتورینگ —
**بدون بازصدور حتی یک پروفایل کلاینت**.

```sh
./bin/awg-mesh adopt --container amnezia-awg --host YOUR_IP --port 443
# یا از یک فایل کانفیگ روی هاست:
./bin/awg-mesh adopt --config /root/awg0.conf --image amneziavpn/amneziawg-go:latest \
    --host YOUR_IP --port 443
```

چه چیزهایی **عیناً** منتقل می‌شود (تا کلاینت‌ها چیزی نفهمند):

| | پس از adopt |
|---|---|
| کلید خصوصی سرور | همان — کلاینت‌ها همان سرور را می‌بینند |
| پروفایل مبهم‌سازی (Jc/Jmin/Jmax/S/H, HeaderProtectionKey, تایمرها) | همان — اثر انگشت DPI تغییر نمی‌کند |
| کلیدهای عمومی و PSK پیرها | همان‌ها |
| IP پیرها | همان‌ها — از `AllowedIPs` هر پیر گرفته می‌شود |
| پروفایل‌های کلاینت روی دستگاه‌ها | کار می‌کنند، بازصدور لازم نیست |

چه چیزی تغییر می‌کند: کانتینر زیر پروژه compose با نام `amnezia-mesh`
دوباره ساخته می‌شود (به `amnezia-mesh-awg` تغییر نام می‌دهد، dnsmasq تبدیل به
sidecar می‌شود) و از آن پس دیپلوی توسط `awg-mesh` مدیریت می‌شود. گزینه‌هایی
که `awg0.conf` نمی‌تواند بیان کند با فلگ‌ها داده می‌شوند: `--dns1/--dns2`
(رزولورهای بالادستی برای فوروارد MagicDNS، پیش‌فرض 1.1.1.1)، `--rdp-reject`
(قانون reject برای RDP UDP/3389)، `--domain` (پیش‌فرض `awg`).

گام‌به‌گام، `adopt`:

1. `awg0.conf` را می‌خواند — از داخل کانتینر (`--container`، ایمیج به‌صورت
   خودکار تشخیص داده می‌شود) یا از فایل (`--config`، `--image` الزامی)؛
2. بخش‌های `[Interface]` + `[Peer]` را به `config/server.env` +
   `config/peers.db` تجزیه می‌کند — در برخورد با کلید ناشناخته **رد می‌کند**
   (با فهرست آن کلیدها)، نه این‌که بی‌صدا چیزی را حذف کند؛
3. `awg0.conf` / `dnsmasq.conf` / `start.sh` را رندر و استک را اجرا می‌کند؛
4. اگر `--container`: کانتینر قدیمی را **متوقف** می‌کند (هرگز حذف نمی‌کند) و
   `doctor` را اجرا می‌کند؛ در خطا به‌صورت خودکار عقب می‌گردد — کانتینر قدیمی
   دوباره اجرا می‌شود و چیزی حذف نمی‌شود.

قوانین ایمنی:

- کانتینر قدیمی فقط متوقف می‌شود و روی هاست به‌عنوان برنامه عقب‌گرد باقی
  می‌ماند: `docker stop amnezia-mesh-awg amnezia-mesh-dns && docker start <قدیمی>`
- adopt در این موارد متوقف می‌شود: کلیدهای ناشناخته `[Interface]`، `Address`
  سرور که اولین هاست ساب‌نت نیست، یا پیرهای بدون `PublicKey`/`PresharedKey`؛
- نام پیرها از کامنت‌های `# name (added …)` می‌آید؛ پیرهای بی‌نام نام
  تولیدشده `peer-xxxxxx` می‌گیرند و برای برخوردها پسوند `-2`.

## طراحی: چرا به‌روزرسانی‌های AmneziaWG اهمیت ندارند

1. **ایمیج AWG یک وابستگی معمولی است.** `docker-compose.yml` به
   `amneziavpn/amneziawg-go` ارجاع می‌دهد (با `--image` یا `AWG_MESH_IMAGE`
   قابل بازتعریف است). هیچ چیزی fork یا patch نشده؛ تعویض تگ ایمیج به هیچ
   تغییری در پروژه نیاز ندارد.
2. **تمام منطق روی هاست اجرا می‌شود.** کانفیگ سرور، کانفیگ dnsmasq و
   entrypoint کانتینر (بوت‌استرپ iptables: forwarding، MASQUERADE، MSS clamp،
   reject اختیاری RDP-UDP) در `config/` تولید و mount می‌شوند. بازسازی یا
   ارتقای کانتینر چیزی از دست نمی‌دهد.
3. **اینترفیس یک UAPI پایدار است.** پارامترهای `awg0.conf` (Jc/S/H،
   HeaderProtectionKey، تایمرها) بخشی از پروتکل AWG هستند و بین نسخه‌ها
   تغییر نمی‌کنند. پارامترهای آزمایشی `I1`–`I5` (CPS) هنگام `init` سنجیده
   می‌شوند؛ پشتیبانی ثبت می‌شود و در هر دو حالت سازگاری حفظ است.
4. **پروفایل‌ها فرمت بومی اپ هستند.** پروفایل‌های `vpn://` با خروجی اپ رسمی
   Amnezia سازگار تا سطح بایت هستند
   (`base64url(uint32_be(len) + zlib(json, 9))` با جداکننده‌های فشرده — بایت‌به‌بایت
   تأیید شده). نسخه‌های جدید اپ به ایمپورت آن‌ها ادامه می‌دهند.

## ساختار

```
docker-compose.yml      کانتینر awg + sidecar dnsmasq (netns مشترک)
bin/awg-mesh            ورودی CLI (شیم نازک، از همان checkout اجرا می‌شود)
awg_mesh/               پکیج python: cli, envfile, peers, keygen, compose,
                        render, profile, doctor, adopt (فقط stdlib)
scripts/                مانیتورینگ اختیاری (stats, watchdog, cron)
tests/                  سوییت pytest: فایل‌های golden رندر، peers db +
                        flock، roundtrip کدک profile
config/                 کلیدهای تولیدشده و وضعیت — در gitignore، روی هاست می‌ماند
```

## شبکه مش چطور کار می‌کند (۳۰ ثانیه)

WireGuard مسیریابی با کلید رمزنگاری است: هر بسته با کلید عمومی پیر رمز می‌شود
و `AllowedIPs` IP مقصد را به پیر نگاشت می‌کند. تلفنی که `100.64.0.4` را
ping می‌کند، بسته را با کلید **هاب** رمز می‌کند — هرگز آدرس واقعی macbook را
نمی‌فهمد. هاب رمزگشایی می‌کند، با کلید macbook دوباره رمز می‌کند و فوروارد
می‌کند. این الگو hub-and-spoke (مش مسیریابی‌شده) است، نه P2P: پشت هر NATی
کار می‌کند، حتی NAT موبایل carrier-grade که در آن hole punching بی‌فایده است.
`PersistentKeepalive=25` در هر دو سمت نگاشت NAT را زنده نگه می‌دارد تا
دستگاه‌ها همیشه به هم برسند.

## نکات سخت‌گیرانه

- `config/` شامل کلیدهای خصوصی است — در gitignore است، با مجوز 600، و هرگز
  سرور را ترک نمی‌کند. در بازسازی VPS از آن رمزنگاری‌شده نسخه پشتیبان بگیرید.
- فایروال VPS را default-deny نگه دارید؛ فقط SSH و پورت UDP انتخابی‌تان را
  باز کنید (‏443/udp بهترین آمیختگی را با ترافیک معمولی HTTPS/QUIC دارد).
- مبهم‌سازی **اثر انگشت‌های** DPI را می‌شکند، نه تحلیل حجم ترافیک را. در
  برابر یک دشمن پسیو جهانی جایگزین Tor نیست.
- `--rdp-reject` به RDP روی تونل کمک می‌کند (fallback فوری TCP کانال گرافیکی
  UDP را مجبور می‌کند). اگر از RDP روی مش استفاده می‌کنید در `init` فعالش کنید.

## عیب‌یابی

| علامت | بررسی |
|---|---|
| دستگاه وصل نمی‌شود | `awg-mesh doctor`؛ فایروال VPS پورت UDP را باز می‌کند |
| «connecting» طولانی، بعد «connected» ولی بدون اینترنت | تقریباً همیشه پروفایل اشتباه/قدیمی روی دستگاه است: پروفایل فعال در اپ را چک کنید و قدیمی‌ها/تستی‌ها را حذف کنید |
| دامنه‌ها روی دستگاه رزولو نمی‌شوند | چک magicdns در `doctor`؛ DNS پروفایل دستگاه باید هاب باشد (پروفایل‌های تولیدشده همین‌طورند) |
| سرعت پایین | MTU برابر 1280 آگاهانه است (فضای padding)؛ روی VPSهای کوچک steal/CPU را چک کنید |
| `Protocol not supported` از CLI `awg` | رفتار شناخته‌شده amneziawg-tools در کوئری‌های تک‌کلیده؛ از `awg show` کامل استفاده کنید — فقط ظاهری است |

## تست‌ها

```sh
python3 -m venv .venv && .venv/bin/pip install pytest
.venv/bin/python -m pytest tests/ -q
```

این سوییت به Docker و شبکه نیاز ندارد: رندر کانفیگ سرور بایت‌به‌بایت با
golden fileهای تولیدشده توسط پیاده‌سازی اولیه مقایسه می‌شود، peers db با
نویسنده‌های هم‌زمان مورد حمله قرار می‌گیرد تا سریال‌سازی `flock` اثبات شود، و
کدک `vpn://` تست roundtrip می‌گذراند.

## مجوز

MIT
