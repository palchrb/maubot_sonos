# socobo.py
import re
import secrets
from typing import Type, Dict, Optional, Tuple
from maubot import Plugin, MessageEvent
from maubot.handlers import command
from mautrix.util.config import BaseProxyConfig, ConfigUpdateHelper

ACCOUNT_DATA_KEY = "com.vibb.socobo.credentials"
# Struktur:
# {
#   "<@user:server>": {
#       "endpoint": "https://sonos-backend.example",
#       "secret": "optional-or-None",
#       "device_id": "a1b2c3d4"
#   },
#   ...
# }

class Config(BaseProxyConfig):
    def do_update(self, helper: ConfigUpdateHelper) -> None:
        # behold kun disse i base-config
        helper.copy("default_device")
        helper.copy("whitelist")


class SonosBot(Plugin):
    config: Config
    user_config: Dict[str, Dict[str, Optional[str]]]

    @classmethod
    def get_config_class(cls) -> Type[Config]:
        return Config

    async def start(self) -> None:
        self.config.load_and_update()
        self._last_speaker: dict[str, str] = {}

        # hent lagrede brukerkredentialer
        try:
            data = await self.client.get_account_data(ACCOUNT_DATA_KEY)
            self.user_config = dict(data) if isinstance(data, dict) else {}
        except Exception:
            self.user_config = {}

        self.log.info(
            f"[start] default_device={self.config['default_device']!r}, "
            f"whitelist={self.config['whitelist']!r}, "
            f"user_config_count={len(self.user_config)}"
        )

    def on_external_config_update(self) -> None:
        self.config.load_and_update()
        self.log.info(f"[reload] whitelist={self.config['whitelist']!r}")

    async def _persist_user_config(self) -> None:
        await self.client.set_account_data(ACCOUNT_DATA_KEY, self.user_config)

    async def _check_perms(self, evt: MessageEvent) -> bool:
        sender = str(evt.sender)
        whitelist = self.config["whitelist"]

        # Eksakt brukermatch (ren streng)
        if sender in whitelist:
            return True

        # Støtt både spesifikke brukere, domener (":server.tld") og regex-mønstre
        for allowed in whitelist:
            # 1) Regex-støtte: prøv å matche som regex
            try:
                if re.match(allowed, sender):
                    return True
            except re.error:
                # ikke gyldig regex -> faller tilbake til strenglogikk
                pass

            # 2) Eksakt brukernavn (starter ofte med "@")
            if allowed.startswith("@") and sender == allowed:
                return True

            # 3) Domenebasert (oppgi ":vibb.me" for å matche hvilket som helst @user:vibb.me)
            if allowed.startswith(":") and sender.endswith(allowed):
                return True

        await evt.reply("🚫 You are not allowed to use Sonos commands.")
        return False


    def _get_user_id(self, evt: MessageEvent) -> str:
        return str(evt.sender)

    def _normalize_api(self, endpoint: str) -> str:
        return endpoint.rstrip("/")

    def _headers(self, secret: Optional[str]) -> Optional[Dict[str, str]]:
        # returner None (ikke tom dict) slik at vi kan droppe 'headers' helt i http-kall
        if secret:
            return {"Authorization": f"Bearer {secret}"}
        return None

    async def _get_user_api(self, evt: MessageEvent) -> Optional[Tuple[str, Optional[Dict[str, str]]]]:
        """Returner (api_base, headers|None) eller None hvis ikke logget inn/ukorrekt."""
        user = self._get_user_id(evt)
        creds = self.user_config.get(user)
        if not creds:
            await evt.reply("ℹ️ Not logged in. Use `!sonos login <endpoint> [secret]`.")
            return None
        api = self._normalize_api(creds.get("endpoint", "") or "")
        if not api:
            await evt.reply("ℹ️ Your endpoint is empty. Re-login: `!sonos login <endpoint> [secret]`.")
            return None
        return api, self._headers(creds.get("secret"))

    def _get_device_id(self, evt: MessageEvent) -> str:
        """Returner device_id for denne brukeren, eller fallback til default_device fra base-config."""
        user = self._get_user_id(evt)
        dev = (self.user_config.get(user) or {}).get("device_id")
        return dev or self.config["default_device"]

    # Små helpers for å unngå å sende 'headers' når den er None
    async def _http_get(self, url: str, headers: Optional[Dict[str, str]] = None):
        if headers:
            return await self.http.get(url, headers=headers)
        return await self.http.get(url)

    async def _http_post(self, url: str, json: Optional[dict] = None, headers: Optional[Dict[str, str]] = None):
        # Unngå å sende json=None (noen backend'er tolker det som body 'null').
        kwargs: Dict[str, object] = {}
        if headers:
            kwargs["headers"] = headers
        if json is not None:
            kwargs["json"] = json
        return await self.http.post(url, **kwargs)

    # ---------- ROOT + HELP ----------
    @command.new(name="sonos", require_subcommand=False, help="Sonos commands")
    async def sonos(self, evt: MessageEvent) -> None:
        await evt.reply(
            "!sonos help for commands\n"
        )

    # ---------- AUTH ----------
    @sonos.subcommand(name="login", help="Save your endpoint (and optional secret).")
    @command.argument("args", pass_raw=True, required=True)
    async def login(self, evt: MessageEvent, args: str) -> None:
        raw = args.strip()
        if not raw:
            await evt.reply("Usage: `!sonos login <endpoint> [secret]`")
            return

        parts = raw.split(maxsplit=1)
        endpoint_in = parts[0].strip()
        secret_in = parts[1].strip() if len(parts) > 1 else None

        user = self._get_user_id(evt)
        existing = self.user_config.get(user) or {}

        # Bevar device_id hvis det allerede finnes, ellers generer en ny nå
        device_id = existing.get("device_id") or secrets.token_hex(4)  # f.eks. 'a3f19c7e'

        api = self._normalize_api(endpoint_in)
        headers = self._headers(secret_in)

        self.user_config[user] = {
            "endpoint": api,
            "secret": secret_in or None,
            "device_id": device_id,
        }
        await self._persist_user_config()

        # Forsøk å verifisere mot /speakers
        verify_ok = False
        verify_msg = ""
        try:
            resp = await self._http_get(f"{api}/speakers", headers=headers)
            if resp.status == 200:
                data = await resp.json()
                # Tillat både dict {"Name":"ip"} og liste ["Name", ...]
                if isinstance(data, dict):
                    names = list(data.keys())
                elif isinstance(data, list):
                    names = [str(x) for x in data]
                else:
                    names = []

                count = len(names)
                if count:
                    preview = ", ".join(sorted(names)[:10])
                    more = f" (+{count-10} more)" if count > 10 else ""
                    verify_msg = f"✅ Connected. Found {count} speaker(s): {preview}{more}"
                else:
                    verify_msg = "✅ Connected, but no speakers reported."
                verify_ok = True
            else:
                verify_msg = f"⚠️ Backend responded with HTTP {resp.status} on `/speakers`."
        except Exception as e:
            verify_msg = f"⚠️ Could not reach `{api}`: {e}"

        await evt.reply(
            f"✅ Saved endpoint for **{user}**. "
            f"Secret set: **{'yes' if secret_in else 'no'}** • DeviceID: `{device_id}`\n"
            + (verify_msg if verify_ok else verify_msg + "\nTip: try `!sonos speakers` to re-check.")
        )

        # Redact login-meldingen hvis secret var oppgitt
        if secret_in:
            try:
                await self.client.redact(evt.room_id, evt.event_id, reason="Cleanup: contained secret")
            except Exception as e:
                self.log.warning(f"Failed to redact login message: {e}")

    @sonos.subcommand(name="whoami", help="Show your saved endpoint (secret is not shown).")
    async def whoami(self, evt: MessageEvent) -> None:
        user = self._get_user_id(evt)
        creds = self.user_config.get(user)
        if not creds:
            await evt.reply("ℹ️ No login found. Use `!sonos login <endpoint> [secret]`.")
            return
        endpoint = creds.get("endpoint") or "(none)"
        has_secret = "yes" if creds.get("secret") else "no"
        device_id = creds.get("device_id") or self.config["default_device"]
        await evt.reply(
            f"👤 Endpoint: **{endpoint}**\n"
            f"🔑 Secret set: **{has_secret}**\n"
            f"🆔 DeviceID: `{device_id}`"
        )

    @sonos.subcommand(name="logout", help="Remove your saved endpoint/secret.")
    async def logout(self, evt: MessageEvent) -> None:
        user = self._get_user_id(evt)
        if user in self.user_config:
            del self.user_config[user]
            await self._persist_user_config()
            await evt.reply("🚪 Logged out. Your endpoint/secret have been removed.")
        else:
            await evt.reply("You have no saved login.")

    # ---------- SPEAKERS ----------
    @sonos.subcommand(name="speakers", help="List all Sonos speakers")
    async def speakers(self, evt: MessageEvent) -> None:
        if not await self._check_perms(evt): return
        got = await self._get_user_api(evt)
        if not got: return
        api, headers = got

        resp = await self._http_get(f"{api}/speakers", headers=headers)
        data = await resp.json()
        lines = [f"- **{name}** → `{ip}`" for name, ip in data.items()]
        await evt.reply("Available speakers:\n" + "\n".join(lines))

    # ---------- PLAY ----------
    @sonos.subcommand(name="play", help="Play Spotify PlayLink, NRK podcast series or episode, or a generic stream")
    @command.argument("args", pass_raw=True, required=True)
    async def play(self, evt: MessageEvent, args: str) -> None:
        if not await self._check_perms(evt): return
        got = await self._get_user_api(evt)
        if not got: return
        api, headers = got

        device = self._get_device_id(evt)
        text = args.strip()

        # --- speaker + uri parsing (multiword speaker, optional '#') ---
        if " " not in text:
            uri = text
            speaker = self._last_speaker.get(evt.room_id)
            if not speaker:
                return await evt.reply(
                    "❌ No speaker specified and none used before in this room. "
                    "Use `!sonos play <speaker> <uri>` once first."
                )
        else:
            speaker_input, uri = text.rsplit(maxsplit=1)
            speaker_input = speaker_input.lstrip("#")

            # get speakers and find canonical name (case-insensitive)
            resp = await self._http_get(f"{api}/speakers", headers=headers)
            speakers = await resp.json()  # {"Edith": "...", "Kjøkken": "...", ...}
            match = next((n for n in speakers if n.lower() == speaker_input.lower()), None)
            if not match:
                return await evt.reply(f"❌ Unknown speaker: {speaker_input}")
            speaker = match

        # always set mapping before play
        await self._http_post(
            f"{api}/set_speaker",
            json={"device_id": device, "speaker": speaker},
            headers=headers,
        )
        self._last_speaker[evt.room_id] = speaker

        # --- URI routing ---
        # 1) NRK podcast: EPISODE-URL -> backend løser tittel => MP3 fra lokal XML
        m_pod_ep = re.match(
            r'^https?://radio\.nrk\.no/podkast/([a-z0-9_]+)/([A-Za-z0-9_-]+)$',
            uri, re.IGNORECASE
        )
        if m_pod_ep:
            endpoint = "/play/nrk_podcast"
            body = {"device_id": device, "media": uri}

        # 2) NRK podcast: SERIE-URL -> <slug>.xml -> spill hele feeden
        elif re.match(r'^https?://radio\.nrk\.no/podkast/([a-z0-9_]+)$', uri, re.IGNORECASE):
            slug = uri.rstrip("/").split("/")[-1]
            endpoint = "/play/nrk_podcast"
            body = {"device_id": device, "media": f"{slug}.xml"}

        # 3) Spotify PlayLink
        elif re.match(r'^(?:spotify:|https?://open\.spotify\.com/)', uri, re.IGNORECASE):
            endpoint = "/play/playlink"
            body = {"device_id": device, "media": uri}

        # 4) Fallback: generisk stream (mp3/aac/wav/flac/… eller /stream path)
        else:
            endpoint = "/play/stream"
            body = {"device_id": device, "uri": uri}

        resp2 = await self._http_post(f"{api}{endpoint}", json=body, headers=headers)
        try:
            data = await resp2.json()
        except Exception:
            data = await resp2.text()
        await evt.reply(f"▶️ `{endpoint}` on **{speaker}** → {data}")

    # ---------- PAUSE ----------
    @sonos.subcommand(name="pause", help="Pause playback (currently toggles via backend)")
    async def pause(self, evt: MessageEvent) -> None:
        if not await self._check_perms(evt): return
        got = await self._get_user_api(evt)
        if not got: return
        api, headers = got

        device = self._get_device_id(evt)
        resp = await self._http_post(f"{api}/play_pause", json={"device_id": device}, headers=headers)
        data = await resp.json()
        await evt.reply(f"⏯️ Pause (toggle): {data}")

    @sonos.subcommand(name="next", help="Next track")
    async def next(self, evt: MessageEvent) -> None:
        if not await self._check_perms(evt): return
        got = await self._get_user_api(evt)
        if not got: return
        api, headers = got

        device = self._get_device_id(evt)
        resp = await self._http_post(f"{api}/next", json={"device_id": device}, headers=headers)
        data = await resp.json()
        await evt.reply(f"⏭️ Next track: {data}")

    @sonos.subcommand(name="previous", help="Previous track")
    async def previous(self, evt: MessageEvent) -> None:
        if not await self._check_perms(evt): return
        got = await self._get_user_api(evt)
        if not got: return
        api, headers = got

        device = self._get_device_id(evt)
        resp = await self._http_post(f"{api}/previous", json={"device_id": device}, headers=headers)
        data = await resp.json()
        await evt.reply(f"⏮️ Previous track: {data}")

    # ---------- GROUP ----------
    @sonos.subcommand(name="group", help="Group speakers. First is coordinator. Example: 'Edith, Bad 2 etg, TV'")
    @command.argument("members", pass_raw=True, required=True)
    async def group_cmd(self, evt: MessageEvent, members: str) -> None:
        if not await self._check_perms(evt):
            return
        got = await self._get_user_api(evt)
        if not got: return
        api, headers = got

        text = members.strip()

        # Helper: fetch canonical speaker names from backend
        try:
            resp = await self._http_get(f"{api}/speakers", headers=headers)
            all_speakers = await resp.json()          # {"Edith": "ip", "Bad 2 etg": "ip", ...}
            canon_by_lower = {name.lower(): name for name in all_speakers.keys()}
        except Exception as e:
            return await evt.reply(f"⚠️ Could not fetch speakers from backend: {e}")

        resolved: list[str] = []

        if "," in text:
            for raw in text.split(","):
                nm = raw.strip()
                key = nm.lower()
                if key in canon_by_lower:
                    resolved.append(canon_by_lower[key])
                else:
                    return await evt.reply(f"❌ Unknown speaker: {nm}")
        else:
            tokens = text.split()
            i = 0
            while i < len(tokens):
                found = None
                found_len = 0
                for j in range(len(tokens), i, -1):
                    candidate = " ".join(tokens[i:j]).lower()
                    if candidate in canon_by_lower:
                        found = canon_by_lower[candidate]
                        found_len = j - i
                        break
                if not found:
                    remainder = " ".join(tokens[i:])
                    return await evt.reply(
                        "❌ Could not parse speakers near: "
                        f"`{remainder}`\nTip: separate with commas, e.g. `!sonos group Edith, Bad 2 etg`"
                    )
                resolved.append(found)
                i += found_len

        if len(resolved) < 2:
            return await evt.reply("❌ Need at least two speakers. Example: `!sonos group Edith, Bad 2 etg`")

        coordinator = resolved[0]
        payload = {
            "speakers": resolved,
            "coordinator": coordinator,
            "exact": True
            # valgfritt: "device_id": self._get_device_id(evt),
        }

        try:
            r = await self._http_post(f"{api}/group", json=payload, headers=headers)
            data = await r.json()
        except Exception as e:
            return await evt.reply(f"⚠️ Grouping failed: {e}")

        added = ", ".join(data.get("added", [])) or "none"
        final_group = ", ".join(data.get("final_group", [])) or "unknown"
        errors = data.get("errors", [])
        msg = f"🔗 Grouped with **{coordinator}** as coordinator.\n• Added: {added}\n• Final group: {final_group}"
        if errors:
            msg += f"\n• Errors: {errors}"
        await evt.reply(msg)

    # ---------- UNGROUP ----------
    @sonos.subcommand(name="ungroup", help="Ungroup all grouped speakers")
    async def ungroup(self, evt: MessageEvent) -> None:
        if not await self._check_perms(evt): return
        got = await self._get_user_api(evt)
        if not got: return
        api, headers = got

        resp = await self._http_post(f"{api}/ungroup", headers=headers)
        try:
            data = await resp.json()
        except Exception:
            data = await resp.text()

        if isinstance(data, dict):
            ungrouped = data.get("ungrouped") or []
            already = data.get("already_solo") or []
            parts = []
            if ungrouped:
                parts.append(f"Ungrouped: {', '.join(ungrouped)}")
            if already:
                parts.append(f"Already solo: {', '.join(already)}")
            text = "✅ " + ("; ".join(parts) if parts else "Done.")
        else:
            text = f"✅ {data}"
        await evt.reply(text)
