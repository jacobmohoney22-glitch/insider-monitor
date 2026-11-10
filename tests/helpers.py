"""Synthetic Form 4 / feed builders (modelled on the SEC ownershipDocument layout)."""
from __future__ import annotations


def form4_xml(*, issuer_cik="0000111111", issuer_name="Acme Corp", ticker="ACME",
              owners=(("Jane Doe", "0000222222"),), title="Chief Executive Officer",
              director=False, tx=(("P", "A", 10000, 12.5, "2026-11-03"),),
              derivative_code=None) -> bytes:
    owner_xml = "".join(f"""
  <reportingOwner>
    <reportingOwnerId><rptOwnerCik>{cik}</rptOwnerCik><rptOwnerName>{name}</rptOwnerName></reportingOwnerId>
    <reportingOwnerRelationship>
      <isDirector>{1 if director else 0}</isDirector><isOfficer>{1 if title else 0}</isOfficer>
      <officerTitle>{title}</officerTitle>
    </reportingOwnerRelationship>
  </reportingOwner>""" for name, cik in owners)
    tx_xml = ""
    for code, acq, shares, price, date in tx:
        price_xml = (f"<transactionPricePerShare><value>{price}</value></transactionPricePerShare>"
                     if price is not None else "<transactionPricePerShare/>")
        tx_xml += f"""
    <nonDerivativeTransaction>
      <securityTitle><value>Common Stock</value></securityTitle>
      <transactionDate><value>{date}</value></transactionDate>
      <transactionCoding><transactionFormType>4</transactionFormType><transactionCode>{code}</transactionCode></transactionCoding>
      <transactionAmounts>
        <transactionShares><value>{shares}</value></transactionShares>
        {price_xml}
        <transactionAcquiredDisposedCode><value>{acq}</value></transactionAcquiredDisposedCode>
      </transactionAmounts>
    </nonDerivativeTransaction>"""
    deriv = ""
    if derivative_code:
        deriv = f"""<derivativeTable><derivativeTransaction>
      <transactionCoding><transactionCode>{derivative_code}</transactionCode></transactionCoding>
    </derivativeTransaction></derivativeTable>"""
    return f"""<?xml version="1.0"?>
<ownershipDocument>
  <schemaVersion>X0508</schemaVersion><documentType>4</documentType>
  <issuer><issuerCik>{issuer_cik}</issuerCik><issuerName>{issuer_name}</issuerName>
    <issuerTradingSymbol>{ticker}</issuerTradingSymbol></issuer>{owner_xml}
  <nonDerivativeTable>{tx_xml}
  </nonDerivativeTable>{deriv}
</ownershipDocument>""".encode()


def feed_xml(entries) -> bytes:
    """entries: (title, accession) pairs; each also emitted as a second 'filer' entry."""
    body = ""
    for title, acc in entries:
        nodash = acc.replace("-", "")
        href = f"https://www.sec.gov/Archives/edgar/data/111111/{nodash}/{acc}-index.htm"
        body += f"""
<entry><title>{title}</title><link rel="alternate" href="{href}"/>
<updated>2026-11-05T10:00:00-05:00</updated>
<id>urn:tag:sec.gov,2008:accession-number={acc}</id></entry>"""
    return f"""<?xml version="1.0"?><feed xmlns="http://www.w3.org/2005/Atom">{body}</feed>""".encode()


class FakeClient:
    """Stands in for EdgarClient: pages of feed entries + a dict of filing XML."""

    def __init__(self, entries, xml_by_acc):
        self.entries, self.xml_by_acc, self.fetched = entries, xml_by_acc, []

    def feed_page(self, start=0, count=100):
        return self.entries[start:start + count]

    def form4_xml(self, index_url):
        self.fetched.append(index_url)
        for acc, xml in self.xml_by_acc.items():
            if acc in index_url:
                return xml
        return None


class FakeNotifier:
    def __init__(self, ok=True):
        self.sent, self.ok = [], ok

    def send(self, text):
        self.sent.append(text)
        return self.ok
