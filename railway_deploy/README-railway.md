# Deploying Era Sniper Discord bot to Railway

## What's in this folder
- `era_sniper_discord_bot.py` — the bot itself
- `requirements.txt` — dependencies Railway will install automatically
- `railway.toml` — tells Railway how to start the bot
- `Procfile` — fallback start command (same info, some setups look for this instead)
- `runtime.txt` — pins the Python version
- `.gitignore` — keeps tokens.json and local secrets out of git

## Steps

### 1. Get a Discord bot token (skip if you already have one)
1. Go to https://discord.com/developers/applications
2. "New Application" -> name it -> "Bot" tab -> "Add Bot" -> "Reset Token" -> copy it (keep it secret)
3. "OAuth2 -> URL Generator": check `bot` and `applications.commands` scopes,
   permission `Send Messages`, open the generated URL to invite it to your server

### 2. Put this folder in a GitHub repo
Railway deploys from a git repo. Create a new repo (private is fine) and
push this folder's contents to it. Example:
```
git init
git add .
git commit -m "Era Sniper Discord bot"
git branch -M main
git remote add origin https://github.com/YOUR_USERNAME/era-sniper-bot.git
git push -u origin main
```
(`tokens.json`, if it ever gets created locally, is already excluded by `.gitignore` — never commit your token or tokens.json.)

### 3. Create the Railway project
1. Go to https://railway.app -> "New Project" -> "Deploy from GitHub repo"
2. Pick the repo you just pushed
3. Railway will detect Python via `requirements.txt` and auto-build using Nixpacks

### 4. Set environment variables
In the Railway project -> "Variables" tab, add:
- `DISCORD_BOT_TOKEN` = your bot token from step 1
- (optional, only if you want `/check platform:bedrock` to work)
  `XBOX_CLIENT_ID` and `XBOX_CLIENT_SECRET` = your Azure app credentials

### 5. Deploy
Railway deploys automatically after you push / set variables. Check the
"Deployments" tab logs for `Logged in as ... — slash commands synced.`
— that confirms the bot is online.

### 6. About the Bedrock/Xbox tokens.json
Xbox Live auth needs a one-time interactive login (opening a link,
logging in with your Microsoft account, pasting back a code) — that
can't happen inside Railway's build process. If you want `/check
platform:bedrock` to work:
1. Run `era_sniper_bedrock.py --setup --client-id ... --client-secret ...`
   once on your own computer to generate a `tokens.json` file.
2. Upload that `tokens.json` into the Railway service's filesystem —
   easiest way is Railway's "Volumes" feature, or committing it to a
   *private* repo (not ideal since it's a live credential — a volume is
   safer).
Without this, `/check` still works fine for `platform:java` (Minecraft
Java / Mojang API), no extra setup needed.

## Cost note
Railway's free tier includes limited monthly usage hours/credits — a
lightweight Discord bot like this one typically fits comfortably within
that, but check Railway's current pricing page since limits change.
