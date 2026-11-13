// Grouping for the Results card's "By company" view. Pure functions so they
// can be unit-tested without a browser.

// Normalise a company name the same way job_hunt/dedupe.py's _norm_text does:
// strip accents, lower-case, "&" -> "and", punctuation to spaces, collapse
// spaces. "Acme Inc." and "acme  inc" group together; "Acme" and "Acme Inc"
// stay apart.
export function companyKey(name) {
  return String(name ?? '')
    .normalize('NFKD')
    .replace(/[^\x00-\x7f]/g, '')
    .toLowerCase()
    .replace(/&/g, ' and ')
    .replace(/[^a-z0-9]+/g, ' ')
    .trim()
    .replace(/\s+/g, ' ')
}

const scoreOf = (j) => (typeof j.score === 'number' ? j.score : -1)

// Group jobs by company. Each group: { key, name, jobs, count, best }.
// `name` is the first spelling seen; `jobs` are best score first; `best` is the
// highest score (null if none scored). sort: 'name' (A–Z, unnamed last) or
// 'score' (best first, then A–Z).
export function groupByCompany(jobs, sort = 'name') {
  const groups = new Map()
  for (const j of jobs || []) {
    const key = companyKey(j.company)
    let g = groups.get(key)
    if (!g) {
      g = { key, name: String(j.company ?? '').trim() || 'Unknown company', jobs: [] }
      groups.set(key, g)
    }
    g.jobs.push(j)
  }
  const out = [...groups.values()].map((g) => {
    // Array.prototype.sort is stable, so equal scores keep the API's order.
    const sorted = [...g.jobs].sort((a, b) => scoreOf(b) - scoreOf(a))
    const best = sorted.length && scoreOf(sorted[0]) >= 0 ? sorted[0].score : null
    return { ...g, jobs: sorted, count: sorted.length, best }
  })
  const byName = (a, b) => {
    if (!a.key !== !b.key) return a.key ? -1 : 1  // unnamed company last
    return a.key.localeCompare(b.key)
  }
  out.sort(sort === 'score'
    ? (a, b) => (b.best ?? -1) - (a.best ?? -1) || byName(a, b)
    : byName)
  return out
}
