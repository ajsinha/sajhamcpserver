"""
SAJHA MCP Server — One-Time Prompt Migration (JSON → Database)
Copyright All rights Reserved 2025-2030, Ashutosh Sinha

Run once to import existing config/prompts/*.json into the prompts table.
Safe to re-run — skips duplicates.

Usage:
    python -m sajha.db.migrate_prompts
    # or called automatically during lifespan if prompts table is empty
"""

import json
import logging
from pathlib import Path
from sqlalchemy.orm import Session

from sajha.db.dao import PromptDAO
from sajha.db.models import Prompt

logger = logging.getLogger(__name__)


def migrate_prompts_from_json(db: Session, prompts_dir: str = 'config/prompts') -> int:
    """Import all JSON prompt files into the database.
    Returns count of prompts imported (skips existing).
    """
    path = Path(prompts_dir)
    if not path.is_dir():
        logger.info(f'No prompts directory at {path}, skipping migration')
        return 0

    # Check if prompts already exist in DB
    existing_count = db.query(Prompt).count()
    if existing_count > 0:
        logger.info(f'Prompts table already has {existing_count} records, skipping JSON migration')
        return 0

    dao = PromptDAO(db)
    imported = 0

    for json_file in sorted(path.glob('*.json')):
        try:
            with open(json_file, 'r', encoding='utf-8') as f:
                data = json.load(f)

            if isinstance(data, list):
                for item in data:
                    if dao.import_from_json(item):
                        imported += 1
            elif isinstance(data, dict):
                if 'name' in data:
                    if dao.import_from_json(data):
                        imported += 1
                elif 'prompts' in data:
                    for item in data['prompts']:
                        if dao.import_from_json(item):
                            imported += 1
        except Exception as e:
            logger.warning(f'Failed to import {json_file.name}: {e}', exc_info=True)

    logger.info(f'Prompt migration: {imported} prompts imported from {prompts_dir}')
    return imported


if __name__ == '__main__':
    logging.basicConfig(level=logging.INFO)
    from sajha.db.engine import get_db_session
    with get_db_session() as db:
        count = migrate_prompts_from_json(db)
        print(f'Migrated {count} prompts')
