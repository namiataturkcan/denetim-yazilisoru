"""Evidence-based markings. Never guess a location when a quote cannot be found."""
import html
import re

import pymupdf


def marked_text(text, checks, page):
    spans = []
    for check in checks:
        quote = check['quote'].strip()
        if check['page'] != page or check['status'] != 'uyari' or not quote:
            continue
        pattern = r'\s+'.join(re.escape(w) for w in quote.split())
        context = check.get('highlight_context', '')
        context_spans = []
        if context:
            context_pattern = r'\s+'.join(re.escape(w) for w in context.split())
            context_spans = [(m.start(), m.end()) for m in re.finditer(context_pattern, text)]
        spans.extend((m.start(), m.end()) for m in re.finditer(pattern, text)
                     if not context or any(start <= m.start() and m.end() <= end for start, end in context_spans))
    merged = []
    for start, end in sorted(spans):
        if merged and start <= merged[-1][1]:
            merged[-1] = (merged[-1][0], max(end, merged[-1][1]))
        else:
            merged.append((start, end))
    out = []; cursor = 0
    for start, end in merged:
        out.extend([html.escape(text[cursor:start]), '<mark class="issue-text">', html.escape(text[start:end]), '</mark>'])
        cursor = end
    out.append(html.escape(text[cursor:]))
    return '<div class="document-text">' + ''.join(out) + '</div>'


def find_quote(page, quote, context, textpage=None):
    if not quote:
        return []
    quads = page.search_for(quote, quads=True, textpage=textpage)
    if context:
        anchors = page.search_for(context, quads=True, textpage=textpage)
        quads = [q for q in quads if any((q.rect & a.rect).get_area() > q.rect.get_area() * 0.5 for a in anchors)]
    return quads


def annotate_pdf(data, checks):
    """Return a separate annotated PDF, preview images, and explicit unmapped findings."""
    images = []; locations = []; missing = []
    with pymupdf.open(stream=data, filetype='pdf') as doc:
        for page_index, page in enumerate(doc):
            ocr = None; ocr_attempted = False
            for number, check in enumerate(checks, 1):
                if check['page'] != page_index + 1 or check['status'] != 'uyari':
                    continue
                quote = check['quote'].strip()
                context = check.get('highlight_context', '')
                quads = find_quote(page, quote, context)
                if quote and not quads:
                    if not ocr_attempted:
                        ocr_attempted = True
                        # OCR is used only to locate findings, never as model input.
                        for language in ('tur+eng', 'eng'):
                            try:
                                ocr = page.get_textpage_ocr(language=language, dpi=200, full=True)
                                break
                            except (RuntimeError, ValueError):
                                continue
                    if ocr is not None:
                        quads = find_quote(page, quote, context, textpage=ocr)
                if not quads:
                    missing.append({'number': number, 'page': page_index + 1,
                                    'reason': 'Belgede bulunmayan alan' if not quote else 'Alıntının sayfadaki konumu doğrulanamadı'})
                    continue
                annotation = page.add_highlight_annot(quads)
                annotation.set_colors(stroke=(0.95, 0.16, 0.2))
                annotation.set_opacity(0.35)
                annotation.set_info(title=f'Kontrol {number}', content=check['explanation'])
                annotation.update()
                for q in quads:
                    border = page.add_rect_annot(q.rect)
                    border.set_colors(stroke=(0.75, 0.06, 0.1))
                    border.set_border(width=0.8)
                    border.update()
                locations.append({'number': number, 'page': page_index + 1, 'rects': [list(q.rect) for q in quads]})
            scale = min(2, 2200 / max(page.rect.width, page.rect.height))
            images.append(page.get_pixmap(matrix=pymupdf.Matrix(scale, scale), alpha=False).tobytes('png'))
        output = doc.tobytes(garbage=3, deflate=True)
    return {'pdf': output, 'images': images, 'locations': locations, 'missing': missing}
