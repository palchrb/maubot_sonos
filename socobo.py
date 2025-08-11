from typing import Type
from maubot import Plugin, MessageEvent
from maubot.handlers import command
from mautrix.util.config import BaseProxyConfig, ConfigUpdateHelper

class Config(BaseProxyConfig):
    def do_update(self, helper: ConfigUpdateHelper) -> None:
        helper.copy("api_url")
        helper.copy("default_device")
        helper.copy("whitelist")

class SonosBot(Plugin):
    config: Config

    @classmethod
    def get_config_class(cls) -> Type[Config]:
        return Config

    async def start(self) -> None:
        # initial load of defaults + any saved UI overrides
        self.config.load_and_update()
        # last used speaker per Matrix room
        self._last_speaker: dict[str, str] = {}
        self.log.info(
            f"[start] api_url={self.config['api_url']!r}, "
            f"default_device={self.config['default_device']!r}, "
            f"whitelist={self.config['whitelist']!r}"
        )

    def on_external_config_update(self) -> None:
        # reload whenever you click “Save” in the web UI
        self.config.load_and_update()
        self.log.info(f"[reload] whitelist={self.config['whitelist']!r}")

    async def _check_perms(self, evt: MessageEvent) -> bool:
        # only allow users in the whitelist array
        if evt.sender not in self.config["whitelist"]:
            await evt.reply("🚫 You are not allowed to use Sonos commands.")
            return False
        return True

    @command.new(name="sonos", require_subcommand=True, help="Sonos commands")
    async def sonos(self, evt: MessageEvent) -> None:
        # root dispatcher
        pass

    @sonos.subcommand(name="speakers", help="List all Sonos speakers")
    async def speakers(self, evt: MessageEvent) -> None:
        if not await self._check_perms(evt): return
        api = self.config["api_url"].rstrip("/")
        resp = await self.http.get(f"{api}/speakers")
        data = await resp.json()
        lines = [f"- **{name}** → `{ip}`" for name, ip in data.items()]
        await evt.reply("Available speakers:\n" + "\n".join(lines))

    @sonos.subcommand(name="play", help="Play Spotify PlayLink on a speaker")
    @command.argument("args", pass_raw=True, required=True)
    async def play(self, evt: MessageEvent, args: str) -> None:
        if not await self._check_perms(evt): return

        api = self.config["api_url"].rstrip("/")
        device = self.config["default_device"]
        text = args.strip()

        # Hvis bare URI er gitt: bruk sist brukte speaker i dette rommet
        if " " not in text:
            playlink = text
            speaker = self._last_speaker.get(evt.room_id)
            if not speaker:
                return await evt.reply(
                    "❌ No speaker specified and none used before in this room. "
                    "Please run `!sonos play <speaker> <spotify-playlink>` first."
                )
        else:
            # allow speakers names with spaces
            speaker_input, playlink = text.rsplit(maxsplit=1)
            speaker_input = speaker_input.lstrip("#")

            # get speaker list
            resp = await self.http.get(f"{api}/speakers")
            speakers = await resp.json()  # f.eks. {"Edith": "…", "Kjøkken": "…"}

            # Case-insensitiv speaker names
            match = next((name for name in speakers if name.lower() == speaker_input.lower()), None)
            if not match:
                return await evt.reply(f"❌ Unknown speaker: {speaker_input}")
            speaker = match

        # re-mapping speakers to ensure correct IP
        await self.http.post(
            f"{api}/set_speaker",
            json={"device_id": device, "speaker": speaker}
        )

        # remember last used speaker
        self._last_speaker[evt.room_id] = speaker

        # Play via Spotify PlayLink
        resp2 = await self.http.post(
            f"{api}/play/playlink",
            json={"device_id": device, "media": playlink}
        )
        data = await resp2.json()
        await evt.reply(f"▶️ Playing Spotify PlayLink on **{speaker}**: {data}")

    # Renamed: playpause -> pause 
    @sonos.subcommand(name="pause", help="Pause playback (currently toggles via backend)")
    async def pause(self, evt: MessageEvent) -> None:
        if not await self._check_perms(evt): return
        device = self.config["default_device"]
        api = self.config["api_url"].rstrip("/")
        resp = await self.http.post(f"{api}/play_pause", json={"device_id": device})
        data = await resp.json()
        await evt.reply(f"⏯️ Pause (toggle): {data}")

    @sonos.subcommand(name="next", help="Next track")
    async def next(self, evt: MessageEvent) -> None:
        if not await self._check_perms(evt): return
        device = self.config["default_device"]
        api = self.config["api_url"].rstrip("/")
        resp = await self.http.post(f"{api}/next", json={"device_id": device})
        data = await resp.json()
        await evt.reply(f"⏭️ Next track: {data}")

    @sonos.subcommand(name="previous", help="Previous track")
    async def previous(self, evt: MessageEvent) -> None:
        if not await self._check_perms(evt): return
        device = self.config["default_device"]
        api = self.config["api_url"].rstrip("/")
        resp = await self.http.post(f"{api}/previous", json={"device_id": device})
        data = await resp.json()
        await evt.reply(f"⏮️ Previous track: {data}")
