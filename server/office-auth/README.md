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
| POST | `/api/tool_cli/slide_generate` | One-slide PPTX for `generate_deck` (Gemini + python-pptx) |

## Deploy

```bash
rsync -avz --exclude .venv ./ root@SERVER:/opt/trivena/office-auth/
ssh root@SERVER 'cd /opt/trivena/office-auth && python3 -m venv .venv && .venv/bin/pip install -r requirements.txt && systemctl restart trivena-office-auth'
```

Nginx snippets: `nginx-office-auth.conf` (already applied on press host).

## Press guest API allowlist (required for signup)

Trivena Press blocks most `/api/method/*` calls for Guests / Website Users
(`press.auth.hook` → “Access not allowed for this URL”).

These paths must stay in `ALLOWED_PATHS` in `press/auth.py` (live module is
under `/opt/trivena/press-src/...`, hard-linked into the bench app):

- `/api/method/trivena.core.doctype.user.user.sign_up`
- `/api/method/trivena.core.doctype.user.user.reset_password`
- `/api/method/trivena.core.doctype.user.user.update_password`
- `/api/method/trivena.core.doctype.user.user.test_password_strength`
- `/api/method/trivena_framework.core.doctype.user.user.sign_up`
- `/api/method/trivena_framework.core.doctype.user.user.reset_password`
- `/api/method/trivena_framework.core.doctype.user.user.update_password`
- `/api/method/trivena_framework.core.doctype.user.user.test_password_strength`
- `/api/method/trivena.auth.get_logged_user`
- `/api/method/frappe.auth.get_logged_user`

(The update-password page calls the `trivena_framework.*` method names; both
prefixes must be allowlisted.)

After editing, restart `trivena-press-web.service` (not only `bench restart`).

### Press Team required after signup

Framework `sign_up` only creates a **User**. Press login then expects a **Team**
and the **Press User** role (`User … is not part of any team`).

- One-off: create a free Team + `Press User` for the email (see ops notes /
  `ensure_team_for_website_user` in `press/overrides.py`).
- Ongoing: `on_login` auto-provisions a free Parent Team when missing so
  TrivOffice device-code signups can finish login.

## Env

- `FRAPPE_BASE_URL` — default `https://cloud.trivena.tech`
- `PUBLIC_BASE_URL` — auth URLs shown to the desktop
- `GEMINI_API_KEY` — primary LLM gateway (Google AI Studio; OpenAI-compatible proxy)
- `GEMINI_DEFAULT_MODEL` — default `gemini-2.5-flash`
- `OPENROUTER_API_KEY` — fallback if Gemini is unset
- `ANTHROPIC_API_KEY` / `OPENAI_API_KEY` — optional direct vendor proxies
