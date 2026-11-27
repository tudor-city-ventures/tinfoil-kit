---
name: tinfoil-home-server
description: Share a Tinfoil Kit with the phones and laptops at home, behind an access code, or make a computer that stays on into a home server that starts the kit with the computer. Use when someone wants family devices to use the kit, a home server, a new access code, or to stop sharing.
---

# Share the kit at home

Sharing is off until the person turns it on. Then phones and laptops on the same Wi-Fi or hotspot open an address like http://192.168.1.20:8000 and type an 8-digit access code once, or scan a QR code that includes it. Share with family, under More on the kit page, copies a message to text them, with a link that includes it too. No internet is needed, just the home network. To find the kit, see the tinfoil-update skill.

## A new kit, as a home server

A home server is experimental for now: tell them, so rough edges don't surprise them.

On the computer that stays on (a Linux box, a Mac mini, or a laptop on its charger), the setup command from the tinfoil-install skill with `--this-computer --home-server`. It sets the kit up on that computer's own disk, gets all of it, shares it, and starts it with the computer.

## A kit that's already set up

In the kit's app folder (`.\kit.cmd` for `./kit` in PowerShell on Windows):

    ./kit share on          # share it: prints the address, the access code and a QR code
    ./kit share             # show them again
    ./kit share new-code    # a new code, which signs every device out (--code CODE picks it: 6 to 64 letters or digits)
    ./kit share off         # only this computer can open it again
    ./kit autostart on      # start it now, and whenever the computer starts
    ./kit autostart off     # stop it starting by itself

On the computer the kit runs on, Share with family (under More on the kit page) does the same with buttons: Turn on sharing, New code, Turn off sharing. Either way the running kit starts or stops sharing at once, and it stays that way at the next start. Phones and laptops that come in with the code can't change it.

`bash "Open Tinfoil Kit.command" --share` (`& ".\Open Tinfoil Kit for Windows.bat" --share` on Windows) shares it just this once.

## Each system

- Linux: autostart is a systemd user service (`systemctl --user status tinfoil-kit`). It starts at boot once lingering is on: `sudo loginctl enable-linger $USER`. The kit tries that itself and says if it needs the person.
- Mac: a LaunchAgent that starts when the person logs in, so turn on automatic login on a Mac that's a server.
- Windows: "Tinfoil Kit.cmd" in the Startup folder starts the kit when the person signs in, so keep that PC signed in (locking is fine) and plugged in. The first time it shares, Windows asks whether tinfoilkit-windows-x64.exe may use the network: click Allow access. If phones still can't connect, the Wi-Fi must be a private network (Settings > Network & internet), and that program allowed for private networks in Windows Security > Firewall & network protection > Allow an app through firewall.
- If macOS asks whether to accept incoming connections, click Allow.
- In an outage the router still needs power, even with no internet: a small battery backup keeps it on.

## Good to know

- Every device sees the same notes (Notes) and map pins, and can change them: anyone with the code can read them.
- It's plain HTTP inside the home network: share it on the person's own Wi-Fi or hotspot, never a public one.
- Only devices with home network addresses get in, and each gets 10 wrong codes per 10 minutes. Anyone with the code, or a link from Share with family, gets in from the home network: `./kit share new-code` turns old links off and signs every device out.
- The gate listens on port 8000 (`share_port` in data/kit.json). Every server behind it listens only on 127.0.0.1.
- Programs can use the AI's OpenAI-compatible API with the code as the key: `Authorization: Bearer CODE` at http://ADDRESS:8000/ai/v1.
