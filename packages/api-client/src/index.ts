import createClient from 'openapi-fetch'
import type { components, paths } from './schema'

export type { components, paths }
type Schemas = components['schemas']
export type Me = Schemas['Me']
export type ImportJob = Schemas['ImportJobOut']
export type ImportRow = Schemas['ImportRowOut']
export type Candidate = Schemas['Candidate']
export type RatedTitle = Schemas['RatedTitle']
export type DivergentTitle = Schemas['DivergentTitle']
export type OutlierTitle = Schemas['OutlierTitle']
export type RatingsPage = Schemas['RatingsPage']
export type Persona = Schemas['PersonaOut']
export type ServerSettings = Schemas['ServerSettings']
export type TitleReaction = Schemas['TitleReaction']
export type Reaction = NonNullable<TitleReaction['reaction']>
export type TitleAvailability = Schemas['TitleAvailability']
export type StreamingProvider = Schemas['Provider']
export type PlatformCount = Schemas['PlatformCount']
export type FeedItem = Schemas['FeedItem']
export type FeedPage = Schemas['FeedPage']
export type AskAnswer = Schemas['AskAnswer']
export type TitleDetail = Schemas['TitleDetail']
export type FeedbackKind = Schemas['FeedbackUpdate']['kind']
export type DataExport = Schemas['DataExport']
export type RestoreSummary = Schemas['RestoreSummary']
export type TogetherOptions = Schemas['TogetherOptions']
export type GroupItem = Schemas['GroupItem']
export type Ballot = Schemas['Ballot']
export type BallotFilm = Schemas['BallotFilm']
export type VoteSessionOut = Schemas['VoteSessionOut']
export type InviteOut = Schemas['InviteOut']
export type Backups = Schemas['Backups']
export type GuestProfile = Schemas['GuestOut']
export type ChildProfile = Schemas['ChildOut']
export type RadarrShortlistStatus = Schemas['RadarrShortlistStatus']
export type RadarrShortlistSyncResponse = Schemas['RadarrShortlistSyncResponse']
export type DeclutterCandidateItem = Schemas['DeclutterCandidateItem']
export type DeclutterInspection = Schemas['DeclutterInspection']
export type DeclutterDeleteResponse = Schemas['DeclutterDeleteResponse']
export type RadarItem = Schemas['RadarItem']
export type MissingCandidatesResponse = Schemas['MissingCandidatesResponse']
export type TheatricalRadarResponse = Schemas['TheatricalRadarResponse']
export type RadarQueueResponse = Schemas['RadarQueueResponse']
export type InProgressItem = Schemas['InProgressItem']
export type RatingPromptItem = Schemas['RatingPromptItem']
export type FeedSort = NonNullable<NonNullable<paths['/api/v1/feed']['get']['parameters']['query']>['sort']>

/**
 * Typed client for the iWantToWatch REST API.
 * The web app uses the same origin; mobile apps pass their server URL.
 */
export function createApiClient(baseUrl = '') {
  return createClient<paths>({ baseUrl, credentials: 'include' })
}
