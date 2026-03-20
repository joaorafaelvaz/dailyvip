#!/usr/bin/env python3
"""
Utilitário para listar todas as unidades ativas do ERP e gerar
o esqueleto do config/unit_groups.json.

Uso:
  python tools/export_units.py              → imprime no stdout
  python tools/export_units.py --save       → salva em config/unit_groups.json (preserva chat_ids existentes)
"""

import argparse
import json
import os
import sys

# Adiciona raiz do projeto ao path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import config
import pymysql
import pymysql.cursors


def get_unidades() -> list[dict]:
    """Busca todas as unidades ativas do ERP."""
    conn = pymysql.connect(
        host=config.ERP_HOST,
        port=config.ERP_PORT,
        db=config.ERP_DB,
        user=config.ERP_USER,
        password=config.ERP_PASSWORD,
        charset="utf8mb4",
        cursorclass=pymysql.cursors.DictCursor,
        connect_timeout=10,
    )
    try:
        with conn.cursor() as cur:
            cur.execute("""
                SELECT
                    u.id,
                    u.nome,
                    u.cidade,
                    u.estado
                FROM unidades u
                WHERE u.status = 1
                ORDER BY u.estado, u.cidade, u.nome
            """)
            return cur.fetchall()
    finally:
        conn.close()


def main():
    parser = argparse.ArgumentParser(description="Exporta unidades para unit_groups.json")
    parser.add_argument("--save", action="store_true", help="Salva o arquivo (preserva chat_ids existentes)")
    args = parser.parse_args()

    print("Buscando unidades no ERP...\n")
    unidades = get_unidades()

    # Carrega grupos existentes para preservar chat_ids já configurados
    groups_path = os.path.join(os.path.dirname(os.path.dirname(__file__)), "config", "unit_groups.json")
    existing = {}
    if os.path.exists(groups_path):
        with open(groups_path, "r", encoding="utf-8") as f:
            existing = json.load(f).get("units", {})

    # Monta o novo dict
    units = {}
    for u in unidades:
        uid = str(u["id"])
        cidade = u.get("cidade", "")
        nome = u.get("nome", "")

        # Extrai bairro (última parte do nome)
        if " - " in nome:
            parts = nome.split(" - ")
            bairro = parts[-1].strip()
            display = f"{cidade} - {bairro}"
        else:
            display = nome

        # Preserva chat_id se já existir
        existing_entry = existing.get(uid, {})
        units[uid] = {
            "nome": display,
            "chat_id": existing_entry.get("chat_id", ""),
        }

    output = {
        "_doc": "Mapeamento unidade_id → grupo WhatsApp do franqueado. Preencha o chat_id de cada unidade.",
        "_instrucoes": "chat_id formato: '5548999999999-1234567890@g.us' (grupo) ou '5548999999999@c.us' (direto)",
        "units": units,
    }

    json_str = json.dumps(output, ensure_ascii=False, indent=2)

    if args.save:
        os.makedirs(os.path.dirname(groups_path), exist_ok=True)
        with open(groups_path, "w", encoding="utf-8") as f:
            f.write(json_str)
        print(f"✅ Salvo em {groups_path}")
        print(f"   {len(units)} unidades exportadas")
        print(f"   {sum(1 for u in units.values() if u['chat_id'])} com chat_id configurado")
    else:
        print(json_str)
        print(f"\n--- {len(units)} unidades ativas ---")
        print("Use --save para salvar o arquivo.")


if __name__ == "__main__":
    main()
