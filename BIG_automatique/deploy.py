from gns_config_bot import GNSConfigBot

configs_gen_dir = r"configs_gen" # changer selon l'adresse des configs générées
dynamips_dir = r"project-files/dynamips" # changer selon l'adresse du dossier dynamips du projet GNS3

bot = GNSConfigBot(configs_gen_dir, dynamips_dir)

print("Routeurs détectés :", bot.router_map)

bot.deploy_all()
