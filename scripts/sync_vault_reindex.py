#!/usr/bin/env python3
"""
Reindex the Obsidian vault to ChromaDB and BM25.

This script triggers a full reindex of all vault notes, which:
1. Chunks documents and indexes to ChromaDB (vector search)
2. Indexes to BM25 (keyword search)
3. Extracts people mentions and syncs to PersonEntity via EntityResolver
4. Creates vault mention interactions in InteractionStore

Should run AFTER all CRM data collection is complete so that entity
resolution has access to the latest people data.
"""
import sys
from pathlib import Path

# Add project root to path
sys.path.insert(0, str(Path(__file__).parent.parent))

import argparse
import logging
import time

logging.basicConfig(level=logging.INFO, format='%(levelname)s: %(message)s')
logger = logging.getLogger(__name__)


def sync_vault_reindex(dry_run: bool = True) -> dict:
    """
    Reindex the Obsidian vault.

    Args:
        dry_run: If True, just report what would happen

    Returns:
        Stats dict
    """
    from config.settings import settings
    from api.services.indexer import IndexerService

    vault_path = settings.vault_path

    if not Path(vault_path).exists():
        logger.error(f"Vault path not found: {vault_path}")
        return {"status": "error", "reason": "vault_not_found"}

    # Count markdown files
    md_files = list(Path(vault_path).rglob("*.md"))
    logger.info(f"Found {len(md_files)} markdown files in vault")

    if dry_run:
        logger.info("DRY RUN - would reindex vault")
        logger.info(f"  Vault path: {vault_path}")
        logger.info(f"  Files to index: {len(md_files)}")
        return {"status": "dry_run", "files_found": len(md_files)}

    logger.info(f"Starting vault reindex for {vault_path}...")
    start_time = time.time()

    indexer = IndexerService(vault_path=vault_path)
    files_indexed = indexer.index_all()

    elapsed = time.time() - start_time

    logger.info(f"\n=== Vault Reindex Results ===")
    logger.info(f"  Files indexed: {files_indexed}")
    logger.info(f"  Time elapsed: {elapsed:.1f}s")

    return {
        "status": "success",
        "files_indexed": files_indexed,
        "elapsed_seconds": round(elapsed, 1),
    }


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description='Reindex Obsidian vault')
    parser.add_argument('--execute', action='store_true', help='Actually perform reindex')
    args = parser.parse_args()

    sync_vault_reindex(dry_run=not args.execute)
