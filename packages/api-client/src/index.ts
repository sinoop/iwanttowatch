import createClient from 'openapi-fetch'
import type { components, paths } from './schema'

export type { components, paths }
export type Me = components['schemas']['Me']

/**
 * Typed client for the CineMatch REST API.
 * The web app uses the same origin; mobile apps pass their server URL.
 */
export function createApiClient(baseUrl = '') {
  return createClient<paths>({ baseUrl, credentials: 'include' })
}
