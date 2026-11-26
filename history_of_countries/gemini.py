"""Quota deferral shared by Gemini stages."""
from .core import PipelineError

class QuotaDeferred(PipelineError):
    pass
