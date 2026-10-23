"""Docker-based key generation and image probing.

The host only needs Docker — keys are produced by the same AWG image the
server runs, so formats always match. --entrypoint is load-bearing: images
built with their own entrypoint (e.g. the Amnezia app's container) would
run it and hang instead of generating keys.
"""
import base64
import os
import random
import subprocess

from . import MeshError

# Probe for I1-I5 (CPS) support: bring up a throwaway interface whose config
# contains an I1 line. Success means the parser accepts it. Never fatal —
# init records the result in server.env.
PROBE_SCRIPT = r"""
command -v awg-quick >/dev/null 2>&1 || { echo NO_AWGQUICK; exit 0; }
d=$(mktemp -d)
priv=$(awg genkey)
printf "[Interface]\nPrivateKey = %s\nAddress = 10.213.0.1/30\nListenPort = 23199\nI1 = 30-50\n[Peer]\nPublicKey = %s\nAllowedIPs = 10.213.0.2/32\n" "$priv" "$priv" > "$d/p.conf"
if awg-quick up "$d/p.conf" >/dev/null 2>&1; then
  awg-quick down "$d/p.conf" >/dev/null 2>&1
  echo SUPPORTED
else
  echo UNSUPPORTED
fi
rm -rf "$d"
"""


def _docker(*args, input_text=None):
    return subprocess.run(["docker", *args], input=input_text, text=True,
                          capture_output=True)


def gen_keypair(image):
    """Returns (private, public). Keys come from `awg` inside the image."""
    priv = _docker("run", "--rm", "--network", "none", "--entrypoint", "awg",
                   image, "genkey")
    if priv.returncode != 0:
        raise MeshError(f"awg genkey failed (image: {image}): {priv.stderr.strip()}")
    pub = _docker("run", "--rm", "--network", "none", "--entrypoint", "awg",
                  "-i", image, "pubkey", input_text=priv.stdout.strip())
    if pub.returncode != 0:
        raise MeshError(f"awg pubkey failed (image: {image}): {pub.stderr.strip()}")
    return priv.stdout.strip(), pub.stdout.strip()


def gen_psk(image):
    psk = _docker("run", "--rm", "--network", "none", "--entrypoint", "awg",
                  image, "genpsk")
    if psk.returncode != 0:
        raise MeshError(f"awg genpsk failed (image: {image}): {psk.stderr.strip()}")
    return psk.stdout.strip()


def pub_from_priv(image, priv):
    """Derive a public key from an existing private key (used by adopt)."""
    pub = _docker("run", "--rm", "--network", "none", "--entrypoint", "awg",
                  "-i", image, "pubkey", input_text=priv.strip())
    if pub.returncode != 0:
        raise MeshError(f"awg pubkey failed (image: {image}): {pub.stderr.strip()}")
    return pub.stdout.strip()


def probe_i_support(image):
    """-> SUPPORTED | UNSUPPORTED | NO_AWGQUICK."""
    r = _docker("run", "--rm", "--network", "none",
                "--device", "/dev/net/tun:/dev/net/tun",
                "--entrypoint", "sh", image, "-c", PROBE_SCRIPT)
    out = r.stdout.strip()
    return out if out in ("SUPPORTED", "UNSUPPORTED", "NO_AWGQUICK") else "UNSUPPORTED"


def gen_obfuscation():
    """Randomized per-deployment obfuscation profile (AmneziaWG junk-packet
    handshake parameters) — same ranges as the original implementation, so
    DPI fingerprints differ between installs. Returns KEY=VALUE lines."""
    r = random.SystemRandom()
    jmin = r.randint(10, 20)
    lines = [
        f"OBF_JC={r.randint(3, 7)}",
        f"OBF_JMIN={jmin}",
        f"OBF_JMAX={r.randint(jmin + 30, jmin + 50)}",
    ]
    lines += [f"OBF_S{i}={v}" for i, v in enumerate(r.sample(range(30, 220), 4), 1)]
    lines += [f"OBF_H{i}={v}" for i, v in enumerate(r.sample(range(1, 2**32), 4), 1)]
    lines.append(
        f"OBF_HEADERPROTECTIONKEY={base64.b64encode(os.urandom(32)).decode()}")
    lines += [
        "OBF_CONTENTPADDINGADDITION=2-10",
        "OBF_REKEYAFTERTIME=120-180",
        "OBF_REKEYTIMEOUT=5-10",
        "OBF_REJECTAFTERTIME=540-600",
        "OBF_KEEPALIVETIMEOUT=8-12",
        "OBF_MAXHANDSHAKEATTEMPTS=80-100",
        "OBF_RANDOMTRAILERS=on",
        "OBF_DISABLECOOKIES=on",
    ]
    return lines
