import discord
from discord.ext import commands, tasks
from discord import app_commands
import os
import itertools
import string
import aiohttp
import asyncio

# Initialize bot
intents = discord.Intents.default()
intents.message_content = True
bot = commands.Bot(command_prefix="!", intents=intents)

# Global state
checking_active = False
checking_mode = None
checking_count = 0
checked_count = 0
found_names = []

# Webhook URL (set via environment variable)
WEBHOOK_URL = os.getenv("WEBHOOK_URL", "")

class ModeSelect(discord.ui.Select):
    """Dropdown to select checking mode (3c, 3l, 4c, 4l)"""
    def __init__(self):
        options = [
            discord.SelectOption(label="3c (3 chars: letters + numbers)", value="3c"),
            discord.SelectOption(label="3l (3 letters only)", value="3l"),
            discord.SelectOption(label="4c (4 chars: letters + numbers)", value="4c"),
            discord.SelectOption(label="4l (4 letters only)", value="4l"),
        ]
        super().__init__(placeholder="Select a mode...", options=options)
    
    async def callback(self, interaction: discord.Interaction):
        mode = self.values[0]
        # Show modal to get username count
        await interaction.response.send_modal(CountModal(mode, self.view.platform))

class ModeView(discord.ui.View):
    def __init__(self, platform: str):
        super().__init__()
        self.platform = platform
        self.add_item(ModeSelect())

class CountModal(discord.ui.Modal, title="Username Count"):
    """Modal to input how many usernames to test"""
    count_input = discord.ui.TextInput(
        label="How many usernames to test?",
        placeholder="Enter a number (e.g., 100)",
        required=True,
        min_length=1,
        max_length=10
    )
    
    def __init__(self, mode: str, platform: str):
        super().__init__()
        self.mode = mode
        self.platform = platform
    
    async def on_submit(self, interaction: discord.Interaction):
        global checking_active, checking_mode, checking_count, checked_count, found_names
        
        try:
            count = int(self.count_input.value)
            if count <= 0:
                await interaction.response.send_message("❌ Please enter a positive number!", ephemeral=True)
                return
        except ValueError:
            await interaction.response.send_message("❌ Please enter a valid number!", ephemeral=True)
            return
        
        checking_active = True
        checking_mode = (self.mode, self.platform)
        checking_count = count
        checked_count = 0
        found_names = []
        
        await interaction.response.send_message(
            f"✅ Started checking **{count}** usernames on **{self.platform.upper()}** (Mode: **{self.mode}**)\nUse `/stop` to cancel.",
            ephemeral=True
        )
        
        # Start the checking task
        bot.loop.create_task(check_usernames(self.mode, self.platform, count))

async def generate_usernames(mode: str, count: int):
    """Generate usernames based on mode"""
    if mode == "3c":
        # 3 characters: letters + numbers, no leading numbers for Xbox
        chars = string.ascii_lowercase + string.digits
        names = set()
        for combo in itertools.combinations_with_replacement(chars, 3):
            names.add(''.join(combo))
        return list(names)[:count]
    
    elif mode == "3l":
        # 3 letters only
        chars = string.ascii_lowercase
        names = set()
        for combo in itertools.combinations_with_replacement(chars, 3):
            names.add(''.join(combo))
        return list(names)[:count]
    
    elif mode == "4c":
        # 4 characters: letters + numbers
        chars = string.ascii_lowercase + string.digits
        names = set()
        for combo in itertools.combinations_with_replacement(chars, 4):
            names.add(''.join(combo))
        return list(names)[:count]
    
    elif mode == "4l":
        # 4 letters only
        chars = string.ascii_lowercase
        names = set()
        for combo in itertools.combinations_with_replacement(chars, 4):
            names.add(''.join(combo))
        return list(names)[:count]
    
    return []

async def check_xbox_username(username: str) -> bool:
    """Check if username is available on Xbox"""
    try:
        async with aiohttp.ClientSession() as session:
            # Xbox Live username check
            url = f"https://xboxgamertag.com/search/{username}"
            async with session.get(url, timeout=5) as resp:
                return resp.status == 404  # 404 means available
    except:
        return False

async def check_discord_username(username: str) -> bool:
    """Check if username is available on Discord"""
    try:
        async with aiohttp.ClientSession() as session:
            # This is a simplified check - Discord doesn't have a public API for this
            # You may need to adjust based on your actual checking method
            url = f"https://discord.com/api/v10/users/search?q={username}"
            async with session.get(url, timeout=5) as resp:
                return resp.status == 404  # Simplified
    except:
        return False

async def send_webhook_message(username: str, platform: str):
    """Send embed message via webhook"""
    if not WEBHOOK_URL:
        print(f"⚠️ Webhook URL not set! Found: {username} on {platform}")
        return
    
    embed = discord.Embed(
        title=f"✅ Available!",
        description=f"**{username}** is available on **{platform.upper()}**!",
        color=discord.Color.green()
    )
    
    try:
        async with aiohttp.ClientSession() as session:
            data = {"embeds": [embed.to_dict()]}
            async with session.post(WEBHOOK_URL, json=data, timeout=5) as resp:
                if resp.status == 204:
                    print(f"✅ Webhook sent: {username} on {platform}")
    except Exception as e:
        print(f"❌ Webhook error: {e}")

async def check_usernames(mode: str, platform: str, count: int):
    """Main checking loop"""
    global checking_active, checked_count, found_names
    
    usernames = await generate_usernames(mode, count)
    
    for username in usernames:
        if not checking_active:
            break
        
        if platform == "xbox":
            available = await check_xbox_username(username)
        else:  # discord
            available = await check_discord_username(username)
        
        checked_count += 1
        
        if available:
            found_names.append(username)
            await send_webhook_message(username, platform)
            print(f"✅ Found: {username} on {platform}")
        
        # Small delay to avoid rate limiting
        await asyncio.sleep(0.5)
    
    checking_active = False
    print(f"✅ Checking completed! Found {len(found_names)} available usernames.")

@bot.event
async def on_ready():
    print(f"✅ Bot logged in as {bot.user}")
    try:
        synced = await bot.tree.sync()
        print(f"✅ Synced {len(synced)} command(s)")
    except Exception as e:
        print(f"❌ Failed to sync commands: {e}")

@bot.tree.command(name="start", description="Start checking usernames")
@app_commands.describe(platform="Choose Xbox or Discord")
async def start_command(interaction: discord.Interaction, platform: str):
    """Start checking command"""
    global checking_active
    
    if checking_active:
        await interaction.response.send_message("⚠️ Already checking! Use `/stop` first.", ephemeral=True)
        return
    
    if platform.lower() not in ["xbox", "discord"]:
        await interaction.response.send_message("❌ Platform must be 'xbox' or 'discord'", ephemeral=True)
        return
    
    view = ModeView(platform.lower())
    await interaction.response.send_message(
        f"🎮 Select a mode for **{platform.upper()}**:",
        view=view,
        ephemeral=True
    )

@bot.tree.command(name="stop", description="Stop checking usernames")
async def stop_command(interaction: discord.Interaction):
    """Stop checking command"""
    global checking_active
    
    if not checking_active:
        await interaction.response.send_message("⚠️ No checking in progress!", ephemeral=True)
        return
    
    checking_active = False
    await interaction.response.send_message(
        f"🛑 Stopped checking! Found {len(found_names)} available usernames.",
        ephemeral=True
    )

@bot.tree.command(name="status", description="Check current status")
async def status_command(interaction: discord.Interaction):
    """Status command"""
    global checking_active, checked_count, checking_count, found_names
    
    if not checking_active:
        await interaction.response.send_message("⏸️ No checking in progress.", ephemeral=True)
        return
    
    embed = discord.Embed(title="📊 Checking Status", color=discord.Color.blue())
    embed.add_field(name="Progress", value=f"{checked_count}/{checking_count}", inline=False)
    embed.add_field(name="Found", value=f"{len(found_names)} available", inline=False)
    embed.add_field(name="Mode", value=f"{checking_mode[0]} ({checking_mode[1]})", inline=False)
    
    await interaction.response.send_message(embed=embed, ephemeral=True)

# Run the bot
bot.run(os.getenv("DISCORD_BOT_TOKEN"))
