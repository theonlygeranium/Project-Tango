# RB-04 — Account administration and credential recovery

Use this runbook for initial admin creation, regular-user provisioning, password
reset, and account deactivation. Never paste generated passwords into logs,
issues, shell history, Git, or shared documentation.

## Initial admin bootstrap

1. Confirm migration `004` has been applied and both Tango services are stopped
   or unavailable to public traffic during the first bootstrap.
2. Run the interactive bootstrap tool as `z121532` from the backend virtual
   environment.
3. Enter the admin's first name, last name, and email only at the prompt.
4. Copy the generated password directly to the owner. It is displayed once.
5. Start the backend and frontend, sign in, and store the password in the
   owner's password manager.

The bootstrap operation refuses to silently create a second admin. Do not put
an initial password in an environment variable or migration file.

## Provision a regular account

1. Sign in as the admin and open `/admin`.
2. Choose **New account** and enter first name, last name, and email.
3. Enable only the personas the user needs.
4. For each enabled persona, retain **Persona default** or choose an allowlisted
   model override.
5. Create the account and deliver the one-time generated password securely.

All dashboard-created users have the `regular` role.

## Reset a password

1. Open the account in the admin dashboard.
2. Choose **Reset password** and confirm the warning.
3. Deliver the newly generated password. Closing the result dialog removes it
   from dashboard state.
4. Confirm the previous password no longer signs in.

Reset revokes the user's web sessions and voice-room grants. Tango also asks
LiveKit to remove any connected participant immediately; the worker's periodic
account check stops the session if that best-effort removal does not complete.

## Deactivate or reactivate an account

Deactivation blocks new logins, revokes active web sessions and room grants,
and disconnects active voice participants. Reactivation does not change the
password or persona policy. The current admin cannot deactivate their own
account.

## Verification

- An anonymous request to a protected API receives `401`.
- A regular user receives `403` from admin routes and for an unassigned persona.
- The user sees only assigned personas in the Tango interface.
- A default policy resolves to the persona's source-controlled model.
- An override resolves only to an allowlisted LiteLLM alias.
- Another user's history and open-loop memories are not returned.

## Recovery

If the admin password is lost, run the documented bootstrap/reset CLI directly
on Schubert as `z121532`. Do not edit password hashes by hand. If the auth
lookup secret is lost or changed, every password lookup digest must be reset by
issuing new passwords; existing Argon2id hashes alone cannot identify an
account from the one-field login efficiently.
