#!/usr/bin/env python3
"""
Comprehensive sync runner for all CRM data sources.

Runs all sync scripts in the correct order to ensure complete data coverage.
"""
import sys
from pathlib import Path

# Add project root to path
sys.path.insert(0, str(Path(__file__).parent.parent))

import subprocess
import logging
import argparse
from datetime import datetime, timezone

logging.basicConfig(level=logging.INFO, format='%(levelname)s: %(message)s')
logger = logging.getLogger(__name__)

SCRIPTS_DIR = Path(__file__).parent


def run_script(script_name: str, args: list[str] = None, dry_run: bool = True) -> dict:
    """Run a sync script and return results."""
    script_path = SCRIPTS_DIR / script_name
    if not script_path.exists():
        return {'success': False, 'error': f'Script not found: {script_name}'}

    cmd = ['uv', 'run', 'python', str(script_path)]
    if not dry_run:
        cmd.append('--execute')
    if args:
        cmd.extend(args)

    logger.info(f"\n{'='*60}")
    logger.info(f"Running: {script_name}")
    logger.info(f"{'='*60}")

    try:
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=600,  # 10 minute timeout
            cwd=SCRIPTS_DIR.parent,
        )

        if result.stdout:
            for line in result.stdout.strip().split('\n'):
                logger.info(f"  {line}")

        if result.returncode != 0:
            logger.error(f"Script failed with code {result.returncode}")
            if result.stderr:
                logger.error(f"  {result.stderr}")
            return {'success': False, 'error': result.stderr or 'Unknown error'}

        return {'success': True, 'output': result.stdout}

    except subprocess.TimeoutExpired:
        logger.error(f"Script timed out after 10 minutes")
        return {'success': False, 'error': 'Timeout'}
    except Exception as e:
        logger.error(f"Error running script: {e}")
        return {'success': False, 'error': str(e)}


def run_relationship_discovery() -> dict:
    """Run relationship discovery programmatically."""
    logger.info(f"\n{'='*60}")
    logger.info("Running: Relationship Discovery")
    logger.info(f"{'='*60}")

    try:
        from api.services.relationship_discovery import run_full_discovery
        results = run_full_discovery(days_back=365)
        logger.info(f"  Calendar: {results['by_source']['calendar']} relationships")
        logger.info(f"  Email: {results['by_source']['email']} relationships")
        logger.info(f"  Vault: {results['by_source']['vault']} relationships")
        logger.info(f"  Messaging: {results['by_source']['messaging']} relationships")
        logger.info(f"  Total: {results['total']} relationships")
        return {'success': True, 'results': results}
    except Exception as e:
        logger.error(f"Error: {e}")
        return {'success': False, 'error': str(e)}


def get_data_stats() -> dict:
    """Get current data statistics."""
    import sqlite3

    stats = {}

    # Interactions
    int_db = SCRIPTS_DIR.parent / "data" / "interactions.db"
    if int_db.exists():
        conn = sqlite3.connect(int_db)
        cursor = conn.execute("""
            SELECT source_type, COUNT(*)
            FROM interactions
            GROUP BY source_type
        """)
        stats['interactions'] = dict(cursor.fetchall())
        cursor = conn.execute("SELECT COUNT(*) FROM interactions")
        stats['total_interactions'] = cursor.fetchone()[0]
        conn.close()

    # Relationships
    crm_db = SCRIPTS_DIR.parent / "data" / "crm.db"
    if crm_db.exists():
        conn = sqlite3.connect(crm_db)
        cursor = conn.execute("SELECT COUNT(*) FROM relationships")
        stats['total_relationships'] = cursor.fetchone()[0]
        conn.close()

    # People
    from api.services.person_entity import get_person_entity_store
    store = get_person_entity_store()
    stats['total_people'] = len(store.get_all())

    return stats


def run_comprehensive_sync(dry_run: bool = True) -> dict:
    """
    Run all sync scripts in order.

    Order:
    1. Link iMessage entities (so they can be synced)
    2. Sync iMessage interactions
    3. Sync WhatsApp contacts and messages
    4. Sync person stats
    5. Discover WhatsApp relationships
    6. Run full relationship discovery

    Args:
        dry_run: If True, don't actually make changes

    Returns:
        Summary statistics
    """
    start_time = datetime.now(timezone.utc)
    results = {
        'started_at': start_time.isoformat(),
        'dry_run': dry_run,
        'scripts': {},
        'errors': [],
    }

    # Get before stats
    before_stats = get_data_stats()
    logger.info(f"\n{'='*60}")
    logger.info("BEFORE SYNC:")
    logger.info(f"  Interactions: {before_stats.get('total_interactions', 0)}")
    logger.info(f"  Relationships: {before_stats.get('total_relationships', 0)}")
    logger.info(f"  People: {before_stats.get('total_people', 0)}")
    logger.info(f"{'='*60}")

    # 1. Link iMessage entities
    result = run_script('link_imessage_entities.py', dry_run=dry_run)
    results['scripts']['link_imessage'] = result
    if not result['success']:
        results['errors'].append(f"link_imessage: {result.get('error')}")

    # 2. Sync iMessage interactions
    result = run_script('sync_imessage_interactions.py', dry_run=dry_run)
    results['scripts']['sync_imessage'] = result
    if not result['success']:
        results['errors'].append(f"sync_imessage: {result.get('error')}")

    # 3. Sync WhatsApp
    result = run_script('sync_whatsapp.py', dry_run=dry_run)
    results['scripts']['sync_whatsapp'] = result
    if not result['success']:
        results['errors'].append(f"sync_whatsapp: {result.get('error')}")

    # 4. Sync person stats
    result = run_script('sync_person_stats.py', dry_run=dry_run)
    results['scripts']['sync_stats'] = result
    if not result['success']:
        results['errors'].append(f"sync_stats: {result.get('error')}")

    # 5. Discover WhatsApp relationships
    result = run_script('discover_whatsapp_relationships.py', dry_run=dry_run)
    results['scripts']['discover_whatsapp'] = result
    if not result['success']:
        results['errors'].append(f"discover_whatsapp: {result.get('error')}")

    # 6. Discover iMessage relationships
    result = run_script('discover_imessage_relationships.py', dry_run=dry_run)
    results['scripts']['discover_imessage'] = result
    if not result['success']:
        results['errors'].append(f"discover_imessage: {result.get('error')}")

    # 7. Run relationship discovery (always runs, it's idempotent)
    if not dry_run:
        result = run_relationship_discovery()
        results['scripts']['relationship_discovery'] = result
        if not result['success']:
            results['errors'].append(f"relationship_discovery: {result.get('error')}")

    # Get after stats
    after_stats = get_data_stats()
    end_time = datetime.now(timezone.utc)

    results['ended_at'] = end_time.isoformat()
    results['duration_seconds'] = (end_time - start_time).total_seconds()
    results['before'] = before_stats
    results['after'] = after_stats
    results['delta'] = {
        'interactions': after_stats.get('total_interactions', 0) - before_stats.get('total_interactions', 0),
        'relationships': after_stats.get('total_relationships', 0) - before_stats.get('total_relationships', 0),
    }

    # Summary
    logger.info(f"\n{'='*60}")
    logger.info("SYNC COMPLETE")
    logger.info(f"{'='*60}")
    logger.info(f"Duration: {results['duration_seconds']:.1f} seconds")
    logger.info(f"Errors: {len(results['errors'])}")
    logger.info(f"\nAFTER SYNC:")
    logger.info(f"  Interactions: {after_stats.get('total_interactions', 0)} (+{results['delta']['interactions']})")
    logger.info(f"  Relationships: {after_stats.get('total_relationships', 0)} (+{results['delta']['relationships']})")
    logger.info(f"  People: {after_stats.get('total_people', 0)}")

    if results['errors']:
        logger.warning(f"\nErrors occurred:")
        for error in results['errors']:
            logger.warning(f"  - {error}")

    if dry_run:
        logger.info(f"\nDRY RUN - no changes made. Use --execute to apply.")

    return results


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description='Run comprehensive CRM sync')
    parser.add_argument('--execute', action='store_true', help='Actually apply changes')
    parser.add_argument('--stats-only', action='store_true', help='Only show current stats')
    args = parser.parse_args()

    if args.stats_only:
        stats = get_data_stats()
        print(f"\nCurrent Data Stats:")
        print(f"  Total interactions: {stats.get('total_interactions', 0)}")
        if 'interactions' in stats:
            for source, count in sorted(stats['interactions'].items(), key=lambda x: -x[1]):
                print(f"    {source}: {count}")
        print(f"  Total relationships: {stats.get('total_relationships', 0)}")
        print(f"  Total people: {stats.get('total_people', 0)}")
    else:
        run_comprehensive_sync(dry_run=not args.execute)
