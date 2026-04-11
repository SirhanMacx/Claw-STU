"""Optional standards alignment.

Stuart is designed to work independent of any institution, but many
users (teachers, homeschooling parents, students preparing for state
exams) need to map what Stuart is teaching to a recognized framework:
New York State Social Studies Framework, Common Core, C3, etc.

Standards alignment is always **optional**. A learning block may carry
zero, one, or many standard tags; the engagement loop never filters on
a standard unless the session explicitly requests it.
"""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict


class StandardAlignment(BaseModel):
    """Reference to an external standard (NYS, Common Core, etc.)."""

    model_config = ConfigDict(frozen=True)

    framework: str  # e.g., "NYS_SS_11", "CCSS_ELA", "C3"
    code: str       # e.g., "11.1a", "RH.9-10.1"
    description: str
