import { describe, expect, it } from 'vitest'
import { parseMapCoordinates } from './coordinates'

describe('map coordinate input', () => {
  it('parses the Reelfoot Lake decimal coordinates', () => {
    expect(parseMapCoordinates('36.3889', '-89.3889')).toEqual({
      coordinate: { lat: 36.3889, lng: -89.3889 },
    })
  })

  it('accepts degree symbols and cardinal directions', () => {
    expect(parseMapCoordinates('36.3889° N', '89.3889° W')).toEqual({
      coordinate: { lat: 36.3889, lng: -89.3889 },
    })
  })

  it('rejects missing, malformed, and out-of-range coordinates', () => {
    expect(parseMapCoordinates('', '-89')).toHaveProperty('error')
    expect(parseMapCoordinates('north', '-89')).toHaveProperty('error')
    expect(parseMapCoordinates('91', '-89')).toEqual({ error: 'Latitude must be between -90 and 90.' })
    expect(parseMapCoordinates('36', '-181')).toEqual({ error: 'Longitude must be between -180 and 180.' })
  })
})
