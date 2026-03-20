#!/usr/bin/env bash
# =============================================================================
# init-repo.sh — Inicializa o repositório Git e faz o primeiro push para GitHub
#
# Pré-requisito: ter criado o repositório vazio no GitHub antes.
# Uso (no diretório raiz do projeto):
#   bash deploy/init-repo.sh
# =============================================================================
set -euo pipefail

GITHUB_USER="joaorafaelvaz"
REPO_NAME="dailyvip"

echo "Configurando repositório Git..."

git init
git add .
git commit -m "chore: estrutura inicial do Daily Briefing"

git remote add origin "git@github.com:$GITHUB_USER/$REPO_NAME.git"
git branch -M main
git push -u origin main

echo ""
echo "Repositório publicado: https://github.com/$GITHUB_USER/$REPO_NAME"
