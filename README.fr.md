[English](README.md) | [Русский](README.ru.md) | [中文](README.zh-CN.md) | [Español](README.es.md) | [فارسی](README.fa.md) | [العربية](README.ar.md) | [Português](README.pt-BR.md) | [日本語](README.ja.md) | [Deutsch](README.de.md) | [한국어](README.ko.md) | **Français** | [हिन्दी](README.hi.md) | [Bahasa Indonesia](README.id.md) | [Українська](README.uk.md)

_Traduction du README anglais ; elle peut être en retard sur l'original._

# amnezia-mesh

Mesh WireGuard auto-hébergé avec obfuscation du trafic AmneziaWG, MagicDNS et
profils exit/mesh façon Tailscale — sur un seul VPS, en ~10 minutes, sans
autre dépendance que Docker.

Imaginez « votre propre Tailscale », mais où chaque saut vous appartient : un
petit serveur, l'application officielle Amnezia sur vos appareils, et aucun
serveur de coordination, aucun compte, aucun relais tiers.

## Fonctionnalités

- **Réseau mesh CGNAT** (`100.64.0.0/24`, RFC 6598) — chaque appareil reçoit une
  IP stable ; SSH/ping entre appareils passe par le hub, comme `tailscale ssh`.
- **Obfuscation AmneziaWG 3.1** — handshakes avec paquets junk, substitution
  des types d'en-têtes, clé de protection d'en-tête, padding/trailers
  aléatoires. Les paramètres sont **randomisés à chaque déploiement**, donc les
  empreintes DPI diffèrent entre les installations.
- **MagicDNS** — dnsmasq sur le hub répond à `<appareil>.<domaine>` (p. ex.
  `laptop.awg`) et transfère le reste à votre résolveur upstream via le tunnel.
- **Profils exit + mesh par appareil** — `exit` route tout le trafic via le VPS
  (contournement de la censure) ; `mesh` ne route que le sous-réseau CGNAT et
  laisse l'internet direct. Les deux sont générés pour chaque appareil.
- **Profils natifs de l'app Amnezia** (`vpn://`) plus un `.conf` simple pour
  tout client compatible awg/wg.
- **Agnostique des versions par design** — l'image AWG est une dépendance
  externe remplaçable ; toute la logique vit sur l'hôte (voir *Design*).
- **CLI conviviale pour les agents** — chaque commande a une sortie `--json`,
  des overrides par variables d'environnement et un mode non interactif.

## Prérequis

- Un VPS avec IP publique, Docker avec le plugin compose et `python3`
  (>= 3.8, bibliothèque standard uniquement — pas de `pip install`).
- Un port UDP ouvert dans le pare-feu du VPS (443/udp recommandé — il se fond
  dans le trafic HTTPS/QUIC normal et c'est le plus dur à shaper pour les FAI).

## Installation avec un agent IA (Claude Code, Kimi Code, Cursor, …)

Le CLI embarque sa propre skill d'opérateur — un runbook compact couvrant
l'installation, le protocole d'automatisation, la sémantique des redémarrages
et un arbre de décision pour le diagnostic. Donnez-la à votre agent et tout le
flux devient conversationnel :

```sh
# cask macOS : awg-mesh (CLI) et awg-mesh-tui. Linux : voir Releases.
brew tap alexpozdnyakof/tap
brew install --cask alexpozdnyakof/tap/awg-mesh
# ou : git clone de ce dépôt

awg-mesh-tui install --ssh root@VOTRE_VPS --json
awg-mesh skill --install   # ~/.agents/skills/awg-mesh/SKILL.md
```

Ensuite demandez simplement, p. ex. *« monte mon VPN sur ce VPS (IP
203.0.113.7), ajoute mon portable et mon téléphone, puis lance les
auto-tests »*. L'agent exécute `awg-mesh init` / `peer add` / `doctor --json`,
importe les profils générés sur vos appareils et diagnostique la connectivité
avec l'arbre de décision de la skill. `AGENTS.md` à la racine du dépôt fait la même orientation pour les agents travaillant dans un checkout.

## Démarrage rapide (humain)

```sh
git clone https://github.com/<you>/amnezia-mesh && cd amnezia-mesh

./bin/awg-mesh init --host VOTRE_IP_OU_DOMAINE --port 443
./bin/awg-mesh peer add laptop
# → imprime : config/peers/laptop-exit.vpn, laptop-mesh.vpn, plus les variantes .conf
# importez le lien .vpn dans l'app Amnezia sur l'appareil

./bin/awg-mesh peer add phone
./bin/awg-mesh doctor      # auto-tests après installation
./bin/awg-mesh monitoring install   # optionnel : stats cron + watchdog
```

Sur l'appareil : app Amnezia → importer le lien `vpn://` → connecter. Les
appareils se joignent désormais par IP (`100.64.0.x`) ou par nom
(`phone.awg`).

## Démarrage rapide (agent / automatisation)

```sh
export AWG_MESH_NONINTERACTIVE=1
./bin/awg-mesh --json init --host 198.51.100.10 --port 443
./bin/awg-mesh --json peer add laptop
./bin/awg-mesh --json doctor        # code de sortie 0 = tous les checks verts
```

La sortie est un unique objet JSON par commande ; en cas d'échec le code de
sortie est non nul et `{"ok": false, "error": "..."}`.

## Commandes

| Commande | Description |
|---|---|
| `awg-mesh init [--host H] [--port P] [--subnet CIDR] [--image IMG] [--domain D] [--rdp-reject]` | Génère les clés + l'obfuscation aléatoire, rend les configs, démarre les conteneurs |
| `awg-mesh peer add <name> [--type exit\|mesh\|both]` | Nouvel appareil : clés, IP, profils (application en direct via `awg set` + SIGHUP dnsmasq — sans redémarrage ; les pairs existants gardent leurs sessions) |
| `awg-mesh peer list` | Appareils, IP, dates de création |
| `awg-mesh peer rename <name> <new-name> [pairs...]` | Renommer un ou plusieurs appareils — passez plusieurs paires ancien/nouveau pour balayer en une fois les noms `peer-xxxx` générés après un adopt (les noms MagicDNS suivent ; SIGHUP dnsmasq seulement — sans redémarrage ; validation all-or-nothing, échanges supportés) |
| `awg-mesh peer rotate <name>` | Réémettre les clés d'un appareil (même IP ; le hub redémarre comme pour revoke — l'appareil doit réimporter son profil, l'ancien lien `vpn://` meurt) |
| `awg-mesh peer revoke <name>` | Supprimer un appareil (les conteneurs awg + dns redémarrent — retirer des pairs du démon userspace via UAPI peut bloquer silencieusement les handshakes frais ; profils supprimés) |
| `awg-mesh doctor [--json]` | Docker, conteneurs, port d'écoute, ip_forward, MagicDNS, publication de ports |
| `awg-mesh dns add <name> <ipv4>` / `dns remove <name>` / `dns list` | Enregistrements MagicDNS personnalisés au-dessus de `<name>.<domaine>` (`nas.awg` → n'importe quelle IPv4) dans `config/custom.hosts` — un deuxième `--addn-hosts` pour dnsmasq, rechargé par SIGHUP, sans redémarrage |
| `awg-mesh monitoring install\|uninstall` | Stats cron (`/var/log/amnezia-mesh-stats.log`) + watchdog |
| `awg-mesh adopt (--container C \| --config F --image IMG) --host H [--port P] [--dns1 D] [--dns2 D] [--rdp-reject]` | Migrer un serveur AmneziaWG existant sous gestion awg-mesh (voir ci-dessous) |

## Mode distant (gérez le serveur depuis votre Mac)

```sh
awg-mesh --server my-vps peer list --json   # ou : export AWG_MESH_SSH=my-vps
```

Le CLI local exécute `ssh my-vps 'cd ~ && awg-mesh <args>'` avec le client ssh
du système (alias et clés de `~/.ssh/config`) et laisse passer
stdout/stderr/codes de sortie — aucune logique n'est dupliquée localement.
Après une commande mutante (`init`, `adopt`, `peer add|rename|revoke|rotate`),
le `config/peers/` distant est renvoyé en miroir via scp, donc les profils
`.vpn` atterrissent à côté de votre checkout local. `AWG_MESH_REMOTE_ROOT`
définit la racine du mesh sur le serveur (défaut `~`). `skill` et `--version`
tournent toujours localement.

## Adopter un serveur existant

Vous faites déjà tourner AmneziaWG (un conteneur ou un déploiement maison) et
vous voulez la gestion `awg-mesh` — pairs, MagicDNS, doctor, monitoring —
**sans réémettre un seul profil client**.

```sh
./bin/awg-mesh adopt --container amnezia-awg --host VOTRE_IP --port 443
# ou, depuis un fichier de config sur l'hôte :
./bin/awg-mesh adopt --config /root/awg0.conf --image amneziavpn/amneziawg-go:latest \
    --host VOTRE_IP --port 443
```

Ce qui est repris **à l'identique** (pour que les clients ne remarquent rien) :

| | après adopt |
|---|---|
| clé privée du serveur | la même — les clients voient le même serveur |
| profil d'obfuscation (Jc/Jmin/Jmax/S/H, HeaderProtectionKey, timers) | le même — l'empreinte DPI ne change pas |
| clés publiques et PSK des pairs | les mêmes |
| IP des pairs | les mêmes — prises dans le `AllowedIPs` de chaque peer |
| profils clients sur les appareils | continuent de fonctionner, sans réémission |

Ce qui change : le conteneur est recréé sous le projet compose
`amnezia-mesh` (renommé en `amnezia-mesh-awg`, dnsmasq devient un sidecar) et
le déploiement est ensuite géré par `awg-mesh`. Les options qu'un `awg0.conf`
ne peut pas exprimer sont des flags : `--dns1/--dns2` (résolveurs upstream
pour le forwarding MagicDNS, défaut 1.1.1.1), `--rdp-reject` (règle de reject
RDP UDP/3389), `--domain` (défaut `awg`).

Étape par étape, `adopt` :

1. lit `awg0.conf` — depuis le conteneur (`--container`, l'image est détectée
   automatiquement) ou depuis un fichier (`--config`, `--image` requis) ;
2. analyse les sections `[Interface]` + `[Peer]` vers `config/server.env` +
   `config/peers.db` — face à des clés inconnues il **refuse** (en les
   listant) plutôt que de les perdre silencieusement ;
3. rend `awg0.conf` / `dnsmasq.conf` / `start.sh` et démarre la pile ;
4. avec `--container` : **arrête** l'ancien conteneur (ne le supprime jamais)
   et lance `doctor` ; en cas d'échec il annule automatiquement — l'ancien
   conteneur repart, rien n'est supprimé.

Règles de sécurité :

- l'ancien conteneur est seulement arrêté et reste sur l'hôte comme plan de
  retour arrière :
  `docker stop amnezia-mesh-awg amnezia-mesh-dns && docker start <ancien>`
- adopt s'interrompt sur des clés `[Interface]` inconnues, un `Address` serveur
  qui n'est pas le premier hôte du sous-réseau, ou des pairs sans
  `PublicKey`/`PresharedKey` ;
- les noms de pairs viennent des commentaires `# nom (added …)` ; les pairs sans
  nom reçoivent un nom généré `peer-xxxxxx`, et les collisions un suffixe `-2`.

## Design : pourquoi les mises à jour d'AmneziaWG n'ont pas d'importance

1. **L'image AWG est une dépendance comme une autre.** `docker-compose.yml`
   référence `amneziavpn/amneziawg-go` (surchargeable via `--image` ou
   `AWG_MESH_IMAGE`). Rien n'est forké ni patché ; changer le tag de l'image ne
   demande aucune modification du projet.
2. **Toute la logique vit sur l'hôte.** La config serveur, la config dnsmasq et
   le point d'entrée du conteneur (amorçage iptables : forwarding,
   MASQUERADE, MSS clamp, reject RDP-UDP optionnel) sont générés dans `config/`
   et montés. Recréer ou mettre à jour le conteneur ne perd rien.
3. **L'interface est l'UAPI stable.** Les paramètres de `awg0.conf` (Jc/S/H,
   HeaderProtectionKey, timers) font partie du protocole AWG et ne changent
   pas entre releases. Les paramètres expérimentaux `I1`–`I5` (CPS) sont
   sondés au `init` ; le support est enregistré et la compatibilité est
   maintenue dans les deux cas.
4. **Les profils sont le format natif de l'app.** Les profils `vpn://` sont
   compatibles au byte près avec ce que l'app officielle Amnezia exporte
   (`base64url(uint32_be(len) + zlib(json, 9))`, séparateurs compacts — vérifié
   byte à byte). Les nouvelles versions de l'app continuent de les importer.

## Arborescence

```
docker-compose.yml      conteneur awg + sidecar dnsmasq (netns partagé)
bin/awg-mesh            entrée du CLI (shim fin, tourne depuis le checkout)
awg_mesh/               paquet python : cli, envfile, peers, keygen, compose,
                        render, profile, doctor, adopt (stdlib uniquement)
scripts/                monitoring optionnel (stats, watchdog, cron)
tests/                  suite pytest : golden files du rendu, peers db +
                        flock, roundtrip du codec profile
config/                 secrets et état générés — dans le gitignore, reste sur l'hôte
```

## Comment le mesh fonctionne (30 secondes)

WireGuard, c'est du routage par clés cryptographiques : chaque paquet est
chiffré avec la clé publique du pair, et `AllowedIPs` associe les IP de
destination aux pairs. Un téléphone qui ping `100.64.0.4` chiffre avec la clé
du **hub** — il n'apprend jamais l'adresse réelle du macbook. Le hub déchiffre,
rechiffre avec la clé du macbook et transmet. C'est du hub-and-spoke (mesh
routé), pas du P2P : ça fonctionne derrière n'importe quel NAT, y compris les
NAT mobiles de grade opérateur où le hole punching est inutile.
`PersistentKeepalive=25` des deux côtés garde les mappings NAT actifs pour que
les appareils restent mutuellement joignables.

## Notes de durcissement

- `config/` contient des clés privées — elle est dans le gitignore, en mode
  600, et ne quitte jamais le serveur. Sauvegardez-la chiffrée si vous
  reconstituez le VPS.
- Gardez le pare-feu du VPS en default-deny ; n'autorisez que SSH et le port
  UDP choisi (443/udp se fond le mieux dans le trafic HTTPS/QUIC normal).
- L'obfuscation bat les **empreintes** DPI, pas l'analyse de volume de
  trafic. Elle ne remplace pas Tor face à un adversaire passif global.
- `--rdp-reject` aide le RDP via le tunnel (force le repli TCP immédiat du
  canal graphique UDP). Activez-le dans `init` si vous utilisez RDP à travers
  le mesh.

## Dépannage

| Symptôme | Vérifier |
|---|---|
| L'appareil ne se connecte pas | `awg-mesh doctor` ; le pare-feu du VPS autorise le port UDP |
| Long « connecting », puis « connected » mais pas d'internet | Presque toujours le mauvais/vieux profil sur l'appareil : vérifiez quel profil est actif dans l'app et supprimez les anciens/tests |
| Les domaines ne se résolvent pas sur l'appareil | check magicdns du `doctor` ; le DNS du profil de l'appareil doit être le hub (les profils générés le font) |
| Débit faible | MTU 1280 est voulu (marge pour le padding) ; vérifiez steal/CPU sur les petites offres VPS |
| `Protocol not supported` du CLI `awg` | bizarrerie connue d'amneziawg-tools sur les requêtes à clé unique ; utilisez le `awg show` complet — purement cosmétique |

## Tests

```sh
python3 -m venv .venv && .venv/bin/pip install pytest
.venv/bin/python -m pytest tests/ -q
```

La suite n'a besoin ni de Docker ni de réseau : le rendu de la config serveur
est comparé byte à byte à des golden files produits par l'implémentation
d'origine, la peers db est martelée par des écrivains concurrents pour prouver
la sérialisation du `flock`, et le codec `vpn://` passe des tests de roundtrip.

## Licence

MIT
