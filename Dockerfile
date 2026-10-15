FROM python:3.12-slim

# Empêche Python d'écrire des fichiers .pyc et force l'affichage immédiat des logs
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

WORKDIR /app

# Installation des utilitaires système nécessaires (curl pour healthcheck, netcat pour attente BDD)
RUN apt-get update && apt-get install -y --no-install-recommends \
    curl \
    netcat-openbsd \
    && rm -rf /var/lib/apt/lists/*

# Copie et installation des dépendances Python
COPY requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt

# Création des dossiers de persistance
RUN mkdir -p /app/data /app/medias /app/staticfiles

# Copie du code source de l'application Django
COPY . .

# Configuration des permissions du script d'entrée
RUN chmod +x /app/entrypoint.sh

# Vérification de santé du service
HEALTHCHECK --interval=30s --timeout=5s --start-period=20s --retries=3 \
  CMD curl -f http://127.0.0.1:8000/sante/ || exit 1

EXPOSE 8000

ENTRYPOINT ["/app/entrypoint.sh"]
CMD ["gunicorn", "config.wsgi:application", "--bind", "0.0.0.0:8000", "--workers", "3", "--timeout", "120", "--access-logfile", "-", "--error-logfile", "-"]
