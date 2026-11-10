2.1.0 first-run workaround (Video Processor) - config only

Why: on a machine with no app_config.json, first-run setup cannot persist the
mode or the selected input. The app restarts into Media Player and capture gets
an empty device name ("No signal detected"). The file below gives the app the
config keys it needs, so the normal setup writes work from then on.

WHERE THE FILE GOES (the step that is easy to get wrong):

   %USERPROFILE%\.unplugged\app_config.json

NOT %USERPROFILE%\.unplugged\logs\app_config.json.
If the .unplugged folder does not exist, create it.

1. Close Unplugged completely (Exit in the app; check Task Manager).

2. Copy app_config.json to:
      %USERPROFILE%\.unplugged\app_config.json
   Replace any file already there.

3. Start Unplugged. The one-time setup appears, already in Video Processor mode.

4. Choose Video Processor, pick your DeckLink HDMI port (the list shows every
   port; your input is the one with a signal), then press Start Capture.
   The mode and the port are now saved; normal restarts go straight to capture.
   If the port does not appear or never shows a signal, open Blackmagic Desktop
   Video Setup and make sure that connector is set to HDMI Video Input (the
   cards ship with some connectors configured as outputs).

5. If you land on "No signal detected" instead: click "Switch input" on the
   card, pick the DeckLink HDMI port, and it will persist from then on.

No registry changes are required.

The permanent fix - the app creating its own config on a fresh install - will
be in the next build.