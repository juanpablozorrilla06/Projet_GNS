#!/usr/bin/env python3
# Script de génération automatique de configurations IPv6 (IGP + BGP + policies communities)
# - IGP: RIPng ou OSPFv3 (ou none)
# - iBGP full-mesh via loopbacks
# - eBGP sur liens inter_as
# - Policies: client = tout / peer+provider = SELF + CLIENTS
# - Communities propagées (send-community)
# - Prefix-list SELF auto-générée sur border routers
# - Force "no shutdown" sur toutes les interfaces

import json
import os
import ipaddress


# =========================
# Utilitaires / Validation
# =========================

def ensure(cond, msg):
    if not cond:
        raise SystemExit(f"[ERROR] {msg}")


def ip_no_prefix(addr):
    return addr.split("/")[0].strip()


# =========================
# Allocation des adresses
# =========================

def allocate_loopbacks(intent):
    out = {}
    for asn, asdata in intent["ases"].items():
        pool = ipaddress.IPv6Network(asdata["ip_pools"]["loopbacks"])
        ensure(pool.prefixlen == 64, f"AS {asn} loopback pool must be /64, got /{pool.prefixlen}")
        base = pool.network_address

        routers = asdata.get("routers", [])
        ensure(isinstance(routers, list) and routers, f"AS {asn} must define a non-empty routers list")

        for idx, rname in enumerate(routers, start=1):
            out[rname] = f"{base + idx}/128"
    return out


def allocate_link_ips(intent):
    out = {}
    for link in intent["links"]:
        name = link.get("name", "<unnamed>")
        subnet_str = link.get("subnet_v6")
        ensure(subnet_str, f"Link {name} missing subnet_v6")

        net = ipaddress.IPv6Network(subnet_str)
        ensure(net.prefixlen == 64, f"Link {name} subnet must be /64, got /{net.prefixlen}")

        eps = link.get("endpoints", [])
        ensure(len(eps) == 2, f"Link {name} must have exactly 2 endpoints")

        r0, i0 = eps[0]["router"], eps[0]["interface"]
        r1, i1 = eps[1]["router"], eps[1]["interface"]

        ensure((r0, i0) not in out, f"Interface reused: {r0}:{i0}")
        ensure((r1, i1) not in out, f"Interface reused: {r1}:{i1}")

        out[(r0, i0)] = f"{net.network_address + 1}/64"
        out[(r1, i1)] = f"{net.network_address + 2}/64"

    return out


def adjacency(intent):
    adj = {}
    for link in intent["links"]:
        for ep in link["endpoints"]:
            adj.setdefault(ep["router"], []).append(link)
    return adj


def get_endpoint_for_router(link, rname):
    eps = link["endpoints"]
    if eps[0]["router"] == rname:
        return eps[0]
    if eps[1]["router"] == rname:
        return eps[1]
    raise SystemExit(f"[ERROR] Router {rname} not in {link.get('name','<unnamed>')}")


def other_endpoint(link, rname):
    eps = link["endpoints"]
    if eps[0]["router"] == rname:
        return eps[1]
    if eps[1]["router"] == rname:
        return eps[0]
    raise SystemExit(f"[ERROR] Router {rname} not in {link.get('name','<unnamed>')}")


# =========================
# Génération IGP
# =========================

def igp_global(asdata, router_id):
    igp = asdata["igp"]
    t = igp["type"]

    if t == "none":
        return ["!"]

    if t == "ospfv3":
        pid = igp["process_id"]
        return [
            f"ipv6 router ospf {pid}",
            f" router-id {router_id}",
            "exit",
            "!"
        ]

    if t == "ripng":
        proc = igp.get("process_name", "RIPNG")
        return [
            f"ipv6 router rip {proc}",
            "exit",
            "!"
        ]

    raise SystemExit(f"[ERROR] Unsupported IGP type: {t}")


def igp_iface_lines(asdata, link):
    igp = asdata["igp"]
    t = igp["type"]

    if t == "none":
        return []

    if t == "ospfv3":
        pid = igp["process_id"]
        area = igp["area"]
        lines = [f" ipv6 ospf {pid} area {area}"]
        if "ospf_cost" in link:
            lines.append(f" ipv6 ospf cost {int(link['ospf_cost'])}")
        return lines

    if t == "ripng":
        proc = igp.get("process_name", "RIPNG")
        return [f" ipv6 rip {proc} enable"]

    raise SystemExit(f"[ERROR] Unsupported IGP type: {t}")


# =========================
# Helpers BGP / Policies
# =========================

def has_ebgp_neighbor(intent, rname):
    for link in intent["links"]:
        if link.get("type") != "inter_as":
            continue
        eps = link["endpoints"]
        if eps[0]["router"] == rname or eps[1]["router"] == rname:
            return True
    return False


def intra_as_prefixes_for_as(intent, asn_str):
    """Ensemble des /64 de liens intra_as appartenant à l'AS asn_str."""
    prefs = set()
    for link in intent.get("links", []):
        if link.get("type") != "intra_as":
            continue
        if str(link.get("as")) != str(asn_str):
            continue
        subnet = link.get("subnet_v6")
        if subnet:
            prefs.add(subnet)
    return prefs


def loopbacks_for_as(intent, loopbacks, asn_str):
    """Liste des loopbacks /128 de tous les routeurs de l'AS asn_str."""
    out = []
    for r in intent["ases"][str(asn_str)]["routers"]:
        out.append(loopbacks[r])
    return out


def get_interas_relationship_for_router(intent, rname, adj):
    """dict peer_router -> relationship ('client'|'peer'|'provider') pour les liens inter_as connectés à rname."""
    rel = {}
    for link in adj.get(rname, []):
        if link.get("type") != "inter_as":
            continue
        other = other_endpoint(link, rname)
        peer = other["router"]
        rel[peer] = link.get("relationship", "peer")
    return rel


# =========================
# BGP + Policies
# =========================

def build_bgp(intent, rname, loopbacks, link_ips, adj):
    if not intent.get("bgp", {}).get("required", False):
        return []

    routers = intent["routers"]
    ases = intent["ases"]
    bgp = intent["bgp"]

    my_asn = int(routers[rname]["as"])
    rid = routers[rname]["router_id"]

    lines = [
        f"router bgp {my_asn}",
        f" bgp router-id {rid}",
        " bgp log-neighbor-changes",
        " no bgp default ipv4-unicast",
    ]

    # ---- iBGP full mesh via loopbacks
    ibgp_peers = []
    ibgp = bgp.get("ibgp", {})
    if ibgp.get("mode", "full_mesh") == "full_mesh":
        for peer in ases[str(my_asn)]["routers"]:
            if peer == rname:
                continue
            peer_lb = ip_no_prefix(loopbacks[peer])
            ibgp_peers.append(peer_lb)
            lines.append(f" neighbor {peer_lb} remote-as {my_asn}")
            lines.append(f" neighbor {peer_lb} update-source Loopback0")

    # ---- eBGP peers (inter_as connectés à ce routeur)
    ebgp_peers = []  # list of (peer_ip, peer_asn, peer_router)
    for link in adj.get(rname, []):
        if link.get("type") != "inter_as":
            continue

        other = other_endpoint(link, rname)
        peer_router = other["router"]
        peer_asn = int(routers[peer_router]["as"])
        peer_ip = ip_no_prefix(link_ips[(peer_router, other["interface"])])

        if peer_ip in [p for (p, _, _) in ebgp_peers]:
            continue

        lines.append(f" neighbor {peer_ip} remote-as {peer_asn}")
        ebgp_peers.append((peer_ip, peer_asn, peer_router))

    # ---- Address-family IPv6 unicast
    lines += [" !", " address-family ipv6 unicast"]

    border = has_ebgp_neighbor(intent, rname)

    # Activate iBGP + next-hop-self si border router + send-community
    for peer_lb in ibgp_peers:
        lines.append(f"  neighbor {peer_lb} activate")
        if border:
            lines.append(f"  neighbor {peer_lb} next-hop-self")
        lines.append(f"  neighbor {peer_lb} send-community")

    # Activate eBGP peers + send-community
    for peer_ip, _asn, _pr in ebgp_peers:
        lines.append(f"  neighbor {peer_ip} activate")
        lines.append(f"  neighbor {peer_ip} send-community")

    # ----------------------------
    # Origination des réseaux
    # ----------------------------
    # (A) Loopback /128 du routeur
    lines.append(f"  network {loopbacks[rname]}")

    # (B) Préfixes inter-AS directement connectés à CE routeur
    for link in adj.get(rname, []):
        if link.get("type") == "inter_as":
            lines.append(f"  network {link['subnet_v6']}")

    # (C) Si border router : annoncer tous les /64 intra-AS de son AS
    if border:
        for pfx in sorted(intra_as_prefixes_for_as(intent, str(my_asn))):
            lines.append(f"  network {pfx}")

        # (D) Si border router : annoncer toutes les loopbacks /128 de l'AS
        #     => indispensable pour que les autres AS puissent retourner vers n'importe quel routeur interne
        for lb in sorted(loopbacks_for_as(intent, loopbacks, str(my_asn))):
            lines.append(f"  network {lb}")

    # ----------------------------
    # Policies communities (sur border routers)
    #   - Client: on lui annonce tout
    #   - Peer/Provider: SELF + CLIENT only
    # ----------------------------
    if border:
        comm_self   = f"{my_asn}:50"
        comm_client = f"{my_asn}:100"
        comm_peer   = f"{my_asn}:200"
        comm_prov   = f"{my_asn}:300"


        # Construire "SELF prefixes" (ce qui appartient à notre AS)
        self_pfx = set()

        # toutes les loopbacks de l'AS (dont la nôtre)
        for lb in loopbacks_for_as(intent, loopbacks, str(my_asn)):
            self_pfx.add(lb)

        # tous les liens intra-as du AS
        for pfx in intra_as_prefixes_for_as(intent, str(my_asn)):
            self_pfx.add(pfx)

        # Sortie AF pour définir community-lists, prefix-lists et route-maps
        lines += [" exit-address-family", "!",  # quitter l'AF pour déclarer les objets
                  f"ip community-list standard COMM-SELF permit {comm_self}",
                  f"ip community-list standard COMM-CLIENT permit {comm_client}",
                  "!"]

        # Prefix-list SELF
        seq = 10
        lines.append("ipv6 prefix-list PL-SELF seq 5 deny ::/0")  # safe baseline (optionnel)
        for pfx in sorted(self_pfx):
            lines.append(f"ipv6 prefix-list PL-SELF seq {seq} permit {pfx}")
            seq += 10
        lines.append("!")

        # Route-maps:
        # - RM-IN-CLIENT: tagger tout ce qui arrive d'un client en COMM-CLIENT
        # - RM-OUT-PEERPROV:
        #    permit 10: SELF => tag COMM-SELF + permit
        #    permit 20: CLIENT routes => permit
        #    deny 100: tout le reste
        # - RM-OUT-CLIENT: permit all

        lines += [
            # --- IN tags + local-pref
            "route-map RM-IN-CLIENT permit 10",
            f" set community {comm_client} additive",
            " set local-preference 200",
            "!",
            "route-map RM-IN-PEER permit 10",
            f" set community {comm_peer} additive",
            " set local-preference 150",
            "!",
            "route-map RM-IN-PROV permit 10",
            f" set community {comm_prov} additive",
            " set local-preference 50",
            "!",

            # --- OUT filtering to peer/provider: only SELF + CLIENT
            "route-map RM-OUT-PEERPROV permit 10",
            " match ipv6 address prefix-list PL-SELF",
            f" set community {comm_self} additive",
            "!",
            "route-map RM-OUT-PEERPROV permit 20",
            " match community COMM-CLIENT",
            "!",
            "route-map RM-OUT-PEERPROV deny 100",
            "!",

            # --- OUT to client: everything
            "route-map RM-OUT-CLIENT permit 10",
            "!",

            # Re-enter BGP AF to attach route-maps
            f"router bgp {my_asn}",
            " address-family ipv6 unicast",
        ]

        relmap = get_interas_relationship_for_router(intent, rname, adj)

        for peer_ip, _asn, peer_router in ebgp_peers:
            rel = relmap.get(peer_router, "peer")

            if rel == "client":
                lines.append(f"  neighbor {peer_ip} route-map RM-OUT-CLIENT out")
                lines.append(f"  neighbor {peer_ip} route-map RM-IN-CLIENT in")

            elif rel == "provider":
                lines.append(f"  neighbor {peer_ip} route-map RM-OUT-PEERPROV out")
                lines.append(f"  neighbor {peer_ip} route-map RM-IN-PROV in")

            else:  # peer
                lines.append(f"  neighbor {peer_ip} route-map RM-OUT-PEERPROV out")
                lines.append(f"  neighbor {peer_ip} route-map RM-IN-PEER in")


        lines += [" exit-address-family", "exit", "!"]
        return lines

    # Non-border router : fermeture standard
    lines += [" exit-address-family", "exit", "!"]
    return lines


# =========================
# Génération config routeur
# =========================

def build_router_config(intent, rname, loopbacks, link_ips, adj):
    routers = intent["routers"]
    ases = intent["ases"]

    asn = routers[rname]["as"]
    asdata = ases[asn]

    lines = [
        "!",
        f"hostname {rname}",
        "!",
        "no ip domain-lookup",
        "ipv6 unicast-routing",
        "!",
    ]

    # Loopback0
    lines += [
        "interface Loopback0",
        " no ip address",
        f" ipv6 address {loopbacks[rname]}",
    ]
    lines += igp_iface_lines(asdata, {"type": "intra_as"})
    lines += [" no shutdown", "exit", "!"]

    # Interfaces physiques
    for link in adj.get(rname, []):
        my_ep = get_endpoint_for_router(link, rname)
        iface = my_ep["interface"]
        ip = link_ips[(rname, iface)]

        lines += [
            f"interface {iface}",
            " no ip address",
            " ipv6 enable",
            f" ipv6 address {ip}",
        ]

        # IGP sur liens intra-AS seulement
        if link.get("type") == "intra_as":
            lines += igp_iface_lines(asdata, link)

        lines += [" no shutdown", "exit", "!"]

    # IGP global
    lines += igp_global(asdata, routers[rname]["router_id"])

    # BGP (+ policies)
    lines += build_bgp(intent, rname, loopbacks, link_ips, adj)

    lines += [ "!"]
    return "\n".join(lines) + "\n"


# =========================
# Main
# =========================

def main():
    intent_path = os.environ.get("INTENT_PATH", "intents/intent.json") # changer selon l'adresse du fichier intent.json
    out_dir = os.environ.get("OUT_DIR", "configs_gen") # changer selon l'adresse du dossier de sortie

    ensure(os.path.isfile(intent_path), f"Intent file not found: {intent_path}")

    with open(intent_path, "r", encoding="utf-8") as f:
        intent = json.load(f)

    loopbacks = allocate_loopbacks(intent)
    link_ips = allocate_link_ips(intent)
    adj = adjacency(intent)

    os.makedirs(out_dir, exist_ok=True)

    for rname in intent["routers"].keys():
        cfg = build_router_config(intent, rname, loopbacks, link_ips, adj)
        with open(os.path.join(out_dir, f"{rname}.cfg"), "w", encoding="utf-8") as f:
            f.write(cfg)

    print(f"[OK] Generated configs in {out_dir}/")


if __name__ == "__main__":
    main()
