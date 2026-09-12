"""Orphan cleanup after a note is deleted - `app.db.cleanup`.

Deleting a note cascades to what belongs to it. What it *pointed at* - the topic
it was filed under, that topic's subject, the people it mentioned - cannot
cascade, because those are shared: ten notes may sit under one topic. So they
are pruned explicitly when nothing references them any more.
"""

from __future__ import annotations

from app.db.cleanup import prune_orphans
from app.db.models import Contact, Note, Subject, Topic

NOTE_A = "Call Sarah about the database project meeting."
NOTE_B = "Deadlock detection needs a wait for graph in operating systems."


class TestDeleteCleansUpContainers:
    def test_topics_emptied_by_a_delete_are_removed(self, client, db_session):
        note = client.post(
            "/api/v1/understand", json={"text": NOTE_B, "persist": True}
        ).json()
        assert db_session.query(Topic).count() > 0

        assert client.delete(f"/api/v1/notes/{note['note_id']}").status_code == 204
        db_session.expire_all()
        assert db_session.query(Topic).count() == 0

    def test_subject_left_empty_is_removed_too(self, client, db_session):
        note = client.post(
            "/api/v1/understand", json={"text": NOTE_B, "persist": True}
        ).json()
        client.delete(f"/api/v1/notes/{note['note_id']}")
        db_session.expire_all()

        remaining = db_session.query(Subject).filter(~Subject.is_unfiled).count()
        assert remaining == 0

    def test_a_topic_other_notes_still_use_is_kept(self, client, db_session):
        """The reason none of this can be a foreign-key cascade: a topic is
        shared, and deleting one of its notes must not take it from the rest."""
        first = client.post(
            "/api/v1/understand", json={"text": NOTE_B, "persist": True}
        ).json()
        client.post("/api/v1/understand", json={"text": NOTE_B, "persist": True})

        before = db_session.query(Topic).count()
        assert before > 0

        client.delete(f"/api/v1/notes/{first['note_id']}")
        db_session.expire_all()
        assert db_session.query(Topic).count() == before, (
            "a topic the surviving note still uses was pruned"
        )


class TestContactsAreTreatedDifferently:
    def test_a_bare_extracted_contact_is_removed(self, client, db_session):
        note = client.post(
            "/api/v1/understand", json={"text": NOTE_A, "persist": True}
        ).json()
        assert db_session.query(Contact).count() >= 1

        client.delete(f"/api/v1/notes/{note['note_id']}")
        db_session.expire_all()
        assert db_session.query(Contact).count() == 0

    def test_a_contact_you_filled_in_survives(self, client, db_session):
        """A phone number is something the user typed. It was never derived
        from the note, so deleting the note must not destroy it."""
        note = client.post(
            "/api/v1/understand", json={"text": NOTE_A, "persist": True}
        ).json()
        contact = db_session.query(Contact).first()
        contact.phone = "555-0100"
        db_session.commit()

        client.delete(f"/api/v1/notes/{note['note_id']}")
        db_session.expire_all()

        kept = db_session.query(Contact).all()
        assert len(kept) == 1
        assert kept[0].phone == "555-0100"

    def test_an_email_also_keeps_a_contact(self, client, db_session):
        note = client.post(
            "/api/v1/understand", json={"text": NOTE_A, "persist": True}
        ).json()
        contact = db_session.query(Contact).first()
        contact.email = "sarah@example.com"
        db_session.commit()

        client.delete(f"/api/v1/notes/{note['note_id']}")
        db_session.expire_all()
        assert db_session.query(Contact).count() == 1


class TestPruneDirectly:
    def test_pruning_an_empty_database_does_nothing(self, db_session):
        assert prune_orphans(db_session) == {
            "topics": 0,
            "subjects": 0,
            "contacts": 0,
        }

    def test_it_reports_what_it_removed(self, client, db_session):
        note = client.post(
            "/api/v1/understand", json={"text": NOTE_B, "persist": True}
        ).json()
        db_session.query(Note).filter(Note.id == note["note_id"]).delete()

        removed = prune_orphans(db_session)
        db_session.commit()
        assert removed["topics"] > 0

    def test_the_unfiled_subject_is_never_removed(self, db_session):
        """The organizer expects it to exist; recreating it on every delete
        would churn ids for nothing."""
        from app.db.repositories import SubjectRepository

        unfiled = SubjectRepository(db_session).get_or_create_unfiled()
        db_session.commit()

        prune_orphans(db_session)
        db_session.commit()
        db_session.expire_all()

        assert db_session.query(Subject).filter(Subject.id == unfiled.id).count() == 1

    def test_pruning_never_raises_into_a_delete(self, client, monkeypatch):
        """Tidying up must not be the reason a delete the user asked for
        fails."""
        from app.db import cleanup

        monkeypatch.setattr(
            cleanup,
            "prune_orphans",
            lambda *a, **k: (_ for _ in ()).throw(RuntimeError("boom")),
        )
        note = client.post(
            "/api/v1/understand", json={"text": NOTE_A, "persist": True}
        ).json()
        assert client.delete(f"/api/v1/notes/{note['note_id']}").status_code == 204
