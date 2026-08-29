const runtimeConfig = window.__THERMASITE_CONFIG__

export const runtimeApiBaseUrl = runtimeConfig?.apiBaseUrl?.trim() || ''
