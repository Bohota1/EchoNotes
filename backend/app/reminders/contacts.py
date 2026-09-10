"""Contacts (Phase 5).

When a person is named in a note, they become a `Contact` and the note is linked
to them. That is the whole feature: recognise the same person across captures,
and let a note point at them. The brief was explicit - "keep this simple; do not
build a full contact-management application" - so there is no address book, no
sync, no groups.

Person detection is **Team Member 1's**, read from the `note_entities` rows their
`app/understanding/entities.py` wrote. This module only resolves those names to
stable identities.

**Why fuzzy matching.** ASR spells the same name differently between captures -
"Raman", "Ramen", "Professor Raman". Exact matching would scatter one person
across four contacts, and for a user who navigates by listening, four
near-identical entries in a list is worse than none. `difflib` at
`CONTACT_MATCH_CUTOFF` collapses them, using the same approach and threshold
style as Team Member 2's `find_best_name_match` for subjects and topics.

**No outbound actions.** `suggest_actions` returns things the user can choose to
do. EchoNotes never places a call or sends a message on its own: an accidental
outbound message cannot be recalled, and cannot be spotted by glancing at a
screen.
"""

from __future__ import annotations

import difflib
import logging
import re
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.config import get_settings
from app.db.models import Contact, Entity, EntityKind, Note, NoteContact

logger = logging.getLogger(__name__)

#: Titles stripped before matching, so "Professor Raman" and "Raman" are one
#: person. The title is kept in the stored display name of whichever mention
#: created the contact.
_TITLES = re.compile(
    r"^(?:prof(?:essor)?|dr|doctor|mr|mrs|ms|miss|sir|madam)\.?\s+", re.IGNORECASE
)

_EMAIL_RE = re.compile(r"[\w.+-]+@[\w-]+\.[\w.-]+")
#: Deliberately loose. Spoken phone numbers arrive from ASR in many shapes, and
#: a missed number is a worse outcome here than a false positive the user can
#: ignore. Not using `phonenumbers` keeps the dependency footprint unchanged.
_PHONE_RE = re.compile(r"(?:\+\d{1,3}[\s-]?)?(?:\(?\d{3}\)?[\s.-]?)\d{3}[\s.-]?\d{4}\b")


def normalize_name(name: str) -> str:
    """The match key: lowercased, title-stripped, whitespace-collapsed."""
    cleaned = _TITLES.sub("", (name or "").strip())
    cleaned = re.sub(r"[^\w\s'-]", "", cleaned)
    return re.sub(r"\s+", " ", cleaned).strip().lower()


class ContactService:
    """Contact resolution and note linking. Flushes, never commits."""

    def __init__(self, db: Session):
        self.db = db

    # --- resolution ------------------------------------------------------

    def find_exact(self, name: str) -> Contact | None:
        key = normalize_name(name)
        if not key:
            return None
        statement = select(Contact).where(Contact.normalized_name == key)
        return self.db.execute(statement).scalars().first()

    def find_best_match(self, name: str, cutoff: float | None = None) -> Contact | None:
        """Exact match first, then the closest name above the cutoff."""
        exact = self.find_exact(name)
        if exact is not None:
            return exact

        key = normalize_name(name)
        if not key:
            return None

        cutoff = cutoff if cutoff is not None else get_settings().contact_match_cutoff
        contacts = self.list()
        keys = {c.normalized_name: c for c in contacts}
        matches = difflib.get_close_matches(key, list(keys), n=1, cutoff=cutoff)
        return keys[matches[0]] if matches else None

    def get_or_create(self, name: str) -> tuple[Contact, bool]:
        """Resolve a spoken name to a contact, creating one if it is new."""
        display = " ".join((name or "").split()).strip()
        if not display:
            raise ValueError("contact name cannot be empty")

        existing = self.find_best_match(display)
        if existing is not None:
            return existing, False

        contact = Contact(name=display, normalized_name=normalize_name(display))
        self.db.add(contact)
        self.db.flush()
        logger.info("created contact %s (%s)", contact.name, contact.id)
        return contact, True

    # --- linking ---------------------------------------------------------

    def link(self, note_id: str, contact_id: str, mention_text: str | None = None) -> NoteContact | None:
        """Link a note to a contact, ignoring a link that already exists."""
        statement = (
            select(NoteContact)
            .where(NoteContact.note_id == note_id)
            .where(NoteContact.contact_id == contact_id)
        )
        existing = self.db.execute(statement).scalars().first()
        if existing is not None:
            return existing

        link = NoteContact(
            note_id=note_id, contact_id=contact_id, mention_text=mention_text
        )
        self.db.add(link)
        self.db.flush()
        return link

    def link_from_note(self, note: Note) -> list[Contact]:
        """Create and link every person Team Member 1's extractor found.

        Idempotent, so reprocessing a note does not duplicate links.
        """
        statement = (
            select(Entity)
            .where(Entity.note_id == note.id)
            .where(Entity.kind == EntityKind.PERSON.value)
        )
        people = list(self.db.execute(statement).scalars().all())

        linked: list[Contact] = []
        for entity in people:
            name = (entity.value or "").strip()
            if not name:
                continue
            try:
                contact, _created = self.get_or_create(name)
            except ValueError:
                continue
            self.link(note.id, contact.id, mention_text=name)
            if contact not in linked:
                linked.append(contact)

        # Contact details spoken in the same note belong to whoever it named.
        # With exactly one person mentioned the attribution is unambiguous; with
        # several it is a guess, so it is skipped rather than risked.
        if len(linked) == 1:
            self._absorb_details(linked[0], note.cleaned_text or "")

        if linked:
            logger.info("linked %d contact(s) to note %s", len(linked), note.id)
        return linked

    def _absorb_details(self, contact: Contact, text: str) -> None:
        """Fill in an email or phone found in the note, without overwriting."""
        if contact.email is None:
            email = _EMAIL_RE.search(text)
            if email:
                contact.email = email.group(0)
        if contact.phone is None:
            phone = _PHONE_RE.search(text)
            if phone:
                contact.phone = phone.group(0).strip()
        self.db.flush()

    # --- read ------------------------------------------------------------

    def get(self, contact_id: str) -> Contact | None:
        return self.db.get(Contact, contact_id)

    def list(self, limit: int = 200, offset: int = 0) -> list[Contact]:
        statement = select(Contact).order_by(Contact.name.asc()).limit(limit).offset(offset)
        return list(self.db.execute(statement).scalars().all())

    def notes_for_contact(self, contact_id: str, limit: int = 50) -> list[Note]:
        """Which notes mention this person - answers "what did I note about Sarah"."""
        statement = (
            select(Note)
            .join(NoteContact, NoteContact.note_id == Note.id)
            .where(NoteContact.contact_id == contact_id)
            .order_by(Note.created_at.desc())
            .limit(limit)
        )
        return list(self.db.execute(statement).scalars().all())

    def contacts_for_note(self, note_id: str) -> list[Contact]:
        statement = (
            select(Contact)
            .join(NoteContact, NoteContact.contact_id == Contact.id)
            .where(NoteContact.note_id == note_id)
            .order_by(Contact.name.asc())
        )
        return list(self.db.execute(statement).scalars().all())

    # --- update / delete --------------------------------------------------

    def update(
        self,
        contact_id: str,
        *,
        name: str | None = None,
        email: str | None = None,
        phone: str | None = None,
    ) -> Contact | None:
        contact = self.get(contact_id)
        if contact is None:
            return None
        if name is not None:
            contact.name = name
            contact.normalized_name = normalize_name(name)
        if email is not None:
            contact.email = email
        if phone is not None:
            contact.phone = phone
        self.db.flush()
        return contact

    def delete(self, contact_id: str) -> bool:
        contact = self.get(contact_id)
        if contact is None:
            return False
        self.db.delete(contact)
        self.db.flush()
        return True

    # --- serialisation ----------------------------------------------------

    def to_dict(self, contact: Contact, include_counts: bool = True) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "id": contact.id,
            "name": contact.name,
            "normalized_name": contact.normalized_name,
            "email": contact.email,
            "phone": contact.phone,
            "created_at": contact.created_at.isoformat() if contact.created_at else None,
        }
        if include_counts:
            payload["mention_count"] = len(contact.mentions)
        return payload

    def suggest_actions(self, contact: Contact) -> list[dict[str, str]]:
        """Actions the user may choose. Never executed automatically."""
        actions: list[dict[str, str]] = []
        if contact.phone:
            actions.append(
                {
                    "action": "call",
                    "target": contact.phone,
                    "spoken": f"Call {contact.name} on {contact.phone}?",
                }
            )
            actions.append(
                {
                    "action": "message",
                    "target": contact.phone,
                    "spoken": f"Send {contact.name} a message?",
                }
            )
        if contact.email:
            actions.append(
                {
                    "action": "email",
                    "target": contact.email,
                    "spoken": f"Email {contact.name} at {contact.email}?",
                }
            )
        return actions


def link_contacts_safe(db: Session, note: Note) -> list[Contact]:
    """Contact linking that never raises, for the capture pipeline."""
    try:
        return ContactService(db).link_from_note(note)
    except Exception:
        logger.exception("contact linking failed for note %s; note kept", note.id)
        return []
