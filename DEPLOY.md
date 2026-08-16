# Deploying jobwatch to Render

The whole stack is declared in [`render.yaml`](render.yaml): a Postgres database,
the Go API, the React static site, and two scheduled jobs (scrape, digest).

## 1. Create the services

In the Render dashboard: **New → Blueprint**, pick the `devinrhaslam/jobwatch`
repo, and apply. Render reads `render.yaml` and creates everything. It will prompt
for the `sync: false` values — you can enter placeholders now and correct them in
step 3.

## 2. Note the URLs

Once the services exist, Render shows each one's URL, e.g.:

- backend → `https://jobwatch-backend.onrender.com`
- web → `https://jobwatch-web.onrender.com`

(If a name was taken, Render appends a suffix — use the actual URLs it shows.)

## 3. Set the environment variables

| Service | Key | Value |
|---|---|---|
| jobwatch-backend | `ANTHROPIC_API_KEY` | your Anthropic key |
| jobwatch-backend | `JOBWATCH_APP_URL` | the **web** URL |
| jobwatch-backend | `JOBWATCH_ALLOWED_ORIGIN` | the **web** URL |
| jobwatch-web | `VITE_API_BASE` | the **backend** URL |
| jobwatch-digest | `ANTHROPIC_API_KEY` | your Anthropic key |

`VITE_API_BASE` is baked in at build time, so after setting it, **redeploy the
web service** (Manual Deploy → Deploy latest commit) so the build picks it up.

## 4. Create the database schema

Render's Postgres starts empty. Apply the schema once, using the database's
**External Connection String** (Render dashboard → jobwatch-db → Connect):

```bash
psql "<external-connection-string>" -f schema.sql
```

Every statement is `IF NOT EXISTS`, so re-running is safe.

## 5. Seed the jobs

Trigger the scrape once by hand so the jobs table isn't empty: Render dashboard →
**jobwatch-ingest → Run now**. The first run seeds every company (tens of
thousands of postings) and takes several minutes. After that it runs nightly on
the schedule in `render.yaml`.

## 6. Try it

Open the web URL and sign in. **Email isn't wired up yet** (the digest and the
login link currently use a dev mailer that only logs), so to get your magic link:

- read it from the **backend service logs** (it prints `login link for … : …`), or
- temporarily set `JOBWATCH_DEV_AUTH=1` on the backend, which returns the link in
  the sign-in response. **Turn it back off after** — with it on, anyone can obtain
  anyone's login link.

## Before this is real

- **Turn on real email (Resend).** Without it, login links and digests only log.
  To send for real: create a [Resend](https://resend.com) account, make an API
  key, and set `RESEND_API_KEY` on both **jobwatch-backend** (login links) and
  **jobwatch-digest** (digests). Set `RESEND_FROM` to your sender, e.g.
  `jobwatch <alerts@yourdomain.com>`. Note: to email *anyone*, verify a domain in
  Resend; the default test sender (`onboarding@resend.dev`, used when `RESEND_FROM`
  is unset) only delivers to your own account email — fine for testing sign-in.
  Before sending at scale, add a one-click unsubscribe and a physical mailing
  address to the digest footer (CAN-SPAM); today the only opt-out is deleting the
  account.
- **Browser scrapers are skipped on the server** (`JOBWATCH_SKIP_BROWSER=1` on the
  ingest cron). Meta, Tesla, and Revolut need a headless browser and bot-block
  datacenter IPs, and a hung browser can't be interrupted mid-run — so they're
  left out rather than risked. To cover them, run the scrape behind a residential
  proxy and drop the flag.
- **Upgrade the free plans.** Free web services sleep after inactivity, and free
  Postgres is deleted after 30 days.
- **Session hardening** (httpOnly cookies) and a **privacy policy** before real
  users.
