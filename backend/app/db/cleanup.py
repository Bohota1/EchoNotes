"""Removing containers that nothing points at any more.

Deleting a note cascades to everything that *belongs* to it - its entities, its
understanding row, its LNT analysis, its reminders, its contact links. What does
not cascade is everything the note merely *pointed at*: the topic it was filed
under, that topic's subject, and the people it mentioned.

That is correct as a foreign-key rule and wrong as a user-visible outcome. A
topic is shared - ten notes may sit under "Databases", so deleting one must not
take the topic with it - but a foreign key cannot tell "one of ten" from "the
last one". So the database keeps them all, and every deleted note leaves a
little debris behind: an empty topic in the graph, an empty subject above it, a
contact mentioned in nothing.

This prunes what is genuinely orphaned, and only that.

**Contacts with details you added are kept.** A person with an email or a phone
number is something you deliberately filled in; losing it because the last note
mentioning them was deleted would destroy work that was never derived from the
note in the first place. A bare name with no remaining mentions is only ever a
by-product of extraction, so it goes.

**The Unfiled subject is never removed.** It is a singleton the organizer
expects to exist, and recreating it per delete would churn ids for no reason.
"""

from __future__ import annotations

import logging

from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session

from app.db.models import Contact, Note, NoteContact, Subject, Topic

logger = logging.getLogger(__name__)


def _topic_is_empty(db: Session, topic_id: str) -> bool:
    """True when no note reaches this topic by either route.

    Notes link to topics two ways after the graph redesign: the original
    `notes.topic_id` column and the `note_topics` association table. A topic is
    only orphaned when *both* are empty, or deleting a note would strand topics
    that other notes still reach by the other route.
    """
    direct = db.execute(
        select(func.count()).select_from(Note).where(Note.topic_id == topic_id)
    ).scalar_one()
    if direct:
        return False

    note_topics = Topic.__table__.metadata.tables.get("note_topics")
    if note_topics is not None:
        linked = db.execute(
            select(func.count())
            .select_from(note_topics)
            .where(note_topics.c.topic_id == topic_id)
        ).scalar_one()
        if linked:
            return False

    return True


def prune_orphans(db: Session) -> dict[str, int]:
    """Remove topics, subjects and contacts nothing references any more.

    Flushes but does not commit - the caller owns the transaction, so this runs
    inside the same one as the delete that caused the orphans. Returns what it
    removed, for logging and for tests.
    """
    removed = {"topics": 0, "subjects": 0, "contacts": 0}

    # Push the caller's pending delete to the database before counting what is
    # left. Without this the DELETE is still sitting in the session, the
    # database still sees the note and its `note_topics` rows, and every topic
    # looks occupied - so nothing is pruned and the orphans survive until some
    # later delete happens to flush first. Flushing also fires the ON DELETE
    # CASCADE that clears the link rows these counts depend on.
    db.flush()

    # --- topics with no notes left ---------------------------------------
    for topic in db.execute(select(Topic)).scalars().all():
        if _topic_is_empty(db, topic.id):
            db.delete(topic)
            removed["topics"] += 1

    db.flush()

    # --- subjects with no topics left ------------------------------------
    # After the topics above are gone, so a subject emptied by this same
    # delete is caught in the same pass rather than lingering until the next.
    for subject in db.execute(select(Subject)).scalars().all():
        if subject.is_unfiled:
            continue
        remaining = db.execute(
            select(func.count()).select_from(Topic).where(Topic.subject_id == subject.id)
        ).scalar_one()
        if not remaining:
            db.delete(subject)
            removed["subjects"] += 1

    # --- contacts mentioned in nothing, with nothing you added -----------
    orphaned = (
        select(Contact)
        .outerjoin(NoteContact, NoteContact.contact_id == Contact.id)
        .where(NoteContact.id.is_(None))
        .where(or_(Contact.email.is_(None), Contact.email == ""))
        .where(or_(Contact.phone.is_(None), Contact.phone == ""))
    )
    for contact in db.execute(orphaned).scalars().all():
        db.delete(contact)
        removed["contacts"] += 1

    db.flush()

    if any(removed.values()):
        logger.info(
            "pruned %d topic(s), %d subject(s), %d contact(s)",
            removed["topics"],
            removed["subjects"],
            removed["contacts"],
        )
    return removed


def prune_orphans_safe(db: Session) -> dict[str, int]:
    """`prune_orphans` that never raises.

    Tidying up must not be the reason a delete the user asked for fails. Left
    behind, an orphan is clutter; a failed delete is a note that would not go
    away.
    """
    try:
        return prune_orphans(db)
    except Exception:
        logger.exception("pruning orphans failed; the delete itself stands")
        return {"topics": 0, "subjects": 0, "contacts": 0}
