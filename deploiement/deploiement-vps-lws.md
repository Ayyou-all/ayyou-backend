# 🚀 GUIDE DE DÉPLOIEMENT COMPLET D'AYYOU SUR VPS LWS

Ce guide fournit la procédure complète et détaillée, étape par étape, pour déployer et administrer la plateforme **AYYOU** en production sur un serveur VPS LWS (système Debian 12 ou Ubuntu 22.04 / 24.04 LTS).

---

## 📑 TABLE DES MATIÈRES

1. [Architecture et Domaines](#1-architecture-et-domaines)
2. [Étape 1 — Configuration des DNS chez LWS](#étape-1--configuration-des-dns-chez-lws)
3. [Étape 2 — Connexion SSH et Sécurisation du Serveur](#étape-2--connexion-ssh-et-sécurisation-du-serveur)
4. [Étape 3 — Installation de Docker et Docker Compose](#étape-3--installation-de-docker-et-docker-compose)
5. [Étape 4 — Mise en Place du Projet sur le VPS](#étape-4--mise-en-place-du-projet-sur-le-vps)
6. [Étape 5 — Configuration du Fichier .env de Production](#étape-5--configuration-du-fichier-env-de-production)
7. [Étape 6 — Reverse Proxy Nginx et Certificats SSL Let's Encrypt](#étape-6--reverse-proxy-nginx-et-certificats-ssl-lets-encrypt)
8. [Étape 7 — Lancement de l'Application via Docker](#étape-7--lancement-de-lapplication-via-docker)
9. [Étape 8 — Création du Super Administrateur Django](#étape-8--création-du-super-administrateur-django)
10. [Étape 9 — Commandes Utiles d'Exploitation Quotidienne](#étape-9--commandes-utiles-dexploitation-quotidienne)
11. [Étape 10 — Procédure de Mise à Jour Future](#étape-10--procédure-de-mise-à-jour-future)
12. [Étape 11 — Sauvegarde et Restauration des Données](#étape-11--sauvegarde-et-restauration-des-données)
13. [Diagnostic et Résolution des Problèmes Courants](#diagnostic-et-résolution-des-problèmes-courants)

---

## 1. Architecture et Domaines

| Service | Domaine public | Port conteneur interne | Port publié sur le VPS | Rôle |
| :--- | :--- | :--- | :--- | :--- |
| **Frontend** | `https://ayyou.site` | `80` (Nginx) | `2401` | Application Angular 22 SPA |
| **Backend** | `https://api.ayyou.site` | `8000` (Gunicorn) | `8888` | API REST Django 6 / DRF |
| **Service IA** | Accès interne uniquement | `8000` (Uvicorn) | `8881` | Microservice IA FastAPI |
| **Reverse Proxy** | Terminaison TLS | Ports `80` et `443` | `80` & `443` | Nginx hôte + Certbot SSL |
| **Base de Données** | Persistance volume | `/app/data` | Interne | SQLite par défaut (PostgreSQL prêt) |

---

## Étape 1 — Configuration des DNS chez LWS

Avant de générer les certificats SSL, vos domaines doivent pointer vers l'adresse IPv4 publique de votre VPS LWS (ex: `185.xxx.xxx.xxx`).

1. Connectez-vous à votre espace client **LWS** ([https://panel.lws.fr](https://panel.lws.fr)).
2. Cliquez sur **Gestion du Domaine** pour `ayyou.site`.
3. Rendez-vous dans la rubrique **Zone DNS** (ou Gestion DNS).
4. Ajoutez ou modifiez les enregistrements de type **A** suivants :

| Type | Nom d'hôte / Sous-domaine | Valeur (Cible) | TTL |
| :--- | :--- | :--- | :--- |
| **A** | `@` (ou laisser vide pour `ayyou.site`) | `IP_DE_VOTRE_VPS` | 3600 |
| **A** | `www` | `IP_DE_VOTRE_VPS` | 3600 |
| **A** | `api` | `IP_DE_VOTRE_VPS` | 3600 |

> ⏳ **Délai de propagation :** La propagation DNS prend généralement entre 15 minutes et 2 heures. Vérifiez que la propagation est effective depuis votre terminal avec la commande :
> ```bash
> ping ayyou.site
> ping api.ayyou.site
> ```
> Les deux doivent renvoyer l'adresse IP de votre VPS.

---

## Étape 2 — Connexion SSH et Sécurisation du Serveur

### 1. Se connecter en SSH à votre VPS
Ouvrez un terminal (PowerShell, Git Bash ou macOS/Linux) :
```bash
ssh root@IP_DE_VOTRE_VPS
```

### 2. Mettre à jour le système
```bash
apt-get update && apt-get upgrade -y
apt-get install -y curl wget git htop ufw unzip fail2ban
```

### 3. Configurer le fuseau horaire de Dakar
```bash
timedatectl set-timezone Africa/Dakar
```

### 4. Configurer le Pare-feu UFW
Ouvrez uniquement les ports nécessaires :
```bash
# Autoriser SSH
ufw allow 22/tcp

# Autoriser HTTP et HTTPS pour le Reverse Proxy Nginx
ufw allow 80/tcp
ufw allow 443/tcp

# Ports applicatifs pour diagnostic ou accès direct
ufw allow 2401/tcp
ufw allow 8888/tcp

# Activer le pare-feu
ufw enable
ufw status verbose
```

---

## Étape 3 — Installation de Docker et Docker Compose

Exécutez le script officiel Docker sur votre VPS :

```bash
# 1. Téléchargement et installation automatique du moteur Docker officiel
curl -fsSL https://get.docker.com -o get-docker.sh
sh get-docker.sh
rm get-docker.sh

# 2. Vérification de l'installation
docker --version
docker compose version

# 3. Activation du service Docker au démarrage du serveur
systemctl enable docker
systemctl start docker
```

---

## Étape 4 — Mise en Place du Projet sur le VPS

Nous organisons le projet dans `/var/www/ayyou`.

```bash
# 1. Créer le dossier principal
mkdir -p /var/www/ayyou
cd /var/www/ayyou

# 2. Cloner les 3 dépôts Git du projet
git clone https://github.com/Ayyou-all/ayyou-frontend.git ayyouFrontend
git clone https://github.com/Ayyou-all/ayyou-backend.git ayyouBackend
git clone https://github.com/Ayyou-all/ayyou-ai.git ayyouServiceIA

# 3. Créer le dossier de persistance pour SQLite et médias
mkdir -p /var/www/ayyou/donnees_sqlite
mkdir -p /var/www/ayyou/medias
chmod -R 775 /var/www/ayyou/donnees_sqlite /var/www/ayyou/medias
```

Copiez également les fichiers racine (`docker-compose.yml`, `.env.example`, `nginx-vps.conf`) dans `/var/www/ayyou/`.

---

## Étape 5 — Configuration du Fichier .env de Production

Créez votre fichier de configuration d'environnement réel :

```bash
cd /var/www/ayyou
cp .env.example .env
nano .env
```

### Générer une clé secrète Django aléatoire et robuste :
Exécutez dans votre terminal :
```bash
python3 -c "import secrets; print(secrets.token_urlsafe(50))"
```
Copiez la clé obtenue et collez-la dans `.env` à la variable `AYYOU_CLE_SECRETE_DJANGO`.

### Valeurs recommandées dans `.env` :
```env
AYYOU_DEBUG=False
AYYOU_CLE_SECRETE_DJANGO=votre_cle_generee_precedemment
AYYOU_HOTES_AUTORISES=api.ayyou.site,ayyou.site,localhost,127.0.0.1,backend
AYYOU_ORIGINES_FRONTEND=https://ayyou.site,http://localhost:2401
AYYOU_CSRF_ORIGINES=https://api.ayyou.site,https://ayyou.site,http://localhost:2401,http://localhost:8888
AYYOU_URL_FRONTEND=https://ayyou.site
AYYOU_URL_PUBLIQUE_BACKEND=https://api.ayyou.site
AYYOU_NIVEAU_JOURNAL=INFO

# Base de données (SQLite par défaut)
AYYOU_MOTEUR_BDD=sqlite
AYYOU_BDD_FICHIER_SQLITE=data/db.sqlite3

# IA interne Docker
AYYOU_SERVICE_IA_URL=http://service-ia:8000
AYYOU_SERVICE_IA_CLE_INTERNE=cle-secrete-interne-ayyou-ia-2026

# PayTech Sénégal
PAYTECH_URL_BASE=https://paytech.sn/api
PAYTECH_CLE_API=votre_cle_api_paytech
PAYTECH_CLE_SECRETE=votre_cle_secrete_paytech
PAYTECH_ENVIRONNEMENT=test
```

---

## Étape 6 — Reverse Proxy Nginx et Certificats SSL Let's Encrypt

Sur le VPS, nous installons Nginx et Certbot pour gérer le HTTPS gratuit avec renouvellement automatique.

### 1. Installer Nginx et Certbot
```bash
apt-get install -y nginx certbot python3-certbot-nginx
```

### 2. Obtenir les certificats SSL Let's Encrypt
Assurez-vous que vos DNS sont bien propagés, puis lancez :
```bash
certbot certonly --nginx -d ayyou.site -d www.ayyou.site -d api.ayyou.site --agree-tos --email contact@ayyou.site --no-eff-email
```
> Les certificats seront stockés dans `/etc/letsencrypt/live/ayyou.site/` et `/etc/letsencrypt/live/api.ayyou.site/`.

### 3. Installer la configuration Reverse Proxy
```bash
cp /var/www/ayyou/nginx-vps.conf /etc/nginx/sites-available/ayyou
ln -s /etc/nginx/sites-available/ayyou /etc/nginx/sites-enabled/
rm -f /etc/nginx/sites-enabled/default
```

### 4. Tester et recharger Nginx
```bash
nginx -t
systemctl reload nginx
```

---

## Étape 7 — Lancement de l'Application via Docker

Depuis `/var/www/ayyou`, construisez et démarrez les conteneurs :

```bash
cd /var/www/ayyou
docker compose up -d --build
```

### Vérifier le statut des conteneurs :
```bash
docker compose ps
```
Tous les conteneurs (`ayyou-frontend`, `ayyou-backend`, `ayyou-service-ia`) doivent afficher le statut `Up (healthy)`.

---

## Étape 8 — Création du Super Administrateur Django

Créez le compte d'administration sans afficher le mot de passe dans les logs :

```bash
docker compose exec -it backend python manage.py createsuperuser
```
Renseignez :
- **Numéro de téléphone / Identifiant** : ex: `770000000`
- **Nom / Prénom**
- **Mot de passe administrateur**

L'administration Django est accessible à l'adresse :
`https://api.ayyou.site/admin/`

---

## Étape 9 — Commandes Utiles d'Exploitation Quotidienne

| Action | Commande |
| :--- | :--- |
| **Vérifier l'état des conteneurs** | `docker compose ps` |
| **Consulter tous les logs en direct** | `docker compose logs -f` |
| **Consulter les logs du Backend** | `docker compose logs -f backend` |
| **Consulter les logs du Frontend** | `docker compose logs -f frontend` |
| **Consulter les logs du Service IA** | `docker compose logs -f service-ia` |
| **Redémarrer tous les services** | `docker compose restart` |
| **Redémarrer uniquement le Backend** | `docker compose restart backend` |
| **Arrêter les conteneurs (données conservées)** | `docker compose down` |
| **Surveiller l'usage CPU / RAM** | `docker stats` |

---

## Étape 10 — Procédure de Mise à Jour Future

Lorsque vous apportez des modifications au code (sur GitHub) :

```bash
cd /var/www/ayyou

# 1. Récupérer les dernières modifications de chaque dépôt
cd ayyouFrontend && git pull origin develop && cd ..
cd ayyouBackend && git pull origin develop && cd ..
cd ayyouServiceIA && git pull origin main && cd ..

# 2. Reconstruire et relancer les conteneurs sans interruption prolongée
docker compose up -d --build

# 3. Vérifier les logs
docker compose logs -f --tail=50
```

---

## Étape 11 — Sauvegarde et Restauration des Données

### Sauvegarder la base SQLite :
```bash
# Copie à chaud sécurisée de la base SQLite
mkdir -p /var/backups/ayyou
docker compose exec backend python -c "
import sqlite3
source = sqlite3.connect('/app/data/db.sqlite3')
dest = sqlite3.connect('/app/data/sauvegarde.sqlite3')
source.backup(dest)
dest.close()
source.close()
print('Sauvegarde SQLite terminée avec succès.')
"
docker cp ayyou-backend:/app/data/sauvegarde.sqlite3 /var/backups/ayyou/db_$(date +%F_%H%M%S).sqlite3
```

### Sauvegarder les fichiers médias :
```bash
docker cp ayyou-backend:/app/medias /var/backups/ayyou/medias_$(date +%F_%H%M%S)
```

---

## Diagnostic et Résolution des Problèmes Courants

### 1. Erreur 502 Bad Gateway sur `https://ayyou.site` ou `https://api.ayyou.site`
- Le conteneur Docker correspondant est arrêté ou en cours de redémarrage.
- Exécutez `docker compose ps` pour vérifier son statut.
- Consultez les logs : `docker compose logs --tail=100 backend`.

### 2. Erreur `403 CSRF verification failed` lors des formulaires Django
- Vérifiez la variable `AYYOU_CSRF_ORIGINES` dans votre `.env`.
- Elle doit inclure `https://api.ayyou.site,https://ayyou.site`.
- Redémarrez le backend : `docker compose restart backend`.

### 3. Erreur de connexion entre Django et le service IA
- Django contacte l'IA via le nom de service Docker `http://service-ia:8000`.
- Testez la communication interne :
  ```bash
  docker compose exec backend curl -i http://service-ia:8000/sante
  ```
- Cela doit renvoyer `{"statut": "OK", ...}` avec le code HTTP `200`.

### 4. Renouvellement automatique des certificats SSL
Certbot installe automatiquement un timer systemd pour le renouvellement. Testez la simulation de renouvellement :
```bash
certbot renew --dry-run
```
Si le test réussit, vos certificats SSL se renouvelleront automatiquement avant expiration sans aucune action manuelle.
