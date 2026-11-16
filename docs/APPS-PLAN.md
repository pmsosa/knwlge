# Desktop and phone apps

A plan for Knwlge as an app people download, for people who aren't technical: one person makes courses and
gives them to another, each with their own copy. Decided on 2026-11-15.

## What it is

- **Each person runs their own Knwlge**, inside the app, in personal mode: one person, no sign-in, their own
  database on their own computer. Nothing to host.
- **Courses travel as `.knwlge` files** (the packages from v0.3). Make a course, press **Download course package**,
  send the file by email or a USB stick; the other person opens it and it's imported. The app registers `.knwlge`
  so a double-click opens it.
- **AI is optional per copy.** With a key typed into the app (each person's own, or the course-maker's), everything
  works: making courses, the tutor, feedback on written answers. Without one, reading, quick questions, warm-ups,
  progress and printing still work, and the app says plainly what needs a key.

## How it's built

One codebase: the app is a thin shell around the existing server, not a rewrite.

- **Shell: Tauri (Rust).** A native window with the system's web view (WebKit on Mac, WebView2 on Windows), a
  menu, file associations, and the app's own icon. Small (a few MB) next to Electron.
- **Server: the same Python app**, shipped inside as a standalone Python (python-build-standalone) with its
  packages, started by the shell on `127.0.0.1` on a free port, stopped when the window closes.
  - Its dependencies are pure Python apart from `pydantic-core`, which has wheels for every desktop platform;
    `uvicorn` runs without its optional speed-ups.
  - Data goes in the system's per-user app folder (`~/Library/Containers/…` on Mac, `%APPDATA%\Knwlge` on Windows),
    never next to the program.
  - **Only the app may talk to it:** the shell makes a random token at each start and the server refuses requests
    without it, so other programs on the computer can't use the local server.
- **Desktop mode in the server** (a new `KNWLGE_MODE=desktop`, close to personal): no password screen, no team
  features, a first-run screen to paste a key (or skip), an "open a course file" button, and links that open in the
  real browser.
- **Updates:** the Mac App Store updates the Mac app. The Windows app checks a small update file on start and
  offers the new installer (Tauri's signed updater).

## Where each app comes from

| | How | What it needs |
|---|---|---|
| **Mac** (the course-maker) | Mac App Store | Apple Developer Program ($99/year, someone's Apple ID), an App Store Connect record, App Store review (a few days the first time). The app runs in Apple's sandbox, which allows a local server with the network entitlements |
| **Windows** (her mom) | A download link | A public place for the installer (see below). Unsigned, Windows shows "Windows protected your PC" once: **More info → Run anyway**. A code-signing certificate would remove that; the Microsoft Store (free for individuals) is the other way round it if the warning is a problem |
| **Android** (later) | Google Play or an APK link | First a test that the Python server runs on Android (Chaquopy). Play needs 12 testers opted in for 14 days for a new personal account; an APK link needs "install unknown apps" allowed once |

### The download link

The repo is private, so its releases can't be downloaded without a GitHub sign-in. Options: a separate public repo
that holds only the release files (no code), or a public link from somewhere else. To decide before the first
Windows release.

### Builds

Mac and Windows apps are built on GitHub's Mac and Windows machines (GitHub Actions), on each version tag:
`.github/workflows/apps.yml`. This needs the `skadi-git` token's **Workflows** permission (root). Apple's signing
certificate, provisioning profile and App Store Connect API key go in the repo's GitHub secrets, set by whoever owns
the Apple account; they're never in the repo or on skadi. A Linux build of the shell runs here in a container, for
development and the smoke test.

## Steps

1. **Desktop mode in the server** (here): the mode, the launch token, the first-run key screen, opening `.knwlge`
   files, external links, data folder handling. Tests.
2. **The Tauri shell** (here, Linux build in a container): start and stop the server, pick a port, pass the token,
   the window, file association, the bundled Python. The browser smoke test against it.
3. **Windows build and installer** (GitHub Actions): NSIS installer, the updater, the release upload.
4. **Mac build** (GitHub Actions): sandbox entitlements, signing, upload to App Store Connect; then App Store review.
5. **Android**: the Chaquopy test first, then its own plan.

## What only people can do

- **You (root):** give the `skadi-git` token the Workflows permission.
- **Whoever owns the Mac app:** join the Apple Developer Program, create the app in App Store Connect, and put the
  signing certificate and API key in the repo's secrets (step-by-step notes come with step 4).
- **Someone:** decide where the Windows download lives.
