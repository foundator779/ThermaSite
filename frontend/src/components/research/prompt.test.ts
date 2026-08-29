import { describe, expect, it } from 'vitest'
import { CANONICAL_PROMPT } from './ResearchLauncher'

describe('canonical research launcher', () => {
  it('preserves the scientific scope and non-trivial multi-source intent', () => {
    expect(CANONICAL_PROMPT).toContain('this habitat')
    expect(CANONICAL_PROMPT).toContain('species and biodiversity')
    expect(CANONICAL_PROMPT).toContain('wildfire exposure')
  })
})
