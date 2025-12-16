# LOGISCO GitLab Mirror

**Outil interne de synchronisation GitLab vers système de fichiers local.**

Synchronise automatiquement tous les projets d'un ou plusieurs groupes GitLab vers votre machine locale, en conservant la structure des dossiers.

---

## 🚀 Installation

### Prérequis

- **Python 3.12+**
- **Git** installé et configuré
- **pipx** (recommandé) ou pip

### Installation avec pipx (recommandé)

```bash
# Installer pipx si pas déjà fait
sudo apt install pipx
pipx ensurepath

# Installer lgm depuis le wheel
pipx install logisco_gitlab_mirror-1.0.0-py3-none-any.whl

# Vérifier l'installation
lgm --version
```

### Installation avec pip (alternative)

```bash
# Créer un environnement virtuel
python3 -m venv ~/.venv/lgm
source ~/.venv/lgm/bin/activate

# Installer
pip install logisco_gitlab_mirror-1.0.0-py3-none-any.whl

# Créer un alias pour accès global (optionnel)
echo 'alias lgm="~/.venv/lgm/bin/lgm"' >> ~/.bashrc
source ~/.bashrc
```

### Installation pour développement

```bash
# Cloner le dépôt
git clone <url-du-repo>
cd logisco-gitlab-mirror

# Installer avec Poetry
pip install poetry
poetry install

# Utiliser
poetry run lgm --help
```

---

## ⚙️ Configuration

### Première utilisation : `lgm init`

Après l'installation, lancez la commande d'initialisation :

```bash
lgm init
```

Cette commande interactive :

1. ✅ Crée le dossier `~/.config/lgm/`
2. ✅ Demande l'URL de votre instance GitLab
3. ✅ Demande votre token GitLab (masqué à la saisie)
4. ✅ Demande le répertoire de synchronisation
5. ✅ Teste la connexion à GitLab
6. ✅ Crée les fichiers de configuration sécurisés

**Exemple :**

```
╭──────────────────────────────────────────────────────────────╮
│ LOGISCO GitLab Mirror v1.0.0                                 │
╰──────────────────────────────────────────────────────────────╯

🔧 Initialisation de LOGISCO GitLab Mirror

Configuration requise:

URL GitLab [https://gitlab.com]: https://gitlab.example.com
Token GitLab (glpat-...): ********
Répertoire de synchronisation [~/gitlab-repos]: ~/dev/gitlab

✓ Dossier créé: /home/user/.config/lgm
✓ Fichier créé: /home/user/.config/lgm/.env (permissions: 600)
✓ Fichier créé: /home/user/.config/lgm/config.toml

🔌 Test de connexion...
✓ Connecté en tant que: votre-username

══════════════════════════════════════════════════════════════

✓ Configuration terminée !

Commandes utiles:
  lgm config      - Voir la configuration
  lgm sync -g G   - Synchroniser le groupe G
  lgm status -g G - Voir l'état du groupe G
```

### Fichiers créés

```
~/.config/lgm/
├── .env          # Token et URL (permissions 600, sécurisé)
└── config.toml   # Options avancées (workers, timeout, filtres)
```

### Création du token GitLab

1. Aller sur **GitLab → Préférences → Access Tokens**
2. Créer un token avec le scope **`read_api`**
3. Copier le token (commence par `glpat-`)

### Voir la configuration active

```bash
lgm config
```

Affiche les fichiers de configuration trouvés et les valeurs actives.

---

## 📖 Utilisation

### Commandes disponibles

| Commande | Description |
|----------|-------------|
| `lgm init` | Initialiser la configuration (première utilisation) |
| `lgm sync` | Synchroniser des groupes GitLab |
| `lgm status` | Vérifier l'état de synchronisation |
| `lgm config` | Afficher la configuration active |
| `lgm clean` | Nettoyer les dossiers orphelins |

### Exemples de synchronisation

```bash
# Synchroniser un groupe
lgm sync -g mon-groupe

# Synchroniser plusieurs groupes
lgm sync -g groupe1 -g groupe2

# Sync rapide avec 8 threads parallèles
lgm sync -g groupe -j 8

# Shallow clone (plus rapide, moins d'espace disque)
lgm sync -g groupe --depth 1

# Exclure certains projets
lgm sync -g groupe -e "*/test-*" -e "*/archived-*"

# Inclure seulement certains projets
lgm sync -g groupe -i "*/prod-*" -i "*/core-*"

# Mode simulation (aucune modification)
lgm sync -g groupe --dry-run

# Sortie JSON (pour CI/CD)
lgm sync -g groupe --json
```

### Options de synchronisation

```
Options:
  -g, --group TEXT        Groupe GitLab à synchroniser (requis, répétable)
  -r, --root-dir PATH     Répertoire racine de synchronisation
  -u, --instance-url URL  URL de l'instance GitLab
  -t, --token TEXT        Token GitLab (ou variable GITLAB_TOKEN)
  -m, --clone-method      Méthode: http ou ssh
  -j, --threads INT       Nombre de threads parallèles (défaut: 4)
  -e, --exclude PATTERN   Pattern d'exclusion (répétable)
  -i, --include PATTERN   Pattern d'inclusion (répétable)
  --depth INT             Profondeur de clonage (0=complet, 1=shallow)
  --prune                 Supprimer les branches distantes supprimées
  --archived              Inclure les projets archivés
  --since INT             Projets modifiés depuis N jours seulement
  --timeout INT           Timeout Git en secondes (défaut: 300)
  --log-file PATH         Fichier de log
  --json                  Sortie JSON
  -n, --dry-run           Mode simulation
  -v, --verbose           Mode verbeux
  -d, --debug             Mode debug
```

### Vérifier l'état

```bash
# Comparer GitLab vs local
lgm status -g mon-groupe
```

Affiche :
- ✓ Projets synchronisés
- ✗ Projets non clonés
- ? Projets orphelins (supprimés de GitLab)

### Nettoyer

```bash
# Voir ce qui serait supprimé
lgm clean --dry-run

# Supprimer les dossiers vides et repos invalides
lgm clean --force
```

---

## 📊 Exemple de sortie

```
╭────────────────────────────────────────────────────────────╮
│     LOGISCO GitLab Mirror v1.0.0                           │
╰────────────────────────────────────────────────────────────╯

🚀 Démarrage de la synchronisation...

✓ [1/15] devops/infrastructure
✓ [2/15] devops/terraform-modules
↑ [3/15] backend/api-core
= [4/15] backend/shared-libs
⊖ [5/15] backend/old-project (exclu par pattern)
...

══════════════════════════════════════════════════════════════

       📊 Résumé de la synchronisation

 Métrique              Valeur
────────────────────────────────
 Groupes traités           1
 Projets trouvés          15

 ✓ Clonés                  2
 ↑ Mis à jour              1
 = Déjà à jour            11
 ⊖ Exclus                  1
 ✗ Erreurs                 0

 Taux de réussite      100.0%
 ⏱ Durée               6.2s

✓ Synchronisation terminée ! Dossier: ~/gitlab-repos
```

---

## 🔧 Configuration avancée

### Fichier `~/.config/lgm/config.toml`

```toml
[performance]
max_workers = 8          # Threads parallèles
git_timeout = 300        # Timeout Git (secondes)

[smart_update]
enabled = true           # Vérifier avant de fetch
skip_recent_hours = 4    # Ignorer si fetch récent

[clone]
depth = 0                # 0=complet, 1=shallow
prune = true             # Nettoyer branches supprimées

[filters]
exclude = ["*/test-*", "*/archived-*"]
# include = ["*/prod-*"]
```

### Variables d'environnement

```bash
# Dans ~/.config/lgm/.env ou exportées
GITLAB_URL=https://gitlab.example.com
GITLAB_TOKEN=glpat-xxx
LGM_ROOT_DIR=~/gitlab-repos
```

---

## 🔄 Mise à jour

```bash
# Avec pipx
pipx upgrade logisco-gitlab-mirror

# Ou réinstaller
pipx install --force logisco_gitlab_mirror-X.X.X-py3-none-any.whl
```

---

## 🏗️ Build (pour mainteneurs)

```bash
# Créer le wheel
cd logisco-gitlab-mirror
poetry build

# Le wheel est dans dist/
ls dist/
# logisco_gitlab_mirror-1.0.0-py3-none-any.whl
```

---

## 📝 Licence

**Propriétaire - LOGISCO** - Usage interne uniquement.
