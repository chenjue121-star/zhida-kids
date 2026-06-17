# 智搭 Phase 1 API

FastAPI backend for the Phase 1 WeChat mini program foundation: WeChat login, user profile, and child profile management.

## Local Setup

1. Create a MySQL database:

```sql
CREATE DATABASE zhida_kids DEFAULT CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci;
```

2. Install dependencies:

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

3. Configure environment:

```bash
cp .env.example .env
```

Set `DATABASE_URL`, `JWT_SECRET`, `WECHAT_APPID`, and `WECHAT_SECRET`.

For local interface testing without real WeChat credentials, set:

```env
DEV_WECHAT_MOCK=true
```

4. Start the API:

```bash
uvicorn app.main:app --reload
```

The mini program defaults to `http://127.0.0.1:8000`.

## Local Model Debugging With ngrok

External model APIs need to read uploaded images from `/uploads/...`. In local development, keep FastAPI on `127.0.0.1:8000` and expose it with ngrok:

```bash
uvicorn app.main:app --host 127.0.0.1 --port 8000
ngrok http 8000
```

Copy the HTTPS forwarding URL from ngrok into `backend/.env`:

```env
PUBLIC_BASE_URL=https://xxxx.ngrok-free.app
AI_IMAGE_DATA_URL_FALLBACK=false
```

Restart FastAPI after editing `.env`. New uploads will return ngrok-based URLs. Old `127.0.0.1/uploads/...` records can still be reused because the backend rewrites the `/uploads/...` path with the current `PUBLIC_BASE_URL` before sending it to model APIs.

## Tencent Cloud COS Uploads

For stable model image access, use Tencent Cloud COS instead of ngrok:

```env
UPLOAD_BACKEND=cos
TENCENT_COS_SECRET_ID=your-cos-secret-id
TENCENT_COS_SECRET_KEY=your-cos-secret-key
TENCENT_COS_REGION=ap-shanghai
TENCENT_COS_BUCKET=your-bucket-1250000000
TENCENT_COS_PREFIX=zhida-kids/dev
TENCENT_COS_PUBLIC_BASE_URL=https://your-bucket-1250000000.cos.ap-shanghai.myqcloud.com
```

Install dependencies after updating `requirements.txt`:

```bash
pip install -r requirements.txt
```

Keep the bucket public-read/private-write for local MVP testing so Doubao and gptsapi can download image URLs directly. Use a CAM sub-account with permission limited to the target bucket.

## Phase 1 Endpoints

- `GET /health`
- `POST /auth/wechat-login`
- `GET /me`
- `PUT /me`
- `GET /children`
- `POST /children`
- `PUT /children/{child_id}`
- `DELETE /children/{child_id}`
