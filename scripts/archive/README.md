# Archived Scripts

Scripts in this directory are no longer actively used but preserved for reference.

**Archived**: 2026-01-30

## Categories

### Superseded by Newer Scripts
- `run_comprehensive_sync.py` - Replaced by `run_all_syncs.py`
- `discover_imessage_relationships.py` - Replaced by `sync_relationship_discovery.py`
- `discover_whatsapp_relationships.py` - Replaced by `sync_relationship_discovery.py`

### One-Time Migration Scripts (Completed)
- `migrate_to_crm.py` - Initial CRM migration
- `migrate_interactions.py` - Interaction data migration
- `populate_relationships.py` - Initial relationship population
- `populate_source_entities.py` - Initial source entity population

### One-Off Data Fix Scripts
- `auto_categorize_people.py` - Bulk categorization
- `backfill_whatsapp_history.py` - WhatsApp history backfill
- `batch_extract_facts.py` - Bulk fact extraction
- `clean_interaction_database.py` - Database cleanup
- `clean_source_entity_phones.py` - Phone normalization
- `cleanup_imessage_data.py` - iMessage data cleanup
- `create_relationship.py` - Manual relationship creation
- `fix_concatenated_names.py` - Name parsing fix
- `fix_entity_resolution.py` - Entity resolution fix
- `fix_gmail_sent_emails.py` - Gmail sent email fix
- `fix_past_merges.py` - Merge history fix
- `fix_taylor_data.py` - Person-specific data fix
- `import_calendar_participants.py` - Calendar import
- `import_phone_contacts.py` - Phone contacts import

### Development/Test Scripts
- `test_mcp.py` - MCP testing utility
- `launchd-wrapper.sh` - Unused launchd wrapper

## Recovery

If any script is needed again, simply move it back to `scripts/`:
```bash
mv scripts/archive/script_name.py scripts/
```
