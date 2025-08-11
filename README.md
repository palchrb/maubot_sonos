# maubot_sonos
Plugin for Maubot to control your Sonos sound system. Requires a server running https://github.com/palchrb/sonos-remotes/blob/main/app.py, which is a SoCo based server backend, in the local network where you will control your Sonos system. For now it only plays links you give it from Spotify (spotify sharelinks), but plan is to include other media links as well.

Currently you need to configure/point to the backend in the maubot instance window - and also whitelist which users can actually use it. There is no auth yet, as myself I am letting it connect encrypted via tailscale.

Development ideas I might do;
- Implement secret based auth
- Allow users to configure their sonos backend via a room state event, so multiple users can use the bot on the same instance - and not just the maubot admin
- Implement other media types, so that basically any http music stream can be played via the bot
- Implement NRK podcasts from the Norwegian broadcaster, since my kids use it - based on https://github.com/sindrel/nrk-pod-feeds
- ?
