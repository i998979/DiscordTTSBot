import asyncio
import os

from dotenv import load_dotenv

load_dotenv()

import discord
from discord.ext import commands
from gtts import gTTS, gTTSError
from gtts.lang import tts_langs

TOKEN = os.getenv('TOKEN')
intents = discord.Intents.default()
intents.message_content = True
intents.guilds = True
intents.voice_states = True

client = commands.Bot(command_prefix="!", intents=intents)
tree = client.tree

@client.event
async def on_ready():
    await tree.sync()
    await tree.sync(guild=discord.Object(id=os.getenv('GUILD')))
    print(f'Logged in as {client.user}')

@tree.command(name="speak", description="Bot joins VC and speaks the given text in the specified language.")
async def speak(interaction: discord.Interaction, lang: str, accent: str, text: str, play_tone: bool = False):
    await interaction.response.defer(ephemeral=True)
    await interaction.edit_original_response(content="Speaking...")

    if interaction.user.voice is None or interaction.user.voice.channel is None:
        await interaction.edit_original_response(content="You need to be in a voice channel!")
        return

    # Convert text to speech
    try:
        tts = gTTS(text, lang=lang, tld=accent)
        tts.save("speech.mp3")

        channel = interaction.user.voice.channel
        vc = discord.utils.get(client.voice_clients, guild=interaction.guild)

        if vc is None or not vc.is_connected():
            vc = await channel.connect()

        # Play tritone if enabled
        if play_tone:
            vc.play(discord.FFmpegPCMAudio(source="tritone.mp3"))
            while vc.is_playing():
                await asyncio.sleep(1)

        # Play the speech file
        vc.play(discord.FFmpegPCMAudio(
            source="speech.mp3",
            before_options="-nostdin",
            options="-filter:a 'atempo=1.2'"
        ), after=lambda e: print("Done playing"))
        while vc.is_playing():
            await asyncio.sleep(1)

        os.remove("speech.mp3")
        await interaction.edit_original_response(content="Done playing.")
    except ValueError:
        await interaction.edit_original_response(content="Language not supported. " + str(tts_langs()))
    except gTTSError:
        await interaction.edit_original_response(content="Accent not supported. https://gtts.readthedocs.io/en/latest/module.html#localized-accents")


@client.event
async def on_voice_state_update(member, before, after):
    """Disconnects the bot if it is alone in the voice channel."""
    if not member.guild:  # Ensure it's a valid guild
        return

    vc = discord.utils.get(client.voice_clients, guild=member.guild)

    if vc and vc.is_connected():  # Ensure bot is in a voice channel
        if len(vc.channel.members) == 1:  # Only the bot remains
            await vc.disconnect()
            print("Bot disconnected due to an empty voice channel.")

client.run(TOKEN)