# Invoice Atlas

Ülke adaptörleriyle genişleyebilen, XML/JSON/metin tabanlı e-fatura validasyon ve görsel önizleme portalı.

## Özellikler

- Slovakya varsayılan profil: EN 16931 / Peppol BIS Billing 3.0 bağlamında temel alan, taraf ve tutar kontrolleri
- Aynı kanonik veri modeli üzerinden SK, CZ, DE, FR, IT, ES, NL, GB ve US profilleri
- XML (UBL benzeri), JSON ve etiketli düz metin parse etme
- Sağ panelde insan-okunabilir fatura görünümü; yazdırma ve tam ekran
- Opsiyonel OpenAI bağlantılı AI Invoice Copilot; anahtar yoksa yerel soru-cevap fallback'i
- Vercel Python runtime ile deploy edilebilir

## Lokal çalıştırma

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
python api/index.py
```

Sonra `http://127.0.0.1:8000` adresini açın. Lokal server FastAPI API'sini çalıştırır; frontend Vercel route'larıyla sunulacağı için lokal geliştirmede hızlı test için `public/index.html` dosyasını Live Server ile de açabilirsiniz.

## AI Copilot

Copilot panelindeki “Kendi OpenAI API anahtarın” alanına müşteri kendi anahtarını girebilir. Anahtar `X-OpenAI-API-Key` header'ı ile yalnızca o istekte kullanılır; uygulama tarafından kaydedilmez, loglanmaz ve Git/Vercel'e yazılmaz. Anahtar girilmezse temel alan soruları yerel fallback ile yanıtlanır. Sunucu sahibi anahtarıyla çalıştırmak isterseniz `.env` içine `OPENAI_API_KEY` ve isteğe bağlı `OPENAI_MODEL` ekleyebilirsiniz.

## Git ve Vercel

```powershell
git init
git add .
git commit -m "Build generic e-invoice validation portal"
git branch -M main
git remote add origin <GITHUB_REPO_URL>
git push -u origin main
```

Vercel'de repo'yu import edin. Framework preset için `Other` seçilebilir; `vercel.json` Python API ve statik frontend route'larını tanımlar. Müşteri anahtarı kullanacağı için Vercel'e `OPENAI_API_KEY` eklemek zorunlu değildir. Kullanıcıların yalnızca güvendikleri deployment'a anahtar girmesi gerekir; OpenAI API anahtarı paylaşılmamalıdır.

> Not: Bu proje resmi vergi otoritesi onayı veya hukuki uyumluluk kararı vermez; validasyon katmanı genişletilebilir bir ürün temelidir.
