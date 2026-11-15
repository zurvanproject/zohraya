# ATMOSPHERE evidence trust + offline recovery + Awake/DIOS ingress (candidate)

این بسته از PR #237 و #205 جداست. فقط داده‌های محدود شبیه‌سازی را می‌پذیرد، نه فرمان‌های اجرایی یا دادهٔ بالینی.

## Quick tests

```bash
python -m unittest discover -s tests -p 'test_atmosphere_*.py' -v
```

نیازمندی برای تأیید امضای Ed25519: `cryptography>=42`. بدون آن، اعتبارسنجی از کار می‌افتد و داده‌ای پذیرفته نمی‌شود.

برای اجرای مستقیم test اصل PR #205، checkout مستقل `90692bde9f1e4b5b7f311162b7c83127715df710` باید در PYTHONPATH قرار داده شود.

راهنمای کامل و مرزهای امنیتی: `docs/ATMOSPHERE_TRUST_AWAKE_RECOVERY_FA.md`.

> توجه: این بسته آمادهٔ بررسی و آزمایش ایزوله است، **نه استقرار خودکار روی VPS**. کپی مستقل پشتیبان و امضای منبع خارجی هنوز باید توسط اپراتور برقرار شود.