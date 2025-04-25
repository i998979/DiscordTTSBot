# DiscordTTSBot
DiscordTTSBot is a Discord Bot that will play Text-to-Speech in voice channel upon user's command. Command `/speak` speaks texts in specified language and accent using Google TTS Service. `/celebrity_tts` speak texts with specified celebrity's voice using FakeYou Text-to-Speech. `/kcr_speak` and `/mtr_speak` speak texts with specified GPT-SoVITS trained AI models.


This bot is only be used in 1 guild, please host multiple instances when using in more than 1 guild.


Please visit the websites in the command for more information.


When using GPT-SoVITS trained AI models, please make sure you have the [API server](https://github.com/RVC-Boss/GPT-SoVITS/blob/main/api.py) running and necessary parameters specified.


Before using the bot, you will have to create a `.env` file, the content is as follows:
```
TOKEN=DISCORD_BOT_TOKEN
GUILD=DISCORD_CHANNEL_TO_RUN
TTS_SERVER=http://192.168.1.87:9880
KCR_SOVITS=SoVITS_weights_v2/TRAINED_AI_MODEL_FOR_kcr_speak.pth
MTR_SOVITS=SoVITS_weights_v2/TRAINED_AI_MODEL_FOR_mtr_speak.pth
KCR_GPT=GPT_weights_v2/TRAINED_AI_MODEL_FOR_kcr_speak.ckpt
MTR_GPT=GPT_weights_v2/TRAINED_AI_MODEL_FOR_mtr_speak.ckpt
KCR_REFERENCE=REFERENCE_AUDIO_FOR_kcr_speak.wav
MTR_REFERENCE=REFERENCE_AUDIO_FOR_mtr_speak.WAV
KCR_REF_TEXT=REFERENCE_TEXT_FOR_kcr_speak
MTR_REF_TEXT=REFERENCE_TEXT_FOR_mtr_speak
```



## Terms of Use
- You are not allowed to redistribute any part of the code and claim that is your work.
