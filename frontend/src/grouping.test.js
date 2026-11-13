import { describe, expect, it } from 'vitest'
import { companyKey, groupByCompany } from './grouping.js'

const job = (company, score, title = 'Engineer') => ({ company, score, title, url: `${company}/${title}/${score}` })

describe('companyKey', () => {
  it('ignores case, spacing, punctuation and accents', () => {
    expect(companyKey('Acme Inc.')).toBe('acme inc')
    expect(companyKey('  acme   INC ')).toBe('acme inc')
    expect(companyKey('Café Group')).toBe(companyKey('cafe group'))
    expect(companyKey('Smith & Co')).toBe('smith and co')
  })

  it('keeps legal suffixes so different names stay apart', () => {
    expect(companyKey('Acme')).not.toBe(companyKey('Acme Inc'))
  })

  it('treats missing names as empty', () => {
    expect(companyKey(undefined)).toBe('')
    expect(companyKey(null)).toBe('')
  })
})

describe('groupByCompany', () => {
  it('shows each company once with its roles, best score first', () => {
    const groups = groupByCompany([job('Acme', 60, 'A'), job('Globex', 90), job('Acme', 85, 'B'), job('Acme', 70, 'C')])
    expect(groups.map((g) => g.name)).toEqual(['Acme', 'Globex'])
    expect(groups[0].count).toBe(3)
    expect(groups[0].best).toBe(85)
    expect(groups[0].jobs.map((j) => j.title)).toEqual(['B', 'C', 'A'])
    expect(groups[1].count).toBe(1)
  })

  it('groups spelling variants under the first spelling seen', () => {
    const groups = groupByCompany([job('Acme Inc.', 50), job('acme inc', 40)])
    expect(groups).toHaveLength(1)
    expect(groups[0].name).toBe('Acme Inc.')
    expect(groups[0].count).toBe(2)
  })

  it('sorts companies A–Z by default', () => {
    const names = groupByCompany([job('zeta', 99), job('Beta', 10), job('alpha', 50)]).map((g) => g.name)
    expect(names).toEqual(['alpha', 'Beta', 'zeta'])
  })

  it('sorts companies by best score on request, ties A–Z', () => {
    const names = groupByCompany([job('Acme', 75), job('Globex', 90), job('Beta', 75)], 'score').map((g) => g.name)
    expect(names).toEqual(['Globex', 'Acme', 'Beta'])
  })

  it('puts roles with no company last, under one heading', () => {
    const groups = groupByCompany([job('', 99), job(undefined, 10), job('Acme', 1)])
    expect(groups.map((g) => g.name)).toEqual(['Acme', 'Unknown company'])
    expect(groups[1].count).toBe(2)
  })

  it('handles unscored roles', () => {
    const groups = groupByCompany([job('Acme', null, 'X'), job('Acme', 40, 'Y'), job('Beta', undefined)], 'score')
    expect(groups[0].name).toBe('Acme')
    expect(groups[0].jobs.map((j) => j.title)).toEqual(['Y', 'X'])
    expect(groups[1].best).toBeNull()
  })

  it('returns nothing for no results', () => {
    expect(groupByCompany([])).toEqual([])
    expect(groupByCompany(undefined)).toEqual([])
  })
})
