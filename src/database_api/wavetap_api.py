"""WaveTap API entry point aggregating SDR capabilities."""

from __future__ import annotations

from flask import Flask, render_template, url_for

from adsb_module import adsb_bp


app = Flask(__name__)
app.register_blueprint(adsb_bp, url_prefix="/adsb")


@app.route("/")
def home():
    cards = [
        {
            "title": "ADS-B Operations",
            "description": "Monitor ADS-B telemetry, history, and situational awareness tools.",
            "href": url_for("adsb.dashboard"),
            "cta": "Enter ADS-B Suite",
        },
        {
            "title": "VHF Radio (Future)",
            "description": "Roadmap for aviation-band voice capture and analysis.",
            "href": url_for("vhf_dashboard"),
            "cta": "Explore VHF Plans",
        },
        {
            "title": "FM Radio (Future)",
            "description": "Roadmap for FM broadcast reception and analytics.",
            "href": url_for("fm_dashboard"),
            "cta": "Explore FM Plans",
        },
        {
            "title": "AM Radio (Future)",
            "description": "Placeholder for AM broadcast demodulation initiatives.",
            "href": url_for("am_dashboard"),
            "cta": "View AM Roadmap",
        },
        {
            "title": "Other Signals",
            "description": "Concepts and experiments for future SDR domains within WaveTap.",
            "href": url_for("other_dashboard"),
            "cta": "See Emerging Ideas",
        },
    ]
    return render_template("home.html", title="WaveTap Control Center", cards=cards)


@app.route("/vhf")
def vhf_dashboard():
    return render_template(
        "capability_placeholder.html",
        title="VHF Radio",
        capability="VHF Radio",
        description=(
            "Spectrum capture, demodulation, and transcription of aviation band voice "
            "communications will be introduced in a future release."
        ),
        roadmap=[
            "Integrate SDR streaming pipeline for VHF frequency ranges",
            "Implement squelch, filtering, and audio recording",
            "Provide live transcription and archival of communications",
        ],
    )


@app.route("/fm")
def fm_dashboard():
    return render_template(
        "capability_placeholder.html",
        title="FM Radio",
        capability="FM Radio",
        description=(
            "FM broadcast reception, program metadata extraction, and audio analytics "
            "will be added as the WaveTap platform expands."
        ),
        roadmap=[
            "Enable frequency scanning and preset management",
            "Add RDS/RBDS decoding for station metadata",
            "Surface audio-level metrics and recording controls",
        ],
    )


@app.route("/am")
def am_dashboard():
    return render_template(
        "capability_placeholder.html",
        title="AM Radio",
        capability="AM Radio",
        description=(
            "AM broadcast capture and demodulation will be introduced as WaveTap expands into "
            "additional frequency domains."
        ),
        roadmap=[
            "Survey medium-wave bands for regional signal strength",
            "Develop automatic gain and noise reduction pipelines",
            "Integrate audio recording and archival tooling",
        ],
    )


@app.route("/other")
def other_dashboard():
    return render_template(
        "capability_placeholder.html",
        title="Other Signals",
        capability="Emerging SDR Capabilities",
        description=(
            "Concepts under evaluation such as satellite downlink capture, ADS-C, and spectrum "
            "anomaly detection will be staged here as prototypes mature."
        ),
        roadmap=[
            "Identify candidate frequency bands for future integrations",
            "Prototype capture pipelines and assess data quality",
            "Design user workflows for multi-domain signal intelligence",
        ],
    )


if __name__ == "__main__":
    app.run(debug=True, host="0.0.0.0", port=5000)
