## Projet GNS3 – Réseau IPv6 multi‑AS, Intent‑Based Networking et automatisation

  
# 1.Présentation du projet

Ce projet a pour objectif de concevoir, automatiser et déployer un réseau IPv6 multi‑AS dans GNS3 en utilisant une approche d’Intent‑Based Networking. L’idée principale est de ne plus configurer les routeurs manuellement, mais de décrire le réseau sous forme d’une intention globale, puis de laisser un programme générer et déployer automatiquement toutes les configurations.

Le projet repose sur trois éléments :

-   un fichier JSON qui décrit l’architecture et les politiques du réseau,
-   un script Python qui transforme cette intention en configurations Cisco complètes,
-   un bot utilisant Telnet qui déploie automatiquement ces configurations dans GNS3.

On passe ainsi d’un travail manuel routeur par routeur à une automatisation complète du réseau.

  
# 2. Architecture du réseau
L’architecture du réseau représente une mini‑Internet.

Elle est composée de plusieurs AS ayant des rôles différents :

-   AS 111 : AS opérateur interne utilisant RIPng comme IGP
-   AS 112 : AS opérateur interne utilisant OSPFv3 comme IGP
-   AS 65001 : AS externe jouant le rôle de provider
-   AS 65002 : AS externe jouant le rôle de client
-   AS 65003 : AS externe jouant le rôle de client

Cette organisation permet de reproduire une hiérarchie réaliste d’Internet avec des relations client, peer et provider.

Tous les liens du réseau sont point‑à‑point :

-   un lien correspond à un sous‑réseau IPv6 /64,
-   l’endpoint 0 reçoit l’adresse ::1,
-   l’endpoint 1 reçoit l’adresse ::2.

Chaque routeur possède également une loopback IPv6 /128 :

-   indépendante des interfaces physiques,
-   toujours active,
-   utilisée comme identité BGP,
-   transportée par l’IGP interne.

# 3. Rôle des protocoles de routage
L’architecture repose sur une séparation claire des fonctions :
-   Les IGP (RIPng et OSPFv3) servent uniquement à faire circuler les routes à l’intérieur d’un AS.
-   BGP sert uniquement à échanger des routes entre AS.
-   iBGP permet de partager les routes BGP à l’intérieur d’un même AS.
-   eBGP permet les échanges entre AS différents.

L’IGP transporte la connectivité interne, tandis que BGP transporte les routes inter‑AS.

# 4. iBGP, full‑mesh et border routers
Un routeur devient automatiquement un border router dès qu’il possède au moins un lien de type inter\_as.

Le border router :

-   relie l’IGP interne et le BGP,
-   annonce les réseaux internes vers l’extérieur,
-   applique les politiques BGP,
-   utilise next‑hop‑self pour rendre les routes externes atteignables depuis l’intérieur de l’AS.

# 5. Politiques BGP
Les politiques BGP implémentées suivent le modèle économique réel d’Internet, basé sur le principe de _no free transit_ : on ne transporte jamais gratuitement le trafic des autres.

Relations :

-   Client : on reçoit tout, on annonce tout.
-   Peer : on reçoit SELF + CLIENT, on annonce SELF + CLIENT.
-   Provider : on reçoit SELF + CLIENT, on annonce SELF + CLIENT.

# 6. Communities BGP
Pour appliquer ces règles, des communities sont utilisées :

-   SELF → ASN:50
-   CLIENT → ASN:100
-   PEER → ASN:200
-   PROVIDER → ASN:300

Chaque route est étiquetée avec une communauté indiquant son origine, puis les route‑maps utilisent ces étiquettes pour filtrer les annonces et définir les priorités de routage.

  
# 7. Le JSON : l’intention du réseau
Le JSON représente l’intention du réseau.

Il ne contient aucune commande Cisco et ne décrit pas comment configurer les routeurs, mais comment le réseau doit se comporter.

Il est structuré en blocs logiques :

-   meta : règles globales d’adressage IPv6,
-   ases : politiques par AS (IGP, pools de loopbacks, liste des routeurs),
-   routers : identité des routeurs,
-   links : topologie physique et relations inter‑AS,
-   bgp : politique BGP globale (BGP activé, iBGP en full‑mesh).

Une ligne comme :

"bgp": { "required": true, "ibgp": { "mode": "full\_mesh" } }

signifie simplement que BGP doit être utilisé sur le réseau et que l’iBGP doit être généré automatiquement en full‑mesh dans chaque AS opérateur.

# 8. Le script Python : moteur de génération
Le script Python agit comme un moteur de traduction entre l’intention et la configuration réelle :

1.  Il lit le fichier JSON.
2.  Il calcule automatiquement toutes les adresses IP :

-   loopbacks /128 à partir des pools,
-   adresses des liens /64 à partir des subnets.

3.  Il reconstruit la topologie complète du réseau.
4.  Pour chaque routeur, il génère :

-   la configuration des interfaces,
-   l’IGP correspondant à son AS,
-   la configuration BGP complète (iBGP, eBGP, annonces, politiques, communities, route‑maps).

5.  Il écrit un fichier de configuration Cisco complet par routeur.

Chaque routeur possède ainsi son propre fichier :

R1.cfg, R2.cfg, R3.cfg, etc., dans le dossier `configs_gen`.


# 9. Déploiement automatique
Le bot basé sur Telnet permet ensuite d’automatiser le déploiement.

**La version python pour le déploiement avec telnet doit être Python 3.12.x (ou inférieur)**

Il se connecte directement aux routeurs GNS3 et injecte les fichiers de configuration générés. Le réseau complet peut ainsi être déployé en quelques secondes sans aucune configuration manuelle.

La chaîne complète du projet est donc :

JSON → Script Python → Configurations Cisco → Bot Telnet → GNS3

Pour lancer tout la configuration automatique il vous faut:

1. Ouvrir le reseau GNS3 souhaité.
2. Lancer le programme config_script.py, le dossier des configurations des routeurs est généré.
3. Lancer le programme deploy.py, le bot il va initialiser la config de chaque routeur en copiant et collant les configs générées précedemment.
4. Initialiser les routeurs sur GNS3.
5. Lancer le programme deploy_telnet.py pour lancer telnet.

  

Loujaine, Clara, Juan Pablo et Jade
