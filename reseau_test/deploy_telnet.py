import telnetlib
import time
import os

HOST = "localhost"

ROUTER_TELNET_PORTS = {
    "R1": 5001,
    "R2": 5002,
    "R3": 5003,
    "R4": 5004
}

CONFIG_DIR = "configs_gen" #chaanger selon l'adresse des configs générées


def clean_lines_for_cli(cfg_text):
    """
    Nettoyage : on enlève les lignes inutiles, et on évite les doublons
    """
    lines = []
    for raw in cfg_text.splitlines():
        line = raw.rstrip()

        # skip commentaires vides
        if line.strip() == "":
            continue

        # skip markers inutiles
        if line.strip().startswith("!"):
            continue

        # skip boot markers & autres
        if "boot-start-marker" in line or "boot-end-marker" in line:
            continue

        # évite "end" au milieu
        if line.strip() == "end":
            continue

        # évite "conf terminal" si déjà injecté
        if line.strip() in ("conf terminal", "configure terminal"):
            continue

        lines.append(line)
    return lines


def deploy_router(router_name):
    port = ROUTER_TELNET_PORTS[router_name]
    cfg_path = os.path.join(CONFIG_DIR, f"{router_name}.cfg")

    if not os.path.isfile(cfg_path):
        print(f"[SKIP] Fichier manquant: {cfg_path}")
        return

    with open(cfg_path, "r", encoding="utf-8") as f:
        cfg_text = f.read()

    cfg_lines = clean_lines_for_cli(cfg_text)

    print(f"[INFO] Connexion Telnet à {router_name} sur {HOST}:{port} ...")
    tn = telnetlib.Telnet(HOST, port, timeout=10)

    time.sleep(1)
    tn.write(b"\r\n")

    #enable mode
    tn.write(b"enable\r\n")
    time.sleep(0.5)

    #conf terminal
    tn.write(b"conf t\r\n")
    time.sleep(0.5)

    #envoi les lignes de config
    for line in cfg_lines:
        tn.write(line.encode("utf-8") + b"\r\n")
        time.sleep(0.02)  # mini pause, sinon IOS rate des lignes

    #fin de config et sauvegarde
    tn.write(b"end\r\n")
    time.sleep(0.3)
    tn.write(b"wr mem\r\n")
    time.sleep(1)

    tn.write(b"\r\n")
    tn.close()

    print(f"[OK] {router_name} déployé via Telnet.")


def main():
    for r in ROUTER_TELNET_PORTS.keys():
        deploy_router(r)


if __name__ == "__main__":
    main()


