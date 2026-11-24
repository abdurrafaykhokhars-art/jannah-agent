# Jannah Leveling Reel Agent

Free agent that runs on GitHub Actions, with no server and no payment:

| Schedule (Pakistan time) | Job | What it does |
|---|---|---|
| Sundays 11 PM | Find Ideas | Reads your idea pages through Instagram's official API |
| Every day 9 PM | Make Reels | Gemini writes the scripts; the free voice and renderer make the MP4s; each one is sent to your Telegram |
| Every 30 min | Sync Approvals | Reads your Approve / Decline taps |
| 7:30 AM, 1:30 PM, 9:30 PM | Publish | Posts the oldest approved reel to Instagram |

## Files you may edit (pencil icon on GitHub)

- `idea_pages.txt`: the pages you take ideas from
- `settings.json`: `reels_per_day`, `voice`, Gemini model, pillar rotation
- `brand/brand_jannah.md`: your brand rules (Gemini reads them for every reel)
- `renderer/themes.json`: colours · `renderer/pronunciations.json`: how Arabic words are spoken

## Secrets (Settings > Secrets and variables > Actions)

`GEMINI_API_KEY`, `META_TOKEN`, `IG_USER_ID`, `TELEGRAM_BOT_TOKEN`, `TELEGRAM_CHAT_ID`

The agent's memory lives in `data/` and the videos on the `videos` branch (last 14 days).
GitHub may start scheduled jobs 5 to 30 minutes late at busy times.
