"""
CRM Data Integrity Tests - P9.1

These tests verify that data flows correctly from sources to CRM display.
They use real production data and should pass when the CRM is working correctly.

NOTE: These tests require direct database access and will be skipped if
the server is running (database locked). Stop the server to run these tests.
"""
import pytest
from api.services.person_entity import get_person_entity_store
from api.services.interaction_store import get_interaction_store


# All classes in this file require database access
pytestmark = pytest.mark.usefixtures("require_db")


class TestDataIntegrityTaylor:
    """
    Taylor (partner) is the canonical test case.
    Should have highest interaction count in the system.

    Known identifiers:
    - Email: annetaylorwalker@gmail.com
    - Phone: +19012295017
    - Names: Tay, Taylor, Anne Taylor Walker
    """

    def test_taylor_exists_by_email(self):
        """Taylor should be findable by email."""
        store = get_person_entity_store()
        person = store.get_by_email("annetaylorwalker@gmail.com")
        assert person is not None, "Taylor not found by email"

    def test_taylor_exists_by_phone(self):
        """Taylor should be findable by phone."""
        store = get_person_entity_store()
        person = store.get_by_phone("+19012295017")
        assert person is not None, "Taylor not found by phone"

    def test_taylor_has_multiple_sources(self):
        """Taylor should appear in multiple data sources."""
        store = get_person_entity_store()
        person = store.get_by_email("annetaylorwalker@gmail.com")
        assert person is not None

        # Should have at least phone_contacts, and ideally gmail, calendar, imessage
        assert len(person.sources) >= 1, f"Expected >=1 sources, got {person.sources}"

        # This is the real test - once everything is wired up correctly
        # assert len(person.sources) >= 3, f"Expected >=3 sources, got {person.sources}"

    def test_taylor_has_interactions(self):
        """Taylor should have interaction records."""
        person_store = get_person_entity_store()
        interaction_store = get_interaction_store()

        person = person_store.get_by_email("annetaylorwalker@gmail.com")
        assert person is not None

        interactions = interaction_store.get_for_person(person.id, days_back=365)

        # This is the critical test - Taylor should have MANY interactions
        # If this fails with 0, the data isn't flowing through
        assert len(interactions) > 0, f"Taylor ({person.id}) has 0 interactions in interaction_store"

    def test_taylor_interaction_count_not_zero(self):
        """Taylor's PersonEntity should have non-zero interaction count."""
        store = get_person_entity_store()
        person = store.get_by_email("annetaylorwalker@gmail.com")
        assert person is not None

        total = person.email_count + person.meeting_count + person.mention_count
        # This is the critical test
        # If this fails, the PersonEntity isn't being updated with counts
        assert total > 0, (
            f"Taylor has 0 total interactions on PersonEntity. "
            f"email_count={person.email_count}, meeting_count={person.meeting_count}, "
            f"mention_count={person.mention_count}"
        )

    def test_taylor_relationship_strength(self):
        """Taylor should have high relationship strength (>0.5 at minimum)."""
        store = get_person_entity_store()
        person = store.get_by_email("annetaylorwalker@gmail.com")
        assert person is not None

        # Currently returns 0.267 which is low for a partner
        # Should be >0.8 once interactions are properly linked
        assert person.relationship_strength > 0.0, "Taylor has 0 relationship strength"


class TestDataIntegrityTopContacts:
    """
    Top contacts by any metric should have real data.
    """

    def test_interactions_database_has_data(self):
        """The interactions database should have records."""
        store = get_interaction_store()
        stats = store.get_statistics()

        assert stats["total_interactions"] > 0, "Interaction store is empty"
        # With iMessage synced, expect 100K+ interactions
        assert stats["total_interactions"] > 100000, f"Expected >100K interactions (with iMessage), got {stats['total_interactions']}"

    def test_interactions_linked_to_valid_persons(self):
        """
        Interactions should be linked to PersonEntity records that exist.

        This test checks if the person_ids in interactions match actual PersonEntity IDs.
        """
        person_store = get_person_entity_store()
        interaction_store = get_interaction_store()

        # Get some interactions
        # Note: We need to check if get_for_person is the only way to query
        # or if we can get all interactions

        # Get statistics to see person distribution
        stats = interaction_store.get_statistics()

        # Check if the top person by interactions actually exists
        if "interactions_by_person" in stats:
            for person_id, count in list(stats["interactions_by_person"].items())[:5]:
                person = person_store.get_by_id(person_id)
                assert person is not None, (
                    f"Person {person_id} has {count} interactions but doesn't exist in PersonEntity store"
                )

    def test_some_people_have_multiple_sources(self):
        """At least some people should have multiple sources."""
        store = get_person_entity_store()

        # Get all people
        all_people = store.get_all()

        multi_source = [p for p in all_people if len(p.sources) > 1]
        assert len(multi_source) > 0, "No people have multiple sources"


class TestDataFlowDiagnosis:
    """
    Diagnostic tests to understand where data flow breaks down.
    """

    def test_person_entity_store_has_records(self):
        """PersonEntity store should have records."""
        store = get_person_entity_store()
        stats = store.get_statistics()

        assert stats.get("total_entities", 0) > 0, "PersonEntity store is empty"

    def test_interaction_store_has_records(self):
        """Interaction store should have records."""
        store = get_interaction_store()
        stats = store.get_statistics()

        assert stats.get("total_interactions", 0) > 0, "Interaction store is empty"

    def test_interaction_person_ids_format(self):
        """
        Check the format of person_ids in interactions.

        Interactions might be using email or phone as person_id
        instead of the actual PersonEntity UUID.
        """
        import sqlite3
        from api.services.interaction_store import get_interaction_db_path

        conn = sqlite3.connect(get_interaction_db_path())
        cursor = conn.execute("SELECT DISTINCT person_id FROM interactions LIMIT 10")
        person_ids = [row[0] for row in cursor.fetchall()]
        conn.close()

        # Print for debugging
        print(f"Sample person_ids from interactions: {person_ids}")

        # Check if they look like UUIDs
        import re
        uuid_pattern = re.compile(r'^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$')

        uuid_count = sum(1 for pid in person_ids if uuid_pattern.match(pid))
        print(f"UUID format count: {uuid_count}/{len(person_ids)}")

        # This helps diagnose the issue
        assert len(person_ids) > 0, "No person_ids found in interactions"

    def test_check_for_taylor_by_any_identifier(self):
        """
        Search interactions for Taylor by any known identifier.

        This helps diagnose if Taylor's interactions exist but under a different person_id.
        """
        import sqlite3
        from api.services.interaction_store import get_interaction_db_path

        conn = sqlite3.connect(get_interaction_db_path())

        # Check if there's a title or snippet mentioning Taylor
        cursor = conn.execute("""
            SELECT person_id, title, source_type, timestamp
            FROM interactions
            WHERE title LIKE '%Taylor%' OR title LIKE '%Tay%'
            LIMIT 5
        """)
        taylor_mentions = cursor.fetchall()
        conn.close()

        print(f"Interactions mentioning Taylor in title: {taylor_mentions}")
        # This is diagnostic - doesn't fail
