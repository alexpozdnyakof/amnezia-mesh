[English](README.md) | [Русский](README.ru.md) | [中文](README.zh-CN.md) | **Español** | [فارسی](README.fa.md) | [العربية](README.ar.md) | [Português](README.pt-BR.md) | [日本語](README.ja.md) | [Deutsch](README.de.md) | [한국어](README.ko.md) | [Français](README.fr.md) | [हिन्दी](README.hi.md) | [Bahasa Indonesia](README.id.md) | [Українська](README.uk.md)

_Traducción del README en inglés; puede estar desactualizada respecto al original._

# amnezia-mesh

Mesh WireGuard autohospedado con ofuscación de tráfico AmneziaWG, MagicDNS y
perfiles exit/mesh al estilo Tailscale — en un solo VPS, en ~10 minutos y sin
dependencias más allá de Docker.

Piensa en «tu propio Tailscale», pero donde cada salto te pertenece: un
servidor pequeño, la app oficial de Amnezia en tus dispositivos, y sin
servidores de coordinación, sin cuentas ni relays de terceros.

## Características

- **Red mesh CGNAT** (`100.64.0.0/24`, RFC 6598) — cada dispositivo recibe una
  IP estable; SSH/ping entre dispositivos funciona a través del hub, como
  `tailscale ssh`.
- **Ofuscación AmneziaWG 3.1** — handshakes con paquetes junk, sustitución de
  tipos de cabecera, clave de protección de cabecera, padding/trailers
  aleatorios. Los parámetros se **aleatorizan en cada despliegue**, así las
  huellas DPI difieren entre instalaciones.
- **MagicDNS** — dnsmasq en el hub responde `<dispositivo>.<dominio>` (p. ej.
  `laptop.awg`) y reenvía todo lo demás a tu resolvedor upstream a través del
  túnel.
- **Perfiles exit + mesh por dispositivo** — `exit` enruta todo el tráfico por
  el VPS (elusión de censura); `mesh` enruta solo la subred CGNAT, dejando
  internet directo. Ambos se generan para cada dispositivo.
- **Perfiles nativos de la app Amnezia** (`vpn://`) más `.conf` plano para
  cualquier cliente compatible con awg/wg.
- **Diseño independiente de la versión** — la imagen AWG es una dependencia
  externa y reemplazable; toda la lógica vive en el host (ver *Diseño*).
- **CLI amigable con agentes** — cada comando tiene salida `--json`,
  overrides por variables de entorno y modo no interactivo.

## Requisitos

- Un VPS con IP pública, Docker con el plugin compose y `python3`
  (>= 3.8, solo biblioteca estándar — sin `pip install`).
- Un puerto UDP abierto en el firewall del VPS (se recomienda 443/udp — se
  confunde con tráfico HTTPS/QUIC normal y es el más difícil de moldear para
  los ISP).

## Configuración con un agente de IA (Claude Code, Kimi Code, Cursor, …)

El CLI trae su propio skill de operador — un runbook compacto que cubre la
instalación, el protocolo de automatización, la semántica de reinicios y un
árbol de decisión para diagnóstico. Dáselo a tu agente y todo el flujo se
vuelve conversacional:

```sh
# cask de macOS: awg-mesh (CLI) y awg-mesh-tui. Linux: ver Releases.
brew tap alexpozdnyakof/tap
brew install --cask alexpozdnyakof/tap/awg-mesh
# o: git clone de este repo

awg-mesh-tui install --ssh root@TU_VPS --json
awg-mesh skill --install   # ~/.agents/skills/awg-mesh/SKILL.md
```

Después simplemente pide, p. ej. *«monta mi VPN en este VPS (IP 203.0.113.7),
añade mi portátil y mi móvil, y luego ejecuta las autocomprobaciones»*. El
agente ejecuta `awg-mesh init` / `peer add` / `doctor --json`, importa los
perfiles generados en tus dispositivos y diagnostica la conectividad con el
árbol de decisión del skill. `AGENTS.md` en la raíz del repo hace la misma
orientación para agentes que trabajan dentro de un checkout.

## Inicio rápido (humano)

```sh
git clone https://github.com/<you>/amnezia-mesh && cd amnezia-mesh

./bin/awg-mesh init --host TU_IP_O_DOMINIO --port 443
./bin/awg-mesh peer add laptop
# → imprime: config/peers/laptop-exit.vpn, laptop-mesh.vpn, más variantes .conf
# importa el enlace .vpn en la app Amnezia del dispositivo

./bin/awg-mesh peer add phone
./bin/awg-mesh doctor      # autocomprobación post-instalación
./bin/awg-mesh monitoring install   # opcional: estadísticas por cron + watchdog
```

En el dispositivo: app Amnezia → importar el enlace `vpn://` → conectar. Los
dispositivos ahora se alcanzan entre sí por IP (`100.64.0.x`) o por nombre
(`phone.awg`).

## Inicio rápido (agente / automatización)

```sh
export AWG_MESH_NONINTERACTIVE=1
./bin/awg-mesh --json init --host 198.51.100.10 --port 443
./bin/awg-mesh --json peer add laptop
./bin/awg-mesh --json doctor        # código de salida 0 = todo en verde
```

La salida es un único objeto JSON por comando; los fallos ponen código de
salida distinto de cero y `{"ok": false, "error": "..."}`.

## Comandos

| Comando | Descripción |
|---|---|
| `awg-mesh init [--host H] [--port P] [--subnet CIDR] [--image IMG] [--domain D] [--rdp-reject]` | Genera claves + ofuscación aleatoria, renderiza configs, arranca contenedores |
| `awg-mesh peer add <name> [--type exit\|mesh\|both]` | Nuevo dispositivo: claves, IP, perfiles (se aplica en vivo con `awg set` + SIGHUP a dnsmasq — sin reinicio; los peers existentes conservan sus sesiones) |
| `awg-mesh peer list` | Dispositivos, IPs, fechas de creación |
| `awg-mesh peer rename <name> <new-name> [pairs...]` | Renombrar dispositivo(s) — acepta varias parejas viejo/nuevo para barrer de una vez los nombres `peer-xxxx` generados tras un adopt (los nombres MagicDNS siguen; solo SIGHUP de dnsmasq — sin reinicio; validación all-or-nothing, soporta swaps) |
| `awg-mesh peer rotate <name>` | Reemitir las claves de un dispositivo (misma IP; el hub se reinicia como en revoke — el dispositivo debe reimportar su perfil, el enlace `vpn://` viejo muere) |
| `awg-mesh peer revoke <name>` | Eliminar dispositivo (se reinician los contenedores awg + dns — quitar peers del demonio userspace vía UAPI puede atascar silenciosamente los handshakes nuevos; perfiles borrados) |
| `awg-mesh doctor [--json]` | Docker, contenedores, puerto de escucha, ip_forward, MagicDNS, publicación de puertos |
| `awg-mesh dns add <name> <ipv4>` / `dns remove <name>` / `dns list` | Registros MagicDNS propios encima de `<name>.<dominio>` (`nas.awg` → cualquier IPv4) en `config/custom.hosts` — un segundo `--addn-hosts` para dnsmasq, se recarga con SIGHUP, sin reinicio |
| `awg-mesh monitoring install\|uninstall` | Estadísticas por cron (`/var/log/amnezia-mesh-stats.log`) + watchdog |
| `awg-mesh adopt (--container C \| --config F --image IMG) --host H [--port P] [--dns1 D] [--dns2 D] [--rdp-reject]` | Migrar un servidor AmneziaWG existente bajo gestión de awg-mesh (ver abajo) |

## Modo remoto (gestiona el servidor desde tu Mac)

```sh
awg-mesh --server my-vps peer list --json   # o: export AWG_MESH_SSH=my-vps
```

El CLI local ejecuta `ssh my-vps 'cd ~ && awg-mesh <args>'` con el cliente ssh
del sistema (alias y claves de `~/.ssh/config`) y deja pasar stdout/stderr/los
códigos de salida — no se duplica lógica localmente. Tras un comando que
muta (`init`, `adopt`, `peer add|rename|revoke|rotate`) el `config/peers/`
remoto se refleja de vuelta con scp, así los perfiles `.vpn` acaban junto a tu
checkout local. `AWG_MESH_REMOTE_ROOT` fija la raíz del mesh en el servidor
(por defecto `~`). `skill` y `--version` siempre se ejecutan en local.

## Adoptar un servidor existente

Ya tienes AmneziaWG funcionando (un contenedor o un despliegue a mano) y
quieres la gestión de `awg-mesh` — gestión de peers, MagicDNS, doctor,
monitoring — **sin reemitir ni un solo perfil de cliente**.

```sh
./bin/awg-mesh adopt --container amnezia-awg --host TU_IP --port 443
# o, desde un archivo de configuración en el host:
./bin/awg-mesh adopt --config /root/awg0.conf --image amneziavpn/amneziawg-go:latest \
    --host TU_IP --port 443
```

Lo que se conserva **literalmente** (para que los clientes no noten nada):

| | tras adopt |
|---|---|
| clave privada del servidor | la misma — los clientes ven el mismo servidor |
| perfil de ofuscación (Jc/Jmin/Jmax/S/H, HeaderProtectionKey, timers) | el mismo — la huella DPI no cambia |
| claves públicas y PSK de los peers | los mismos |
| IPs de los peers | las mismas — tomadas del `AllowedIPs` de cada peer |
| perfiles de cliente en los dispositivos | siguen funcionando, sin reemisión |

Lo que cambia: el contenedor se recrea bajo el proyecto compose
`amnezia-mesh` (renombrado a `amnezia-mesh-awg`, dnsmasq pasa a ser un
sidecar) y el despliegue queda gestionado por `awg-mesh` desde entonces.
Los ajustes que un `awg0.conf` no puede expresar son flags: `--dns1/--dns2`
(resolvedores upstream para el forwarding de MagicDNS, por defecto 1.1.1.1),
`--rdp-reject` (regla de reject RDP UDP/3389), `--domain` (por defecto `awg`).

Paso a paso, `adopt`:

1. lee `awg0.conf` — desde dentro del contenedor (`--container`, la imagen se
   detecta automáticamente) o desde un archivo (`--config`, requiere `--image`);
2. analiza las secciones `[Interface]` + `[Peer]` hacia `config/server.env` +
   `config/peers.db` — ante claves que no entiende **se niega** (listándolas)
   en lugar de descartarlas en silencio;
3. renderiza `awg0.conf` / `dnsmasq.conf` / `start.sh` y arranca el stack;
4. si es `--container`: **detiene** el contenedor viejo (jamás lo elimina) y
   ejecuta `doctor`; si falla, revierte automáticamente — el contenedor viejo
   vuelve a arrancar, nada se borra.

Reglas de seguridad:

- el contenedor viejo solo se detiene y permanece en el host como plan de
  rollback: `docker stop amnezia-mesh-awg amnezia-mesh-dns && docker start <viejo>`
- adopt aborta ante claves `[Interface]` desconocidas, un `Address` de
  servidor que no sea el primer host de la subred, o peers sin
  `PublicKey`/`PresharedKey`;
- los nombres de peer salen de comentarios `# nombre (added …)`; los peers sin
  nombre reciben un nombre generado `peer-xxxxxx`, y las colisiones reciben
  sufijo `-2`.

## Diseño: por qué las actualizaciones de AmneziaWG no importan

1. **La imagen AWG es una dependencia más.** `docker-compose.yml` referencia
   `amneziavpn/amneziawg-go` (se sobreescribe con `--image` o
   `AWG_MESH_IMAGE`). Nada está forkeado ni parcheado; cambiar el tag de la
   imagen no requiere cambios en el proyecto.
2. **Toda la lógica vive en el host.** La config del servidor, la config de
   dnsmasq y el entrypoint del contenedor (bootstrap de iptables: forwarding,
   MASQUERADE, MSS clamp, reject RDP-UDP opcional) se generan en `config/` y se
   montan. Recrear o actualizar el contenedor no pierde nada.
3. **La interfaz es el UAPI estable.** Los parámetros de `awg0.conf` (Jc/S/H,
   HeaderProtectionKey, timers) son parte del protocolo AWG y no cambian entre
   releases. Los parámetros experimentales `I1`–`I5` (CPS) se prueban en
   `init`; el proyecto registra el soporte y se mantiene compatible en ambos
   casos.
4. **Los perfiles son el formato nativo de la app.** Los perfiles `vpn://`
   son byte-compatibles con lo que exporta la app oficial de Amnezia
   (`base64url(uint32_be(len) + zlib(json, 9))`, separadores compactos —
   verificado byte a byte). Los nuevos releases de la app siguen
   importándolos.

## Estructura

```
docker-compose.yml      contenedor awg + sidecar dnsmasq (netns compartido)
bin/awg-mesh            entrada del CLI (shim fino, corre desde el checkout)
awg_mesh/               paquete python: cli, envfile, peers, keygen, compose,
                        render, profile, doctor, adopt (solo stdlib)
scripts/                monitoring opcional (stats, watchdog, cron)
tests/                  suite pytest: golden files del render, peers db +
                        flock, roundtrip del códec profile
config/                 secretos y estado generados — en gitignore, vive en
                        el host
```

## Cómo funciona la malla (30 segundos)

WireGuard es enrutado por criptoclaves: cada paquete se cifra con la clave
pública del peer, y `AllowedIPs` mapea IPs destino a peers. Un teléfono que
hace ping a `100.64.0.4` cifra con la clave del **hub** — nunca conoce la
dirección real del macbook. El hub descifra, recifra con la clave del macbook
y reenvía. Esto es hub-and-spoke (malla enrutada), no P2P: funciona detrás de
cualquier NAT, incluidos los NAT móviles de grado operador donde el hole
punching es inútil. `PersistentKeepalive=25` en ambos extremos mantiene vivos
los mapeos NAT para que los dispositivos sean mutuamente alcanzables.

## Notas de endurecimiento

- `config/` contiene claves privadas — está en gitignore, con modo 600, y
  nunca sale del servidor. Haz copia de seguridad cifrada si rehaces el VPS.
- Mantén el firewall del VPS en default-deny; permite solo SSH y tu puerto UDP
  elegido (443/udp se mezcla mejor con el tráfico HTTPS/QUIC normal).
- La ofuscación vence **huellas** DPI, no el análisis de volumen de tráfico.
  No sustituye a Tor frente a un adversario pasivo global.
- `--rdp-reject` ayuda al RDP a través del túnel (fuerza el fallback TCP
  instantáneo del canal gráfico UDP). Actívalo en `init` si usas RDP por la
  malla.

## Resolución de problemas

| Síntoma | Comprobar |
|---|---|
| El dispositivo no conecta | `awg-mesh doctor`; el firewall del VPS permite el puerto UDP |
| Largo «connecting», luego «connected» pero sin internet | Casi siempre el perfil equivocado/anticuado en el dispositivo: revisa qué perfil está activo en la app y borra los viejos/de prueba |
| Los dominios no resuelven en el dispositivo | chequeo magicdns de `doctor`; el perfil del dispositivo debe usar el DNS del hub (los perfiles generados lo hacen) |
| Throughput bajo | MTU 1280 es a propósito (margen para padding); revisa steal/CPU en planes VPS pequeños |
| `Protocol not supported` desde el CLI `awg` | peculiaridad conocida de amneziawg-tools en consultas de clave única; usa `awg show` completo — solo cosmético |

## Tests

```sh
python3 -m venv .venv && .venv/bin/pip install pytest
.venv/bin/python -m pytest tests/ -q
```

La suite no necesita Docker ni red: el render de la config del servidor se
compara byte a byte contra golden files producidos por la implementación
original, la peers db se martillea con escritores concurrentes para probar la
serialización de `flock`, y el códec `vpn://` pasa pruebas de roundtrip.

## Licencia

MIT
