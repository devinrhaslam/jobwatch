import { useState } from "react";

// The company logo, falling back to a coloured monogram when no icon loads.
//
// The URL is resolved by the API (see backend/internal/server/logo.go) rather
// than guessed here, so the web app and the digest email always show the same
// icon and the domain overrides live in one place. The previous version built
// Clearbit URLs in this file; when that service was withdrawn every icon
// silently became a monogram, which is precisely the failure this fallback is
// designed to survive — and precisely why the source is now configurable.
function colorFor(company: string): string {
  let hash = 0;
  for (let i = 0; i < company.length; i++) {
    hash = (Math.imul(hash, 31) + company.charCodeAt(i)) | 0;
  }
  return `hsl(${Math.abs(hash) % 360}, 45%, 45%)`;
}

export default function CompanyIcon({
  company,
  src,
}: {
  company: string;
  src?: string;
}) {
  const [failed, setFailed] = useState(false);

  if (!src || failed) {
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
      src={src}
      alt=""
      loading="lazy"
      onError={() => setFailed(true)}
    />
  );
}
