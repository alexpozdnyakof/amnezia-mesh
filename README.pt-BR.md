[English](README.md) | [Русский](README.ru.md) | [中文](README.zh-CN.md) | [Español](README.es.md) | [فارسی](README.fa.md) | [العربية](README.ar.md) | **Português** | [日本語](README.ja.md) | [Deutsch](README.de.md)

_Tradução do README em inglês; pode estar desatualizada em relação ao original._

# amnezia-mesh

Mesh WireGuard auto-hospedado com ofuscação de tráfego AmneziaWG, MagicDNS e
perfis exit/mesh no estilo Tailscale — em um único VPS, em ~10 minutos, sem
dependências além do Docker.

Pense em «seu próprio Tailscale», mas onde cada salto é seu: um servidor
pequeno, o app oficial da Amnezia nos seus dispositivos, e sem servidores de
coordenação, contas ou relays de terceiros.

## Recursos

- **Rede mesh CGNAT** (`100.64.0.0/24`, RFC 6598) — cada dispositivo recebe um
  IP estável; SSH/ping entre dispositivos funciona através do hub, como
  `tailscale ssh`.
- **Ofuscação AmneziaWG 3.1** — handshakes com pacotes junk, substituição de
  tipos de cabeçalho, chave de proteção de cabeçalho, padding/trailers
  aleatórios. Os parâmetros são **randomizados a cada instalação**, então as
  impressões DPI diferem entre instalações.
- **MagicDNS** — dnsmasq no hub responde `<dispositivo>.<domínio>` (ex.:
  `laptop.awg`) e encaminha todo o restante ao seu resolvedor upstream pelo
  túnel.
- **Perfis exit + mesh por dispositivo** — `exit` roteia todo o tráfego pelo
  VPS (elusão de censura); `mesh` roteia apenas a subrede CGNAT, deixando a
  internet direta. Ambos são gerados para cada dispositivo.
- **Perfis nativos do app Amnezia** (`vpn://`) mais `.conf` simples para
  qualquer cliente compatível com awg/wg.
- **Agnóstico a versões por design** — a imagem AWG é uma dependência externa
  substituível; toda a lógica vive no host (veja *Design*).
- **CLI amigável a agentes** — todo comando tem saída `--json`, overrides por
  variáveis de ambiente e modo não interativo.

## Requisitos

- Um VPS com IP público, Docker com o plugin compose e `python3`
  (>= 3.8, somente biblioteca padrão — sem `pip install`).
- Uma porta UDP aberta no firewall do VPS (recomenda-se 443/udp — ela se mistura
  ao tráfego HTTPS/QUIC normal e é a mais difícil de ser moldada pelos ISPs).

## Início rápido (humano)

```sh
git clone https://github.com/<you>/amnezia-mesh && cd amnezia-mesh

./bin/awg-mesh init --host SEU_IP_OU_DOMINIO --port 443
./bin/awg-mesh peer add laptop
# → imprime: config/peers/laptop-exit.vpn, laptop-mesh.vpn, além das variantes .conf
# importe o link .vpn no app Amnezia do dispositivo

./bin/awg-mesh peer add phone
./bin/awg-mesh doctor      # autoverificação pós-instalação
./bin/awg-mesh monitoring install   # opcional: estatísticas via cron + watchdog
```

No dispositivo: app Amnezia → importar o link `vpn://` → conectar. Os
dispositivos passam a se alcançar por IP (`100.64.0.x`) ou por nome
(`phone.awg`).

## Início rápido (agente / automação)

```sh
export AWG_MESH_NONINTERACTIVE=1
./bin/awg-mesh --json init --host 198.51.100.10 --port 443
./bin/awg-mesh --json peer add laptop
./bin/awg-mesh --json doctor        # código de saída 0 = todos os checks verdes
```

A saída é um único objeto JSON por comando; em caso de falha o código de saída é
não zero e `{"ok": false, "error": "..."}`.

## Comandos

| Comando | Descrição |
|---|---|
| `awg-mesh init [--host H] [--port P] [--subnet CIDR] [--image IMG] [--domain D] [--rdp-reject]` | Gera chaves + ofuscação aleatória, renderiza configs, sobe os contêineres |
| `awg-mesh peer add <name> [--type exit\|mesh\|both]` | Novo dispositivo: chaves, IP, perfis (aplicado via `awg syncconf`, depois o contêiner awg é reiniciado — o syncconf sozinho pode inutilizar silenciosamente handshakes novos no daemon userspace) |
| `awg-mesh peer list` | Dispositivos, IPs, datas de criação |
| `awg-mesh peer rename <name> <new-name>` | Renomear um dispositivo (o registro MagicDNS `<name>.<domain>` segue o nome) |
| `awg-mesh peer revoke <name>` | Remover dispositivo (config aplicada, perfis apagados) |
| `awg-mesh doctor [--json]` | Docker, contêineres, porta de escuta, ip_forward, MagicDNS, publicação de portas |
| `awg-mesh monitoring install\|uninstall` | Estatísticas via cron (`/var/log/amnezia-mesh-stats.log`) + watchdog |
| `awg-mesh adopt (--container C \| --config F --image IMG) --host H [--port P] [--dns1 D] [--dns2 D] [--rdp-reject]` | Migrar um servidor AmneziaWG existente para gestão do awg-mesh (veja abaixo) |

## Adotar um servidor existente

Você já roda AmneziaWG (um contêiner ou um deploy manual) e quer a gestão do
`awg-mesh` — gestão de peers, MagicDNS, doctor, monitoramento — **sem reemitir
um único perfil de cliente**.

```sh
./bin/awg-mesh adopt --container amnezia-awg --host SEU_IP --port 443
# ou, a partir de um arquivo de config no host:
./bin/awg-mesh adopt --config /root/awg0.conf --image amneziavpn/amneziawg-go:latest \
    --host SEU_IP --port 443
```

O que é transferido **literalmente** (para que os clientes não percebam nada):

| | após o adopt |
|---|---|
| chave privada do servidor | a mesma — os clientes veem o mesmo servidor |
| perfil de ofuscação (Jc/Jmin/Jmax/S/H, HeaderProtectionKey, timers) | o mesmo — a impressão DPI não muda |
| chaves públicas e PSKs dos peers | os mesmos |
| IPs dos peers | os mesmos — tirados do `AllowedIPs` de cada peer |
| perfis de cliente nos dispositivos | continuam funcionando, sem reemissão |

O que muda: o contêiner é recriado sob o projeto compose `amnezia-mesh`
(renomeado para `amnezia-mesh-awg`, o dnsmasq vira um sidecar) e o deploy passa
a ser gerido pelo `awg-mesh` daí em diante. Ajustes que um `awg0.conf` não
consegue expressar são flags: `--dns1/--dns2` (resolvedores upstream para o
encaminhamento do MagicDNS, padrão 1.1.1.1), `--rdp-reject` (regra de reject
para RDP UDP/3389), `--domain` (padrão `awg`).

Passo a passo, o `adopt`:

1. lê o `awg0.conf` — de dentro do contêiner (`--container`, a imagem é
   detectada automaticamente) ou de um arquivo (`--config`, exige `--image`);
2. analisa as seções `[Interface]` + `[Peer]` para `config/server.env` +
   `config/peers.db` — diante de chaves que não entende **recusa** (listando-as)
   em vez de descartá-las silenciosamente;
3. renderiza `awg0.conf` / `dnsmasq.conf` / `start.sh` e sobe o stack;
4. com `--container`: **para** o contêiner antigo (jamais o remove) e roda o
   `doctor`; em caso de falha reverte automaticamente — o contêiner antigo
   volta a rodar e nada é apagado.

Regras de segurança:

- o contêiner antigo é apenas parado e permanece no host como plano de
  rollback: `docker stop amnezia-mesh-awg amnezia-mesh-dns && docker start <antigo>`
- o adopt aborta diante de chaves `[Interface]` desconhecidas, um `Address` de
  servidor que não seja o primeiro host da subrede, ou peers sem
  `PublicKey`/`PresharedKey`;
- os nomes de peer vêm dos comentários `# nome (added …)`; peers sem nome
  recebem um nome gerado `peer-xxxxxx`, e colisões ganham sufixo `-2`.

## Design: por que atualizações da versão do AmneziaWG não importam

1. **A imagem AWG é uma dependência qualquer.** O `docker-compose.yml`
   referencia `amneziavpn/amneziawg-go` (sobrescreva com `--image` ou
   `AWG_MESH_IMAGE`). Nada é forkado ou patchado; trocar a tag da imagem não
   exige mudanças no projeto.
2. **Toda a lógica vive no host.** A config do servidor, a config do dnsmasq e
   o entrypoint do contêiner (bootstrap de iptables: forwarding, MASQUERADE,
   MSS clamp, reject RDP-UDP opcional) são gerados em `config/` e montados.
   Recriar ou atualizar o contêiner não perde nada.
3. **A interface é o UAPI estável.** Os parâmetros do `awg0.conf` (Jc/S/H,
   HeaderProtectionKey, timers) fazem parte do protocolo AWG e não mudam entre
   releases. Os parâmetros experimentais `I1`–`I5` (CPS) são sondados no
   `init`; o suporte é registrado e a compatibilidade se mantém de qualquer
   forma.
4. **Os perfis são o formato nativo do app.** Os perfis `vpn://` são
   byte-compatíveis com o que o app oficial da Amnezia exporta
   (`base64url(uint32_be(len) + zlib(json, 9))`, separadores compactos —
   verificado byte a byte). Novos releases do app continuam importando-os.

## Estrutura

```
docker-compose.yml      contêiner awg + sidecar dnsmasq (netns compartilhado)
bin/awg-mesh            entrada do CLI (shim fino, roda do checkout)
awg_mesh/               pacote python: cli, envfile, peers, keygen, compose,
                        render, profile, doctor, adopt (só stdlib)
scripts/                monitoramento opcional (stats, watchdog, cron)
tests/                  suíte pytest: golden files do render, peers db +
                        flock, roundtrip do codec profile
config/                 segredos e estado gerados — no gitignore, fica no host
```

## Como a malha funciona (30 segundos)

WireGuard é roteamento por criptochaves: cada pacote é cifrado com a chave
pública do peer, e o `AllowedIPs` mapeia IPs destino a peers. Um telefone
pingando `100.64.0.4` cifra com a chave do **hub** — nunca aprende o endereço
real do macbook. O hub decifra, recifra com a chave do macbook e encaminha.
Isso é hub-and-spoke (malha roteada), não P2P: funciona atrás de qualquer NAT,
incluindo NATs móveis de grau operador onde hole punching é inútil.
`PersistentKeepalive=25` nos dois lados mantém os mapeamentos NAT vivos para
que os dispositivos se alcancem mutuamente.

## Notas de endurecimento

- `config/` contém chaves privadas — está no gitignore, com modo 600, e nunca
  sai do servidor. Faça backup cifrado se for reinstalar o VPS.
- Mantenha o firewall do VPS em default-deny; libere apenas SSH e sua porta UDP
  escolhida (443/udp se mistura melhor ao tráfego HTTPS/QUIC normal).
- A ofuscação derrota **impressões** DPI, não análise de volume de tráfego. Não
  substitui o Tor diante de um adversário passivo global.
- `--rdp-reject` ajuda o RDP pelo túnel (força o fallback TCP imediato do canal
  gráfico UDP). Ative-o no `init` se usa RDP pela malha.

## Solução de problemas

| Sintoma | Verificar |
|---|---|
| Dispositivo não conecta | `awg-mesh doctor`; firewall do VPS libera a porta UDP |
| «connecting» longo, depois «connected» mas sem internet | Quase sempre o perfil errado/velho no dispositivo: confira qual perfil está ativo no app e apague os antigos/de teste |
| Domínios não resolvem no dispositivo | check magicdns do `doctor`; o DNS do perfil do dispositivo deve ser o hub (os perfis gerados já são assim) |
| Vazão baixa | MTU 1280 é de propósito (folga para padding); verifique steal/CPU em planos VPS pequenos |
| `Protocol not supported` do CLI `awg` | peculiaridade conhecida do amneziawg-tools em consultas de chave única; use o `awg show` completo — só cosmético |

## Testes

```sh
python3 -m venv .venv && .venv/bin/pip install pytest
.venv/bin/python -m pytest tests/ -q
```

A suíte não precisa de Docker nem de rede: a renderização da config do servidor
é comparada byte a byte com golden files produzidos pela implementação
original, a peers db é martelada por escritores concorrentes para provar a
serialização do `flock`, e o codec `vpn://` passa por testes de roundtrip.

## Licença

MIT
