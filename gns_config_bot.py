import os
import re


class GNSConfigBot:
    """
    Copie les configurations générées (ex: configs_gen/R1.cfg)
    vers les fichiers startup-config des routeurs GNS3 (Dynamips) :
    .../dynamips/<uuid>/configs/i1_startup-config.cfg
    """

    STARTUP_RE = re.compile(r"^i(\d+)_startup-config\.cfg$", re.IGNORECASE)

    def __init__(self, configs_gen_dir, dynamips_dir):
        self.configs_gen_dir = os.path.abspath(configs_gen_dir)
        self.dynamips_dir = os.path.abspath(dynamips_dir)

        self._check_paths()
        self.router_map = self.auto_detect_router_map()

    def _check_paths(self):
        if not os.path.isdir(self.configs_gen_dir):
            raise FileNotFoundError(f"[ERROR] configs_gen_dir introuvable: {self.configs_gen_dir}")
        if not os.path.isdir(self.dynamips_dir):
            raise FileNotFoundError(f"[ERROR] dynamips_dir introuvable: {self.dynamips_dir}")

    def auto_detect_router_map(self) :
        """
        Scanne dynamips/*/configs/ et trouve les fichiers iX_startup-config.cfg
        => retourne { 'R1': '<uuid>', 'R2': '<uuid>', ... }
        """
        router_map = {}

        for folder in os.listdir(self.dynamips_dir):
            full = os.path.join(self.dynamips_dir, folder)
            if not os.path.isdir(full):
                continue

            cfg_dir = os.path.join(full, "configs")
            if not os.path.isdir(cfg_dir):
                continue

            for fname in os.listdir(cfg_dir):
                m = self.STARTUP_RE.match(fname)
                if not m:
                    continue
                num = m.group(1)          
                router_map[f"R{num}"] = folder

        if not router_map:
            print("[WARN] Aucun routeur Dynamips détecté. Vérifie que tu pointes vers le bon dossier dynamips.")
        return router_map



    def deploy_all(self, dry_run = False) :
        """Déploie pour tous les routeurs détectés."""
        # tri R1, R2, R10...
        def keyfn(r):
            return int(re.sub(r"\D", "", r) or 0)

        for r in sorted(self.router_map.keys(), key=keyfn):
            self.deploy_router(r, dry_run=dry_run)

    def deploy_router(self, router_name, dry_run = False):
        """Déploie la config d’un seul routeur."""
        if router_name not in self.router_map:
            raise ValueError(f"[ERROR] Routeur inconnu/non détecté: {router_name}")

        src_cfg = os.path.join(self.configs_gen_dir, f"{router_name}.cfg")
        if not os.path.isfile(src_cfg):
            print(f"[SKIP] Fichier config manquant: {src_cfg}")
            return

        uuid = self.router_map[router_name]
        router_num = re.sub(r"\D", "", router_name)  # "R1" -> "1"
        dest_fname = f"i{router_num}_startup-config.cfg"

        dest_dir = os.path.join(self.dynamips_dir, uuid, "configs")
        dest_path = os.path.join(dest_dir, dest_fname)

        if not os.path.isdir(dest_dir):
            print(f"[SKIP] Dossier configs introuvable pour {router_name}: {dest_dir}")
            return

        with open(src_cfg, "r", encoding="utf-8") as f:
            raw = f.read()


        final = "\n".join([
            "!",
            "! Startup-config généré automatiquement par GNSConfigBot",
            f"! Source: {router_name}.cfg",
            "!",
            raw.strip(),
            "!"
        ]) + "\n"

        if dry_run:
            print(f"[DRY] {router_name} -> {dest_path}")
            return

        with open(dest_path, "w", encoding="utf-8") as f:
            f.write(final)

        print(f"[OK] {router_name} -> {dest_path}")
