# Trivena Office Auth

Device-code login + API keys for **TrivOffice**, hosted on Trivena Cloud.

## Live endpoints (cloud.trivena.tech)

| Method | Path | Purpose |
|--------|------|---------|
| POST | `/api/office_addin_auth/device_code` | Start desktop login |
| GET | `/office-auth/verify?code=` | Browser authorize page (uses Trivena Cloud session) |
| GET | `/api/office_addin_auth/token` | Poll until approved |
| POST | `/api/office_addin_auth/session` | Mint session cookie |
| POST | `/api/api_tokens/create` | Create TrivOffice API key |
| POST | `/api/api_tokens/revoke` | Revoke key |
| * | `/api/llm/...` | LLM gateway (needs vendor keys in env) |

## Deploy

```bash
rsync -avz --exclude .venv ./ root@SERVER:/opt/trivena/office-auth/
ssh root@SERVER 'cd /opt/trivena/office-auth && python3 -m venv .venv && .venv/bin/pip install -r requirements.txt && systemctl restart trivena-office-auth'
```

Nginx snippets: `nginx-office-auth.conf` (already applied on press host).

## Env

- `FRAPPE_BASE_URL` — default `https://cloud.trivena.tech`
- `PUBLIC_BASE_URL` — auth URLs shown to the desktop
- `GEMINI_API_KEY` — primary LLM gateway (Google AI Studio; OpenAI-compatible proxy)
- `GEMINI_DEFAULT_MODEL` — default `gemini-2.5-flash`
- `OPENROUTER_API_KEY` — fallback if Gemini is unset
- `ANTHROPIC_API_KEY` / `OPENAI_API_KEY` — optional direct vendor proxies
