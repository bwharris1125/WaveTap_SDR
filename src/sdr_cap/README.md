# dump1090-fa Setup Guide

The ADS-B publisher in `sdr_cap` expects an existing dump1090 (or rtl_tcp) feed
that streams raw Mode-S frames on TCP port `30002`. Use the steps below to set
up dump1090-fa and confirm it is producing data on both Linux and Windows/WSL.

## Linux (Debian/Ubuntu)

1. **Installing Dump1090**
	```bash
	sudo apt update
	sudo apt install ca-certificates curl gnupg
	wget https://flightaware.com/adsb/piaware/files/packages/pool/piaware/p/piaware-support/piaware-repository_latest_all.deb
    sudo dpkg -i piaware-repository_latest_all.deb
	sudo apt update
	```

2. **Install dump1090-fa**
	```bash
	sudo apt install dump1090-fa
	```

3. **Verify the service**
	```bash
	sudo systemctl status dump1090-fa
	sudo journalctl -u dump1090-fa --since "5 minutes ago"
	```

4. **Confirm TCP output**
	```bash
	nc -vz localhost 30002
	# or stream a few hex frames
	nc localhost 30002 | head
	```

If you are running inside WSL, attach the RTL-SDR USB device with `usbipd
attach --wsl` before starting the service.

## Windows

1. Download the latest FlightAware dump1090 package: <https://flightaware.com/adsb/piaware/build>
2. Run the installer (`dump1090-fa-<version>.exe`) and follow the prompts.
3. After installation, launch **Services** and ensure `dump1090-fa` is set to
	*Automatic* and the status is *Running*.
4. Optional: open the local status page in a browser to confirm reception:
	<http://127.0.0.1:8080/>.

If you want WSL to consume the feed, set `DUMP1090_HOST=<Windows_IP>` (often
`127.0.0.1` works thanks to localhost forwarding, otherwise use `ipconfig` to
find the Windows host address).

## Checking that WaveTap sees the feed

From the `sdr_cap` publisher container or your local environment you can test
connectivity:

```bash
nc -vz $DUMP1090_HOST $DUMP1090_RAW_PORT   # should report "succeeded"
```

Once the check passes, `python -m sdr_cap.adsb_publisher` (or the Docker
service) will stream aircraft JSON to any WaveTap subscriber.

