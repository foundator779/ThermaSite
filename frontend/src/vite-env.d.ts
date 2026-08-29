/// <reference types="vite/client" />

interface ImportMetaEnv {
  readonly VITE_GOOGLE_MAPS_API_KEY?: string
}

interface Window {
  __THERMASITE_CONFIG__?: {
    apiBaseUrl?: string
    googleMapsApiKey?: string
  }
}
