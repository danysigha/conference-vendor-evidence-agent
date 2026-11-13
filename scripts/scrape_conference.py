from __future__ import annotations

import csv
import hashlib
import html
import json
import re
import subprocess
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

from lxml import html as lxml_html


ROOT = Path(__file__).resolve().parents[1]
DATA_DIR = ROOT / "data" / "conference"
COMPANY_DIR = DATA_DIR / "company-sites"
EVENT_DIR = DATA_DIR / "event"
CHECKED_AT = "2026-11-13"
TIMEZONE = ZoneInfo("America/New_York")
USER_AGENT = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/143.0.0.0 Safari/537.36"
)
EVENT_AGENDA_URL = "https://world.aiacceleratorinstitute.com/location/boston/agenda"
EVENT_SPEAKERS_URL = "https://world.aiacceleratorinstitute.com/location/boston/speakers"


CAPABILITY_RULES = [
    ("AI governance", "Governance", r"\bAI governance\b|\bgovern(?:ance|ed)?\b"),
    ("Policy enforcement", "Governance", r"\bpolicy enforcement\b|\benforce\b.{0,30}\bpolicy"),
    ("Guardrails", "Governance", r"\bguardrails?\b"),
    ("Human approval", "Governance", r"\bhuman[- ]in[- ]the[- ]loop\b|\bhuman approval\b|\brequire approval\b|\bapproval gate\b"),
    ("Identity and access", "Security", r"\bidentity and access\b|\baccess management\b|\baccess control\b|\bRBAC\b"),
    ("Agent identity", "Security", r"\bagent identit(?:y|ies)\b|\bnon-human identit(?:y|ies)\b"),
    ("Sensitive data protection", "Security", r"\bsensitive data\b|\bdata protection\b|\bdata loss prevention\b|\bDLP\b|\bPII\b"),
    ("Observability and audit", "Security", r"\bobservability\b|\baudit(?:ing)?\b|\baudit trail\b"),
    ("Compliance", "Trust", r"\bSOC 2\b|\bISO 27001\b|\bcompliance\b|\bGDPR\b|\bHIPAA\b"),
    ("Model routing", "AI infrastructure", r"\bmodel routing\b|\brouting and fallback\b|\bintelligent routing\b|\broute\b.{0,20}\bmodel"),
    ("Cost and usage control", "AI operations", r"\bcost control\b|\bspend\b|\bhard caps?\b|\busage control\b"),
    ("Workflow automation", "Automation", r"\bworkflow automation\b|\bAI automations?\b|\bautomate\b.{0,30}\bworkflow"),
    ("Agent deployment", "AI operations", r"\bdeploy\b.{0,30}\bagents?\b|\bagent deployment\b"),
    ("MCP support", "Platform", r"\bMCP\b|\bModel Context Protocol\b"),
    ("Integrations and connectors", "Platform", r"\bintegrations?\b|\bconnectors?\b|\bconnect(?:s|ed|ing)?\b.{0,30}\b(?:tools?|systems?|applications?)\b"),
    ("Enterprise search", "Knowledge", r"\benterprise search\b|\bknowledge graph\b|\bsemantic search\b"),
    ("Shared context", "Knowledge", r"\bshared context\b|\bcompany context\b|\bcontext layer\b"),
    ("Data analytics", "Data", r"\bdata analytics\b|\banaly[sz]e data\b|\bdashboards?\b|\bSQL\b"),
    ("Code generation", "Engineering", r"\bcode generation\b|\bcoding agents?\b|\bsoftware development\b|\bSDLC\b"),
    ("Cloud and compute", "Infrastructure", r"\bGPU\b|\bcloud compute\b|\bcloud infrastructure\b|\bcompute\b"),
    ("Storage", "Infrastructure", r"\bcloud storage\b|\bobject storage\b|\bstorage platform\b"),
    ("SaaS deployment", "Deployment", r"\bfully managed\b|\bSaaS\b"),
    ("Private cloud or VPC", "Deployment", r"\bprivate cloud\b|\byour VPC\b|\bVPC\b"),
    ("On-premises deployment", "Deployment", r"\bon[- ]prem(?:ises)?\b|\bself-hosted\b"),
    ("Open source", "Licensing", r"\bopen[- ]source\b"),
]


@dataclass
class FetchedPage:
    company_id: str
    company_name: str
    page_type: str
    requested_url: str
    final_url: str
    status: int
    title: str
    description: str
    text: str
    content_hash: str
    fetched_at: str
    raw_path: str
    text_path: str


def csv_write(path: Path, headers: list[str], rows: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=headers, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)


def read_csv(path: Path) -> list[dict[str, str]]:
    with path.open(encoding="utf-8", newline="") as stream:
        return list(csv.DictReader(stream))


def fetch(url: str, timeout: int = 25) -> tuple[int, str, str]:
    request = urllib.request.Request(
        url,
        headers={
            "User-Agent": USER_AGENT,
            "Accept": "text/html,application/xhtml+xml,text/plain;q=0.9,*/*;q=0.5",
            "Accept-Language": "en-US,en;q=0.8",
        },
    )
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            payload = response.read()
            charset = response.headers.get_content_charset() or "utf-8"
            return response.status, response.geturl(), payload.decode(charset, errors="replace")
    except urllib.error.HTTPError:
        # A few public marketing sites vary by TLS/HTTP client fingerprint.
        # Retry once with the system curl client rather than skipping the
        # company solely because Python's client was rejected.
        result = subprocess.run(
            [
                "curl",
                "-L",
                "--silent",
                "--show-error",
                "--max-time",
                str(timeout),
                "-A",
                USER_AGENT,
                "-w",
                "\n__STATUS__:%{http_code}\n__URL__:%{url_effective}",
                url,
            ],
            capture_output=True,
            text=True,
            timeout=timeout + 3,
            check=False,
        )
        marker = "\n__STATUS__:"
        if marker not in result.stdout:
            raise
        payload_text, meta = result.stdout.rsplit(marker, 1)
        status_text, final_url = meta.split("\n__URL__:", 1)
        status = int(status_text)
        if not 200 <= status < 300:
            raise urllib.error.HTTPError(url, status, "request rejected", None, None)
        return status, final_url.strip(), payload_text


def find_json_arrays(source: str, key: str) -> list[list | dict]:
    arrays: list[list | dict] = []
    marker = f'"{key}":['
    start = 0
    while True:
        marker_at = source.find(marker, start)
        if marker_at < 0:
            break
        begin = marker_at + len(marker)
        depth = 1
        quoted = False
        escaped = False
        for index in range(begin, len(source)):
            char = source[index]
            if quoted:
                if escaped:
                    escaped = False
                elif char == "\\":
                    escaped = True
                elif char == '"':
                    quoted = False
            else:
                if char == '"':
                    quoted = True
                elif char == "[":
                    depth += 1
                elif char == "]":
                    depth -= 1
                    if depth == 0:
                        try:
                            arrays.append(json.loads("[" + source[begin:index] + "]"))
                        except json.JSONDecodeError:
                            pass
                        start = index + 1
                        break
        else:
            break
    return arrays


def localized(value: object) -> str:
    if isinstance(value, dict):
        return str(value.get("en") or "").strip()
    return str(value or "").strip()


def scrape_event_data() -> tuple[list[dict], list[dict], list[dict]]:
    EVENT_DIR.mkdir(parents=True, exist_ok=True)
    _, agenda_url, agenda_html = fetch(EVENT_AGENDA_URL)
    _, speakers_url, speakers_html = fetch(EVENT_SPEAKERS_URL)
    (EVENT_DIR / "agenda.html").write_text(agenda_html, encoding="utf-8")
    (EVENT_DIR / "speakers.html").write_text(speakers_html, encoding="utf-8")

    agenda_arrays = find_json_arrays(agenda_html, "agenda")
    agenda_items = max(
        (item for item in agenda_arrays if item and isinstance(item[0], dict) and "tracks" in item[0]),
        key=len,
    )
    presentation_arrays = find_json_arrays(agenda_html, "presentations")
    presentations_by_id: dict[str, dict] = {}
    for collection in presentation_arrays:
        for presentation in collection:
            if not isinstance(presentation, dict) or "title" not in presentation:
                continue
            presentation_id = presentation.get("presentationId") or presentation.get("_id")
            if not presentation_id:
                continue
            existing = presentations_by_id.setdefault(presentation_id, {})
            for key, value in presentation.items():
                if key == "speakers":
                    existing[key] = sorted(
                        set(existing.get(key, [])) | set(value or [])
                    )
                elif value not in (None, "", [], {}):
                    existing[key] = value
    presentations = list(presentations_by_id.values())

    speaker_arrays = [
        *find_json_arrays(agenda_html, "speakers"),
        *find_json_arrays(speakers_html, "speakers"),
    ]
    speakers_by_id: dict[str, dict] = {}
    for collection in speaker_arrays:
        for speaker in collection:
            if not isinstance(speaker, dict) or not speaker.get("firstName"):
                continue
            speaker_id = speaker.get("speakerId") or speaker.get("_id")
            if speaker_id and len(speaker) > len(speakers_by_id.get(speaker_id, {})):
                speakers_by_id[speaker_id] = speaker
    speakers = list(speakers_by_id.values())

    track_by_presentation: dict[str, str] = {}
    for day in agenda_items:
        for track in day.get("tracks", []):
            track_name = localized(track.get("title"))
            for presentation in track.get("presentations", []):
                presentation_id = presentation.get("presentationId")
                if presentation_id:
                    track_by_presentation[presentation_id] = track_name

    speaker_by_id: dict[str, dict] = {}
    for speaker in speakers:
        speaker_id = speaker.get("speakerId") or speaker.get("_id")
        if not speaker_id:
            continue
        speaker_by_id[speaker_id] = speaker
        if speaker.get("_id"):
            speaker_by_id[speaker["_id"]] = speaker

    session_rows: list[dict] = []
    speaker_session_rows: list[dict] = []
    for presentation in presentations:
        session_id = presentation.get("presentationId") or presentation.get("_id")
        if not session_id:
            continue
        start = datetime.fromtimestamp(int(presentation["dateFrom"]) / 1000, TIMEZONE)
        end = datetime.fromtimestamp(int(presentation["dateTo"]) / 1000, TIMEZONE)
        title = localized(presentation.get("title"))
        description = localized(presentation.get("description"))
        format_name = "Session"
        title_lower = title.casefold()
        for candidate in ("panel", "workshop", "roundtable", "fireside"):
            if candidate in title_lower:
                format_name = candidate.title()
                break
        speaker_records = [
            speaker_by_id[sid]
            for sid in presentation.get("speakers", [])
            if sid in speaker_by_id
        ]
        speaker_names = [
            f"{speaker.get('firstName', '')} {speaker.get('lastName', '')}".strip()
            for speaker in speaker_records
        ]
        speaker_companies = [
            (speaker.get("speakerCompany") or {}).get("name", "").strip()
            for speaker in speaker_records
        ]
        session_rows.append(
            {
                "session_id": session_id,
                "title": title,
                "track": track_by_presentation.get(str(session_id), ""),
                "format": format_name,
                "date": start.strftime("%Y-%m-%d"),
                "start_time": start.strftime("%H:%M"),
                "end_time": end.strftime("%H:%M"),
                "duration_minutes": int((end - start).total_seconds() / 60),
                "description": description,
                "speaker_names": "; ".join(name for name in speaker_names if name),
                "speaker_companies": "; ".join(name for name in speaker_companies if name),
                "source_url": agenda_url,
                "source_checked_at": CHECKED_AT,
            }
        )
        for speaker in speaker_records:
            sid = speaker.get("speakerId") or speaker.get("_id")
            name = f"{speaker.get('firstName', '')} {speaker.get('lastName', '')}".strip()
            speaker_session_rows.append(
                {
                    "speaker_id": sid,
                    "session_id": session_id,
                    "speaker_name": name,
                    "company": (speaker.get("speakerCompany") or {}).get("name", ""),
                    "session_title": title,
                }
            )

    seen_speakers: set[str] = set()
    speaker_rows: list[dict] = []
    for speaker in speakers:
        speaker_id = speaker.get("speakerId") or speaker.get("_id")
        if not speaker_id or speaker_id in seen_speakers:
            continue
        seen_speakers.add(speaker_id)
        first_name = str(speaker.get("firstName") or "").strip()
        last_name = str(speaker.get("lastName") or "").strip()
        slug = str(speaker.get("slug") or "").strip()
        speaker_rows.append(
            {
                "speaker_id": speaker_id,
                "first_name": first_name,
                "last_name": last_name,
                "speaker_name": f"{first_name} {last_name}".strip(),
                "position": str(speaker.get("position") or "").strip(),
                "company": (speaker.get("speakerCompany") or {}).get("name", "").strip(),
                "linkedin_url": str(speaker.get("linkedin") or "").strip(),
                "website": str(speaker.get("website") or "").strip(),
                "bio": localized(speaker.get("description")),
                "profile_url": (
                    f"https://world.aiacceleratorinstitute.com/location/boston/speaker/{slug}"
                    if slug
                    else speakers_url
                ),
                "source_checked_at": CHECKED_AT,
            }
        )

    session_rows.sort(key=lambda row: (row["date"], row["start_time"], row["track"], row["title"]))
    speaker_rows.sort(key=lambda row: row["speaker_name"].casefold())
    speaker_session_rows.sort(key=lambda row: (row["speaker_name"].casefold(), row["session_title"]))
    return session_rows, speaker_rows, speaker_session_rows


def parse_html_page(source: str, page_url: str) -> tuple[str, str, str, list[tuple[str, str]]]:
    document = lxml_html.fromstring(source)
    for node in document.xpath("//script|//style|//noscript|//svg"):
        node.drop_tree()
    title = " ".join(document.xpath("//title//text()")).strip()
    description = ""
    for selector in (
        '//meta[translate(@name,"ABCDEFGHIJKLMNOPQRSTUVWXYZ","abcdefghijklmnopqrstuvwxyz")="description"]/@content',
        '//meta[translate(@property,"ABCDEFGHIJKLMNOPQRSTUVWXYZ","abcdefghijklmnopqrstuvwxyz")="og:description"]/@content',
    ):
        values = document.xpath(selector)
        if values:
            description = html.unescape(values[0]).strip()
            break
    roots = document.xpath("//main|//article")
    if not roots:
        roots = document.xpath("//body")
    text_parts: list[str] = []
    for root in roots:
        for value in root.itertext():
            cleaned = re.sub(r"\s+", " ", html.unescape(value)).strip()
            if cleaned:
                text_parts.append(cleaned)
    text = "\n".join(dict.fromkeys(text_parts))
    links: list[tuple[str, str]] = []
    for anchor in document.xpath("//a[@href]"):
        href = urllib.parse.urljoin(page_url, anchor.get("href", ""))
        label = re.sub(r"\s+", " ", " ".join(anchor.itertext())).strip()
        if href.startswith(("http://", "https://")):
            links.append((href, label))
    return title, description, text, links


def choose_company_pages(home_url: str, links: list[tuple[str, str]]) -> list[tuple[str, str]]:
    home = urllib.parse.urlparse(home_url)
    scored: list[tuple[int, str, str]] = []
    seen: set[str] = set()
    blocked = re.compile(
        r"login|signin|sign-in|account|careers|jobs|cookie|privacy|terms|legal|"
        r"contact|support/|blog|news|press|events?|webinar|partner|affiliate",
        re.IGNORECASE,
    )
    wanted = re.compile(
        r"product|platform|solution|feature|security|trust|governance|integration|"
        r"agent|enterprise|pricing|how-it-works|technology",
        re.IGNORECASE,
    )
    for href, label in links:
        parsed = urllib.parse.urlparse(href)
        if parsed.netloc and parsed.netloc != home.netloc:
            continue
        clean = urllib.parse.urldefrag(href)[0].rstrip("/")
        if clean in seen or clean.rstrip("/") == home_url.rstrip("/"):
            continue
        if blocked.search(clean):
            continue
        combined = f"{parsed.path} {label}"
        score = 0
        for weight, term in enumerate(
            ("product", "platform", "security", "trust", "governance", "solution", "feature", "integration", "agent"),
            start=1,
        ):
            if term in combined.casefold():
                score += weight
        if not wanted.search(combined):
            continue
        seen.add(clean)
        scored.append((score, clean, label or parsed.path))
    scored.sort(key=lambda item: (-item[0], item[1]))
    return [(url, label) for _, url, label in scored[:2]]


@dataclass
class RobotsPolicy:
    rules: list[tuple[str, bool]]
    delay: float

    def can_fetch(self, url: str) -> bool:
        parsed = urllib.parse.urlsplit(url)
        path = parsed.path or "/"
        if parsed.query:
            path += f"?{parsed.query}"
        matched: tuple[int, bool] | None = None
        for pattern, allowed in self.rules:
            anchored = pattern.endswith("$")
            raw = pattern[:-1] if anchored else pattern
            regex = "^" + re.escape(raw).replace(r"\*", ".*")
            if anchored:
                regex += "$"
            if re.match(regex, path):
                candidate = (len(raw), allowed)
                if matched is None or candidate[0] > matched[0] or (
                    candidate[0] == matched[0] and not candidate[1]
                ):
                    matched = candidate
        return True if matched is None else matched[1]


def robots_for(url: str) -> tuple[RobotsPolicy, float]:
    parsed = urllib.parse.urlparse(url)
    robots_url = f"{parsed.scheme}://{parsed.netloc}/robots.txt"
    try:
        _, _, text = fetch(robots_url, timeout=10)
    except Exception:
        text = ""

    groups: list[dict] = [{"agents": [], "rules": [], "delay": None}]
    current = groups[0]
    for raw_line in text.splitlines():
        line = raw_line.split("#", 1)[0].strip()
        if not line or ":" not in line:
            continue
        key, value = (part.strip() for part in line.split(":", 1))
        key = key.casefold()
        if key == "user-agent":
            if current["rules"] or current["delay"] is not None:
                current = {"agents": [], "rules": [], "delay": None}
                groups.append(current)
            current["agents"].append(value.casefold())
        elif key in {"allow", "disallow"}:
            if value:
                current["rules"].append((value, key == "allow"))
        elif key == "crawl-delay":
            try:
                current["delay"] = float(value)
            except ValueError:
                pass

    ua = USER_AGENT.casefold()
    exact = [
        group
        for group in groups
        if group["agents"]
        and "*" not in group["agents"]
        and any(agent and agent in ua for agent in group["agents"])
    ]
    wildcard = [group for group in groups if "*" in group["agents"]]
    selected = exact or wildcard
    rules = [rule for group in selected for rule in group["rules"]]
    delays = [group["delay"] for group in selected if group["delay"] is not None]
    delay = min(min(delays) if delays else 1.0, 10.0)
    return RobotsPolicy(rules, delay), delay


def crawl_company(entry: dict[str, str]) -> tuple[dict, list[dict], list[FetchedPage]]:
    company_id = entry["exhibitor_id"]
    company_name = entry["exhibitor_name"]
    home_url = entry["website"].strip()
    company_dir = COMPANY_DIR / company_id
    raw_dir = company_dir / "raw"
    text_dir = company_dir / "clean"
    raw_dir.mkdir(parents=True, exist_ok=True)
    text_dir.mkdir(parents=True, exist_ok=True)
    pages: list[FetchedPage] = []
    sources: list[dict] = []
    status = "ok"

    if not home_url:
        return (
            {
                "company_id": company_id,
                "company_name": company_name,
                "website": "",
                "site_title": "",
                "site_description": "",
                "pages_crawled": 0,
                "crawl_status": "no_website",
                "fetched_at": CHECKED_AT,
            },
            sources,
            pages,
        )

    try:
        parser, delay = robots_for(home_url)
        if not parser.can_fetch(home_url):
            return (
                {
                    "company_id": company_id,
                    "company_name": company_name,
                    "website": home_url,
                    "site_title": "",
                    "site_description": "",
                    "pages_crawled": 0,
                    "crawl_status": "robots_disallowed",
                    "fetched_at": CHECKED_AT,
                },
                sources,
                pages,
            )
        time.sleep(delay)
        status_code, final_url, source = fetch(home_url)
        title, description, text, links = parse_html_page(source, final_url)
        if len(text) < 100:
            text = f"{description}\n{text}".strip()
        pages_to_fetch = [
            ("/", home_url, final_url, title, description, status_code, source, text)
        ]
        for candidate_url, label in choose_company_pages(home_url, links):
            if not parser.can_fetch(candidate_url):
                continue
            time.sleep(delay)
            try:
                child_status, child_final_url, child_source = fetch(candidate_url)
                child_title, child_description, child_text, _ = parse_html_page(
                    child_source, child_final_url
                )
                if len(child_text) < 100:
                    child_text = f"{child_description}\n{child_text}".strip()
                pages_to_fetch.append(
                    (
                        label or urllib.parse.urlparse(candidate_url).path,
                        candidate_url,
                        child_final_url,
                        child_title,
                        child_description,
                        child_status,
                        child_source,
                        child_text,
                    )
                )
            except Exception:
                continue

        for index, (
            page_label,
            requested_url,
            resolved_url,
            page_title,
            page_description,
            page_status,
            raw,
            clean,
        ) in enumerate(pages_to_fetch):
            slug = re.sub(r"[^a-z0-9]+", "-", page_label.casefold()).strip("-") or f"page-{index + 1}"
            raw_path = raw_dir / f"{index + 1:02d}-{slug[:50]}.html"
            text_path = text_dir / f"{index + 1:02d}-{slug[:50]}.txt"
            raw_path.write_text(raw, encoding="utf-8")
            text_path.write_text(clean, encoding="utf-8")
            digest = hashlib.sha256(raw.encode("utf-8")).hexdigest()
            page = FetchedPage(
                company_id=company_id,
                company_name=company_name,
                page_type=page_label,
                requested_url=requested_url,
                final_url=resolved_url,
                status=page_status,
                title=page_title,
                description=page_description,
                text=clean,
                content_hash=digest,
                fetched_at=CHECKED_AT,
                raw_path=str(raw_path.relative_to(ROOT)),
                text_path=str(text_path.relative_to(ROOT)),
            )
            pages.append(page)
            sources.append(
                {
                    "company_id": company_id,
                    "company_name": company_name,
                    "source_url": resolved_url,
                    "page_type": page_label,
                    "page_title": page_title,
                    "description": page_description,
                    "char_count": len(clean),
                    "content_sha256": digest,
                    "http_status": page_status,
                    "fetched_at": CHECKED_AT,
                    "raw_path": page.raw_path,
                    "text_path": page.text_path,
                }
            )
        print(f"[site] {company_id}: {len(pages)} page(s)", flush=True)
    except Exception as error:
        status = f"error: {type(error).__name__}"
        print(f"[site] {company_id}: {status}", flush=True)

    first = pages[0] if pages else None
    return (
        {
            "company_id": company_id,
            "company_name": company_name,
            "website": home_url,
            "site_title": first.title if first else "",
            "site_description": first.description if first else "",
            "pages_crawled": len(pages),
            "crawl_status": status,
            "fetched_at": CHECKED_AT,
        },
        sources,
        pages,
    )


def split_sentences(text: str) -> list[str]:
    normalized = re.sub(r"\s+", " ", text).strip()
    return [
        sentence.strip()
        for sentence in re.split(r"(?<=[.!?])\s+(?=[A-Z0-9])", normalized)
        if 35 <= len(sentence.strip()) <= 600
    ]


def first_support_quote(text: str, pattern: re.Pattern[str]) -> str:
    matches = [sentence for sentence in split_sentences(text) if pattern.search(sentence)]
    if matches:
        return max(matches, key=lambda sentence: len(pattern.findall(sentence)))
    match = pattern.search(text)
    if match:
        start = max(0, match.start() - 180)
        end = min(len(text), match.end() + 260)
        return re.sub(r"\s+", " ", text[start:end]).strip()
    return ""


def extract_capabilities(
    profiles: list[dict],
    pages: list[FetchedPage],
    documents: list[dict],
) -> list[dict]:
    rules = [(label, category, re.compile(pattern, re.IGNORECASE)) for label, category, pattern in CAPABILITY_RULES]
    rows: list[dict] = []
    seen: set[tuple[str, str, str]] = set()

    for company_id in sorted({page.company_id for page in pages}):
        company_pages = [page for page in pages if page.company_id == company_id]
        for label, category, pattern in rules:
            page = next((item for item in company_pages if pattern.search(item.text)), None)
            if page is None:
                continue
            quote = first_support_quote(page.text, pattern)
            if not quote:
                continue
            key = (company_id, label.casefold(), "company_website")
            if key in seen:
                continue
            seen.add(key)
            capability_id = hashlib.sha1("|".join(key + (quote,)).encode("utf-8")).hexdigest()
            rows.append(
                {
                    "capability_id": capability_id,
                    "company_id": company_id,
                    "company_name": next(
                        profile["company_name"] for profile in profiles if profile["company_id"] == company_id
                    ),
                    "capability": label,
                    "category": category,
                    "claim_type": "vendor_stated",
                    "evidence_source": "company_website",
                    "evidence_quote": quote,
                    "source_url": page.final_url,
                    "source_page": "",
                    "captured_at": CHECKED_AT,
                    "review_status": "unreviewed",
                }
            )

    for document in documents:
        markdown_path = DATA_DIR / "extracted" / document["extracted_markdown"]
        if not markdown_path.is_file():
            continue
        markdown = markdown_path.read_text(encoding="utf-8")
        pages_text = re.split(r"(?m)^## Page (\d+)\s*$", markdown)
        for index in range(1, len(pages_text), 2):
            page_number = pages_text[index]
            page_text = re.sub(
                r"<!--.*?-->",
                " ",
                pages_text[index + 1],
                flags=re.DOTALL,
            )
            for label, category, pattern in rules:
                quote = first_support_quote(page_text, pattern)
                if not quote:
                    continue
                key = (
                    document["exhibitor_id"],
                    label.casefold(),
                    f"flyer:{document['doc_id']}:{page_number}",
                )
                if key in seen:
                    continue
                seen.add(key)
                capability_id = hashlib.sha1("|".join(key + (quote,)).encode("utf-8")).hexdigest()
                rows.append(
                    {
                        "capability_id": capability_id,
                        "company_id": document["exhibitor_id"],
                        "company_name": document["exhibitor_name"],
                        "capability": label,
                        "category": category,
                        "claim_type": "flyer_copy",
                        "evidence_source": "conference_flyer",
                        "evidence_quote": quote,
                        "source_url": f"/sources/{document['doc_id']}#page={page_number}",
                        "source_page": page_number,
                        "captured_at": CHECKED_AT,
                        "review_status": "source_verified",
                    }
                )

    rows.sort(
        key=lambda row: (
            row["company_name"].casefold(),
            row["category"],
            row["capability"],
            row["evidence_source"],
        )
    )
    return rows


def write_site_corpus(pages: list[FetchedPage]) -> None:
    chunks = [
        "# Company website evidence",
        "",
        "Public company website pages captured for the conference directory. "
        "These are vendor-stated claims, not independently verified facts.",
        "",
    ]
    for page in sorted(pages, key=lambda item: (item.company_name.casefold(), item.requested_url)):
        chunks.extend(
            [
                f"## {page.company_name} - {page.page_type}",
                "",
                f"Source: {page.final_url}",
                f"Captured: {page.fetched_at}",
                f"Content hash: {page.content_hash}",
                "",
                page.text,
                "",
            ]
        )
    (DATA_DIR / "company_site_text.md").write_text("\n".join(chunks), encoding="utf-8")


def main() -> None:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    print("Fetching official agenda and speaker data...", flush=True)
    sessions, speakers, speaker_sessions = scrape_event_data()
    csv_write(
        DATA_DIR / "sessions.csv",
        list(sessions[0]),
        sessions,
    )
    csv_write(
        DATA_DIR / "speakers.csv",
        list(speakers[0]),
        speakers,
    )
    csv_write(
        DATA_DIR / "speaker_sessions.csv",
        list(speaker_sessions[0]),
        speaker_sessions,
    )
    print(
        f"Official event data: {len(sessions)} sessions, {len(speakers)} speakers, "
        f"{len(speaker_sessions)} speaker-session links",
        flush=True,
    )

    exhibitors = read_csv(DATA_DIR / "exhibitors.csv")
    documents = read_csv(DATA_DIR / "exhibitor_documents.csv")
    profiles: list[dict] = []
    sources: list[dict] = []
    pages: list[FetchedPage] = []
    with ThreadPoolExecutor(max_workers=4) as executor:
        futures = {executor.submit(crawl_company, entry): entry for entry in exhibitors}
        for future in as_completed(futures):
            profile, company_sources, company_pages = future.result()
            profiles.append(profile)
            sources.extend(company_sources)
            pages.extend(company_pages)

    profiles.sort(key=lambda row: row["company_name"].casefold())
    sources.sort(key=lambda row: (row["company_name"].casefold(), row["source_url"]))
    csv_write(
        DATA_DIR / "company_profiles.csv",
        [
            "company_id",
            "company_name",
            "website",
            "site_title",
            "site_description",
            "pages_crawled",
            "crawl_status",
            "fetched_at",
        ],
        profiles,
    )
    csv_write(
        DATA_DIR / "company_sources.csv",
        [
            "company_id",
            "company_name",
            "source_url",
            "page_type",
            "page_title",
            "description",
            "char_count",
            "content_sha256",
            "http_status",
            "fetched_at",
            "raw_path",
            "text_path",
        ],
        sources,
    )
    write_site_corpus(pages)
    capabilities = extract_capabilities(profiles, pages, documents)
    csv_write(
        DATA_DIR / "capabilities.csv",
        [
            "capability_id",
            "company_id",
            "company_name",
            "capability",
            "category",
            "claim_type",
            "evidence_source",
            "evidence_quote",
            "source_url",
            "source_page",
            "captured_at",
            "review_status",
        ],
        capabilities,
    )
    success_count = sum(1 for profile in profiles if profile["pages_crawled"] > 0)
    print(
        f"Company sites: {success_count}/{len(profiles)} reachable, "
        f"{len(sources)} pages, {len(capabilities)} capability claims",
        flush=True,
    )


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        sys.exit(130)
