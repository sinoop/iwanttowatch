import createClient from 'openapi-fetch'
import type { components, paths } from './schema'

export type { components, paths }
type Schemas = components['schemas']
export type Me = Schemas['Me']
export type ImportJob = Schemas['ImportJobOut']
export type ImportRow = Schemas['ImportRowOut']
export type Candidate = Schemas['Candidate']
export type RatedTitle = Schemas['RatedTitle']
export type RatingsPage = Schemas['RatingsPage']

/**
 * Typed client for the iWantToWatch REST API.
 * The web app uses the same origin; mobile apps pass their server URL.
 */
export function createApiClient(baseUrl = '') {
  return createClient<paths>({ baseUrl, credentials: 'include' })
}
