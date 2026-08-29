# ─── LINUXUNIPIN_V2 PERMANENT PROJECT RULES ────────────────────────────────

## 1. PROCESS MANAGEMENT (ALWAYS KILL OLD BEFORE NEW)
- **Always terminate/kill existing running server processes** before launching a new instance to prevent port conflicts or ghost threads on port 45892.

## 2. GIT COMMIT & PUSH POLICY (NEVER COMMIT WITHOUT USER PERMISSION)
- **NEVER perform `git commit` or `git push` automatically without asking the user and getting explicit permission first.**

## 3. GARENA & UNIPIN TLS IMPERSONATION (CURL_CFFI MANDATE)
- **Garena login, payment init, and UniPin voucher redemption MUST use `curl_cffi` with Chrome TLS Impersonation (`requests.Session(impersonate="chrome120")`).**
- NEVER replace with plain `requests.Session()` or `httpx` lacking TLS fingerprinting, as Garena/DataDome strictly check TLS/JA3 browser fingerprints. `curl_cffi` provides native Chrome TLS impersonation for sub-second speeds bypassing DataDome challenges.

## 4. FIXED & IMMUTABLE API CONTRACTS (NEVER CHANGE)
- **Input Formats**:
  - Accepted routes: `/api/unipin`, `/topup-sync`, `/api/unipin/async`, `/topup`
  - Parameters: `uid` / `playerid`, `code`, `orderid`, `packageId`, `apiKey`, `url` (async callback).
- **Output JSON Schemas**:
  - The JSON output structure must NEVER be altered under any circumstances:
  ```json
  {
    "status": "success" | "partial" | "failed",
    "orderid": "string",
    "nickname": "string",
    "username": "string",
    "region": "string",
    "success": 0,
    "failed": 0,
    "total": 0,
    "batch": [
      {
        "uc": "CODE_STRING",
        "ok": true | false,
        "detail": "✅ Success" | "❌ Error Reason",
        "trx_id": "string (optional on success)",
        "receipt": { "date": "...", "trans_no": "...", "reference": "...", "item": "...", "amount": "..." }
      }
    ]
  }
  ```
- **Output Cleanliness**:
  - NEVER output "retry" or internal debug statuses to API responses.

## 5. SILENT AUTO-RETRY & ROTATING PROXY
- Garena payment init uses rotating Webshare Singapore residential proxy (`cghgkxjs-sg`).
- Transient network drops or DataDome empty nickname responses must ALWAYS be retried silently (up to 2 attempts) with a fresh rotating IP before marking as failed.
- UniPin voucher redemption runs direct for 0-latency and maximum speed.
