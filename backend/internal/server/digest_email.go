package server

import (
	"fmt"
	"strconv"
	"strings"
)

// The digest's HTML is hand-built tables with inline styles, which looks archaic
// and is correct: Outlook renders through Word's HTML engine, which supports
// neither flexbox nor grid, and Gmail strips <style> blocks in some contexts. A
// table with inline attributes is the one layout every client agrees on.
//
// Everything here degrades: images are blocked by default in most clients, so no
// logo carries meaning on its own and every row reads correctly without them.

// Kept in step with the light palette in frontend/src/styles.css. Email cannot
// read CSS variables, and a digest in last season's brand colour is the kind of
// drift nobody notices until it is in an inbox.
const (
	emailInk      = "#16161a"
	emailMuted    = "#6b7280"
	emailLine     = "#e7e5e2"
	emailAccent   = "#1f5e46"
	emailBg       = "#fbfaf9"
	emailCard     = "#ffffff"
	emailMaxWidth = 600
)

// digestSubject names companies rather than counting matches. "20 new roles —
// Microsoft, Stripe, Anthropic +6" gives a reason to open; "20 new matches at
// your companies" does not.
func digestSubject(c DigestContent) string {
	roles := plural(c.Total, "new role")
	if len(c.CompanyList) == 0 {
		return roles
	}
	names := strings.Join(c.CompanyList, ", ")
	if rest := len(c.Companies) - len(c.CompanyList); rest > 0 {
		names += " +" + strconv.Itoa(rest)
	}
	return roles + " — " + names
}

// digestPreheader is the grey line clients show after the subject in the inbox
// list. Left unset, they scrape whatever text comes first — usually markup or a
// greeting — so it is worth spending deliberately.
func digestPreheader(c DigestContent) string {
	if len(c.Companies) == 0 {
		return ""
	}
	first := c.Companies[0]
	if len(first.Jobs) == 0 {
		return ""
	}
	return fmt.Sprintf("%s at %s, posted %s — plus %s more.",
		first.Jobs[0].Title, first.Company, first.Jobs[0].Age,
		strconv.Itoa(max(c.Total-1, 0)))
}

func digestHTML(c DigestContent) string {
	var b strings.Builder

	b.WriteString(`<!doctype html><html><head><meta charset="utf-8">`)
	b.WriteString(`<meta name="viewport" content="width=device-width,initial-scale=1">`)
	b.WriteString(`<meta name="color-scheme" content="light">`)
	b.WriteString(`</head><body style="margin:0;padding:0;background:` + emailBg + `;">`)

	// Hidden preheader: shown in the inbox list, never in the opened message.
	if pre := digestPreheader(c); pre != "" {
		b.WriteString(`<div style="display:none;max-height:0;overflow:hidden;opacity:0;">` +
			htmlAttr(pre) + `</div>`)
	}

	b.WriteString(`<table role="presentation" width="100%" cellpadding="0" cellspacing="0" border="0" ` +
		`style="background:` + emailBg + `;padding:24px 12px;"><tr><td align="center">`)
	b.WriteString(`<table role="presentation" width="` + strconv.Itoa(emailMaxWidth) + `" cellpadding="0" cellspacing="0" border="0" ` +
		`style="max-width:` + strconv.Itoa(emailMaxWidth) + `px;width:100%;background:` + emailCard +
		`;border-radius:12px;border:1px solid ` + emailLine + `;font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',Roboto,Helvetica,Arial,sans-serif;">`)

	// Header.
	b.WriteString(`<tr><td style="padding:24px 24px 8px 24px;">`)
	b.WriteString(`<div style="font-size:20px;font-weight:700;color:` + emailInk + `;letter-spacing:-0.02em;">` +
		`job<span style="color:` + emailAccent + `;">watch</span></div>`)
	b.WriteString(`<div style="font-size:15px;color:` + emailInk + `;padding-top:12px;font-weight:600;">` +
		htmlAttr(plural(c.Total, "new role")) + ` since your last digest</div>`)
	b.WriteString(`<div style="font-size:13px;color:` + emailMuted + `;padding-top:2px;">` +
		`Straight from the company career pages, newest first.</div>`)
	b.WriteString(`</td></tr>`)

	for _, company := range c.Companies {
		b.WriteString(`<tr><td style="padding:20px 24px 0 24px;">`)

		// Company heading: logo and name in one row, so a blocked image leaves
		// the name sitting where it should be rather than an empty gap.
		b.WriteString(`<table role="presentation" cellpadding="0" cellspacing="0" border="0"><tr>`)
		if company.LogoURL != "" {
			b.WriteString(`<td style="padding-right:8px;" valign="middle">` +
				`<img src="` + htmlAttr(company.LogoURL) + `" width="20" height="20" alt="" ` +
				`style="display:block;width:20px;height:20px;border-radius:4px;border:0;"></td>`)
		}
		b.WriteString(`<td valign="middle" style="font-size:13px;font-weight:700;color:` + emailInk +
			`;text-transform:uppercase;letter-spacing:0.04em;">` + htmlAttr(company.Company) + `</td>`)
		b.WriteString(`</tr></table>`)
		b.WriteString(`</td></tr>`)

		for _, j := range company.Jobs {
			b.WriteString(`<tr><td style="padding:10px 24px 0 24px;">`)
			b.WriteString(`<table role="presentation" width="100%" cellpadding="0" cellspacing="0" border="0" ` +
				`style="border-top:1px solid ` + emailLine + `;"><tr><td style="padding-top:10px;">`)

			b.WriteString(`<a href="` + htmlAttr(j.LinkURL) + `" ` +
				`style="font-size:15px;font-weight:600;color:` + emailAccent + `;text-decoration:none;">` +
				htmlAttr(j.Title) + `</a>`)

			// Freshness leads the meta line: it is the entire product claim.
			meta := j.Age
			if j.Location != nil && *j.Location != "" {
				meta += " · " + *j.Location
			}
			b.WriteString(`<div style="font-size:13px;color:` + emailMuted + `;padding-top:3px;">` +
				htmlAttr(meta) + `</div>`)

			b.WriteString(`</td></tr></table></td></tr>`)
		}
	}

	if c.Overflow > 0 {
		b.WriteString(`<tr><td style="padding:16px 24px 0 24px;font-size:13px;color:` + emailMuted + `;">` +
			`and ` + strconv.Itoa(c.Overflow) + ` more — ` +
			`<a href="` + htmlAttr(c.AppURL) + `" style="color:` + emailAccent + `;">see them all</a>.</td></tr>`)
	}

	// Footer: CAN-SPAM wants a working opt-out and a physical address on every
	// commercial message, and deliverability wants the opt-out to be obvious
	// rather than hidden — someone who cannot find it reports the message as
	// spam instead, which costs the sending domain far more than the subscriber.
	b.WriteString(`<tr><td style="padding:24px;">`)
	b.WriteString(`<table role="presentation" width="100%" cellpadding="0" cellspacing="0" border="0" ` +
		`style="border-top:1px solid ` + emailLine + `;"><tr><td style="padding-top:16px;font-size:12px;color:` +
		emailMuted + `;line-height:1.6;">`)
	b.WriteString(`You're getting this because you confirmed a jobwatch subscription. `)
	b.WriteString(`<a href="` + htmlAttr(c.PrefsURL) + `" style="color:` + emailMuted + `;">Change what you get</a> · `)
	b.WriteString(`<a href="` + htmlAttr(c.UnsubURL) + `" style="color:` + emailMuted + `;">Unsubscribe</a>`)
	if c.PostalAddr != "" {
		b.WriteString(`<br>` + htmlAttr(c.PostalAddr))
	}
	b.WriteString(`</td></tr></table></td></tr>`)

	b.WriteString(`</table></td></tr></table>`)

	if c.PixelURL != "" {
		b.WriteString(`<img src="` + htmlAttr(c.PixelURL) + `" width="1" height="1" alt="" style="display:block;border:0;">`)
	}
	b.WriteString(`</body></html>`)
	return b.String()
}

// digestText is the plain-text alternative. It is not a formality: a message
// with no text part scores worse with spam filters, and some readers genuinely
// prefer it.
func digestText(c DigestContent) string {
	var b strings.Builder
	fmt.Fprintf(&b, "%s since your last digest\n", plural(c.Total, "new role"))
	b.WriteString("Straight from the company career pages, newest first.\n")

	for _, company := range c.Companies {
		fmt.Fprintf(&b, "\n%s\n", strings.ToUpper(company.Company))
		for _, j := range company.Jobs {
			loc := ""
			if j.Location != nil && *j.Location != "" {
				loc = " · " + *j.Location
			}
			fmt.Fprintf(&b, "  %s\n  %s%s\n  %s\n\n", j.Title, j.Age, loc, j.LinkURL)
		}
	}
	if c.Overflow > 0 {
		fmt.Fprintf(&b, "\nand %d more: %s\n", c.Overflow, c.AppURL)
	}
	fmt.Fprintf(&b, "\n---\nYou're getting this because you confirmed a jobwatch subscription.\n")
	fmt.Fprintf(&b, "Change what you get: %s\nUnsubscribe: %s\n", c.PrefsURL, c.UnsubURL)
	if c.PostalAddr != "" {
		fmt.Fprintf(&b, "%s\n", c.PostalAddr)
	}
	return b.String()
}
