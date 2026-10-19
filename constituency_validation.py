"""Verify the signer's constituency only against the user's reference workbook."""
from recipient_validation import normalize
from reading_validation import evidence_present, field_present, serious_disagreement


def validate_constituency(review, pages, reference):
    check = next(c for c in review.checks if c.kind == 'secim_cevresi')
    readings = {p.page: p for p in review.pages}
    members = {normalize(name): (name, province) for name, province in reference['members'].items()}
    invalid_labels = {normalize(x) for x in reference.get('invalid_constituency_labels', [])}
    outcomes = []
    if not review.signatories:
        if check.status == 'uyari' and not check.quote and not check.reading_uncertain:
            check.explanation = 'Belgede seçim çevresi alanı bulunmuyor.'
        else:
            check.status = 'belirsiz'
            check.explanation = 'İmza bölümündeki milletvekili–seçim çevresi alanı okunamadı veya ayrıştırılamadı.'
        return
    for signer in review.signatories:
        page = readings.get(signer.page)
        quote = signer.evidence
        explanation = ''
        status = 'uygun'
        if page is None:
            raise ValueError('Invalid signatory page')
        readable = (not signer.name_uncertain and not signer.constituency_uncertain
                    and '[OKUNAMADI]' not in quote
                    and evidence_present(page.text, quote)
                    and field_present(quote, signer.name)
                    and (not signer.constituency or field_present(quote, signer.constituency)))
        if not readable:
            status = 'belirsiz'
            explanation = 'İmza bölümündeki ad veya seçim çevresi güvenle okunamadı.'
        elif serious_disagreement(page.text, pages[signer.page-1]['ocr'], quote):
            status = 'belirsiz'
            explanation = 'İmza bölümündeki ad/seçim çevresi, PDF metin katmanı ile görsel okumada farklı; insan kontrolü gerekiyor.'
        elif not signer.constituency:
            status = 'uyari'
            explanation = f'{signer.name}: seçim çevresi alanı belgede bulunmuyor.'
        elif normalize(signer.constituency) in invalid_labels:
            status = 'uyari'
            explanation = f'“{signer.constituency}” kullanıcı tarafından seçim çevresi adı olarak kabul edilmiyor.'
            member = members.get(normalize(signer.name))
            if member:
                explanation += f' Excel’de {member[0]} için seçim çevresi {member[1]}.'
            quote = signer.constituency
        elif normalize(signer.name) not in members:
            status = 'kaynak_yok'
            explanation = f'{signer.name} için yüklenen Excel’de tekil bir seçim çevresi kaydı yok. Okunan il: {signer.constituency}. Kaynak olmadan doğru/yanlış kararı verilmedi.'
        else:
            name, expected = members[normalize(signer.name)]
            if normalize(signer.constituency) != normalize(expected):
                status = 'uyari'
                explanation = f'Yüklenen 28. dönem Excel’inde {name}: {expected}. Belgede {signer.constituency} yazıyor; milletvekili–seçim çevresi eşleşmesi hatalı.'
                quote = signer.constituency
            else:
                explanation = f'{name} – {expected} eşleşmesi yüklenen 28. dönem Excel’indeki kayıtla uyumlu.'
        outcomes.append((status, signer.page, quote, explanation, signer.evidence))
    # Keep a definite error visible; retain every signer's outcome in the explanation.
    priority = {'uyari': 0, 'belirsiz': 1, 'kaynak_yok': 2, 'uygun': 3}
    selected = min(outcomes, key=lambda x: priority[x[0]])
    check.status, check.page, check.quote = selected[:3]
    check.reading_uncertain = check.status == 'belirsiz'
    check.explanation = '\n'.join(item[3] for item in outcomes)
    return selected[4]
