"""Contact endpoints (Phase 5, Team Member 3).

    GET    /api/v1/contacts              everyone mentioned in notes
    POST   /api/v1/contacts              create one directly
    GET    /api/v1/contacts/{id}         one contact, with suggested actions
    PATCH  /api/v1/contacts/{id}         add an email or phone
    DELETE /api/v1/contacts/{id}
    GET    /api/v1/contacts/{id}/notes   which notes mention them
    GET    /api/v1/contacts/notes/{id}   who a note mentions

Contacts are created automatically from the people Team Member 1's extractor
finds; these endpoints are for reading them and for filling in details the
notes did not contain.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.orm import Session

from app.db.session import get_db
from app.reminders.contacts import ContactService
from app.schemas.reminders import (
    ContactActionOut,
    ContactCreate,
    ContactDetailOut,
    ContactOut,
    ContactUpdate,
)

router = APIRouter()


def _spoken(service: ContactService, contact) -> str:
    mentions = len(contact.mentions)
    parts = [f"{contact.name}, mentioned in {mentions} note{'s' if mentions != 1 else ''}."]
    if contact.phone:
        parts.append(f"Phone {contact.phone}.")
    if contact.email:
        parts.append(f"Email {contact.email}.")
    return " ".join(parts)


@router.get("", response_model=list[ContactOut], summary="List contacts")
def list_contacts(
    limit: int = Query(default=200, ge=1, le=500),
    offset: int = Query(default=0, ge=0),
    db: Session = Depends(get_db),
):
    service = ContactService(db)
    return [ContactOut(**service.to_dict(c)) for c in service.list(limit=limit, offset=offset)]


@router.post(
    "",
    response_model=ContactOut,
    status_code=status.HTTP_201_CREATED,
    summary="Create a contact",
)
def create_contact(payload: ContactCreate, db: Session = Depends(get_db)):
    service = ContactService(db)
    try:
        contact, _created = service.get_or_create(payload.name)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    service.update(contact.id, email=payload.email, phone=payload.phone)
    db.commit()
    return ContactOut(**service.to_dict(contact))


@router.get("/notes/{note_id}", response_model=list[ContactOut], summary="Who a note mentions")
def contacts_for_note(note_id: str, db: Session = Depends(get_db)):
    service = ContactService(db)
    return [ContactOut(**service.to_dict(c)) for c in service.contacts_for_note(note_id)]


@router.get("/{contact_id}", response_model=ContactDetailOut, summary="One contact")
def get_contact(contact_id: str, db: Session = Depends(get_db)):
    service = ContactService(db)
    contact = service.get(contact_id)
    if contact is None:
        raise HTTPException(status_code=404, detail="contact not found")
    return ContactDetailOut(
        contact=ContactOut(**service.to_dict(contact)),
        actions=[ContactActionOut(**a) for a in service.suggest_actions(contact)],
        note_ids=[n.id for n in service.notes_for_contact(contact.id)],
        spoken=_spoken(service, contact),
    )


@router.get("/{contact_id}/notes", response_model=list[str], summary="Notes mentioning them")
def notes_for_contact(
    contact_id: str,
    limit: int = Query(default=50, ge=1, le=500),
    db: Session = Depends(get_db),
):
    service = ContactService(db)
    if service.get(contact_id) is None:
        raise HTTPException(status_code=404, detail="contact not found")
    return [n.id for n in service.notes_for_contact(contact_id, limit=limit)]


@router.patch("/{contact_id}", response_model=ContactOut, summary="Edit a contact")
def update_contact(contact_id: str, payload: ContactUpdate, db: Session = Depends(get_db)):
    service = ContactService(db)
    contact = service.update(
        contact_id, name=payload.name, email=payload.email, phone=payload.phone
    )
    if contact is None:
        raise HTTPException(status_code=404, detail="contact not found")
    db.commit()
    return ContactOut(**service.to_dict(contact))


@router.delete("/{contact_id}", status_code=status.HTTP_204_NO_CONTENT, summary="Delete")
def delete_contact(contact_id: str, db: Session = Depends(get_db)):
    if not ContactService(db).delete(contact_id):
        raise HTTPException(status_code=404, detail="contact not found")
    db.commit()
