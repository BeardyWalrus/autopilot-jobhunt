// Ensure a link is an absolute URL. A stored URL without a scheme (e.g.
// "acme.co/jobs/1") would otherwise resolve relative to the app's own origin —
// opening the app again instead of the target, even with target="_blank".
// Prepend https:// when there's no protocol.
export function absUrl(u) {
  if (!u) return u
  return /^[a-z][a-z0-9+.-]*:\/\//i.test(u) ? u : `https://${u}`
}

// A role's pay as the listing gives it ("£45,000 - £55,000 per annum"), or
// "Not given" when the listing has no figure. Never estimated. See ADR 0005.
export const PAY_NOT_GIVEN = 'Not given'
export function payLabel(job) {
  const pay = typeof job?.pay === 'string' ? job.pay.trim() : ''
  return pay && pay !== PAY_NOT_GIVEN ? pay : PAY_NOT_GIVEN
}
