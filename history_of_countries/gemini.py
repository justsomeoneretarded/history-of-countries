"""Quota deferral shared by Gemini stages."""
from .core import PipelineError

class QuotaDeferred(PipelineError):
    def __init__(self,message,source="provider"):
        super().__init__(message)
        self.source=source
