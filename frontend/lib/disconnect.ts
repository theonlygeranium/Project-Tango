import { DisconnectReason } from 'livekit-client';

export const MAX_RECONNECT_ATTEMPTS = 3;

/**
 * Disconnect reasons that end the session instead of triggering an
 * auto-reconnect with a fresh token.
 *
 * `room.disconnect()` always reports CLIENT_INITIATED, so the hang-up button,
 * the session-view "agent never joined" timeout, and effect cleanup all end
 * the session. Server-side removals (an admin revoking the account removes the
 * participant) must not be undone by reconnecting.
 */
const TERMINAL_DISCONNECT_REASONS: ReadonlySet<DisconnectReason> = new Set([
  DisconnectReason.CLIENT_INITIATED,
  DisconnectReason.DUPLICATE_IDENTITY,
  DisconnectReason.PARTICIPANT_REMOVED,
  DisconnectReason.ROOM_DELETED,
  DisconnectReason.ROOM_CLOSED,
  DisconnectReason.USER_UNAVAILABLE,
  DisconnectReason.USER_REJECTED,
  DisconnectReason.SIP_TRUNK_FAILURE,
]);

/**
 * Whether an unexpected `RoomEvent.Disconnected` should trigger an
 * auto-reconnect. Network and server-side failures (SIGNAL_CLOSE,
 * CONNECTION_TIMEOUT, MEDIA_FAILURE, SERVER_SHUTDOWN, MIGRATION, ...) are
 * retried. An undefined reason is only emitted for auth failures inside
 * `connect()`, which the connect error path already handles, so it is not
 * retried here.
 */
export function shouldAutoReconnect(reason: DisconnectReason | undefined): boolean {
  if (reason === undefined) {
    return false;
  }
  return !TERMINAL_DISCONNECT_REASONS.has(reason);
}
