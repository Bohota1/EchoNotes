"""Domain exceptions.

Each carries a `spoken_message`: what the screen reader should announce. Errors that only appear
on screen are invisible to this app's users, so every failure has to be sayable.
"""


class EchoNotesError(Exception):
    spoken_message = "Something went wrong."

    def __init__(self, message: str = "", spoken_message: str | None = None):
        super().__init__(message or self.spoken_message)
        if spoken_message:
            self.spoken_message = spoken_message


class AudioCaptureError(EchoNotesError):
    spoken_message = "I could not record. Check the microphone."


class TranscriptionError(EchoNotesError):
    spoken_message = "I could not understand the recording. Try again."


class TranslationError(EchoNotesError):
    spoken_message = "I could not translate that to English."


class NoteNotFoundError(EchoNotesError):
    spoken_message = "That note no longer exists."


class RetrievalError(EchoNotesError):
    spoken_message = "I could not search your notes right now."


class OCRError(EchoNotesError):
    spoken_message = "I could not read text from that image."
