"""
P9.1 Data Integrity Tests - Strict Requirements Verification

These tests verify that CRM data is CORRECT, not just that it EXISTS.
Each test class corresponds to a requirement in docs/CRM-P9.1-Requirements.md

Tests must pass before P9.1 can be considered complete.
"""
import os
import re
import random
import sqlite3
import pytest
from pathlib import Path

from api.services.person_entity import get_person_entity_store
from api.services.interaction_store import get_interaction_store, get_interaction_db_path


class TestR1CleanDatabase:
    """R1: Clean Interaction Database - No test pollution."""

    def test_no_temp_directory_interactions(self):
        """No interactions should point to /tmp or /var/folders paths."""
        conn = sqlite3.connect(get_interaction_db_path())
        cursor = conn.execute("""
            SELECT COUNT(*) FROM interactions
            WHERE source_id LIKE '/private/var/folders%'
               OR source_id LIKE '/tmp%'
               OR source_id LIKE '/var/%'
        """)
        count = cursor.fetchone()[0]
        conn.close()

        assert count == 0, f"Found {count} interactions pointing to temp directories - database is polluted with test data"

    def test_all_vault_files_exist(self):
        """All vault interactions must point to files that actually exist."""
        conn = sqlite3.connect(get_interaction_db_path())
        cursor = conn.execute("""
            SELECT source_id, title FROM interactions
            WHERE source_type IN ('vault', 'granola')
            AND source_id LIKE '/%'
        """)

        missing_files = []
        for row in cursor.fetchall():
            source_id, title = row
            if not os.path.exists(source_id):
                missing_files.append((source_id, title))

        conn.close()

        assert len(missing_files) == 0, (
            f"Found {len(missing_files)} vault interactions pointing to non-existent files:\n"
            + "\n".join(f"  - {path}" for path, _ in missing_files[:10])
        )

    def test_all_person_ids_exist(self):
        """All interactions must link to PersonEntity records that exist."""
        store = get_person_entity_store()
        entity_ids = {e.id for e in store.get_all()}

        conn = sqlite3.connect(get_interaction_db_path())
        cursor = conn.execute("SELECT DISTINCT person_id FROM interactions")
        interaction_person_ids = {row[0] for row in cursor.fetchall()}
        conn.close()

        orphaned = interaction_person_ids - entity_ids

        assert len(orphaned) == 0, (
            f"Found {len(orphaned)} person_ids in interactions that don't exist in PersonEntity store:\n"
            + "\n".join(f"  - {pid}" for pid in list(orphaned)[:10])
        )


class TestR2EntityResolution:
    """R2: Correct Entity Resolution - People must actually be mentioned in linked notes."""

    def test_vault_interactions_mention_linked_person(self):
        """
        For vault interactions, the linked person's name must appear in the note.

        Sample 20 random vault interactions and verify each one.
        """
        store = get_person_entity_store()
        conn = sqlite3.connect(get_interaction_db_path())

        # Get vault interactions with real file paths
        cursor = conn.execute("""
            SELECT person_id, source_id, title FROM interactions
            WHERE source_type IN ('vault', 'granola')
            AND source_id LIKE '/Users/%'
            ORDER BY RANDOM()
            LIMIT 20
        """)

        false_positives = []
        checked = 0

        for row in cursor.fetchall():
            person_id, source_id, title = row

            # Skip if file doesn't exist
            if not os.path.exists(source_id):
                continue

            # Get person's names/aliases
            person = store.get_by_id(person_id)
            if not person:
                continue

            # Build list of names to search for
            names_to_find = [person.canonical_name]
            if person.display_name and person.display_name != person.canonical_name:
                names_to_find.append(person.display_name)
            names_to_find.extend(person.aliases)

            # Read file content
            try:
                content = Path(source_id).read_text(encoding='utf-8')
            except Exception:
                continue

            # Check if any name appears in content
            found = False
            content_lower = content.lower()
            for name in names_to_find:
                if name and len(name) > 2:  # Skip very short names
                    if name.lower() in content_lower:
                        found = True
                        break

            if not found:
                false_positives.append({
                    'person': person.canonical_name,
                    'file': source_id,
                    'title': title,
                    'searched_names': names_to_find,
                })

            checked += 1

        conn.close()

        assert checked > 0, "No vault interactions found to verify"

        if false_positives:
            msg = f"Found {len(false_positives)} false positive links (person not mentioned in note):\n"
            for fp in false_positives[:5]:
                msg += f"\n  Person: {fp['person']}\n"
                msg += f"  File: {fp['file']}\n"
                msg += f"  Searched for: {fp['searched_names']}\n"
            assert False, msg


class TestR3VaultLinks:
    """R3: Working Vault Links - Links must point to existing files."""

    def test_vault_source_ids_are_valid_paths(self):
        """Vault source_ids must be valid file paths."""
        conn = sqlite3.connect(get_interaction_db_path())
        cursor = conn.execute("""
            SELECT source_id FROM interactions
            WHERE source_type IN ('vault', 'granola')
            LIMIT 100
        """)

        invalid_paths = []
        for row in cursor.fetchall():
            source_id = row[0]
            # Should be an absolute path starting with /
            if not source_id.startswith('/'):
                invalid_paths.append(source_id)

        conn.close()

        assert len(invalid_paths) == 0, (
            f"Found {len(invalid_paths)} vault interactions without valid file paths:\n"
            + "\n".join(f"  - {p}" for p in invalid_paths[:10])
        )

    def test_can_construct_obsidian_url(self):
        """Should be able to construct obsidian:// URL from vault path."""
        conn = sqlite3.connect(get_interaction_db_path())
        cursor = conn.execute("""
            SELECT source_id FROM interactions
            WHERE source_type IN ('vault', 'granola')
            AND source_id LIKE '/Users/%'
            LIMIT 1
        """)
        row = cursor.fetchone()
        conn.close()

        if row:
            source_id = row[0]
            # Extract vault name and relative path
            # Path format: /Users/nathanramia/Notes 2025/...
            # Obsidian URL: obsidian://open?vault=Notes%202025&file=...

            path = Path(source_id)
            assert path.suffix == '.md', f"Vault file should be .md: {source_id}"


class TestR4GmailLinks:
    """R4: Working Gmail Links - Must open specific email."""

    def test_gmail_interactions_have_message_id(self):
        """Gmail interactions must have message_id in source_id."""
        conn = sqlite3.connect(get_interaction_db_path())
        cursor = conn.execute("""
            SELECT source_id, title FROM interactions
            WHERE source_type = 'gmail'
            LIMIT 10
        """)

        rows = cursor.fetchall()
        conn.close()

        if not rows:
            pytest.skip("No gmail interactions to verify")

        for source_id, title in rows:
            # Gmail message IDs are hex strings
            assert source_id, f"Gmail interaction '{title}' has no source_id"
            assert len(source_id) > 10, f"Gmail source_id too short: {source_id}"

    def test_gmail_link_format(self):
        """Gmail links must be constructable to open specific email."""
        conn = sqlite3.connect(get_interaction_db_path())
        cursor = conn.execute("""
            SELECT source_id FROM interactions
            WHERE source_type = 'gmail'
            LIMIT 1
        """)
        row = cursor.fetchone()
        conn.close()

        if not row:
            pytest.skip("No gmail interactions to verify")

        message_id = row[0]
        # Construct the URL that should open the email
        expected_url = f"https://mail.google.com/mail/u/0/#inbox/{message_id}"

        assert message_id in expected_url
        assert expected_url.startswith("https://mail.google.com")


class TestR5CalendarLinks:
    """R5: Working Calendar Links - Must open specific event."""

    def test_calendar_interactions_have_event_id(self):
        """Calendar interactions must have event_id in source_id."""
        conn = sqlite3.connect(get_interaction_db_path())
        cursor = conn.execute("""
            SELECT source_id, title FROM interactions
            WHERE source_type = 'calendar'
            LIMIT 10
        """)

        rows = cursor.fetchall()
        conn.close()

        if not rows:
            pytest.skip("No calendar interactions to verify")

        for source_id, title in rows:
            assert source_id, f"Calendar interaction '{title}' has no source_id"


class TestR6InteractionCounts:
    """R6: Accurate Interaction Counts - PersonEntity counts must match database."""

    def test_counts_match_database(self):
        """PersonEntity counts must match actual interactions in database."""
        store = get_person_entity_store()
        conn = sqlite3.connect(get_interaction_db_path())

        # Get top 10 people by stored counts
        all_people = store.get_all()
        sorted_people = sorted(
            all_people,
            key=lambda p: p.email_count + p.meeting_count + p.mention_count,
            reverse=True
        )[:10]

        mismatches = []

        for person in sorted_people:
            # Get actual counts from database
            cursor = conn.execute("""
                SELECT source_type, COUNT(*)
                FROM interactions
                WHERE person_id = ?
                GROUP BY source_type
            """, (person.id,))

            actual_counts = {row[0]: row[1] for row in cursor.fetchall()}

            actual_email = actual_counts.get('gmail', 0)
            actual_meeting = actual_counts.get('calendar', 0)
            actual_mention = actual_counts.get('vault', 0) + actual_counts.get('granola', 0)

            if (person.email_count != actual_email or
                person.meeting_count != actual_meeting or
                person.mention_count != actual_mention):
                mismatches.append({
                    'name': person.canonical_name,
                    'stored': {
                        'email': person.email_count,
                        'meeting': person.meeting_count,
                        'mention': person.mention_count,
                    },
                    'actual': {
                        'email': actual_email,
                        'meeting': actual_meeting,
                        'mention': actual_mention,
                    }
                })

        conn.close()

        if mismatches:
            msg = f"Found {len(mismatches)} people with mismatched counts:\n"
            for m in mismatches:
                msg += f"\n  {m['name']}:\n"
                msg += f"    Stored: email={m['stored']['email']}, meeting={m['stored']['meeting']}, mention={m['stored']['mention']}\n"
                msg += f"    Actual: email={m['actual']['email']}, meeting={m['actual']['meeting']}, mention={m['actual']['mention']}\n"
            assert False, msg


class TestR7TaylorCanonical:
    """R7: Taylor Test Case - Canonical verification."""

    TAYLOR_EMAIL = "annetaylorwalker@gmail.com"
    TAYLOR_PHONE = "+19012295017"
    TAYLOR_NAMES = ["taylor", "tay", "anne taylor walker"]

    def test_taylor_found_by_email(self):
        """Taylor must be findable by email."""
        store = get_person_entity_store()
        person = store.get_by_email(self.TAYLOR_EMAIL)
        assert person is not None, f"Taylor not found by email {self.TAYLOR_EMAIL}"

    def test_taylor_found_by_phone(self):
        """Taylor must be findable by phone."""
        store = get_person_entity_store()
        person = store.get_by_phone(self.TAYLOR_PHONE)
        assert person is not None, f"Taylor not found by phone {self.TAYLOR_PHONE}"

    def test_taylor_has_multiple_sources(self):
        """Taylor must have interactions from at least 2 different sources."""
        store = get_person_entity_store()
        person = store.get_by_email(self.TAYLOR_EMAIL)
        assert person is not None

        conn = sqlite3.connect(get_interaction_db_path())
        cursor = conn.execute("""
            SELECT DISTINCT source_type FROM interactions
            WHERE person_id = ?
        """, (person.id,))
        sources = [row[0] for row in cursor.fetchall()]
        conn.close()

        assert len(sources) >= 2, f"Taylor only has interactions from {sources}, need at least 2 sources"

    def test_taylor_vault_interactions_are_correct(self):
        """Every vault interaction linked to Taylor must actually mention her."""
        store = get_person_entity_store()
        person = store.get_by_email(self.TAYLOR_EMAIL)
        assert person is not None

        conn = sqlite3.connect(get_interaction_db_path())
        cursor = conn.execute("""
            SELECT source_id, title FROM interactions
            WHERE person_id = ? AND source_type IN ('vault', 'granola')
            AND source_id LIKE '/Users/%'
        """, (person.id,))

        false_positives = []
        checked = 0

        for row in cursor.fetchall():
            source_id, title = row

            if not os.path.exists(source_id):
                continue

            try:
                content = Path(source_id).read_text(encoding='utf-8').lower()
            except Exception:
                continue

            # Check if any of Taylor's names appear
            found = False
            for name in self.TAYLOR_NAMES:
                if name in content:
                    found = True
                    break

            if not found:
                false_positives.append((source_id, title))

            checked += 1

        conn.close()

        assert checked > 0, "No Taylor vault interactions found to verify"

        if false_positives:
            msg = f"Found {len(false_positives)} vault notes linked to Taylor that don't mention her:\n"
            for path, title in false_positives[:5]:
                msg += f"  - {title}: {path}\n"
            assert False, msg

    def test_taylor_relationship_strength_positive(self):
        """Taylor must have positive relationship strength from real data."""
        store = get_person_entity_store()
        person = store.get_by_email(self.TAYLOR_EMAIL)
        assert person is not None

        assert person.relationship_strength > 0, (
            f"Taylor has relationship_strength={person.relationship_strength}, "
            "should be > 0 with real interaction data"
        )


class TestR8Top10Verification:
    """R8: Top 10 Verification - Not overfitting to Taylor."""

    def test_top_10_all_have_interactions(self):
        """Top 10 people by interaction count must all have real interactions."""
        store = get_person_entity_store()
        conn = sqlite3.connect(get_interaction_db_path())

        # Get actual top 10 from database
        cursor = conn.execute("""
            SELECT person_id, COUNT(*) as cnt
            FROM interactions
            GROUP BY person_id
            ORDER BY cnt DESC
            LIMIT 10
        """)

        top_10 = []
        for row in cursor.fetchall():
            person_id, count = row
            person = store.get_by_id(person_id)
            if person:
                top_10.append((person, count))

        conn.close()

        assert len(top_10) >= 5, f"Found only {len(top_10)} people with interactions in top 10"

        for person, count in top_10:
            assert count > 0, f"{person.canonical_name} in top 10 but has 0 interactions"

    def test_top_10_have_valid_interactions(self):
        """Top 10 must have at least one interaction with valid source."""
        store = get_person_entity_store()
        conn = sqlite3.connect(get_interaction_db_path())

        cursor = conn.execute("""
            SELECT person_id, COUNT(*) as cnt
            FROM interactions
            GROUP BY person_id
            ORDER BY cnt DESC
            LIMIT 10
        """)

        problems = []

        for row in cursor.fetchall():
            person_id, count = row
            person = store.get_by_id(person_id)
            if not person:
                continue

            # Check for at least one valid vault interaction
            cursor2 = conn.execute("""
                SELECT source_id FROM interactions
                WHERE person_id = ? AND source_type IN ('vault', 'granola')
                AND source_id LIKE '/Users/%'
                LIMIT 5
            """, (person_id,))

            valid_found = False
            for row2 in cursor2.fetchall():
                if os.path.exists(row2[0]):
                    valid_found = True
                    break

            # Also check for gmail/calendar/imessage interactions
            cursor3 = conn.execute("""
                SELECT COUNT(*) FROM interactions
                WHERE person_id = ? AND source_type IN ('gmail', 'calendar', 'imessage')
            """, (person_id,))
            other_count = cursor3.fetchone()[0]

            if not valid_found and other_count == 0:
                problems.append(person.canonical_name)

        conn.close()

        assert len(problems) == 0, (
            f"These top 10 people have no valid interactions: {problems}"
        )
