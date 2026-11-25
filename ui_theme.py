"""Presentation only: no document, session, or analysis data is cached here."""
from functools import lru_cache
from html import escape
from pathlib import Path

UI_RELEASE = '2026.11.25.2'
_STYLE = Path(__file__).with_name('streamlit_style.css')


@lru_cache(maxsize=1)
def _read_stylesheet(modified_ns):
    return _STYLE.read_text(encoding='utf-8')


def stylesheet():
    # Reuse the static asset on widget reruns; editing it refreshes the cache.
    return _read_stylesheet(_STYLE.stat().st_mtime_ns)


def page_header(title, subtitle):
    return (f'<header class="hero"><div class="hero-title-row"><h1>{escape(title)}</h1>'
            f'<span class="release-tag">Sürüm: {UI_RELEASE}</span></div>'
            f'<p>{escape(subtitle)}</p></header>')


_ICONS = {
    'review': '<path d="M14 3H6a2 2 0 0 0-2 2v14a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V9z"/><path d="M14 3v6h6M8 14l2 2 5-5M8 18h7"/>',
    'incoming': '<rect x="4" y="4" width="16" height="17" rx="2"/><path d="M8 2v4m8-4v4M8 11h8M8 15h5M8 18h3"/>',
    'reader': '<rect x="2" y="4" width="8" height="16" rx="2"/><rect x="14" y="4" width="8" height="16" rx="2"/><path d="M5 9h2m-2 4h2m10-4h2m-2 4h2M10 16h4"/>',
}


def module_card(kind, number, eyebrow, title, description, tags):
    icon = ('<svg width="26" height="26" viewBox="0 0 24 24" fill="none" stroke="currentColor" '
            'stroke-width="1.6" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">'
            + _ICONS[kind] + '</svg>')
    chips = ''.join(f'<span>{escape(tag)}</span>' for tag in tags)
    return (f'<section class="module-card"><div class="module-top"><span class="module-icon {kind}">{icon}</span>'
            f'<span class="module-number">{escape(number)} · {escape(eyebrow)}</span></div>'
            f'<h2>{escape(title)}</h2><p>{escape(description)}</p><div class="module-tags">{chips}</div></section>')
