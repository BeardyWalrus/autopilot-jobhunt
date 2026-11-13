import { describe, expect, it } from 'vitest'
import { absUrl, payLabel, PAY_NOT_GIVEN } from './util.js'

describe('payLabel', () => {
  it('shows the pay as the listing gives it', () => {
    expect(payLabel({ pay: '£45,000 - £55,000 per annum' })).toBe('£45,000 - £55,000 per annum')
    expect(payLabel({ pay: '  $500/day ' })).toBe('$500/day')
  })
  it('says "Not given" when there is no figure', () => {
    expect(payLabel({})).toBe(PAY_NOT_GIVEN)
    expect(payLabel({ pay: '' })).toBe(PAY_NOT_GIVEN)
    expect(payLabel({ pay: null })).toBe(PAY_NOT_GIVEN)
    expect(payLabel(undefined)).toBe(PAY_NOT_GIVEN)
  })
})

describe('absUrl', () => {
  it('adds https:// only when there is no scheme', () => {
    expect(absUrl('acme.co/jobs/1')).toBe('https://acme.co/jobs/1')
    expect(absUrl('http://acme.co')).toBe('http://acme.co')
  })
})
