/** Mirrors the backend rule: Indian mobile, optional +91 / 91 / 0 prefix, 10 digits starting 6-9. */
export function normalizeIndianMobile(raw: string): string | null {
  // Accept Devanagari digits too
  const ascii = raw.replace(/[०-९]/g, (d) => String("०१२३४५६७८९".indexOf(d)));
  let digits = ascii.replace(/[\s\-().]/g, "");
  if (/[^\d+]/.test(digits)) return null;
  if (digits.startsWith("+")) { if (!digits.startsWith("+91")) return null; digits = digits.slice(3); }
  else if (digits.length === 12 && digits.startsWith("91")) digits = digits.slice(2);
  else if (digits.length === 11 && digits.startsWith("0")) digits = digits.slice(1);
  return /^[6-9]\d{9}$/.test(digits) ? "+91" + digits : null;
}

export function validateName(raw: string): string | null {
  const n = raw.trim().replace(/\s+/g, " ");
  if (n.length < 2 || n.length > 80) return null;
  return /^[\p{L}\p{M}][\p{L}\p{M} .'’-]*$/u.test(n) ? n : null;
}
