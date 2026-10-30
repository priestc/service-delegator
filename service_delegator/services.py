"""Web APIs (other than the AI providers in providers.py) that projects call
through the logging proxy.

A project sends a request to /proxy/<project>/<service>/<path> instead of
<base_url>/<path>; it's forwarded unchanged (method, query, body, headers,
including the project's own API key) and the response is passed back, while
the call's duration, status and size are logged. The keys stay with the
projects; the delegator only measures.
"""
from __future__ import annotations

from dataclasses import dataclass


@dataclass
class Service:
    name: str
    display: str
    base_url: str
    used_by: str            # which projects call it, for the Services page
    http2: bool = False     # the upstream only speaks HTTP/2 (Apple Push)
    notes: str = ""


SERVICES: dict[str, Service] = {s.name: s for s in [
    # radioserver: song release years
    Service("musicbrainz", "MusicBrainz", "https://musicbrainz.org/ws/2", "radioserver",
            notes="One request per second; radioserver keeps to it"),
    Service("discogs", "Discogs", "https://api.discogs.com", "radioserver", notes="60 requests a minute"),
    # smart-home
    Service("google-places", "Google Places", "https://places.googleapis.com", "smart-home (gas prices), RoadtripApp"),
    Service("ecobee", "Ecobee", "https://api.ecobee.com", "smart-home (thermostat)"),
    Service("apns", "Apple Push", "https://api.push.apple.com", "smart-home (notifications)", http2=True),
    Service("apns-sandbox", "Apple Push (sandbox)", "https://api.sandbox.push.apple.com",
            "smart-home (notifications to development builds)", http2=True),
    # takeloom
    Service("youtube", "YouTube Data API", "https://www.googleapis.com/youtube/v3", "takeloom"),
    Service("google-oauth", "Google OAuth", "https://oauth2.googleapis.com", "takeloom (YouTube sign-in)"),
    # timeaudit: finding and fetching sources
    Service("crossref", "Crossref", "https://api.crossref.org", "timeaudit"),
    Service("openalex", "OpenAlex", "https://api.openalex.org", "timeaudit"),
    Service("unpaywall", "Unpaywall", "https://api.unpaywall.org", "timeaudit"),
    Service("openlibrary", "Open Library", "https://openlibrary.org", "timeaudit"),
    Service("google-books", "Google Books", "https://www.googleapis.com/books/v1", "timeaudit"),
    Service("ncbi", "NCBI / PubMed Central", "https://www.ncbi.nlm.nih.gov", "timeaudit"),
    Service("europepmc", "Europe PMC", "https://www.ebi.ac.uk/europepmc/webservices/rest", "timeaudit"),
    Service("internet-archive", "Internet Archive", "https://archive.org", "timeaudit"),
    # RoadtripApp
    Service("fueleconomy", "FuelEconomy.gov", "https://www.fueleconomy.gov/ws/rest", "RoadtripApp"),
]}
