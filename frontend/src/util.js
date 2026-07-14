// Ensure a link is an absolute URL. A stored URL without a scheme (e.g.
// "acme.co/jobs/1") would otherwise resolve relative to the app's own origin —
// opening the app again instead of the target, even with target="_blank".
// Prepend https:// when there's no protocol.
export function absUrl(u) {
  if (!u) return u
  return /^[a-z][a-z0-9+.-]*:\/\//i.test(u) ? u : `https://${u}`
}
