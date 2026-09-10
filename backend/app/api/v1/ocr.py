"""OCR endpoints - EchoNotes Feature 7."""

from fastapi import APIRouter, UploadFile

from app.schemas.capture import CaptureResult

router = APIRouter()


@router.post("/check")
async def check_image(file: UploadFile):
    """Assess a photo before OCR and return spoken guidance if it is unusable."""
    raise NotImplementedError


@router.post("/capture", response_model=CaptureResult)
async def capture_image(file: UploadFile):
    """OCR the image, then run the same Understand -> Organize -> Store -> Respond stages."""
    raise NotImplementedError
