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
| jobwatch-backend | `JOBWATCH_API_URL` | the **backend** URL |
| jobwatch-backend | `JOBWATCH_ALLOWED_ORIGIN` | the **web** URL |
| jobwatch-backend | `JOBWATCH_LINK_SECRET` | a long random string |
| jobwatch-backend | `JOBWATCH_POSTAL_ADDRESS` | your mailing address |
| jobwatch-web | `VITE_API_BASE` | the **backend** URL |
| jobwatch-nightly | `ANTHROPIC_API_KEY` | your Anthropic key |
| jobwatch-nightly | `JOBWATCH_API_URL` | the **backend** URL |
| jobwatch-nightly | `JOBWATCH_APP_URL` | the **web** URL |
| jobwatch-nightly | `JOBWATCH_LINK_SECRET` | **the same** random string |
| jobwatch-nightly | `JOBWATCH_POSTAL_ADDRESS` | your mailing address |

Three of these are new and worth explaining:

- **`JOBWATCH_API_URL`** is this API's own public URL. Links inside an email
  cannot be relative, and the click redirector, the open pixel, and the
  unsubscribe endpoint all live on the backend, not the web app.
- **`JOBWATCH_LINK_SECRET`** signs those links. It **must be identical** on the
  backend and the nightly job: the cron mints the links, the backend verifies
  them, and a mismatch means every link in every email 400s. Generate one with
  `openssl rand -hex 32`. If it is unset, click tracking is disabled and emails
  carry plain links — deliberately, since an unsigned redirector would be an open
  redirect. Changing it later invalidates links in already-delivered email.
- **`JOBWATCH_POSTAL_ADDRESS`** is printed in every digest footer. CAN-SPAM
  requires a physical mailing address on commercial email; a PO box is fine.

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

Trigger the nightly job once by hand so the jobs table isn't empty: Render
dashboard → **jobwatch-nightly → Run now**. The first run seeds every company
(tens of thousands of postings) and takes several minutes; it then warms the feed
and sends any digests. After that it runs nightly on the schedule in `render.yaml`.

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
  **jobwatch-nightly** (digests). Set `RESEND_FROM` to your sender, e.g.
  `jobwatch <alerts@yourdomain.com>`. Note: to email *anyone*, verify a domain in
  Resend; the default test sender (`onboarding@resend.dev`, used when `RESEND_FROM`
  is unset) only delivers to your own account email — fine for testing sign-in.
  **Verify a domain in Resend before launch** — this has DNS lead time (SPF and
  DKIM records), and the default test sender (`onboarding@resend.dev`, used when
  `RESEND_FROM` is unset) only delivers to your own account email. Without domain
  authentication, digests land in spam.
- **Browser scrapers are skipped on the server** (`JOBWATCH_SKIP_BROWSER=1` on the
  ingest cron). Meta, Tesla, and Revolut need a headless browser and bot-block
  datacenter IPs, and a hung browser can't be interrupted mid-run — so they're
  left out rather than risked. To cover them, run the scrape behind a residential
  proxy and drop the flag.
- **Upgrade the free plans.** Free web services sleep after inactivity, and free
  Postgres is deleted after 30 days.
- **Session hardening** (httpOnly cookies) and a **privacy policy** before real
  users.

## Reading the launch gates

[`metrics.sql`](metrics.sql) holds the five queries the MVP exists to answer —
reach, activation, click-through, retention, and revenue — with the thresholds
written down. Run it against production:

```bash
psql "<external-connection-string>" -f metrics.sql
```

Nothing populates it until `JOBWATCH_LINK_SECRET` is set on both services, since
clicks are the metric every gate but the first is anchored on.
