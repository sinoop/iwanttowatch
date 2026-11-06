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
export type Persona = Schemas['PersonaOut']
export type ServerSettings = Schemas['ServerSettings']
export type TitleReaction = Schemas['TitleReaction']
export type Reaction = NonNullable<TitleReaction['reaction']>
export type TitleAvailability = Schemas['TitleAvailability']
export type StreamingProvider = Schemas['Provider']
export type FeedItem = Schemas['FeedItem']
export type FeedPage = Schemas['FeedPage']
export type TitleDetail = Schemas['TitleDetail']
export type FeedbackKind = Schemas['FeedbackUpdate']['kind']
export type DataExport = Schemas['DataExport']
export type RestoreSummary = Schemas['RestoreSummary']
export type TogetherOptions = Schemas['TogetherOptions']
export type GroupItem = Schemas['GroupItem']
export type GuestProfile = Schemas['GuestOut']

/**
 * Typed client for the iWantToWatch REST API.
 * The web app uses the same origin; mobile apps pass their server URL.
 */
export function createApiClient(baseUrl = '') {
  return createClient<paths>({ baseUrl, credentials: 'include' })
}
