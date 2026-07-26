#!/usr/bin/env python3
"""
ERA SNIPER - Discord Bot
Slash-command version of the username generator/checker.

Requires:
  pip install discord.py requests
  (optional, only for /check platform:bedrock)
  pip install xbox-webapi httpx

Setup:
  1. Go to https://discord.com/developers/applications, create a
     "New Application", then under "Bot" click "Add Bot" and copy the
     token (Reset Token if needed).
  2. Under "OAuth2 > URL Generator", check scopes "bot" and
     "applications.commands", give it permission "Send Messages", then
     open the generated URL to invite it to your server.
  3. Set the token as an environment variable (don't hardcode it):
       Windows (PowerShell):  $env:DISCORD_BOT_TOKEN="your_token_here"
       macOS/Linux:           export DISCORD_BOT_TOKEN="your_token_here"
  4. (Optional, for Bedrock/Xbox checking) run era_sniper_bedrock.py
     --setup once on this same machine so a tokens.json file exists next
     to this bot script — the bot reuses it. All Discord users who run
     /check platform:bedrock will be checking under that one Microsoft
     account. That's fine for read-only availability checks.
  5. Run:  python era_sniper_discord_bot.py

Commands:
  /generate length count charset exhaustive
  /check    length count charset platform

I could not test this bot live in my build environment (no network
access there, and no Discord bot token), so double-check the first run
and let me know if anything errors out.
"""

import asyncio
import io
import itertools
import os
import random
import string
import time
from pathlib import Path

import discord
from discord import app_commands
from discord.ext import commands

try:
    import requests
except ImportError:
    requests = None

# Optional Bedrock/Xbox support - only needed if you use platform:bedrock
try:
    from httpx import HTTPStatusError
    from xbox.webapi.api.client import XboxLiveClient
    from xbox.webapi.authentication.manager import AuthenticationManager
    from xbox.webapi.authentication.models import OAuth2TokenResponse
    from xbox.webapi.common.signed_session import SignedSession
    BEDROCK_AVAILABLE = True
except ImportError:
    BEDROCK_AVAILABLE = False

LETTERS = string.ascii_lowercase
ALNUM = string.ascii_lowercase + string.digits

TOKEN = os.environ.get("DISCORD_BOT_TOKEN")
XBOX_CLIENT_ID = os.environ.get("XBOX_CLIENT_ID")
XBOX_CLIENT_SECRET = os.environ.get("XBOX_CLIENT_SECRET")
TOKENS_FILE = Path("tokens.json")

CHECK_DELAY_SECONDS = 3          # ~10 names every 30 seconds, same pace as the CLI
PROGRESS_UPDATE_EVERY = 5        # edit the Discord message every N checks


# ---------------- Generation (never starts with a digit) ----------------

def gen_random(length, charset, count):
    seen = set()
    names = []
    guard = 0
    while len(names) < count and guard < count * 50:
        first = random.choice(LETTERS)
        rest = "".join(random.choice(charset) for _ in range(length - 1))
        n = first + rest
        if n not in seen:
            seen.add(n)
            names.append(n)
        guard += 1
    return names


def gen_exhaustive(length, charset):
    for first in LETTERS:
        for rest in itertools.product(charset, repeat=length - 1):
            yield first + "".join(rest)


# ---------------- Java (Mojang) checking ----------------

def check_name_java_sync(name, session):
    if requests is None:
        return "unknown"
    url = f"https://api.mojang.com/users/profiles/minecraft/{name}"
    try:
        r = session.get(url, timeout=5)
        if r.status_code in (204, 404):
            return "free"
        if r.status_code == 200:
            return "taken"
        return "unknown"
    except Exception:
        return "unknown"


async def check_name_java(name, session):
    # requests is blocking; run it off the event loop so the bot stays responsive
    return await asyncio.to_thread(check_name_java_sync, name, session)


# ---------------- Bedrock (Xbox Live) checking ----------------

_xbl_client = None
_xbl_session = None


async def get_xbl_client():
    global _xbl_client, _xbl_session
    if _xbl_client is not None:
        return _xbl_client
    if not BEDROCK_AVAILABLE:
        raise RuntimeError("xbox-webapi isn't installed on this bot host.")
    if not XBOX_CLIENT_ID or not XBOX_CLIENT_SECRET:
        raise RuntimeError("XBOX_CLIENT_ID / XBOX_CLIENT_SECRET env vars aren't set.")
    if not TOKENS_FILE.exists():
        raise RuntimeError(
            "No tokens.json found. Run era_sniper_bedrock.py --setup once on this host first."
        )
    session = SignedSession()
    auth_mgr = AuthenticationManager(session, XBOX_CLIENT_ID, XBOX_CLIENT_SECRET, "")
    auth_mgr.oauth = OAuth2TokenResponse.model_validate_json(TOKENS_FILE.read_text())
    await auth_mgr.refresh_tokens()
    TOKENS_FILE.write_text(auth_mgr.oauth.model_dump_json())
    auth_mgr.user_token = await auth_mgr.request_user_token()
    auth_mgr.xsts_token = await auth_mgr.request_xsts_token()
    _xbl_client = XboxLiveClient(auth_mgr)
    _xbl_session = session
    return _xbl_client


async def check_gamertag_bedrock(xbl_client, name):
    try:
        await xbl_client.account.claim_gamertag(xbl_client.xuid, name)
        return "free"
    except HTTPStatusError as e:
        code = e.response.status_code
        if code == 409:
            return "taken"
        if code == 429:
            return "rate_limited"
        if code == 401:
            return "auth_error"
        return "unknown"
    except Exception:
        return "unknown"


# ---------------- Discord bot ----------------

intents = discord.Intents.default()
bot = commands.Bot(command_prefix="!", intents=intents)


@bot.event
async def on_ready():
    await bot.tree.sync()
    print(f"Logged in as {bot.user} — slash commands synced.")


@bot.tree.command(name="generate", description="Generate a list of usernames (never starting with a digit)")
@app_commands.describe(
    length="Username length (default 4)",
    count="How many to generate (default 30, max 500)",
    charset="letters or letters+digits",
    exhaustive="Generate ALL combinations instead of random ones (careful, can be huge)",
)
@app_commands.choices(charset=[
    app_commands.Choice(name="letters only", value="letters"),
    app_commands.Choice(name="letters + digits", value="alnum"),
])
async def generate(
    interaction: discord.Interaction,
    length: int = 4,
    count: int = 30,
    charset: app_commands.Choice[str] = None,
    exhaustive: bool = False,
):
    await interaction.response.defer(thinking=True)
    cs = ALNUM if (charset and charset.value == "alnum") else LETTERS
    count = max(1, min(count, 500))

    if exhaustive:
        total = len(LETTERS) * (len(cs) ** (length - 1))
        if total > 50000:
            await interaction.followup.send(
                f"Refused: exhaustive generation would produce {total:,} combinations, "
                f"too many for Discord. Try a shorter length or disable exhaustive."
            )
            return
        names = list(gen_exhaustive(length, cs))
    else:
        names = gen_random(length, cs, count)

    text = "\n".join(names)
    if len(text) < 1900:
        await interaction.followup.send(f"Generated **{len(names)}** usernames:\n```\n{text}\n```")
    else:
        file = discord.File(io.BytesIO(text.encode()), filename="usernames.txt")
        await interaction.followup.send(f"Generated **{len(names)}** usernames:", file=file)


@bot.tree.command(name="check", description="Auto-generate and check usernames, shows only the available ones")
@app_commands.describe(
    length="Username length (default 4)",
    count="How many to test (default 20, max 100)",
    charset="letters or letters+digits",
    platform="java (Minecraft Java, default) or bedrock (Xbox Live)",
)
@app_commands.choices(
    charset=[
        app_commands.Choice(name="letters only", value="letters"),
        app_commands.Choice(name="letters + digits", value="alnum"),
    ],
    platform=[
        app_commands.Choice(name="Minecraft Java (Mojang API)", value="java"),
        app_commands.Choice(name="Xbox Live / Bedrock", value="bedrock"),
    ],
)
async def check(
    interaction: discord.Interaction,
    length: int = 4,
    count: int = 20,
    charset: app_commands.Choice[str] = None,
    platform: app_commands.Choice[str] = None,
):
    await interaction.response.defer(thinking=True)
    cs = ALNUM if (charset and charset.value == "alnum") else LETTERS
    plat = platform.value if platform else "java"
    count = max(1, min(count, 100))

    names = gen_random(length, cs, count)

    # ~10 checks per 30s -> this can take a while for large counts; warn the user
    est_seconds = len(names) * CHECK_DELAY_SECONDS
    progress_msg = await interaction.followup.send(
        f"Checking **{len(names)}** names on **{plat}**... "
        f"(~{est_seconds}s at this rate limit, {CHECK_DELAY_SECONDS}s between checks)"
    )

    available = []

    if plat == "bedrock":
        try:
            xbl_client = await get_xbl_client()
        except RuntimeError as e:
            await progress_msg.edit(content=f"Bedrock check unavailable: {e}")
            return

        for i, name in enumerate(names, 1):
            status = await check_gamertag_bedrock(xbl_client, name)
            if status == "rate_limited":
                await asyncio.sleep(5)
                status = await check_gamertag_bedrock(xbl_client, name)
            if status == "free":
                available.append(name)
            elif status == "auth_error":
                await progress_msg.edit(content="Xbox auth expired — the bot host needs to re-run --setup.")
                return
            if i % PROGRESS_UPDATE_EVERY == 0 or i == len(names):
                await progress_msg.edit(
                    content=f"Checking **{len(names)}** names on **{plat}**... {i}/{len(names)} "
                            f"({len(available)} free so far)"
                )
            await asyncio.sleep(CHECK_DELAY_SECONDS)
    else:
        if requests is None:
            await progress_msg.edit(content="The 'requests' module isn't installed on the bot host.")
            return
        session = requests.Session()
        for i, name in enumerate(names, 1):
            status = await check_name_java(name, session)
            if status == "free":
                available.append(name)
            if i % PROGRESS_UPDATE_EVERY == 0 or i == len(names):
                await progress_msg.edit(
                    content=f"Checking **{len(names)}** names on **{plat}**... {i}/{len(names)} "
                            f"({len(available)} free so far)"
                )
            await asyncio.sleep(CHECK_DELAY_SECONDS)

    if available:
        result_text = "\n".join(available)
        await progress_msg.edit(
            content=f"Done. **{len(available)}/{len(names)}** available:\n```\n{result_text}\n```"
        )
    else:
        await progress_msg.edit(content=f"Done. No available usernames found out of {len(names)}.")


if __name__ == "__main__":
    if not TOKEN:
        raise SystemExit(
            "Missing DISCORD_BOT_TOKEN environment variable. "
            "Set it before running this script (see the setup notes at the top of this file)."
        )
    bot.run(TOKEN)
