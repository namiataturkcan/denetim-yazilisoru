"""Readable mismatch summaries; the comparison result and exports stay untouched."""
from difflib import SequenceMatcher
from html import escape
import re

from entry_comparison import LABELS, folded, member_name, member_province, ministry_identity, text


def group_mismatches(items):
    groups = {}
    for item in items:
        identity = tuple(text(item[key]) for key in ('document', 'case', 'kkbs_row', 'ebys_row'))
        groups.setdefault(identity, []).append(item)
    return list(groups.values())


def _html(value):
    # Uploaded cell text must remain text, including inside the source details.
    return escape(str(value)).replace('\n', '<br>')


def highlighted_pair(left, right, *, provinces=False):
    """Word-level visual differences, preserving the full original text on each side."""
    values = (text(left), text(right))
    tokens = [list(re.finditer(r'\w+|[^\w\s]', value)) for value in values]
    keys = [[folded(t.group()) or t.group() for t in side] for side in tokens]
    spans = [[], []]
    if max(map(len, tokens)) > 4000:
        # Bound rendering work for oversized cells; never truncate the evidence.
        if keys[0] != keys[1]:
            spans = [[(0, len(value))] for value in values]
    else:
        for operation, a, b, c, d in SequenceMatcher(None, *keys).get_opcodes():
            if operation == 'equal':
                continue
            for side, start, end in ((0, a, b), (1, c, d)):
                if start < end:
                    spans[side].append((tokens[side][start].start(), tokens[side][end-1].end()))
    rendered = []
    for value, ranges in zip(values, spans):
        if provinces:
            # A directory violation can be identical in both registers; still
            # mark the owner province, without marking places in the narrative.
            province = member_province(value) or (value if re.fullmatch(r'[^\W\d_]+', value) else '')
            match = re.search(r'\b' + re.escape(province) + r'\b', value) if province else None
            if match:
                ranges.append(match.span())
        merged = []
        for start, end in sorted(ranges):
            if merged and start <= merged[-1][1]:
                merged[-1] = (merged[-1][0], max(end, merged[-1][1]))
            else:
                merged.append((start, end))
        parts, offset = [], 0
        for start, end in merged:
            parts.extend((_html(value[offset:start]), '<mark class="entry-changed">',
                          _html(value[start:end]), '</mark>'))
            offset = end
        parts.append(_html(value[offset:]))
        rendered.append(''.join(parts) if value else '<span class="entry-empty">Bilgi yok</span>')
    return rendered


def _description(item, recipients):
    if item['field'] == 'member':
        values = [member_name(item[side]) for side in ('kkbs', 'ebys')]
    elif item['field'] == 'ministry':
        values = [ministry_identity(item[side], recipients)[0] for side in ('kkbs', 'ebys')]
    else:
        values = []
    if values and all(values):
        return (f'<span class="entry-explanation"><b>{_html(LABELS[item["field"]])} farklı:</b> '
                f'KKBS: {_html(values[0])} · EBYS: {_html(values[1])}</span>')
    return f'<span class="entry-explanation">{_html(item["explanation"])}</span>'


def mismatch_table(groups, recipients):
    parts = ['<table class="entry-review-table"><thead><tr><th scope="col">Evrak No</th>'
             '<th scope="col">Açıklama</th></tr></thead><tbody>']
    for items in groups:
        parts.append(f'<tr><td class="entry-document">{_html(items[0]["document"])}</td><td>'
                     '<details class="entry-review-details"><summary>'
                     + ''.join(_description(item, recipients) for item in items) + '</summary>')
        # A combined subject cell may support both findings. Show that text once.
        pairs = {}
        for item in items:
            pairs.setdefault((text(item['kkbs']), text(item['ebys'])), []).append(LABELS[item['field']])
        columns = [[], []]
        for (left, right), fields in pairs.items():
            for side, marked in enumerate(highlighted_pair(left, right, provinces=LABELS['province'] in fields)):
                label = f'<h5>{_html(" / ".join(fields))}</h5>' if len(pairs) > 1 else ''
                columns[side].append(f'<section>{label}<p class="entry-source-text">{marked}</p></section>')
        parts.append('<div class="entry-comparison-pair">')
        for side, name in enumerate(('KKBS', 'EBYS')):
            parts.append(f'<div class="entry-source-box"><h4>{name}</h4>{"".join(columns[side])}</div>')
        parts.append('</div></details></td></tr>')
    parts.append('</tbody></table>')
    return ''.join(parts)


def writing_suggestions_table(items):
    parts = ['<table class="entry-review-table entry-writing-table"><thead><tr>'
             '<th scope="col">Evrak No</th><th scope="col">Olan</th>'
             '<th scope="col">Olması gereken</th></tr></thead><tbody>']
    for item in items:
        original, start, end = item['summary'], item['start'], item['end']
        # Include context, but do not repeat a whole long summary for each edit.
        left = max(0, start-55)
        right = min(len(original), end+55)
        prefix = ('…' if left else '') + original[left:start]
        suffix = original[end:right] + ('…' if right < len(original) else '')
        parts.append(f'<tr><td class="entry-document">{_html(item["document"]) or "Evrak no yok"}</td>')
        for field in ('before', 'after'):
            parts.append(f'<td><p class="entry-writing-text">{_html(prefix)}'
                         f'<mark class="entry-writing-change">{_html(item[field])}</mark>{_html(suffix)}</p>')
            if field == 'after':
                conditional = '<b>Bağlama bağlı öneri.</b> ' if item['conditional'] else ''
                parts.append(f'<p class="entry-writing-reason">{conditional}{_html(item["reason"])}</p>')
            parts.append('</td>')
        parts.append('</tr>')
    parts.append('</tbody></table>')
    return ''.join(parts)
