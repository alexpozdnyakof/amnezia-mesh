[English](README.md) | [Русский](README.ru.md) | [中文](README.zh-CN.md) | [Español](README.es.md) | [فارسی](README.fa.md) | **العربية** | [Português](README.pt-BR.md) | [日本語](README.ja.md) | [Deutsch](README.de.md)

_ترجمة لملف README الإنجليزي وقد تتأخر عن الأصل._

# amnezia-mesh

شبكة WireGuard ذاتية الاستضافة مع تعمية Traffic عبر AmneziaWG وMagicDNS
وملفات تعريف exit/mesh على غرار Tailscale — على VPS واحد، في ~10 دقائق، وبدون
أي اعتماديات سوى Docker.

تخيّل «Tailscale الخاص بك»، لكن كل قفزة شبكية ملك لك: خادم صغير واحد، تطبيق
Amnezia الرسمي على أجهزتك، وبدون خوادم تنسيق أو حسابات أو وسائط طرف ثالث.

## المزايا

- **شبكة mesh من نطاق CGNAT** (`100.64.0.0/24`, RFC 6598) — كل جهاز يحصل
  على IP ثابت؛ يعمل SSH/ping بين الأجهزة عبر الـ hub، مثل `tailscale ssh`.
- **تعمية AmneziaWG 3.1** — مصافحات ببيانات junk، استبدال أنواع الترويسات،
  مفتاح حماية الترويسة، padding/trailers عشوائية. المعاملات **عشوائية في كل
  تثبيت**، لذا تختلف بصمات DPI بين التثبيتات.
- **MagicDNS** — يجيب dnsmasq على الـ hub عن `<جهاز>.<نطاق>` (مثل
  `laptop.awg`) ويمرر كل ما عدا ذلك إلى المحلل upstream عبر النفق.
- **ملفا exit + mesh لكل جهاز** — `exit` يمرر كل الترافيك عبر VPS (تجاوز
  الرقابة)؛ و`mesh` يوجه فقط شبكة CGNAT ويبقي الإنترنت مباشراً. يُنشأ كلاهما
  لكل جهاز.
- **ملفات تعريف أصلية لتطبيق Amnezia** (`vpn://`) إضافة إلى `.conf` عادي لأي
  عميل متوافق مع awg/wg.
- **تصميم محايد للإصدارات** — صورة AWG اعتمادية خارجية قابلة للاستبدال؛ كل
  المنطق يعيش على المضيف (انظر «التصميم»).
- **CLI ودود للوكلاء** — كل أمر له مخرجات `--json` وتحويلات عبر متغيرات
  البيئة ووضع غير تفاعلي.

## المتطلبات

- VPS بعنوان IP عام، وDocker مع إضافة compose، و`python3`
  (‏>= 3.8، مكتبة قياسية فقط — بدون `pip install`).
- منفذ UDP مفتوح في جدار حماية VPS (يُنصح بـ 443/udp — يمتزج مع ترافيك
  HTTPS/QUIC العادي ويصعب على مزودي الخدمة تشكيله).

## البدء السريع (بشري)

```sh
git clone https://github.com/<you>/amnezia-mesh && cd amnezia-mesh

./bin/awg-mesh init --host YOUR_IP_OR_DOMAIN --port 443
./bin/awg-mesh peer add laptop
# → يطبع: config/peers/laptop-exit.vpn وlaptop-mesh.vpn ونسخ .conf
# استورد رابط .vpn في تطبيق Amnezia على الجهاز

./bin/awg-mesh peer add phone
./bin/awg-mesh doctor      # فحص ذاتي بعد التثبيت
./bin/awg-mesh monitoring install   # اختياري: إحصاءات cron + watchdog
```

على الجهاز: تطبيق Amnezia → استيراد رابط `vpn://` → اتصال. يمكن الآن للأجهزة
الوصول لبعضها بالـ IP (`100.64.0.x`) أو بالاسم (`phone.awg`).

## البدء السريع (وكيل / أتمتة)

```sh
export AWG_MESH_NONINTERACTIVE=1
./bin/awg-mesh --json init --host 198.51.100.10 --port 443
./bin/awg-mesh --json peer add laptop
./bin/awg-mesh --json doctor        # رمز الخروج 0 = كل الفحوصات خضراء
```

المخرجات عبارة عن كائن JSON واحد لكل أمر؛ عند الفشل يكون رمز الخروج غير صفري
ومخرجات `{"ok": false, "error": "..."}`.

## الأوامر

| الأمر | الوصف |
|---|---|
| `awg-mesh init [--host H] [--port P] [--subnet CIDR] [--image IMG] [--domain D] [--rdp-reject]` | توليد المفاتيح + تعمية عشوائية، تصيير الإعدادات، تشغيل الحاويات |
| `awg-mesh peer add <name> [--type exit\|mesh\|both]` | جهاز جديد: مفاتيح وIP وملفات تعريف (تُطبق عبر `awg syncconf` ثم تُعاد تشغيل حاوية awg — فـ syncconf وحده قد يعطّل المصافحات الجديدة بصمت في دايمون userspace) |
| `awg-mesh peer list` | الأجهزة وعناوين IP وتواريخ الإنشاء |
| `awg-mesh peer rename <name> <new-name>` | إعادة تسمية جهاز (سجل MagicDNS `<name>.<domain>` يتبع الاسم) |
| `awg-mesh peer revoke <name>` | إزالة جهاز (يُطبق الإعداد وتُحذف ملفات التعريف) |
| `awg-mesh doctor [--json]` | Docker والحاويات ومنفذ الاستماع وip_forward وMagicDNS ونشر المنافذ |
| `awg-mesh monitoring install\|uninstall` | إحصاءات cron (`/var/log/amnezia-mesh-stats.log`) + watchdog |
| `awg-mesh adopt (--container C \| --config F --image IMG) --host H [--port P] [--dns1 D] [--dns2 D] [--rdp-reject]` | ترحيل خادم AmneziaWG موجود إلى إدارة awg-mesh (انظر أدناه) |

## تبنّي خادم موجود

لديك AmneziaWG يعمل أصلاً (حاوية أو نشر يدوي) وتريد إدارة `awg-mesh` —
إدارة الأقران وMagicDNS وdoctor والمراقبة — **دون إعادة إصدار أي ملف تعريف
عميل واحد**.

```sh
./bin/awg-mesh adopt --container amnezia-awg --host YOUR_IP --port 443
# أو من ملف إعداد على المضيف:
./bin/awg-mesh adopt --config /root/awg0.conf --image amneziavpn/amneziawg-go:latest \
    --host YOUR_IP --port 443
```

ما يُنقل **حرفياً** (حتى لا يلاحظ العملاء شيئاً):

| | بعد adopt |
|---|---|
| المفتاح الخاص للخادم | نفسه — العملاء يرون الخادم نفسه |
| ملف التعمية (Jc/Jmin/Jmax/S/H, HeaderProtectionKey, المؤقتات) | نفسه — بصمة DPI لا تتغير |
| مفاتيح الأقران العامة وPSK | نفسها |
| عناوين IP للأقران | نفسها — مأخوذة من `AllowedIPs` لكل peer |
| ملفات تعريف العملاء على الأجهزة | تستمر بالعمل، بلا إعادة إصدار |

ما يتغير: تُعاد إنشاء الحاوية ضمن مشروع compose باسم `amnezia-mesh` (تُعاد
تسميتها إلى `amnezia-mesh-awg` ويصبح dnsmasq sidecar) ويدير النشر `awg-mesh`
منذ تلك اللحظة. الخيارات التي لا يستطيع `awg0.conf` التعبير عنها تُمرر كخيارات:
`--dns1/--dns2` (محللو upstream لتمرير MagicDNS، الافتراضي 1.1.1.1)،
`--rdp-reject` (قاعدة reject لـ RDP UDP/3389)، `--domain` (الافتراضي `awg`).

خطوة بخطوة، `adopt`:

1. يقرأ `awg0.conf` — من داخل الحاوية (`--container`، تُكتشف الصورة تلقائياً)
   أو من ملف (`--config`، يتطلب `--image`)؛
2. يحلل قسمي `[Interface]` + `[Peer]` إلى `config/server.env` +
   `config/peers.db` — عند مصادفة مفاتيح لا يفهمها **يرفض** (ويسردها) بدلاً
   من إسقاطها بصمت؛
3. يصيّر `awg0.conf` / `dnsmasq.conf` / `start.sh` ويشغل المكدس؛
4. مع `--container`: **يوقف** الحاوية القديمة (لا يحذفها أبداً) ويشغل `doctor`؛
   عند الفشل يتراجع تلقائياً — تعود الحاوية القديمة للعمل ولا يُحذف شيء.

قواعد الأمان:

- الحاوية القديمة تُوقف فقط وتبقى على المضيف كخطة تراجع:
  `docker stop amnezia-mesh-awg amnezia-mesh-dns && docker start <القديمة>`
- يتوقف adopt عند مفاتيح `[Interface]` مجهولة، أو `Address` للخادم ليس أول
  مضيف في الشبكة الفرعية، أو أقران بلا `PublicKey`/`PresharedKey`؛
- أسماء الأقران تؤخذ من تعليقات `# name (added …)`؛ الأقران بلا اسم تحصل
  على اسم مولّد `peer-xxxxxx`، والتصادمات تحصل على لاحقة `-2`.

## التصميم: لماذا لا تهم تحديثات إصدارات AmneziaWG

1. **صورة AWG مجرد اعتمادية.** يشير `docker-compose.yml` إلى
   `amneziavpn/amneziawg-go` (يُعاد تعريفه عبر `--image` أو `AWG_MESH_IMAGE`).
   لا شيء مفترع أو مرقع؛ تبديل وسم الصورة لا يحتاج أي تغيير في المشروع.
2. **كل المنطق يعيش على المضيف.** إعداد الخادم وإعداد dnsmasq ونقطة دخول
   الحاوية (إقلاع iptables: forwarding وMASQUERADE وMSS clamp وreject
   اختياري لـ RDP-UDP) تُولّد في `config/` وتُركّب. إعادة إنشاء الحاوية أو
   ترقيتها لا تفقد شيئاً.
3. **الواجهة هي UAPI المستقر.** معاملات `awg0.conf` (Jc/S/H و
   HeaderProtectionKey والمؤقتات) جزء من بروتوكول AWG ولا تتغير بين
   الإصدارات. المعاملات التجريبية `I1`–`I5` (CPS) تُستكشف عند `init`؛
   يُسجل الدعم ويبقى التوافق في الحالتين.
4. **ملفات التعريف هي الصيغة الأصلية للتطبيق.** ملفات `vpn://` متوافقة
   بايتياً مع ما يصدّره تطبيق Amnezia الرسمي
   (`base64url(uint32_be(len) + zlib(json, 9))` بفواصل مضغوطة — تم التحقق
   بايتياً). إصدارات التطبيق الجديدة تستمر في استيرادها.

## البنية

```
docker-compose.yml      حاوية awg + sidecar dnsmasq (netns مشترك)
bin/awg-mesh            مدخل CLI (غلاف رقيق، يعمل من الـ checkout مباشرة)
awg_mesh/               حزمة python: cli, envfile, peers, keygen, compose,
                        render, profile, doctor, adopt (قياسية فقط)
scripts/                مراقبة اختيارية (stats, watchdog, cron)
tests/                  مجموعة pytest: ملفات golden للتصيير، peers db +
                        flock، roundtrip لبرمجية profile
config/                 أسرار وحالة مولّدة — في gitignore، تبقى على المضيف
```

## كيف تعمل الشبكة (30 ثانية)

WireGuard توجيه بتشفير المفاتيح: كل حزمة تُشفر بمفتاح peer العام، و`AllowedIPs`
يربط IP الوجهة بالأقران. هاتف يعمل ping إلى `100.64.0.4` يشفر بمفتاح
**الـ hub** — لا يعرف عنوان macbook الحقيقي أبداً. يفك الـ hub التشفير،
يعيد التشفير بمفتاح macbook، ويمرر. هذا نمط hub-and-spoke (mesh موجّه) وليس
P2P: يعمل خلف أي NAT، بما فيها NAT الموبايل من فئة المشغّل حيث يكون hole
punching عديم الفائدة. `PersistentKeepalive=25` في كلا الاتجاهين يبقي
خرائط NAT حية لتبقى الأجهزة متصلة ببعضها.

## ملاحظات التحصين

- `config/` تحتوي مفاتيح خاصة — في gitignore، بالصلاحية 600، ولا تغادر
  الخادم أبداً. احتفظ بنسخة مشفرة منها إن أعدت بناء VPS.
- أبقِ جدار حماية VPS على default-deny؛ اسمح فقط بـ SSH ومنفذ UDP الذي
  اخترته (‏443/udp يمتزج أفضل مع ترافيك HTTPS/QUIC العادي).
- التعمية تهزم **بصمات** DPI، لا تحليل حجم الترافيك. وليست بديلاً عن Tor
  أمام خصم سلبي شامل.
- `--rdp-reject` يساعد RDP عبر النفق (يفرض تراجع TCP فوري لقناة الرسومات
  UDP). فعّله في `init` إذا كنت تستخدم RDP عبر الشبكة.

## استكشاف الأخطاء

| العَرَض | ما يُفحص |
|---|---|
| الجهاز لا يتصل | `awg-mesh doctor`؛ جدار حماية VPS يسمح بمنفذ UDP |
| «connecting» طويل ثم «connected» لكن بلا إنترنت | في الغالب ملف تعريف خاطئ/قديم على الجهاز: تحقق من الملف النشط في التطبيق واحذف القديمة والتجريبية |
| النطاقات لا تُحل على الجهاز | فحص magicdns في `doctor`؛ DNS في ملف تعريف الجهاز يجب أن يكون الـ hub (ملفات التعريف المولّدة كذلك) |
| إنتاجية منخفضة | MTU قدره 1280 مقصود (هامش للـ padding)؛ افحص steal/CPU على خطط VPS الصغيرة |
| `Protocol not supported` من CLI ‏`awg` | سلوك معروف في amneziawg-tools عند الاستعلام بمفتاح واحد؛ استخدم `awg show` الكامل — مجرد مظهر |

## الاختبارات

```sh
python3 -m venv .venv && .venv/bin/pip install pytest
.venv/bin/python -m pytest tests/ -q
```

لا تحتاج المجموعة إلى Docker ولا شبكة: يُقارن تصيير إعداد الخادم بايتياً مع
ملفات golden أنتجتها التنفيذ الأول، وتُضرب قاعدة peers db بكتاب متزامنين
لإثبات تسلسل `flock`، وتُختبر برمجية `vpn://` باختبارات roundtrip.

## الترخيص

MIT
