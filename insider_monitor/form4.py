from __future__ import annotations

import hashlib
import xml.etree.ElementTree as ET
from dataclasses import dataclass


@dataclass(frozen=True)
class Purchase:
    uid: str
    accession: str
    index_url: str
    issuer_cik: str
    issuer_name: str
    ticker: str
    insider: str
    insider_key: str
    role: str
    tx_date: str          # YYYY-MM-DD
    shares: float
    price: float | None
    value: float


def _strip_ns(root: ET.Element) -> None:
    for el in root.iter():
        el.tag = el.tag.split("}", 1)[-1]


def _txt(el: ET.Element | None, path: str) -> str:
    if el is None:
        return ""
    return (el.findtext(path) or "").strip()


def _role(owner: ET.Element) -> str:
    rel = owner.find("reportingOwnerRelationship")
    if rel is None:
        return "Insider"
    parts = []
    if _txt(rel, "isOfficer") in ("1", "true"):
        parts.append(_txt(rel, "officerTitle") or "Officer")
    if _txt(rel, "isDirector") in ("1", "true"):
        parts.append("Director")
    if _txt(rel, "isTenPercentOwner") in ("1", "true"):
        parts.append("10% owner")
    return ", ".join(parts) or _txt(rel, "otherText") or "Insider"


def parse_form4(xml_bytes: bytes, accession: str = "", index_url: str = "") -> list[Purchase]:
    """Open-market purchases (code 'P', acquired) from one Form 4 / 4-A.

    Jointly filed forms (several reporting owners) are treated as ONE insider,
    keyed on the first owner, so affiliated entities can't fake a cluster.
    """
    root = ET.fromstring(xml_bytes)
    _strip_ns(root)

    issuer = root.find("issuer")
    issuer_cik = _txt(issuer, "issuerCik")
    issuer_name = _txt(issuer, "issuerName")
    ticker = _txt(issuer, "issuerTradingSymbol").upper() or "N/A"

    owners = root.findall("reportingOwner")
    if not owners or not issuer_cik:
        return []
    names = [_txt(o, "reportingOwnerId/rptOwnerName") for o in owners]
    insider = "; ".join(n for n in names if n) or "Unknown"
    insider_key = _txt(owners[0], "reportingOwnerId/rptOwnerCik") or names[0] or insider
    role = _role(owners[0])

    out = []
    for tx in root.findall("nonDerivativeTable/nonDerivativeTransaction"):
        if _txt(tx, "transactionCoding/transactionCode") != "P":
            continue
        acq = _txt(tx, "transactionAmounts/transactionAcquiredDisposedCode/value")
        if acq and acq != "A":
            continue
        try:
            shares = float(_txt(tx, "transactionAmounts/transactionShares/value"))
        except ValueError:
            continue
        raw_price = _txt(tx, "transactionAmounts/transactionPricePerShare/value")
        try:
            price = float(raw_price) if raw_price else None
        except ValueError:
            price = None
        tx_date = _txt(tx, "transactionDate/value")[:10]
        if not tx_date or shares <= 0:
            continue
        # same trade re-reported in a 4/A collapses onto the same uid
        uid = hashlib.sha1(
            f"{issuer_cik}|{insider_key}|{tx_date}|{shares}|{price}".encode()).hexdigest()[:16]
        out.append(Purchase(uid, accession, index_url, issuer_cik, issuer_name, ticker,
                            insider, insider_key, role, tx_date, shares, price,
                            shares * price if price is not None else 0.0))
    return out
