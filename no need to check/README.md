# ⚡ Flexbase Free Fire UniPin Topup API v2

A high-performance, automated REST API gateway for **Garena Free Fire (BD Server)** UniPin voucher redemptions. Built with Flask, Cloudscraper, and BeautifulSoup, fully compatible with **UcBot API specifications**.

[![Deploy with Vercel](https://vercel.com/button)](https://vercel.com/new/clone?repository-url=https%3A%2F%2Fgithub.com%2FLinux-Hossain%2Flinuxunipin-v2)

---

## 🌟 Key Features

- ⚡ **Synchronous Processing**:
  - `POST /topup-sync` — Direct response after the transaction finishes.
  - `POST /api/unipin` — Compatibility alias for `/topup-sync`.
- 🔄 **Batch Voucher Redeem**: Send up to **5 UniPin codes at once** (comma-separated).
- 🎯 **Auto Package Detection**: No manual `packageId` required! Automatically detects denomination from code prefixes (`BDMB-T-S`, `UPBD-N-S`, etc.).
- 🧾 **Detailed Transaction Receipt**: Returns official UniPin `trans_no` (`trx_id`), date, reference, item name, and amount.
- 🔑 **Flexible Authentication**: Pass token via `Authorization: Bearer <key>` header or `apiKey` in JSON body/query params.
- 📊 **Subscription Control**: Each authenticated topup request is counted against a configurable limit and expiry date.
- 🚀 **Vercel Ready**: Pre-configured with `vercel.json` for serverless deployment.

---

## 🚀 One-Click Vercel Deployment

Deploy your own instance on Vercel for free in under 60 seconds:

[![Deploy with Vercel](https://vercel.com/button)](https://vercel.com/new/clone?repository-url=https%3A%2F%2Fgithub.com%2FLinux-Hossain%2Flinuxunipin-v2)

---

## 🛠️ Local Installation & Usage

### Prerequisites
- Python 3.9+
- `pip`

### Step-by-Step Setup

1. **Clone the repository:**
   ```bash
   git clone https://github.com/Linux-Hossain/linuxunipin-v2.git
   cd linuxunipin-v2
   ```

2. **Install dependencies:**
   ```bash
   pip install -r requirements.txt
   ```

3. **Start the API Server:**
   ```bash
   python app.py
   ```
   *Server will run at `http://localhost:8000`*

---

## 📖 API Endpoints Reference

### Subscription and Request Limits

The API key identifies a client subscription. Every authenticated `/topup-sync` request consumes one request, including requests that later fail at the provider. Multiple subscriptions are stored in `logs/subscriptions.json`. The current subscription can be checked with:

```http
GET /status/{api-key}
```

Each JSON record contains `max_requests`, `used_requests`, `expires_at`, and `active`. Exhausted or expired subscriptions return HTTP `402`. JSON is suitable for local development only; for Vercel production, replace it with an external database because serverless filesystems are not durable.

### 1. Synchronous Top-up (Instant Result)

- **Endpoint:** `POST /topup-sync` or `POST /api/unipin`
- **Headers:** `Authorization: Bearer linux-lx0199222` (or `70c9188c-e70e-4eb3-bd50-7d375d2a390c`)
- **Content-Type:** `application/json`

#### Request Body
```json
{
  "orderid": "ORD-1001",
  "playerid": "228197025",
  "code": "BDMB-Q-S-15359391 2331-6265-6656-9336,BDMB-Q-S-15358262 5363-6431-5333-7468",
  "apiKey": "linux-lx0199222"
}
```

#### Success Response (200 OK)
```json
{
  "status": "success",
  "orderid": "ORD-1001",
  "nickname": "PlayerName",
  "username": "PlayerName",
  "region": "BD",
  "total": 2,
  "success": 2,
  "failed": 0,
  "batch": [
    {
      "uc": "BDMB-Q-S-15359391 2331-6265-6656-9336",
      "ok": true,
      "detail": "✅ Success",
      "trx_id": "UP-20260825-12345",
      "receipt": {
        "date": "2026-08-25",
        "trans_no": "UP-20260825-12345",
        "reference": "REF12345",
        "item": "Weekly Membership",
        "amount": "161.00"
      }
    },
    {
      "uc": "BDMB-Q-S-15358262 5363-6431-5333-7468",
      "ok": true,
      "detail": "✅ Success",
      "trx_id": "UP-20260825-12346"
    }
  ]
}
```

---

---

## 🎯 Auto Package Prefix Mapping

| Prefix | Product | Package ID |
| :--- | :--- | :---: |
| `BDMB-T-S` / `UPBD-Q-S` | 25 Diamond | `1` |
| `BDMB-U-S` / `UPBD-R-S` | 50 Diamond | `2` |
| `BDMB-J-S` / `UPBD-G-S` | 115 Diamond | `3` |
| `BDMB-I-S` / `UPBD-F-S` | 240 Diamond | `4` |
| `BDMB-K-S` / `UPBD-H-S` | 610 Diamond | `5` |
| `BDMB-L-S` / `UPBD-I-S` | 1240 Diamond | `6` |
| `BDMB-M-S` / `UPBD-J-S` | 2530 Diamond | `7` |
| `BDMB-Q-S` / `UPBD-N-S` | Weekly Membership | `8` |
| `BDMB-S-S` / `UPBD-P-S` | Monthly Membership | `9` |

---

## 📜 License

Distributed under the MIT License. See `LICENSE` for more information.

---

Made with ❤️ by [Linux Hossain](https://github.com/Linux-Hossain)
