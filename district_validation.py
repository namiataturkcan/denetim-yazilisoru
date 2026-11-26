"""Source-bound checks of explicit district mentions in a manual KKBS summary.

The caller must supply a verified directory. No built-in or network-derived
place names, and absence from a historical list is never proof of current status.
"""
import re
from collections import defaultdict

from entry_comparison import folded, one_edit
from recipient_validation import normalize

LETTERS = 'A-Za-zÇĞİÖŞÜçğıöşüÂÎÛâîû'
WORD = rf'[{LETTERS}0-9]+'
TOKEN = re.compile(rf'\b{WORD}\b')
DISTRICT = re.compile(r'\bilçe(?:si(?:nin|ne|nde(?:ki)?|nden)?|leri(?:nin|ne|nde(?:ki)?|nden)?|lerde(?:ki)?|lerden)?\b', re.I)
GENERIC = {'bir', 'bu', 'şu', 'o', 'bazı', 'birçok', 'birkaç', 'tüm', 'bütün', 'her',
           'diğer', 'komşu', 'ilgili', 'kendi', 'aynı', 'hangi', 'çeşitli', 'merkez',
           'iki', 'üç', 'dört', 'beş', 'altı', 'yedi', 'sekiz', 'dokuz', 'on',
           'yirmi', 'otuz', 'kırk', 'elli', 'altmış', 'yetmiş', 'seksen', 'doksan', 'yüz', 'bin'}


def compact_name(name):
    # Numeric spelling is a language transformation, not an extra place list;
    # the resulting name must still occur in the user's source.
    parts = folded(name).split()
    if len(parts) > 1 and parts[0].isdigit() and 0 < int(parts[0]) < 100:
        units = ('', 'bir', 'iki', 'uc', 'dort', 'bes', 'alti', 'yedi', 'sekiz', 'dokuz')
        tens = ('', 'on', 'yirmi', 'otuz', 'kirk', 'elli', 'altmis', 'yetmis', 'seksen', 'doksan')
        number = int(parts[0])
        parts[0] = tens[number//10] + units[number % 10]
    return ''.join(parts)


class DistrictDirectory:
    def __init__(self, reference):
        self.source = dict(reference['source'])
        self.label = self.source['file']
        self.url = self.source['url']
        self.provinces = dict(reference['provinces'])
        if not self.provinces or any(not cities or not isinstance(cities, list)
                                     or any(not isinstance(c, str) or not c.strip() for c in cities)
                                     for cities in self.provinces.values()):
            raise ValueError('İlçe referans listesi boş veya geçersiz.')
        self.exact, self.ascii = defaultdict(set), defaultdict(set)
        for province, districts in self.provinces.items():
            for district in districts:
                self.exact[normalize(district)].add((province, district))
                self.ascii[compact_name(district)].add((province, district))
        self.max_words = max(len(d.split()) for ds in self.provinces.values() for d in ds)

    def _name_before(self, value, end):
        prefix = value[:end].rstrip()
        tokens = list(TOKEN.finditer(prefix[max(0, len(prefix)-100):]))
        offset = max(0, len(prefix)-100)
        if not tokens or tokens[-1].end()+offset != len(prefix):
            return None
        # Also keep source-backed split/numeric spellings whole, so e.g.
        # "Marmara Ereğlisi" is not misread as the unrelated suffix "Ereğlisi".
        for count in range(min(max(self.max_words, 3), len(tokens)), 0, -1):
            start = tokens[-count].start()+offset
            name = prefix[start:]
            if re.fullmatch(rf'{WORD}(?:\s+{WORD})*', name) and (
                    normalize(name) in self.exact or compact_name(name) in self.ascii):
                return start, len(prefix), name
        if len(tokens) >= 2 and tokens[-2].group().isdigit():
            start = tokens[-2].start()+offset
            return start, len(prefix), prefix[start:]
        last = tokens[-1]
        return last.start()+offset, last.end()+offset, last.group()

    def _province_before(self, value, start):
        # Only an immediately attached ownership/administrative phrase binds a
        # province: "X'in Y ilçesi" / "X ili Y ilçesi". Narrative mentions don't.
        prefix = value[max(0, start-100):start]
        for province in self.provinces:
            pattern = (r'\b' + re.escape(province)
                       + r"(?:['’‘ʼ](?:nın|nin|nun|nün|ın|in|un|ün)|\s+ili(?:nin|nde|ndeki)?)\s*$")
            if re.search(pattern, prefix, re.I):
                return province
        return None

    def check(self, value):
        findings = []
        for marker in DISTRICT.finditer(value):
            mentions = []
            cursor = marker.start()
            while len(mentions) < 20:
                name = self._name_before(value, cursor)
                if not name:
                    break
                if mentions and not (name[2][0].isupper() or normalize(name[2]) in self.exact):
                    break  # "yolları ve X ilçesi" is not a list of districts.
                mentions.append(name)
                separator = re.search(r'(?:,\s*(?:ve\s+)?|\s+(?:ve|ile)\s+)$', value[:name[0]])
                if not separator:
                    break
                cursor = separator.start()
            if not mentions:
                continue
            province = self._province_before(value, mentions[-1][0])
            for start, end, name in reversed(mentions):
                key = normalize(name)
                matches = self.exact.get(key, set())
                if (key in GENERIC or name.isdigit()) and not matches:
                    continue
                if matches:
                    if province and not any(p == province for p, _ in matches):
                        expected = '; '.join(f'{p} / {d}' for p, d in sorted(matches))
                        findings.append(self._finding(start, end, name, expected, 'district_province',
                            f'{self.label} kaynağında {name}, {province} iline bağlı görünmüyor. '
                            'İl adı mı ilçe adı mı hatalı, kaynak belgeyle kontrol edin.'))
                    continue
                # Lowercase narrative words before a generic plural are not names.
                if not province and not name[0].isupper() and not marker.group().lower().startswith('ilçesi'):
                    continue
                compact = compact_name(name)
                candidates = self.ascii.get(compact, set())
                if not candidates and len(compact) >= 4:
                    candidates = {pair for candidate, pairs in self.ascii.items()
                                  if one_edit(compact, candidate) for pair in pairs}
                if province:
                    candidates = {pair for pair in candidates if pair[0] == province}
                names = {d for _, d in candidates}
                if len(names) == 1:
                    replacement = next(iter(names))
                    reason = (f'{self.label} kaynağında yakın yazım: {replacement}. '
                              'Kastedilen yerin bu ilçe olduğunu doğrulayın; aynı adlı başka yerleşimler bulunabilir.')
                    rule = 'district_spelling'
                elif names:
                    replacement = ' / '.join(sorted(names)) + ' (kastedilen ilçeyi doğrulayın)'
                    reason = f'{self.label} kaynağında birden fazla yakın ilçe adı var; otomatik seçim yapılmadı.'
                    rule = 'district_ambiguous'
                else:
                    replacement = 'İlçe adını ve yerleşim türünü doğrulayın'
                    reason = (f'{name}, {self.label} kaynağında ilçe adı olarak bulunamadı. '
                              'Bu sonuç belde/köy olduğunu kanıtlamaz; listenin tarihi ve güncel idari statü kontrol edilmeli.')
                    rule = 'district_not_in_source'
                findings.append(self._finding(start, end, name, replacement, rule, reason))
        return findings

    def _finding(self, start, end, before, after, rule, reason):
        return dict(start=start, end=end, before=before, after=after, rule=rule,
                    reason=reason, source=self.url, conditional=True)
