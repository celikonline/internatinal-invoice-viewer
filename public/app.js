const sampleInvoice = `<Invoice xmlns="urn:oasis:names:specification:ubl:schema:xsd:Invoice-2" xmlns:cac="urn:oasis:names:specification:ubl:schema:xsd:CommonAggregateComponents-2" xmlns:cbc="urn:oasis:names:specification:ubl:schema:xsd:CommonBasicComponents-2">
  <cbc:ID>INV-2026-0042</cbc:ID>
  <cbc:IssueDate>2026-08-29</cbc:IssueDate>
  <cbc:DocumentCurrencyCode>EUR</cbc:DocumentCurrencyCode>
  <cac:AccountingSupplierParty><cac:Party><cac:PartyName><cbc:Name>Danube Digital s.r.o.</cbc:Name></cac:PartyName><cac:PostalAddress><cbc:StreetName>Prievozská 14</cbc:StreetName><cbc:CityName>Bratislava</cbc:CityName></cac:PostalAddress><cac:PartyTaxScheme><cbc:CompanyID>SK2020123456</cbc:CompanyID></cac:PartyTaxScheme></cac:Party></cac:AccountingSupplierParty>
  <cac:AccountingCustomerParty><cac:Party><cac:PartyName><cbc:Name>Nordic Retail AB</cbc:Name></cac:PartyName><cac:PostalAddress><cbc:StreetName>Vasagatan 8</cbc:StreetName><cbc:CityName>Stockholm</cbc:CityName></cac:PostalAddress></cac:Party></cac:AccountingCustomerParty>
  <cac:InvoiceLine><cbc:ID>1</cbc:ID><cbc:InvoicedQuantity>2</cbc:InvoicedQuantity><cac:Item><cbc:Name>Cloud workspace - annual</cbc:Name></cac:Item><cac:Price><cbc:PriceAmount>240.00</cbc:PriceAmount></cac:Price><cac:TaxCategory><cbc:Percent>20</cbc:Percent></cac:TaxCategory></cac:InvoiceLine>
  <cac:InvoiceLine><cbc:ID>2</cbc:ID><cbc:InvoicedQuantity>1</cbc:InvoicedQuantity><cac:Item><cbc:Name>Onboarding &amp; support</cbc:Name></cac:Item><cac:Price><cbc:PriceAmount>120.00</cbc:PriceAmount></cac:Price><cac:TaxCategory><cbc:Percent>20</cbc:Percent></cac:TaxCategory></cac:InvoiceLine>
  <cac:TaxTotal><cbc:TaxAmount>120.00</cbc:TaxAmount></cac:TaxTotal><cac:LegalMonetaryTotal><cbc:TaxExclusiveAmount>600.00</cbc:TaxExclusiveAmount><cbc:TaxInclusiveAmount>720.00</cbc:TaxInclusiveAmount><cbc:PayableAmount>720.00</cbc:PayableAmount></cac:LegalMonetaryTotal>
</Invoice>`;

const state = { countries: [], result: null };
const $ = (id) => document.getElementById(id);

function escapeHtml(value) { return String(value ?? '').replace(/[&<>'"]/g, (char) => ({'&':'&amp;','<':'&lt;','>':'&gt;',"'":'&#39;','"':'&quot;'}[char])); }
function showToast(message) { const toast = $('toast'); toast.textContent = message; toast.classList.add('show'); setTimeout(() => toast.classList.remove('show'), 2600); }
function selectedCountry() { return $('country').value || 'SK'; }
function updateCharCount() { $('charCount').textContent = `${$('invoiceInput').value.length.toLocaleString('tr-TR')} karakter`; }
function profileChanged() { const profile = state.countries.find((item) => item.code === selectedCountry()); if (profile) $('profileStandard').textContent = profile.standard; }
function updateMapState() { const code = selectedCountry(); document.querySelectorAll('.map-country').forEach((country) => country.classList.toggle('active', country.dataset.country === code)); const profile = state.countries.find((item) => item.code === code); if (profile) { $('mapCurrent').textContent = `${profile.code} · ${profile.native || profile.name}`; $('mapCurrentName').textContent = profile.name; } }
function chooseCountry(code) { if (!state.countries.some((country) => country.code === code)) return; $('country').value = code; profileChanged(); updateMapState(); showToast(`${code} ülke profili seçildi.`); $('sourcePanel').scrollIntoView({behavior:'smooth', block:'start'}); setTimeout(() => $('invoiceInput').focus({preventScroll:true}), 450); }
function bindMapCountries() { document.querySelectorAll('.map-country').forEach((country) => { country.addEventListener('click', () => chooseCountry(country.dataset.country)); country.addEventListener('keydown', (event) => { if (event.key === 'Enter' || event.key === ' ') { event.preventDefault(); chooseCountry(country.dataset.country); } }); }); }

async function loadCountries() {
  try {
    const response = await fetch('/api/countries'); state.countries = (await response.json()).countries;
  } catch { state.countries = [{code:'SK',name:'Slovakia',native:'Slovensko',standard:'EN 16931 / Peppol BIS Billing 3.0'}]; }
  $('country').innerHTML = state.countries.map((country) => `<option value="${country.code}">${country.code} · ${escapeHtml(country.native || country.name)}</option>`).join('');
  $('country').value = 'SK'; profileChanged(); bindMapCountries(); updateMapState();
  $('countryCloud').innerHTML = state.countries.map((country) => `<span class="${country.code === 'SK' ? 'active' : ''}">${country.code}</span>`).join('');
}

function renderPaper(invoice, profile) {
  const lines = invoice.lines?.length ? invoice.lines : [{description:'Belgede satır bulunamadı',quantity:'—',unit_price:'—',vat_rate:'—'}];
  $('invoicePaper').innerHTML = `<div class="paper-top"><div class="paper-brand">invoice<span>atlas</span></div><div class="paper-title"><h3>INVOICE</h3><p>${escapeHtml(invoice.invoice_id || 'UNNUMBERED')} · ${escapeHtml(invoice.issue_date || '—')}</p></div></div>
    <div class="paper-grid"><div><div class="paper-label">Issued by</div><div class="paper-value">${escapeHtml(invoice.seller?.name || 'Bilinmiyor')}</div><div class="paper-muted">${escapeHtml(invoice.seller?.address || 'Adres belirtilmemiş')}<br />${escapeHtml(invoice.seller?.vat_id || invoice.vat_id || profile.vat_label + ' belirtilmemiş')}</div></div><div><div class="paper-label">Billed to</div><div class="paper-value">${escapeHtml(invoice.buyer?.name || 'Bilinmiyor')}</div><div class="paper-muted">${escapeHtml(invoice.buyer?.address || 'Adres belirtilmemiş')}</div></div></div>
    <table><thead><tr><th>AÇIKLAMA</th><th>ADET</th><th>BİRİM</th><th>TOPLAM</th></tr></thead><tbody>${lines.map((line) => `<tr><td>${escapeHtml(line.description)}</td><td>${escapeHtml(line.quantity)}</td><td>${escapeHtml(line.unit_price)}</td><td>${line.quantity && line.unit_price && !isNaN(Number(line.quantity) * Number(String(line.unit_price).replace(',','.'))) ? (Number(line.quantity) * Number(String(line.unit_price).replace(',','.'))).toFixed(2) : '—'}</td></tr>`).join('')}</tbody></table>
    <div class="totals"><div class="total-line"><span>Net toplam</span><span>${escapeHtml(invoice.net_total || '—')} ${escapeHtml(invoice.currency || '')}</span></div><div class="total-line"><span>KDV / Vergi</span><span>${escapeHtml(invoice.vat_total || '—')} ${escapeHtml(invoice.currency || '')}</span></div><div class="total-line grand"><span>Ödenecek</span><span>${escapeHtml(invoice.gross_total || '—')} ${escapeHtml(invoice.currency || '')}</span></div></div>
    <div class="paper-footer"><span>${escapeHtml(profile.name)} profile</span><span>${escapeHtml(profile.standard)}</span></div>`;
  $('previewPlaceholder').classList.add('hidden'); $('invoicePaper').classList.remove('hidden');
}

function renderValidation(result) {
  state.result = result; $('validationEmpty').classList.add('hidden'); $('validationContent').classList.remove('hidden');
  const badge = $('statusBadge'); badge.textContent = result.valid ? 'Geçerli yapı' : 'İnceleme gerekli'; badge.className = `status-badge ${result.valid ? 'success' : 'failure'}`;
  $('scoreValue').textContent = `${result.score}`; $('scoreRing').style.background = `conic-gradient(${result.valid ? 'var(--green)' : 'var(--orange)'} ${result.score * 3.6}deg,#edf0f6 0deg)`;
  $('scoreTitle').textContent = result.valid ? 'Temel kontroller başarılı' : 'Bazı alanları gözden geçirin'; $('scoreDetail').textContent = `${result.summary?.passed || 0} geçti · ${result.summary?.warnings || 0} uyarı · ${result.summary?.errors || 0} hata`;
  $('checkList').innerHTML = (result.checks || []).map((item) => `<div class="check-item"><span class="check-icon ${item.severity}">${item.severity === 'pass' ? '✓' : item.severity === 'warning' ? '!' : '×'}</span><span class="check-main">${escapeHtml(item.message)}</span><span class="check-detail">${escapeHtml(item.detail || item.field)}</span></div>`).join('');
  if (result.invoice) renderPaper(result.invoice, result.profile);
}

async function validate() {
  const invoice = $('invoiceInput').value.trim(); if (!invoice) { showToast('Önce bir fatura metni ekleyin.'); $('invoiceInput').focus(); return; }
  const button = $('validateButton'); button.disabled = true; button.innerHTML = '<span class="button-icon">◌</span> Analiz ediliyor…';
  try { const response = await fetch('/api/validate', {method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({invoice,country:selectedCountry()})}); renderValidation(await response.json()); showToast('Fatura analizi tamamlandı.'); }
  catch { showToast('API bağlantısı kurulamadı. Local server çalışıyor mu?'); }
  finally { button.disabled = false; button.innerHTML = '<span class="button-icon">✦</span> Faturayı doğrula <span class="button-arrow">↗</span>'; }
}

function addChat(role, message) { const log = $('chatLog'); const row = document.createElement('div'); row.className = `chat-message ${role}`; row.innerHTML = role === 'assistant' ? `<span class="avatar">✦</span><div>${escapeHtml(message)}</div>` : `<div>${escapeHtml(message)}</div>`; log.appendChild(row); log.scrollTop = log.scrollHeight; }
async function ask(question) { if (!question) return; addChat('user', question); $('chatInput').value = ''; try { const headers = {'Content-Type':'application/json'}; const apiKey = getApiKey(); if (apiKey) headers['X-OpenAI-API-Key'] = apiKey; const response = await fetch('/api/ask', {method:'POST',headers,body:JSON.stringify({question,invoice:state.result?.invoice || null,country:selectedCountry()})}); const data = await response.json(); addChat('assistant', data.answer || data.error || 'Copilot cevap veremedi.'); } catch { addChat('assistant', 'Copilot bağlantısı şu anda kullanılamıyor.'); } }

function getApiKey() { return $('apiKeyInput').value.trim(); }
function updateKeyState() { const hasKey = Boolean(getApiKey()); $('keyState').textContent = hasKey ? 'Bu oturum için hazır' : 'Ayarlanmadı'; $('keyState').className = `key-state ${hasKey ? 'ready' : ''}`; }

$('invoiceInput').value = sampleInvoice; updateCharCount();
$('invoiceInput').addEventListener('input', updateCharCount); $('country').addEventListener('change', () => { profileChanged(); updateMapState(); }); $('validateButton').addEventListener('click', validate);
$('sampleButton').addEventListener('click', () => { $('invoiceInput').value = sampleInvoice; updateCharCount(); showToast('Örnek Slovakya UBL faturası yüklendi.'); });
$('clearButton').addEventListener('click', () => { $('invoiceInput').value = ''; updateCharCount(); $('previewPlaceholder').classList.remove('hidden'); $('invoicePaper').classList.add('hidden'); $('validationEmpty').classList.remove('hidden'); $('validationContent').classList.add('hidden'); $('statusBadge').className = 'status-badge neutral'; $('statusBadge').textContent = 'Bekliyor'; });
$('chatForm').addEventListener('submit', (event) => { event.preventDefault(); ask($('chatInput').value.trim()); }); document.querySelectorAll('.suggestions button').forEach((button) => button.addEventListener('click', () => ask(button.dataset.question)));
$('apiKeyInput').addEventListener('input', updateKeyState); $('clearKeyButton').addEventListener('click', () => { $('apiKeyInput').value = ''; updateKeyState(); });
$('printButton').addEventListener('click', () => { if (!state.result?.invoice) { showToast('Önce faturayı doğrulayın.'); return; } window.print(); }); $('fullscreenButton').addEventListener('click', () => $('previewWrap').requestFullscreen?.());
loadCountries();
