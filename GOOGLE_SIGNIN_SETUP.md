# Sxarf AI — Google sign-in setup

Google sign-in is implemented in Electron's main process using the installed/desktop-app OAuth flow. The renderer never receives access or refresh tokens.

## 1. Create a Google OAuth client

1. Open the Google Cloud Console and select or create a project.
2. Configure the Google Auth Platform consent screen / branding and audience as required for your project.
3. Create an OAuth 2.0 Client ID with application type **Desktop app**.
4. Copy the Client ID. Do not create a Web application client for this desktop callback flow.

Google's desktop OAuth guidance supports a loopback IP callback for macOS desktop applications and recommends PKCE. See:
- https://developers.google.com/identity/protocols/oauth2/native-app
- https://developers.google.com/identity/protocols/oauth2/resources/loopback-migration

## 2. Start Sxarf AI with the Client ID

From the project directory, run:

```bash
export SXARF_GOOGLE_CLIENT_ID="YOUR_DESKTOP_CLIENT_ID.apps.googleusercontent.com"
npm start
```

The Client ID is a public identifier, not a client secret. This implementation does not ask you to place a Google client secret in `index.html`, `preload.js`, or the repository. Google desktop OAuth uses a temporary loopback redirect on `127.0.0.1` with a randomly assigned port and no callback path.

To keep the variable for future Terminal sessions, add the same `export SXARF_GOOGLE_CLIENT_ID="..."` line to your `~/.zshrc`, then open a new Terminal window.

## 3. Sign in

In Sxarf AI, open **Settings → Account → Continue with Google**. Electron opens the system browser, receives Google's redirect on a temporary `127.0.0.1` port, validates the OAuth state, exchanges the authorization code using PKCE, and requests the basic Google profile (`openid email profile`).

When Electron's OS-backed `safeStorage` is available, the session tokens are encrypted before being saved in the app's user-data folder. If secure storage is unavailable, the session remains memory-only and will not be written as plaintext.

## Subscription status

The plan screen currently displays Free, Pro, Max, and Unlimited, but checkout is intentionally disabled. The main process reports the Free plan only and refuses paid checkout until a real billing provider and server-verified entitlements are connected. Selecting a plan in the UI cannot grant paid access.
