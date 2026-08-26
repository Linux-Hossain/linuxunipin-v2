# ─── LINUXUNIPIN_V2 PERMANENT PROJECT RULES ────────────────────────────────

## 1. PROCESS MANAGEMENT (ALWAYS KILL OLD BEFORE NEW)
- **Always terminate/kill existing running server processes** before launching a new instance to prevent port conflicts or ghost threads on port 45892.

## 2. FIXED & IMMUTABLE API CONTRACTS (NEVER CHANGE)
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

## 3. SILENT AUTO-RETRY & ROTATING PROXY
- Garena payment init uses rotating Webshare Singapore residential proxy (`cghgkxjs-sg`).
- Transient network drops or DataDome empty nickname responses must ALWAYS be retried silently (up to 2 attempts) with a fresh rotating IP before marking as failed.
- UniPin voucher redemption runs direct for 0-latency and maximum speed.

