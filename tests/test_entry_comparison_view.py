from copy import deepcopy
from html.parser import HTMLParser

from entry_comparison_view import group_mismatches, highlighted_pair, mismatch_table
from test_entry_comparison import RECIPIENTS, compare, record


class Parsed(HTMLParser):
    def __init__(self, html):
        super().__init__()
        self.tags, self.content, self.marked = [], [], []
        self.in_mark = False
        self.feed(html)

    def handle_starttag(self, tag, attrs):
        self.tags.append(tag)
        assert not any(name.startswith('on') for name, _ in attrs)
        if tag == 'mark':
            self.in_mark = True
        if tag == 'br':
            self.handle_data('\n')

    def handle_endtag(self, tag):
        if tag == 'mark':
            self.in_mark = False

    def handle_data(self, data):
        self.content.append(data)
        if self.in_mark:
            self.marked.append(data)


def test_ministry_summary_keeps_the_addressee_and_full_source_evidence():
    # A ministry mentioned in the subject must not replace the actual addressee.
    left = "Bir milletvekilinin Çevre Bakanı hakkındaki sorularına ilişkin Çalışma ve Sosyal Güvenlik Bakanı'ndan yazılı soru önergesi"
    right = "Çevre Bakanı'na yazılı sorusu"
    report = compare([record(ministry=left)], [record(ministry=right)])
    saved = deepcopy(report)
    html = mismatch_table(group_mismatches(report['issues']), RECIPIENTS)
    assert 'KKBS: Çalışma ve Sosyal Güvenlik Bakanlığı' in html
    assert 'EBYS: Çevre, Şehircilik ve İklim Değişikliği Bakanlığı' in html
    content = ''.join(Parsed(html).content)
    assert left in content and right in content
    assert report == saved


def test_diff_highlights_changed_words_and_preserves_full_source_text():
    left = 'Milletvekili Cengiz Çiçek\nAdalet Bakanı'
    right = 'Milletvekili Çiçek Otlu\nAdalet Bakanı'
    a, b = map(Parsed, highlighted_pair(left, right))
    assert ''.join(a.content) == left and ''.join(b.content) == right
    assert ''.join(a.marked) == 'Cengiz' and ''.join(b.marked) == 'Otlu'
    assert not Parsed(highlighted_pair('ÇİÇEK OTLU', 'Çiçek Otlu')[0]).marked


def test_uploaded_values_are_text_even_in_headers_and_expanded_source():
    payload = '<img src=x onerror=alert(1)>\n<script>alert(1)</script>&'
    item = dict(status='uyari', field='member', document=payload, case='7/12345',
                kkbs=payload, ebys='İstanbul Milletvekili Çiçek Otlu’nun, bir konuya ilişkin önergesi',
                kkbs_row=3, ebys_row=8, explanation=payload)
    html = mismatch_table([[item]], RECIPIENTS)
    parsed = Parsed(html)
    assert 'img' not in parsed.tags and 'script' not in parsed.tags
    assert payload in ''.join(parsed.content)
    assert '7/12345' not in html and 'Excel satırı' not in html


def test_shared_subject_is_shown_once_per_side_for_two_findings():
    left = "İstanbul Milletvekili Çiçek Otlu'nun, bir konuya ilişkin Adalet Bakanı'ndan yazılı soru önergesi"
    right = "İstanbul Milletvekili Cengiz Çiçek'in, bir konuya ilişkin Çevre Bakanı'ndan yazılı soru önergesi"
    report = compare([record(member=left, ministry=left)], [record(member=right, ministry=right)])
    assert len(report['issues']) == 2
    html = mismatch_table(group_mismatches(report['issues']), RECIPIENTS)
    assert html.count('<details ') == 1
    assert html.count('class="entry-source-box"') == 2
    content = ''.join(Parsed(html).content)
    assert content.count(left) == 1 and content.count(right) == 1


def test_writing_table_preserves_extra_spaces_and_escapes_uploaded_text():
    from entry_comparison_view import writing_suggestions_table
    value = '<img src=x onerror=alert(1)> iki  kelime'
    start = value.index('  ')
    finding = dict(document='<script>bad</script>', summary=value, start=start, end=start+2,
                   before='  ', after=' ', reason='İki boşluk yerine bir boşluk.', conditional=False)
    html = writing_suggestions_table([finding])
    parsed = Parsed(html)
    assert 'script' not in parsed.tags and 'img' not in parsed.tags
    assert '<mark class="entry-writing-change">  </mark>' in html
    assert '<mark class="entry-writing-change"> </mark>' in html
    assert value in ''.join(parsed.content)
