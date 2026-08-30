"""Invoice validation API.

The app is intentionally adapter-driven: the canonical invoice model stays the
same while country profiles add local rules, labels and reference links.
"""

from __future__ import annotations

import json
import os
import re
import urllib.request
import xml.etree.ElementTree as ET
from datetime import datetime
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP
from pathlib import Path
from typing import Any

from starlette.applications import Starlette
from starlette.middleware import Middleware
from starlette.middleware.cors import CORSMiddleware
from starlette.requests import Request
from starlette.responses import JSONResponse
from starlette.routing import Mount, Route
from starlette.staticfiles import StaticFiles

PUBLIC_DIR = Path(__file__).resolve().parents[1] / "public"


COUNTRY_PROFILES: dict[str, dict[str, Any]] = {
    "SK": {
        "name": "Slovakia",
        "native": "Slovensko",
        "currency": "EUR",
        "vat_label": "IČ DPH",
        "standard": "EN 16931 / Peppol BIS Billing 3.0",
        "authority": "Finančná správa SR",
        "reference": "https://www.financnasprava.sk/sk/titulna-stranka",
        "rules": ["invoice_id", "issue_date", "currency", "seller", "buyer", "totals", "vat_id"],
    },
    "AT": {"name": "Austria", "native": "Osterreich", "currency": "EUR", "vat_label": "UID-Nr.", "standard": "Austrian e-Rechnung / EN 16931", "authority": "Bundesministerium fur Finanzen", "reference": "https://www.bmf.gv.at/", "rules": ["invoice_id", "issue_date", "currency", "seller", "buyer", "totals", "vat_id"]},
    "BE": {"name": "Belgium", "native": "Belgique", "currency": "EUR", "vat_label": "VAT number", "standard": "Peppol BIS Billing 3.0", "authority": "FPS Finance", "reference": "https://finance.belgium.be/", "rules": ["invoice_id", "issue_date", "currency", "seller", "buyer", "totals", "vat_id"]},
    "BG": {"name": "Bulgaria", "native": "Bulgaria", "currency": "BGN", "vat_label": "VAT ID", "standard": "EN 16931 / Peppol", "authority": "National Revenue Agency", "reference": "https://nra.bg/", "rules": ["invoice_id", "issue_date", "currency", "seller", "buyer", "totals", "vat_id"]},
    "HR": {"name": "Croatia", "native": "Hrvatska", "currency": "EUR", "vat_label": "OIB", "standard": "eRacun / EN 16931", "authority": "Tax Administration", "reference": "https://www.porezna-uprava.hr/", "rules": ["invoice_id", "issue_date", "currency", "seller", "buyer", "totals", "vat_id"]},
    "CY": {"name": "Cyprus", "native": "Kypros", "currency": "EUR", "vat_label": "VAT number", "standard": "EN 16931 / Peppol", "authority": "Tax Department", "reference": "https://www.mof.gov.cy/", "rules": ["invoice_id", "issue_date", "currency", "seller", "buyer", "totals", "vat_id"]},
    "DK": {"name": "Denmark", "native": "Danmark", "currency": "DKK", "vat_label": "CVR", "standard": "OIOUBL / Peppol", "authority": "Danish Business Authority", "reference": "https://erhvervsstyrelsen.dk/", "rules": ["invoice_id", "issue_date", "currency", "seller", "buyer", "totals", "vat_id"]},
    "EE": {"name": "Estonia", "native": "Eesti", "currency": "EUR", "vat_label": "KMKR", "standard": "e-arve / Peppol", "authority": "Tax and Customs Board", "reference": "https://www.emta.ee/", "rules": ["invoice_id", "issue_date", "currency", "seller", "buyer", "totals", "vat_id"]},
    "FI": {"name": "Finland", "native": "Suomi", "currency": "EUR", "vat_label": "ALV number", "standard": "Finvoice / Peppol", "authority": "Vero Skatt", "reference": "https://www.vero.fi/", "rules": ["invoice_id", "issue_date", "currency", "seller", "buyer", "totals", "vat_id"]},
    "GR": {"name": "Greece", "native": "Ellada", "currency": "EUR", "vat_label": "AFM", "standard": "myDATA / EN 16931", "authority": "AADE", "reference": "https://www.aade.gr/", "rules": ["invoice_id", "issue_date", "currency", "seller", "buyer", "totals", "vat_id"]},
    "HU": {"name": "Hungary", "native": "Magyarorszag", "currency": "HUF", "vat_label": "Tax number", "standard": "Online Szamla", "authority": "NAV", "reference": "https://nav.gov.hu/", "rules": ["invoice_id", "issue_date", "currency", "seller", "buyer", "totals", "vat_id"]},
    "IE": {"name": "Ireland", "native": "Eire", "currency": "EUR", "vat_label": "VAT number", "standard": "Peppol BIS Billing 3.0", "authority": "Revenue", "reference": "https://www.revenue.ie/", "rules": ["invoice_id", "issue_date", "currency", "seller", "buyer", "totals", "vat_id"]},
    "LV": {"name": "Latvia", "native": "Latvija", "currency": "EUR", "vat_label": "PVN number", "standard": "e-rekin / EN 16931", "authority": "State Revenue Service", "reference": "https://www.vid.gov.lv/", "rules": ["invoice_id", "issue_date", "currency", "seller", "buyer", "totals", "vat_id"]},
    "LT": {"name": "Lithuania", "native": "Lietuva", "currency": "EUR", "vat_label": "PVM number", "standard": "eSaskaita / Peppol", "authority": "State Tax Inspectorate", "reference": "https://www.vmi.lt/", "rules": ["invoice_id", "issue_date", "currency", "seller", "buyer", "totals", "vat_id"]},
    "LU": {"name": "Luxembourg", "native": "Lëtzebuerg", "currency": "EUR", "vat_label": "TVA number", "standard": "Peppol BIS Billing 3.0", "authority": "Guichet.lu", "reference": "https://guichet.public.lu/", "rules": ["invoice_id", "issue_date", "currency", "seller", "buyer", "totals", "vat_id"]},
    "MT": {"name": "Malta", "native": "Malta", "currency": "EUR", "vat_label": "VAT number", "standard": "Peppol BIS Billing 3.0", "authority": "Commissioner for Revenue", "reference": "https://cfr.gov.mt/", "rules": ["invoice_id", "issue_date", "currency", "seller", "buyer", "totals", "vat_id"]},
    "PL": {"name": "Poland", "native": "Polska", "currency": "PLN", "vat_label": "NIP", "standard": "KSeF / EN 16931", "authority": "Ministry of Finance", "reference": "https://www.podatki.gov.pl/", "rules": ["invoice_id", "issue_date", "currency", "seller", "buyer", "totals", "vat_id"]},
    "PT": {"name": "Portugal", "native": "Portugal", "currency": "EUR", "vat_label": "NIF", "standard": "CIUS-PT / EN 16931", "authority": "Autoridade Tributaria", "reference": "https://www.portaldasfinancas.gov.pt/", "rules": ["invoice_id", "issue_date", "currency", "seller", "buyer", "totals", "vat_id"]},
    "RO": {"name": "Romania", "native": "Romania", "currency": "RON", "vat_label": "CUI", "standard": "RO e-Factura", "authority": "ANAF", "reference": "https://www.anaf.ro/", "rules": ["invoice_id", "issue_date", "currency", "seller", "buyer", "totals", "vat_id"]},
    "SI": {"name": "Slovenia", "native": "Slovenija", "currency": "EUR", "vat_label": "DDV number", "standard": "e-SLOG / Peppol", "authority": "FURS", "reference": "https://www.fu.gov.si/", "rules": ["invoice_id", "issue_date", "currency", "seller", "buyer", "totals", "vat_id"]},
    "SE": {"name": "Sweden", "native": "Sverige", "currency": "SEK", "vat_label": "VAT number", "standard": "Svefaktura / Peppol", "authority": "Skatteverket", "reference": "https://www.skatteverket.se/", "rules": ["invoice_id", "issue_date", "currency", "seller", "buyer", "totals", "vat_id"]},
    "NO": {"name": "Norway", "native": "Norge", "currency": "NOK", "vat_label": "Org number", "standard": "EHF / Peppol", "authority": "Brønnøysund Register Centre", "reference": "https://www.brreg.no/", "rules": ["invoice_id", "issue_date", "currency", "seller", "buyer", "totals", "vat_id"]},
    "IS": {"name": "Iceland", "native": "Island", "currency": "ISK", "vat_label": "VSK number", "standard": "EN 16931 / Peppol", "authority": "Skatturinn", "reference": "https://www.skatturinn.is/", "rules": ["invoice_id", "issue_date", "currency", "seller", "buyer", "totals", "vat_id"]},
    "LI": {"name": "Liechtenstein", "native": "Liechtenstein", "currency": "CHF", "vat_label": "VAT number", "standard": "EN 16931 / Peppol", "authority": "Tax Administration", "reference": "https://www.llv.li/", "rules": ["invoice_id", "issue_date", "currency", "seller", "buyer", "totals", "vat_id"]},
    "CH": {"name": "Switzerland", "native": "Schweiz", "currency": "CHF", "vat_label": "MWST number", "standard": "Swiss QR / EN 16931", "authority": "Federal Tax Administration", "reference": "https://www.estv.admin.ch/", "rules": ["invoice_id", "issue_date", "currency", "seller", "buyer", "totals", "vat_id"]},
    "TR": {"name": "Turkiye", "native": "Turkiye", "currency": "TRY", "vat_label": "VKN / TCKN", "standard": "UBL-TR / GIB e-Fatura", "authority": "Gelir Idaresi Baskanligi", "reference": "https://ebelge.gib.gov.tr/", "rules": ["invoice_id", "issue_date", "currency", "seller", "buyer", "totals", "vat_id"]},
    "EG": {"name": "Egypt", "native": "Misr", "currency": "EGP", "vat_label": "Tax registration number", "standard": "Egyptian ETA e-Invoice", "authority": "Egyptian Tax Authority", "reference": "https://www.eta.gov.eg/", "rules": ["invoice_id", "issue_date", "currency", "seller", "buyer", "totals", "vat_id"]},
    "SA": {"name": "Saudi Arabia", "native": "Al Saudi", "currency": "SAR", "vat_label": "VAT number", "standard": "ZATCA FATOORA XML", "authority": "ZATCA", "reference": "https://zatca.gov.sa/en/E-Invoicing/Pages/default.aspx", "rules": ["invoice_id", "issue_date", "currency", "seller", "buyer", "totals", "vat_id"]},
    "CZ": {
        "name": "Czechia", "native": "Česko", "currency": "CZK", "vat_label": "DIČ",
        "standard": "EN 16931 / Peppol BIS Billing 3.0", "authority": "Finanční správa",
        "reference": "https://www.financnisprava.cz/", "rules": ["invoice_id", "issue_date", "currency", "seller", "buyer", "totals", "vat_id"],
    },
    "DE": {
        "name": "Germany", "native": "Deutschland", "currency": "EUR", "vat_label": "USt-IdNr.",
        "standard": "XRechnung / ZUGFeRD / EN 16931", "authority": "Bundeszentralamt für Steuern",
        "reference": "https://www.bzst.de/", "rules": ["invoice_id", "issue_date", "currency", "seller", "buyer", "totals"],
    },
    "FR": {
        "name": "France", "native": "France", "currency": "EUR", "vat_label": "N° TVA",
        "standard": "Factur-X / EN 16931", "authority": "impots.gouv.fr",
        "reference": "https://www.impots.gouv.fr/", "rules": ["invoice_id", "issue_date", "currency", "seller", "buyer", "totals"],
    },
    "IT": {
        "name": "Italy", "native": "Italia", "currency": "EUR", "vat_label": "Partita IVA",
        "standard": "FatturaPA / SDI", "authority": "Agenzia delle Entrate",
        "reference": "https://www.agenziaentrate.gov.it/", "rules": ["invoice_id", "issue_date", "currency", "seller", "buyer", "totals", "vat_id"],
    },
    "ES": {
        "name": "Spain", "native": "España", "currency": "EUR", "vat_label": "NIF-IVA",
        "standard": "Facturae / EN 16931", "authority": "Agencia Tributaria",
        "reference": "https://sede.agenciatributaria.gob.es/", "rules": ["invoice_id", "issue_date", "currency", "seller", "buyer", "totals"],
    },
    "NL": {
        "name": "Netherlands", "native": "Nederland", "currency": "EUR", "vat_label": "BTW-nummer",
        "standard": "SI-UBL / Peppol BIS Billing 3.0", "authority": "Belastingdienst",
        "reference": "https://www.belastingdienst.nl/", "rules": ["invoice_id", "issue_date", "currency", "seller", "buyer", "totals"],
    },
    "GB": {
        "name": "United Kingdom", "native": "United Kingdom", "currency": "GBP", "vat_label": "VAT number",
        "standard": "Peppol BIS / local network rules", "authority": "HMRC",
        "reference": "https://www.gov.uk/government/organisations/hm-revenue-customs", "rules": ["invoice_id", "issue_date", "currency", "seller", "buyer", "totals"],
    },
    "US": {
        "name": "United States", "native": "United States", "currency": "USD", "vat_label": "Tax ID",
        "standard": "Universal invoice profile", "authority": "Generic profile",
        "reference": "https://www.irs.gov/", "rules": ["invoice_id", "issue_date", "currency", "seller", "buyer", "totals"],
    },
}


SAMPLE_FORMATS: dict[str, str] = {
    "SK": "UBL 2.1 XML / EN 16931", "AT": "ebInterface XML", "BE": "Peppol BIS UBL XML", "BG": "EN 16931 UBL XML", "HR": "eRacun UBL XML", "CY": "Peppol BIS UBL XML", "CZ": "ISDOC XML", "DK": "OIOUBL XML", "EE": "e-arve UBL XML", "FI": "Finvoice XML", "FR": "Factur-X CII XML", "DE": "XRechnung UBL XML", "GR": "myDATA JSON", "HU": "Online Szamla XML", "IE": "Peppol BIS UBL XML", "IT": "FatturaPA XML", "LV": "e-rekin UBL XML", "LT": "eSaskaita UBL XML", "LU": "Peppol BIS UBL XML", "MT": "Peppol BIS UBL XML", "NL": "SI-UBL XML", "PL": "KSeF FA(3) XML", "PT": "CIUS-PT UBL XML", "RO": "RO e-Factura UBL XML", "SI": "e-SLOG XML", "ES": "Facturae XML", "SE": "Svefaktura XML", "NO": "EHF XML", "IS": "Peppol BIS UBL XML", "LI": "Peppol BIS UBL XML", "CH": "Swiss QR / EN 16931 XML", "GB": "Peppol BIS UBL XML", "US": "Universal invoice JSON", "TR": "UBL-TR XML", "EG": "ETA e-Invoice JSON", "SA": "ZATCA FATOORA UBL XML",
}


def local_name(tag: str) -> str:
    return tag.rsplit("}", 1)[-1].lower().replace("-", "").replace("_", "")


def text_of(node: ET.Element | None) -> str:
    return " ".join((node.itertext() if node is not None else [])).strip()


def first_value(data: dict[str, Any], *keys: str) -> Any:
    for key in keys:
        value = data.get(key)
        if value not in (None, "", []):
            return value
    return ""


def money(value: Any) -> Decimal | None:
    if value is None or value == "":
        return None
    try:
        return Decimal(str(value).replace(",", ".").replace(" ", "")).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
    except (InvalidOperation, ValueError):
        return None


def money_str(value: Decimal | None) -> str:
    return f"{value:.2f}" if value is not None else "0.00"


def parse_json_invoice(raw: str) -> dict[str, Any]:
    source = json.loads(raw)
    if not isinstance(source, dict):
        raise ValueError("JSON root must be an object")
    header = source.get("invoiceHeader") or source.get("header") or {}
    summary = source.get("invoiceSummary") or source.get("summary") or {}
    issuer = source.get("issuer") or {}
    counterpart = source.get("counterpart") or {}
    seller = source.get("seller") or source.get("supplier") or issuer
    buyer = source.get("buyer") or source.get("customer") or source.get("receiver") or counterpart
    raw_lines = source.get("lines") or source.get("items") or source.get("invoiceLines") or source.get("invoiceDetails") or []
    lines = []
    for index, item in enumerate(raw_lines, 1):
        if not isinstance(item, dict):
            continue
        quantity = first_value(item, "quantity", "qty", "count") or 1
        unit_value = item.get("unitValue") or {}
        if isinstance(unit_value, dict):
            unit_price = first_value(item, "unit_price", "unitPrice", "price", "net", "netValue") or first_value(unit_value, "amount", "amountEGP") or 0
        else:
            unit_price = first_value(item, "unit_price", "unitPrice", "price", "net", "netValue") or 0
        lines.append({
            "description": first_value(item, "description", "name", "title", "itemDescription", "itemName") or f"Line {index}",
            "quantity": str(quantity), "unit_price": str(unit_price),
            "vat_rate": str(first_value(item, "vat_rate", "vatRate", "tax_rate", "vatPercentage") or "0"),
        })
    totals = source.get("totals") or summary
    tax_totals = source.get("taxTotals") or []
    first_tax = tax_totals[0] if isinstance(tax_totals, list) and tax_totals and isinstance(tax_totals[0], dict) else {}
    line_currency = raw_lines[0].get("unitValue", {}).get("currencySold") if raw_lines and isinstance(raw_lines[0], dict) and isinstance(raw_lines[0].get("unitValue"), dict) else ""
    return {
        "invoice_id": str(first_value(source, "invoice_id", "invoiceNumber", "number", "id", "internalId", "uniqueIdentifier") or first_value(header, "invoice_id", "invoiceNumber", "number", "aa")),
        "issue_date": str(first_value(source, "issue_date", "issueDate", "date", "dateTimeIssued") or first_value(header, "issue_date", "issueDate", "date")),
        "currency": str(first_value(source, "currency", "documentCurrencyCode") or line_currency or ""),
        "seller": normalize_party(seller), "buyer": normalize_party(buyer), "lines": lines,
        "net_total": str(first_value(totals, "net", "net_total", "taxExclusiveAmount", "totalNetValue", "netAmount", "totalSalesAmount") or first_value(source, "net_total", "subtotal", "netAmount", "totalSalesAmount") or ""),
        "vat_total": str(first_value(totals, "vat", "vat_total", "taxAmount", "totalVatAmount") or first_value(source, "vat_total", "tax", "totalVatAmount") or first_value(first_tax, "amount", "taxAmount") or ""),
        "gross_total": str(first_value(totals, "gross", "gross_total", "taxInclusiveAmount", "total", "totalGrossValue") or first_value(source, "total", "amount", "totalAmount") or ""),
        "vat_id": str(first_value(source, "vat_id", "vatId", "tax_id", "taxId") or first_value(seller, "vat_id", "vatId", "tax_id", "vatNumber", "id")),
        "payment_reference": str(first_value(source, "payment_reference", "paymentReference", "variable_symbol") or ""),
        "format": "JSON",
    }


def normalize_party(party: Any) -> dict[str, str]:
    if isinstance(party, str):
        return {"name": party, "address": "", "vat_id": ""}
    if not isinstance(party, dict):
        return {"name": "", "address": "", "vat_id": ""}
    address = party.get("address") or party.get("postal_address") or ""
    if isinstance(address, dict):
        address = ", ".join(str(v) for v in [address.get("street"), address.get("city"), address.get("postal_code"), address.get("country")] if v)
    return {
        "name": str(first_value(party, "name", "legal_name", "company", "businessName", "corporateName") or ""),
        "address": str(address),
        "vat_id": str(first_value(party, "vat_id", "vatId", "tax_id", "taxId", "vatNumber", "id") or ""),
    }


def parse_xml_invoice(raw: str) -> dict[str, Any]:
    root = ET.fromstring(raw)
    nodes: dict[str, list[str]] = {}
    for node in root.iter():
        key = local_name(node.tag)
        value = text_of(node)
        if value and len(value) < 500:
            nodes.setdefault(key, []).append(value)

    def pick(*names: str, default: str = "") -> str:
        for name in names:
            values = nodes.get(local_name(name), [])
            if values:
                return values[0]
        return default

    def descendants(parent: ET.Element, names: set[str]) -> list[str]:
        return [text_of(n) for n in parent.iter() if local_name(n.tag) in names and text_of(n)]

    lines = []
    line_nodes = [n for n in root.iter() if local_name(n.tag) in {"invoiceline", "includedinvoicelineitem", "dettagliolinee", "invoicerow", "line", "fawiersz"}]
    if not line_nodes:
        line_nodes = [n for n in root.iter() if local_name(n.tag) == "item"]
    for index, line in enumerate(line_nodes, 1):
        values = descendants(line, {"name", "description", "itemname", "itemdescription", "articlename", "descrizione", "linedescription", "p7"})
        quantities = descendants(line, {"invoicedquantity", "quantity", "basequantity", "quantita", "p8b"})
        prices = descendants(line, {"priceamount", "unitprice", "unitnetprice", "unitpricenetamount", "prezzounitario", "unitpricewithouttax", "p9a", "value"})
        rates = descendants(line, {"percent", "taxrate", "vatpercent", "taxpercentage", "aliquotaiva", "taxratevalue", "invoicerowvatratepercent", "p12"})
        if values or quantities or prices:
            lines.append({"description": values[0] if values else f"Line {index}", "quantity": quantities[0] if quantities else "1", "unit_price": prices[0] if prices else "0", "vat_rate": rates[0] if rates else "0"})

    def party_data(party_type: str) -> dict[str, str]:
        aliases = {party_type}
        if party_type == "accountingsupplierparty":
            aliases.update({"supplierinfo", "sellerparty", "cedenteprestatore", "issuer", "seller"})
        if party_type == "accountingcustomerparty":
            aliases.update({"customerinfo", "buyerparty", "cessionariocommittente", "receiver", "buyer"})
        party_node = next((n for n in root.iter() if local_name(n.tag) in aliases), None)
        if party_node is None:
            return {"name": "", "address": "", "vat_id": ""}
        names = descendants(party_node, {"registrationname", "name", "companyname", "businessname", "corporatename", "denomination", "denominazione", "legalname", "suppliername", "customername", "sellerorganisationname", "buyerorganisationname", "nazwa"})
        addresses = descendants(party_node, {"streetname", "addressline", "cityname", "address", "city"})
        ids = descendants(party_node, {"companyid", "vatid", "taxschemeid", "taxidentificationnumber", "suppliertaxnumber", "sellerpartyidentifier", "buyerpartyidentifier", "vatnumber", "taxnumber", "taxpayerid", "nip", "idcodice"})
        return {"name": names[0] if names else "", "address": ", ".join(addresses[:3]), "vat_id": ids[0] if ids else ""}

    seller = party_data("accountingsupplierparty")
    buyer = party_data("accountingcustomerparty")
    return {
        "invoice_id": pick("id", "invoicenumber", "number", "numero", "internalid", "p2"), "issue_date": pick("issuedate", "invoicedate", "date", "data", "invoicedate", "invoiceissuedate", "datetimestring", "p1"),
        "currency": pick("documentcurrencycode", "currency", "currencyid", "divisa", "invoicecurrencycode", "invoicecurrency", "kodwaluty"),
        "seller": seller, "buyer": buyer,
        "lines": lines,
        "net_total": pick("taxexclusiveamount", "lineextensionamount", "subtotal", "imponibileimporto", "invoicetotalvatexcludedamount", "totalnetvalue", "invoicenetamount", "p131"),
        "vat_total": pick("taxamount", "vatamount", "taxamounttotal", "imposta", "invoicetotalvatamount", "totalvatamount", "invoicevatamount", "p141"),
        "gross_total": pick("taxinclusiveamount", "payableamount", "totalamount", "amount", "importototale", "importopagamento", "invoicetotalvatincludedamount", "totalgrossamount", "invoicegrossamount", "p15"),
        "vat_id": pick("companyid", "vatid", "taxschemeid", "taxidentificationnumber", "vatnumber", "taxnumber"),
        "payment_reference": pick("paymentid", "variable_symbol", "paymentreference"), "format": "XML",
    }


def parse_text_invoice(raw: str) -> dict[str, Any]:
    def find(*patterns: str) -> str:
        for pattern in patterns:
            match = re.search(pattern, raw, re.I | re.M)
            if match:
                return match.group(1).strip()
        return ""
    return {
        "invoice_id": find(r"(?:invoice|fatura|számla|faktúra)[ _-]?(?:no|number|num|id|numarası)?\s*[:#]?\s*([^\n,;]+)"),
        "issue_date": find(r"(?:issue date|invoice date|tarih|datum)\s*[:#]?\s*([^\n,;]+)"),
        "currency": find(r"(?:currency|para birimi|mă?na|währung)\s*[:#]?\s*([A-Z]{3})") or find(r"\b(EUR|USD|GBP|CZK|PLN|HUF)\b"),
        "seller": {"name": find(r"(?:seller|supplier|satıcı|tedarikçi)\s*[:#]?\s*([^\n,;]+)"), "address": "", "vat_id": ""},
        "buyer": {"name": find(r"(?:buyer|customer|alıcı|müşteri)\s*[:#]?\s*([^\n,;]+)"), "address": "", "vat_id": ""},
        "lines": [], "net_total": find(r"(?:subtotal|net total|ara toplam)\s*[:#]?\s*([\d.,]+)"),
        "vat_total": find(r"(?:vat total|vat|kdv)\s*[:#]?\s*([\d.,]+)"),
        "gross_total": find(r"(?:grand total|gross total|total|genel toplam)\s*[:#]?\s*([\d.,]+)"),
        "vat_id": find(r"(?:vat id|vat number|iç?\s*dph|vergi no)\s*[:#]?\s*([^\n,;]+)"),
        "payment_reference": "", "format": "TEXT",
    }


def parse_invoice(raw: str) -> dict[str, Any]:
    stripped = raw.strip()
    if stripped.startswith("<"):
        return parse_xml_invoice(stripped)
    if stripped.startswith("{") or stripped.startswith("["):
        return parse_json_invoice(stripped)
    return parse_text_invoice(stripped)


def validate_invoice(raw: str, country: str) -> dict[str, Any]:
    code = country.upper() if country.upper() in COUNTRY_PROFILES else "SK"
    profile = {**COUNTRY_PROFILES[code], "sample_format": SAMPLE_FORMATS.get(code, "Generic XML/JSON")}
    checks: list[dict[str, Any]] = []
    try:
        invoice = parse_invoice(raw)
    except (ET.ParseError, json.JSONDecodeError, ValueError) as exc:
        return {"valid": False, "score": 0, "country": code, "profile": profile, "invoice": None, "checks": [{"severity": "error", "code": "parse_error", "message": "Could not read the document", "detail": str(exc), "field": "document"}], "error": "The document must be XML, JSON, or labeled text."}

    def check(code_: str, condition: bool, message: str, field: str, detail: str = "", severity: str = "error"):
        checks.append({"severity": severity if not condition else "pass", "code": code_, "message": message if not condition else message.replace("Missing", "Present"), "detail": detail, "field": field})

    check("invoice_id", bool(invoice["invoice_id"]), "Invoice number present", "invoice_id", "Invoice ID / ID")
    check("issue_date", bool(invoice["issue_date"]), "Issue date present", "issue_date", "IssueDate / date")
    date_ok = False
    if invoice["issue_date"]:
        try:
            datetime.fromisoformat(invoice["issue_date"].replace("Z", "+00:00"))
            date_ok = True
        except ValueError:
            date_ok = bool(re.match(r"^\d{1,2}[./-]\d{1,2}[./-]\d{2,4}$", invoice["issue_date"]))
    check("date_format", date_ok, "Recognizable date format", "issue_date", "ISO 8601 or local date")
    check("currency", bool(invoice["currency"]), "Currency present", "currency", "DocumentCurrencyCode")
    check("seller", bool(invoice["seller"]["name"]), "Seller information present", "seller", "AccountingSupplierParty")
    check("buyer", bool(invoice["buyer"]["name"]), "Buyer information present", "buyer", "AccountingCustomerParty")
    check("vat_id", bool(invoice["vat_id"] or invoice["seller"]["vat_id"]), f"{profile['vat_label']} present", "vat_id", "Tax identifier", "warning")

    line_total = Decimal("0.00")
    line_errors = 0
    for line in invoice["lines"]:
        qty, price = money(line.get("quantity")), money(line.get("unit_price"))
        if qty is not None and price is not None:
            line_total += qty * price
        else:
            line_errors += 1
    stated_net = money(invoice["net_total"])
    if invoice["lines"] and stated_net is not None:
        difference = abs(line_total.quantize(Decimal("0.01")) - stated_net)
        check("line_math", difference <= Decimal("0.02"), "Line totals match the net amount", "net_total", f"Lines {money_str(line_total)}, document {money_str(stated_net)}")
    elif invoice["lines"]:
        check("line_math", line_errors == 0, "Line amounts can be calculated", "lines", f"Number format issue in {line_errors} line(s)", "warning")
    else:
        check("lines", False, "At least one invoice line is recommended", "lines", "No line items found", "warning")

    gross = money(invoice["gross_total"])
    net = money(invoice["net_total"])
    vat = money(invoice["vat_total"])
    if gross is not None and net is not None and vat is not None:
        check("total_math", abs((net + vat) - gross) <= Decimal("0.02"), "Net + VAT = grand total", "gross_total", f"{money_str(net)} + {money_str(vat)} = {money_str(gross)}")
    else:
        check("totals", bool(gross or net), "Total amount fields present", "totals", "Net, VAT, and gross total fields")

    errors = sum(1 for item in checks if item["severity"] == "error")
    warnings = sum(1 for item in checks if item["severity"] == "warning")
    score = max(0, min(100, 100 - errors * 15 - warnings * 4))
    return {"valid": errors == 0, "score": score, "country": code, "profile": profile, "invoice": invoice, "checks": checks, "summary": {"errors": errors, "warnings": warnings, "passed": len(checks) - errors - warnings}}


def fallback_answer(question: str, invoice: dict[str, Any] | None, profile: dict[str, Any]) -> str:
    q = question.lower()
    if not invoice:
        return "Paste invoice text and click Validate first. Then I can answer questions about its fields, amounts, and country profile."
    if any(word in q for word in ["total", "amount", "payable"]):
        return f"The gross total is {invoice.get('gross_total') or 'not provided'} {invoice.get('currency') or profile.get('currency', '')}. Net total: {invoice.get('net_total') or 'not provided'}; VAT: {invoice.get('vat_total') or 'not provided'}."
    if any(word in q for word in ["number", "id"]):
        return f"Invoice number: {invoice.get('invoice_id') or 'not found in the document'}. Issue date: {invoice.get('issue_date') or 'not found in the document'}."
    if any(word in q for word in ["seller", "supplier"]):
        return f"Seller: {invoice.get('seller', {}).get('name') or 'not found in the document'} ({invoice.get('seller', {}).get('vat_id') or 'no tax number'})."
    if any(word in q for word in ["buyer", "customer"]):
        return f"Buyer: {invoice.get('buyer', {}).get('name') or 'not found in the document'}."
    if any(word in q for word in ["slovak", "slovakia", "sk", "profile"]):
        return f"The active country profile is {profile['name']}. Expected approach: {profile['standard']}; local authority: {profile['authority']}. This demo validation is not an official tax authority decision."
    return f"I read the invoice as {invoice.get('invoice_id') or 'unnumbered'}. I found {len(invoice.get('lines') or [])} line(s) and the {invoice.get('currency') or 'unspecified'} currency. You can ask about amounts, parties, or the {profile['name']} profile."


def openai_answer(question: str, invoice: dict[str, Any] | None, profile: dict[str, Any], user_api_key: str | None = None) -> str | None:
    # A customer key is accepted for one request only. It is never persisted or logged.
    api_key = user_api_key or os.getenv("OPENAI_API_KEY")
    if not api_key:
        return None
    payload = {"model": os.getenv("OPENAI_MODEL", "gpt-4o-mini"), "temperature": 0.2, "messages": [
        {"role": "system", "content": "You are an invoice validation copilot. Answer in English, be concise, cite fields from the provided normalized invoice, and never claim official tax compliance. Explain missing data clearly."},
        {"role": "user", "content": json.dumps({"country_profile": profile, "invoice": invoice, "question": question}, ensure_ascii=False)},
    ]}
    request = urllib.request.Request("https://api.openai.com/v1/chat/completions", data=json.dumps(payload).encode(), headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"}, method="POST")
    try:
        with urllib.request.urlopen(request, timeout=18) as response:
            body = json.loads(response.read().decode())
        return body["choices"][0]["message"]["content"].strip()
    except Exception:
        return None


async def health(request: Request):
    return JSONResponse({"ok": True, "service": "invoice-atlas", "profiles": len(COUNTRY_PROFILES)})


async def countries(request: Request):
    return JSONResponse({"countries": [{"code": code, **profile, "sample_format": SAMPLE_FORMATS.get(code, "Generic XML/JSON")} for code, profile in COUNTRY_PROFILES.items()]})


async def validate(request: Request):
    try:
        payload = await request.json()
        invoice = str(payload.get("invoice", ""))
        country = str(payload.get("country", "SK"))
        if not invoice or len(invoice) > 2_000_000:
            return JSONResponse({"error": "invoice must be between 1 and 2,000,000 characters"}, status_code=400)
    except (ValueError, AttributeError):
        return JSONResponse({"error": "Invalid JSON request"}, status_code=400)
    return JSONResponse(validate_invoice(invoice, country))


async def ask(request: Request):
    try:
        payload = await request.json()
        question = str(payload.get("question", "")).strip()
        invoice = payload.get("invoice")
        invoice = invoice if isinstance(invoice, dict) else None
        country = str(payload.get("country", "SK"))
        if not question or len(question) > 2_000:
            return JSONResponse({"error": "question must be between 1 and 2,000 characters"}, status_code=400)
    except (ValueError, AttributeError):
        return JSONResponse({"error": "Invalid JSON request"}, status_code=400)
    code = country.upper() if country.upper() in COUNTRY_PROFILES else "SK"
    profile = COUNTRY_PROFILES[code]
    user_api_key = request.headers.get("x-openai-api-key", "").strip()
    if user_api_key and (len(user_api_key) > 300 or any(character.isspace() for character in user_api_key)):
        user_api_key = None
    answer = openai_answer(question, invoice, profile, user_api_key=user_api_key)
    provider = "openai-user-key" if answer and user_api_key else ("openai-server-key" if answer else "local")
    return JSONResponse({"answer": answer or fallback_answer(question, invoice, profile), "provider": provider, "country": code}, headers={"Cache-Control": "no-store"})


routes = [
    Route("/api/health", health, methods=["GET"]),
    Route("/api/countries", countries, methods=["GET"]),
    Route("/api/validate", validate, methods=["POST"]),
    Route("/api/ask", ask, methods=["POST"]),
]
if PUBLIC_DIR.exists():
    routes.append(Mount("/", app=StaticFiles(directory=str(PUBLIC_DIR), html=True), name="frontend"))
app = Starlette(routes=routes, middleware=[Middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])])


if __name__ == "__main__":
    import uvicorn
    uvicorn.run("api.index:app", host="127.0.0.1", port=int(os.getenv("PORT", "8000")), reload=True)
