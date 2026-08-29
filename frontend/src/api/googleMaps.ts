let mapsPromise: Promise<void> | undefined

export function loadGoogleMaps(apiKey: string) {
  if (window.google?.maps) return Promise.resolve()
  if (mapsPromise) return mapsPromise
  mapsPromise = new Promise((resolve, reject) => {
    const callback = `terraforgeGoogleMapsReady${Date.now()}`
    const target = window as typeof window & Record<string, (() => void) | undefined>
    target[callback] = () => {
      delete target[callback]
      resolve()
    }
    const script = document.createElement('script')
    script.src = `https://maps.googleapis.com/maps/api/js?key=${encodeURIComponent(apiKey)}&libraries=geometry&v=weekly&loading=async&callback=${callback}`
    script.async = true
    script.onerror = () => reject(new Error('Google Maps JavaScript API could not be loaded'))
    document.head.appendChild(script)
  })
  return mapsPromise
}
