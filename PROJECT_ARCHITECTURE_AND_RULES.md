# LinuxUniPin V2 - Project Architecture, Rules & Research Reference

> **CRITICAL NOTICE FOR AI ASSISTANTS & DEVELOPERS**:
> Read this document completely before modifying or creating any files in this project. All rules documented here MUST be followed strictly without exception.

---

## 🛑 STRICT USER RULES (STRICTLY NEVER BREAK)

### 1. LOG PROTECTION POLICY (NEVER OVERWRITE LOGS)
- **RULE**: NEVER clear, truncate, overwrite, or delete `api_requests.log` or any other log file in the repository without explicit user permission.
- **REASON**: Historical logs contain critical business and transaction audit data. All logging MUST be append-only (`mode="a"`).

### 2. FILE SEPARATION & BASELINE PRESERVATION POLICY
- **RULE**: NEVER edit or modify `unpicccc.py` directly under any circumstances.
- **REASON**: `unpicccc.py` is the original stable baseline. All new features, performance optimizations, and updates MUST be written into standalone test files (e.g., `unpicctest1.py`, `unpicctest2.py`).

### 3. LOG FORMATTING & READABILITY REQUIREMENTS
- **Execution Duration**: Every response log entry (`RESP_SINGLE` / `RESP_BATCH`) MUST include `duration={duration}s` recording the exact request processing time.
- **Log Spacing**: Put a blank line separator (`\n\n`) after every completed request pair (`CALL_...` and `RESP_...`) so that logs are easily readable for human operators.

---

## 📑 RESELLER / UCBOT API RESPONSE SCHEMA (100% COMPATIBILITY)

Reseller scripts and UcBot parse responses using different legacy key names. The response returned by `/topup-sync` MUST include **all** of the following keys to prevent breaking reseller bots:

### Root JSON Schema
```json
{
  "batch": [ /* Array of voucher result objects */ ],
  "data": [ /* Mirror array of voucher result objects for legacy scripts */ ],
  "status": "success",
  "success": 1,
  "failed": 0,
  "total": 1,
  "username": "PlayerNickname",
  "nickname": "PlayerNickname",
  "playerid": "572934026",
  "orderid": "ORD-SYNC",
  "total_codes": 1,
  "successful_codes": 1,
  "failed_codes": 0
}
```

### Voucher Result Object Schema (Inside `batch` & `data` arrays)
```json
{
  "ok": true,
  "uc": "UPBD-P-S-04062836 6474-3574-9453-5350",
  "code": "UPBD-P-S-04062836 6474-3574-9453-5350",
  "detail": "",
  "item": "Monthly Membership",
  "status": "SUCCESS",
  "message": "Completed",
  "transaction_no": "7467cb84-6cc9-472c-892f-c87a0e34d151 Copied",
  "amount": "800.00",
  "url": "https://www.unipin.com/unibox/result/..."
}
```

---

## ⚡ TECHNICAL RESEARCH & PERFORMANCE ARCHITECTURE

### 1. Cloudflare & Akamai TLS Impersonation
- Standard libraries (`aiohttp`, `httpx`, `urllib`, `requests`) WILL BE BLOCKED with `HTTP 403 Forbidden` due to TLS/JA3 fingerprinting.
- **Solution**: Use `curl_cffi.requests.Session(impersonate="chrome120")`.

### 2. Session Pre-Warming Pool (`background_session_warmer`)
- Visiting `https://shop.garena.my` and posting to `https://datadome.garena.com/js/` takes ~2.5 seconds per request over WebShare proxies.
- **Solution**: A background daemon thread (`background_session_warmer`) continuously maintains a pool of 3-4 pre-warmed, fully authenticated `curl_cffi` session objects (`SESSION_POOL`).
- When a request arrives, `get_warmed_session()` fetches a pre-initialized session in **0.00 seconds**, instantly saving 2.5 seconds.

### 3. Thread Safety & Denomination Isolation
- **DO NOT** share a single `requests.Session` object directly across concurrent threads during Garena payment init (`proceed_to_payment`). Concurrent mutations of session state cause race conditions on Garena's backend (`Payment init failed or UniPin URL missing`).
- **Solution**: Use `clone_session(base_session)` to assign each concurrent voucher thread its own isolated session copy (cloning cookies and proxy configuration). This maintains 100% thread safety and prevents item denomination mismatches.

### 4. Direct Form Submission & Connection Keep-Alive
- Bypass intermediate HTML redirects on UniPin pages.
- Extract `_token` directly and POST voucher serial & PIN fields with `Connection: keep-alive` to minimize network round-trip time (RTT).

---

## 🌐 DEPLOYMENT & SERVER SPECIFICATIONS

- **Server IP**: `103.204.87.106`
- **Active Port**: `5987`
- **Active Bearer Token**: `70c9188c-e70e-4eb3-bd50-7d375d2a390c`
- **Active Proxy Pool**: WebShare SG proxies (`PROXY_POOL_SG`) with cyclic rotation.
- **Active Script File**: `unpicctest1.py`
