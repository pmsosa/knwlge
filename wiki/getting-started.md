# Getting started

[Guide home](README.md) · Previous: [How to use Knwlge](how-to-use.md) · Next: [Making a course](making-a-course.md)

## Personal or team

Knwlge runs in one of two modes, chosen when it's installed (`KNWLGE_MODE` in `.env`):

| | Personal | Team |
|---|---|---|
| Who | just you, with every permission | accounts made by an admin: learners, authors and admins |
| Signing in | none; it simply opens. You can set a password in **Settings** if you want one | everyone signs in with a username and password |
| Courses | yours | drafts until their author publishes them; everyone's progress is their own |
| Extra pages | | **people** and **audit**, for admins |

## Signing in (team mode)

Open the address you were given and sign in with the username and password an admin gave you. The first time (or
after an admin resets your password) Knwlge asks you to choose your own: at least 10 characters, and not your
username. Too many wrong tries in a row and it makes you wait a little before the next one.

<img src="images/signin.png" alt="The sign-in card" width="70%">

**sign out** is in the top bar, next to your name and role.

### Your name

Click your name in the top bar to change the name others see (on courses you write, in the people list and the audit
log). The username you sign in with stays the same. The same page has **change password**.

## Finding your way around

<img src="images/courses.png" alt="The courses page: a continue banner and course cards with depth and progress" width="100%">

- **courses** (the home page): a **continue** banner for where you left off, then a card per course with its depth,
  progress, and how many questions are waiting to be revisited.
- **new course**: make one (authors and admins).
- **people**, **usage**, **audit**, **settings**: for admins (in personal mode you're the admin, and people and audit
  don't appear).

What you can't use isn't shown. Inside a course the outline stays on the left and only the content on the right
scrolls, so the page itself never moves.

## Light and dark

The button at the right end of the top bar switches between **auto** (follows your device), light and dark. The
same choice is under **Settings → Appearance**. Diagrams and plots keep a light background in both.

<img src="images/dark.png" alt="A lesson in the dark theme" width="100%">

## On a phone

Knwlge works in a phone browser. The top bar keeps just the logo, the theme button and a **menu** button; the
links, your name and **sign out** open from the menu (it does the same in narrow windows on a desk). The outline moves
above the content, paragraphs stop being justified (narrow columns leave gaps), and the tutor's chat fills the screen.
On a touch screen, long-press works as usual (to select text); editors get a **⋯** button on each section's heading
instead of the right-click menu.

<p><img src="images/phone.png" alt="A lesson on a phone" width="32%"> <img src="images/phone-learner-home.png" alt="A learner's courses page on a phone with the menu open" width="32%"></p>

## Installing it as an app

Over HTTPS (or on `localhost`), browsers offer to install Knwlge: **Install app** in Chrome or Edge's address bar,
**Add to Home Screen** on a phone. It then opens in its own window with the green K as its icon. Knwlge keeps its own
files (the page, styles, scripts, fonts and icons) on the device so it opens quickly; your courses and answers always
come from the server, so you need a connection to study.

## Adding the AI key

Knwlge uses Google's Gemini to plan, write, mark and answer. An admin (you, in personal mode) opens **Settings**,
pastes a key from [Google AI Studio](https://aistudio.google.com/apikey) under **Gemini API key** and presses
**save key**, then **test it**. The key stays on the server: it's never sent to a browser and never shown again
(only its last few characters). Live research and the reading list need a paid-tier key; free keys still work,
and those steps say they ran without search.

More: [Administration](administration.md).
