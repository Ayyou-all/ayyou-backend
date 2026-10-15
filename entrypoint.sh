#!/bin/sh
set -e

echo "=== [AYYOU Backend] Démarrage du conteneur ==="

# Création des répertoires indispensables s'ils n'existent pas
mkdir -p /app/data /app/medias /app/staticfiles

# Attente de PostgreSQL si configuré
if [ "${AYYOU_MOTEUR_BDD}" = "postgresql" ]; then
  echo "Attente de la base de données PostgreSQL (${AYYOU_BDD_HOTE:-base-de-donnees}:${AYYOU_BDD_PORT:-5432})..."
  while ! nc -z "${AYYOU_BDD_HOTE:-base-de-donnees}" "${AYYOU_BDD_PORT:-5432}" 2>/dev/null; do
    sleep 1
  done
  echo "PostgreSQL est prêt !"
fi

# Collecte des fichiers statiques
echo "Collecte des fichiers statiques..."
python manage.py collectstatic --noinput

# Application des migrations de base de données
echo "Application des migrations..."
python manage.py migrate --noinput

echo "=== [AYYOU Backend] Prêt à recevoir des requêtes ==="

# Exécution de la commande principale (Gunicorn par défaut)
exec "$@"
