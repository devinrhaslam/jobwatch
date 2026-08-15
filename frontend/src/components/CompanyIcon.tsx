import { useState } from "react";

// Company names where "lowercase, strip non-alphanumeric, + .com" guesses the
// wrong domain. Everything else uses the guess, then falls back to a monogram if
// no logo loads — so a miss is a tidy initial, never a broken image.
const DOMAIN_OVERRIDES: Record<string, string> = {
  "Google DeepMind": "deepmind.com",
  "Hims & Hers": "hims.com",
  "monday.com": "monday.com",
  "Character.AI": "character.ai",
  "Checkout.com": "checkout.com",
  "1X Technologies": "1x.tech",
  X: "x.com",
  "Two Sigma": "twosigma.com",
  "Match Group": "mtch.com",
  "Rocket Lab": "rocketlabusa.com",
  "Electronic Arts": "ea.com",
  "Take-Two Interactive": "take2games.com",
  "Sony Interactive Entertainment": "sony.com",
  "Walmart Global Tech": "walmart.com",
  "Hudson River Trading": "hudsonrivertrading.com",
};

function domainFor(company: string): string {
  return (
    DOMAIN_OVERRIDES[company] ??
    company.toLowerCase().replace(/[^a-z0-9]/g, "") + ".com"
  );
}

function colorFor(company: string): string {
  let hash = 0;
  for (let i = 0; i < company.length; i++) {
    hash = (Math.imul(hash, 31) + company.charCodeAt(i)) | 0;
  }
  return `hsl(${Math.abs(hash) % 360}, 45%, 45%)`;
}

export default function CompanyIcon({ company }: { company: string }) {
  const [failed, setFailed] = useState(false);

  if (failed) {
    return (
      <span
        className="company-icon monogram"
        style={{ background: colorFor(company) }}
        aria-hidden="true"
      >
        {company.charAt(0).toUpperCase()}
      </span>
    );
  }

  return (
    <img
      className="company-icon"
      src={`https://logo.clearbit.com/${domainFor(company)}`}
      alt=""
      loading="lazy"
      onError={() => setFailed(true)}
    />
  );
}
