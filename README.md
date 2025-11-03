# maubot_sonos
Plugin for Maubot to control your Sonos sound system. Requires a server running https://github.com/palchrb/sonos-remotes/blob/main/app.py, which is a SoCo based server backend, in the local network where you will control your Sonos system. For now it only plays links you give it from Spotify (spotify sharelinks), but plan is to include other media links as well.

Currently you need to configure/point to the backend through !sonos login #endpoint #secret (optional, only if you use auth on your endpoint) - and also whitelist which users can actually use it. 

Development ideas I might do;
- Implement secret based auth (now implemented!)
- Allow users to configure their sonos backend via a room state event, so multiple users can use the bot on the same instance - and not just the maubot admin (now implemented, but through account data instead of room specifically)
- Implement other media types, so that basically any http music stream can be played via the bot (implemented, but untested)
- Implement NRK podcasts from the Norwegian broadcaster, since my kids use it - based on https://github.com/sindrel/nrk-pod-feeds (implemented - can give both a link to a podcast series like so https://radio.nrk.no/podkast/fantorangenfortellinger, and it will play the whole series - or like so to play only a specific episode: https://radio.nrk.no/podkast/fantorangenfortellinger/l_17d00a92-711b-4bdc-900a-92711b2bdce1. Not that this requires you to have the xml files from NRK for all the podcasts you want to use, that i get through the above menetioed nrk-pod-feeds repo. They need to be available for the sonos backend server. 
- ?

Feel free to contact me [on Matrix](https://matrix.to/#/#whatever:vibb.me)
