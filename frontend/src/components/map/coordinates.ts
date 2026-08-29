export type MapCoordinate = { lat: number; lng: number }

function parseCoordinate(value: string, axis: 'latitude' | 'longitude') {
  const match = value.trim().toUpperCase().match(/^([+-]?\d+(?:\.\d+)?)\s*°?\s*([NSEW])?$/)
  if (!match) return undefined
  const cardinal = match[2]
  if (cardinal && axis === 'latitude' && !['N', 'S'].includes(cardinal)) return undefined
  if (cardinal && axis === 'longitude' && !['E', 'W'].includes(cardinal)) return undefined
  const magnitude = Math.abs(Number(match[1]))
  const sign = cardinal
    ? ['S', 'W'].includes(cardinal) ? -1 : 1
    : Number(match[1]) < 0 ? -1 : 1
  return magnitude * sign
}

export function parseMapCoordinates(latitude: string, longitude: string): {
  coordinate?: MapCoordinate
  error?: string
} {
  if (!latitude.trim() || !longitude.trim()) {
    return { error: 'Enter both latitude and longitude.' }
  }
  const lat = parseCoordinate(latitude, 'latitude')
  const lng = parseCoordinate(longitude, 'longitude')
  if (lat === undefined || lng === undefined) {
    return { error: 'Use decimal coordinates, for example 36.3889 and -89.3889.' }
  }
  if (lat < -90 || lat > 90) return { error: 'Latitude must be between -90 and 90.' }
  if (lng < -180 || lng > 180) return { error: 'Longitude must be between -180 and 180.' }
  return { coordinate: { lat, lng } }
}
