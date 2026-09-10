"""Outline rendering - Idea11y Section 4.1 (Design Goal 1).

The paper transforms board content "into a header-subheader-bullet list format, following BLV
users' conventional practice of organizing ideas on document editors ... this way, screen reader
users can easily navigate to different clusters and notes using familiar keyboard shortcuts (e.g.
'H'/'Shift+H' in JAWS/NVDA to navigate by heading levels)."

That is the whole point of this module: emit **real heading levels**, not a custom tree widget.
The server produces a structure the client renders as h1 / h2 / ul-li, so what the user navigates
is the browser's own heading list.
"""

from __future__ import annotations

from typing import Any

from app.hierarchy.tree import Hierarchy


def to_outline(hierarchy: Hierarchy) -> dict[str, Any]:
    """Serialize the hierarchy into the outline structure the front end renders.

    {
      "overview": {...},
      "subjects": [
        {"id", "name", "level": 1,
         "topics": [
           {"id", "name", "level": 2, "summary": "...",
            "notes": [{"id", "text", "note_type", "created_at", "quality_score"}]}
         ]}
      ]
    }
    """
    raise NotImplementedError


def to_markdown(hierarchy: Hierarchy) -> str:
    """Same outline as markdown headings and bullets.

    Idea11y offered "Save as Word Document" so users could take the outline into the editor they
    already work in. This is that export, in a format that converts cleanly.
    """
    raise NotImplementedError


def announcement_for_node(node: Any, verbosity: str = "normal") -> str:
    """The string a screen reader should hear for one node.

    Identifying information first: "Deadlock, topic, 6 notes" rather than
    "Topic containing 6 notes called Deadlock".
    """
    raise NotImplementedError
