"""Obsolete: tested the old Idea11y Subject/Topic hierarchy design
(app/hierarchy/*, app/understanding/organizer.py), replaced end-to-end by
app/graph/* in the NexaNota redesign - see app/api/v1/router.py's docstring.

This file is safe to delete outright. It is left as a skip stub, rather than
actually deleted, only because the file bridge to this machine could not run
a delete/move command when this cleanup was done (device_bash was down) - so
Claude wrote this stub via the same file-write path used to push every other
change instead. Deleting it by hand (or asking Claude to, once the bridge is
back) is fine and has zero effect on the app.
"""

import pytest

pytest.skip(
    "obsolete: old hierarchy/organizer/summarization design, replaced by app/graph/*",
    allow_module_level=True,
)
