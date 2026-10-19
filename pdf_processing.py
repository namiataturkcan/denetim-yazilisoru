"""Bound PDF rendering work and serialize PyMuPDF across web sessions."""
from functools import wraps
from threading import RLock


MAX_IMAGE_EDGE = 2200
_pdf_lock = RLock()


def serialized_pdf_work(function):
    @wraps(function)
    def call(*args, **kwargs):
        with _pdf_lock:
            return function(*args, **kwargs)
    return call


def render_scale(page, maximum=2.5):
    return min(maximum, MAX_IMAGE_EDGE / max(page.rect.width, page.rect.height))
