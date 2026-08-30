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
    seller = source.get("seller") or source.get("supplier") or {}
    buyer = source.get("buyer") or source.get("customer") or {}
    raw_lines = source.get("lines") or source.get("items") or []
    lines = []
    for index, item in enumerate(raw_lines, 1):
        if not isinstance(item, dict):
            continue
        quantity = first_value(item, "quantity", "qty", "count") or 1
        unit_price = first_value(item, "unit_price", "unitPrice", "price", "net") or 0
        lines.append({
            "description": first_value(item, "description", "name", "title") or f"Line {index}",
            "quantity": str(quantity), "unit_price": str(unit_price),
            "vat_rate": str(first_value(item, "vat_rate", "vatRate", "tax_rate") or "0"),
        })
    totals = source.get("totals") or {}
    return {
        "invoice_id": str(first_value(source, "invoice_id", "invoiceNumber", "number", "id")),
        "issue_date": str(first_value(source, "issue_date", "issueDate", "date")),
        "currency": str(first_value(source, "currency", "documentCurrencyCode") or ""),
        "seller": normalize_party(seller), "buyer": normalize_party(buyer), "lines": lines,
        "net_total": str(first_value(totals, "net", "net_total", "taxExclusiveAmount") or first_value(source, "net_total", "subtotal") or ""),
        "vat_total": str(first_value(totals, "vat", "vat_total", "taxAmount") or first_value(source, "vat_total", "tax") or ""),
        "gross_total": str(first_value(totals, "gross", "gross_total", "taxInclusiveAmount", "total") or first_value(source, "total", "amount") or ""),
        "vat_id": str(first_value(source, "vat_id", "vatId", "tax_id", "taxId") or first_value(seller, "vat_id", "vatId", "tax_id")),
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
        "name": str(first_value(party, "name", "legal_name", "company") or ""),
        "address": str(address),
        "vat_id": str(first_value(party, "vat_id", "vatId", "tax_id", "taxId") or ""),
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
    line_nodes = [n for n in root.iter() if local_name(n.tag) in {"invoiceline", "includedinvoicelineitem"}]
    if not line_nodes:
        line_nodes = [n for n in root.iter() if local_name(n.tag) == "item"]
    for index, line in enumerate(line_nodes, 1):
        values = descendants(line, {"name", "description", "itemname"})
        quantities = descendants(line, {"invoicedquantity", "quantity", "basequantity"})
        prices = descendants(line, {"priceamount", "unitprice", "unitnetprice"})
        rates = descendants(line, {"percent", "taxrate", "vatpercent"})
        if values or quantities or prices:
            lines.append({"description": values[0] if values else f"Line {index}", "quantity": quantities[0] if quantities else "1", "unit_price": prices[0] if prices else "0", "vat_rate": rates[0] if rates else "0"})

    def party_data(party_type: str) -> dict[str, str]:
        party_node = next((n for n in root.iter() if local_name(n.tag) == party_type), None)
        if party_node is None:
            return {"name": "", "address": "", "vat_id": ""}
        names = descendants(party_node, {"registrationname", "name", "companyname"})
        addresses = descendants(party_node, {"streetname", "addressline", "cityname"})
        ids = descendants(party_node, {"companyid", "vatid", "taxschemeid"})
        return {"name": names[0] if names else "", "address": ", ".join(addresses[:3]), "vat_id": ids[0] if ids else ""}

    seller = party_data("accountingsupplierparty")
    buyer = party_data("accountingcustomerparty")
    return {
        "invoice_id": pick("id", "invoicenumber", "number"), "issue_date": pick("issuedate", "invoicedate", "date"),
        "currency": pick("documentcurrencycode", "currency", "currencyid"),
        "seller": seller, "buyer": buyer,
        "lines": lines,
        "net_total": pick("taxexclusiveamount", "lineextensionamount", "subtotal"),
        "vat_total": pick("taxamount", "vatamount", "taxamounttotal"),
        "gross_total": pick("taxinclusiveamount", "payableamount", "totalamount", "amount"),
        "vat_id": pick("companyid", "vatid", "taxschemeid"),
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
    profile = COUNTRY_PROFILES[code]
    checks: list[dict[str, Any]] = []
    try:
        invoice = parse_invoice(raw)
    except (ET.ParseError, json.JSONDecodeError, ValueError) as exc:
        return {"valid": False, "score": 0, "country": code, "profile": profile, "invoice": None, "checks": [{"severity": "error", "code": "parse_error", "message": "Belge okunamadı", "detail": str(exc), "field": "document"}], "error": "Belge formatı XML, JSON veya etiketli metin olmalı."}

    def check(code_: str, condition: bool, message: str, field: str, detail: str = "", severity: str = "error"):
        checks.append({"severity": severity if not condition else "pass", "code": code_, "message": message if not condition else message.replace("Eksik", "Mevcut"), "detail": detail, "field": field})

    check("invoice_id", bool(invoice["invoice_id"]), "Fatura numarası mevcut", "invoice_id", "Invoice ID / ID")
    check("issue_date", bool(invoice["issue_date"]), "Düzenleme tarihi mevcut", "issue_date", "IssueDate / date")
    date_ok = False
    if invoice["issue_date"]:
        try:
            datetime.fromisoformat(invoice["issue_date"].replace("Z", "+00:00"))
            date_ok = True
        except ValueError:
            date_ok = bool(re.match(r"^\d{1,2}[./-]\d{1,2}[./-]\d{2,4}$", invoice["issue_date"]))
    check("date_format", date_ok, "Tarih formatı tanınabilir", "issue_date", "ISO 8601 veya yerel tarih")
    check("currency", bool(invoice["currency"]), "Para birimi mevcut", "currency", "DocumentCurrencyCode")
    check("seller", bool(invoice["seller"]["name"]), "Satıcı bilgisi mevcut", "seller", "AccountingSupplierParty")
    check("buyer", bool(invoice["buyer"]["name"]), "Alıcı bilgisi mevcut", "buyer", "AccountingCustomerParty")
    check("vat_id", bool(invoice["vat_id"] or invoice["seller"]["vat_id"]), f"{profile['vat_label']} mevcut", "vat_id", "Tax identifier", "warning")

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
        check("line_math", difference <= Decimal("0.02"), "Satır toplamları ile net tutar uyumlu", "net_total", f"Satırlar {money_str(line_total)}, belge {money_str(stated_net)}")
    elif invoice["lines"]:
        check("line_math", line_errors == 0, "Satır tutarları hesaplanabilir", "lines", f"{line_errors} satırda sayı formatı sorunu var", "warning")
    else:
        check("lines", False, "En az bir fatura satırı önerilir", "lines", "Line items bulunamadı", "warning")

    gross = money(invoice["gross_total"])
    net = money(invoice["net_total"])
    vat = money(invoice["vat_total"])
    if gross is not None and net is not None and vat is not None:
        check("total_math", abs((net + vat) - gross) <= Decimal("0.02"), "Net + KDV = genel toplam", "gross_total", f"{money_str(net)} + {money_str(vat)} = {money_str(gross)}")
    else:
        check("totals", bool(gross or net), "Toplam tutar alanları mevcut", "totals", "Net, KDV ve brüt toplam alanları")

    errors = sum(1 for item in checks if item["severity"] == "error")
    warnings = sum(1 for item in checks if item["severity"] == "warning")
    score = max(0, min(100, 100 - errors * 15 - warnings * 4))
    return {"valid": errors == 0, "score": score, "country": code, "profile": profile, "invoice": invoice, "checks": checks, "summary": {"errors": errors, "warnings": warnings, "passed": len(checks) - errors - warnings}}


def fallback_answer(question: str, invoice: dict[str, Any] | None, profile: dict[str, Any]) -> str:
    q = question.lower()
    if not invoice:
        return "Önce bir fatura metni yapıştırıp Validate düğmesine basın. Ardından bu fatura hakkında alan, tutar ve ülke profili sorularını yanıtlayabilirim."
    if any(word in q for word in ["tutar", "total", "amount", "ödenecek", "payable"]):
        return f"Bu faturada brüt toplam {invoice.get('gross_total') or 'belirtilmemiş'} {invoice.get('currency') or profile.get('currency', '')}. Net toplam: {invoice.get('net_total') or 'belirtilmemiş'}, KDV: {invoice.get('vat_total') or 'belirtilmemiş'}."
    if any(word in q for word in ["numara", "number", "id"]):
        return f"Fatura numarası: {invoice.get('invoice_id') or 'belgede bulunamadı'}. Düzenleme tarihi: {invoice.get('issue_date') or 'belgede bulunamadı'}."
    if any(word in q for word in ["satıcı", "seller", "supplier"]):
        return f"Satıcı: {invoice.get('seller', {}).get('name') or 'belgede bulunamadı'} ({invoice.get('seller', {}).get('vat_id') or 'vergi numarası yok'})."
    if any(word in q for word in ["alıcı", "buyer", "customer"]):
        return f"Alıcı: {invoice.get('buyer', {}).get('name') or 'belgede bulunamadı'}."
    if any(word in q for word in ["slovak", "slovakya", "sk", "profil"]):
        return f"Aktif ülke profili {profile['name']}. Beklenen yaklaşım: {profile['standard']}; yerel otorite: {profile['authority']}. Bu demo doğrulaması resmi bir vergi otoritesi kararı değildir."
    return f"Fatura {invoice.get('invoice_id') or 'numarasız'} olarak okundu. {len(invoice.get('lines') or [])} satır ve {invoice.get('currency') or 'belirtilmemiş'} para birimi tespit ettim. Tutar, taraflar veya {profile['name']} profili hakkında sorabilirsiniz."


def openai_answer(question: str, invoice: dict[str, Any] | None, profile: dict[str, Any]) -> str | None:
    api_key = os.getenv("OPENAI_API_KEY")
    if not api_key:
        return None
    payload = {"model": os.getenv("OPENAI_MODEL", "gpt-4o-mini"), "temperature": 0.2, "messages": [
        {"role": "system", "content": "You are an invoice validation copilot. Answer in Turkish, be concise, cite fields from the provided normalized invoice, and never claim official tax compliance. Explain missing data clearly."},
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
    return JSONResponse({"countries": [{"code": code, **profile} for code, profile in COUNTRY_PROFILES.items()]})


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
    answer = openai_answer(question, invoice, profile)
    return JSONResponse({"answer": answer or fallback_answer(question, invoice, profile), "provider": "openai" if answer else "local", "country": code})


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
