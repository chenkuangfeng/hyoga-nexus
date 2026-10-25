"""Vendor-neutral errors contracts; no SDK, database or platform imports."""
from __future__ import annotations


class RuntimeFault(Exception):
    """Only stable codes cross execution boundaries; never retain SDK exceptions."""
    def __init__(self, code: str):
        self.code = code
        super().__init__(code)
