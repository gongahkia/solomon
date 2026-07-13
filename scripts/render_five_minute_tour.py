# SPDX-License-Identifier: Apache-2.0

from __future__ import annotations

import argparse
import shutil
import subprocess  # nosec B404
import tempfile
from dataclasses import dataclass
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont, ImageOps

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_OUTPUT = ROOT / "docs/assets/solomon-five-minute-tour.mp4"
DEFAULT_CAPTIONS = ROOT / "docs/assets/solomon-five-minute-tour.vtt"
FRAME_SIZE = (1280, 720)


@dataclass(frozen=True)
class Chapter:
    title: str
    caption: str
    narration: str
    asset: str


def _narration(text: str) -> str:
    return " ".join(text.split())


def _executable(name: str) -> str:
    path = shutil.which(name)
    if path is None:
        raise RuntimeError(f"required executable not found: {name}")
    return path


CHAPTERS = (
    Chapter(
        "Solomon in five minutes",
        "Currency infrastructure for verified legal knowledge",
        _narration(
            """
            This is Solomon, currency infrastructure for verified legal knowledge. It helps a firm answer a narrow but
            important operational question before knowledge is reused: is this position current for this matter, what
            does it depend on, and what evidence supports that answer? Solomon is not a legal adviser, a research
            database, or a drafting copilot. It records the currency of internal knowledge so a lawyer or compatible
            MCP host can make a reviewable decision about reuse.
            """
        ),
        "docs/assets/solomon-icon.svg",
    ),
    Chapter(
        "The problem is not retrieval alone",
        "A useful memo can still be unsafe to reuse",
        _narration(
            """
            Firm knowledge is valuable because it captures prior analysis, clauses, playbooks, and advice. Search can
            find that work product. But search alone cannot tell us whether an authority moved, a later internal view
            superseded it, a lawyer challenged it, or a matter boundary makes reuse inappropriate. A confident answer
            built on a stale memo is worse than an honest uncertainty. Solomon keeps the evidence path visible instead
            of treating retrieved text as automatically current.
            """
        ),
        "docs/assets/stale-house-view-demo.gif",
    ),
    Chapter(
        "Start with a knowledge record",
        "Provenance, valid time, ingestion time, scope, and verification",
        _narration(
            """
            Each Solomon knowledge item is an internal claim with provenance, valid time, ingestion time, matter and
            client scope, a verification state, and a credence tier. The system preserves history rather than
            overwriting it. A position may be live, stale pending reverification, superseded, retired, or contested.
            Those states are explicit workflow signals. They do not decide whether the law is right. They make sure an
            old answer is not silently presented as a current one.
            """
        ),
        "docs/assets/console/audit-pack.png",
    ),
    Chapter(
        "Model dependencies as evidence",
        "Internal positions can depend on authorities and other positions",
        _narration(
            """
            A curator links a position to the authorities, clauses, guidance, or internal positions that support it.
            Solomon stores those links as a directed dependency graph with evidence and review information. This is
            deliberately different from a keyword association. A dependency gives the system a reason to revisit a
            downstream position when a recorded authority changes. The graph can also show the dependents of an
            authority, so a reviewer sees which positions need attention rather than guessing where an old rule was
            used.
            """
        ),
        "docs/assets/console/dependency-review.png",
    ),
    Chapter(
        "When an authority moves",
        "Solomon propagates a review obligation, not a legal conclusion",
        _narration(
            """
            When an authority change is recorded, Solomon walks the dependency graph and marks affected positions stale
            pending reverification. The signal propagates through transitive dependents, with the source event and
            reason retained for review. This is not automatic legal adjudication. It is a fail-safe routing decision:
            do not reuse the affected material by default until a qualified person has checked it. The stale-house-view
            demonstration shows the difference between returning an old memo without context and returning the same
            memo with a clear reason to verify it.
            """
        ),
        "docs/assets/stale-house-view-demo.gif",
    ),
    Chapter(
        "Use the verification desk",
        "Assign, inspect evidence, reaffirm, supersede, retire, or pin",
        _narration(
            """
            The curator console presents review-required positions in a verification desk. A partner or reviewer can
            inspect the currency explanation, dependencies, provenance, verification history, and audit evidence before
            deciding how to proceed. Reaffirmation records that the position remains usable. Supersession preserves the
            predecessor and links a new position. Retirement removes a position from normal reuse without deleting
            history. Pinning sets a firm-authoritative credence floor. Every action is a human decision with an
            evidence reference, not an automated legal outcome.
            """
        ),
        "docs/assets/console/verification-desk.png",
    ),
    Chapter(
        "Protect the model boundary",
        "Review, minimise, pseudonymise, and fail closed",
        _narration(
            """
            Before Solomon stores or exposes model-bound context, its boundary inspects the route and applies policy.
            The default local posture keeps remote egress disabled. Where a deployment permits an approved remote
            endpoint, the boundary can pseudonymise supported identifiers and retains mappings only for the narrow
            reidentification step. A boundary failure stops ingestion or model egress instead of silently continuing.
            This reduces uncontrolled context flow, but it does not guarantee that content is safe, satisfy
            confidentiality duties, or replace a firm's vendor and matter review.
            """
        ),
        "docs/assets/stale-house-view-demo.gif",
    ),
    Chapter(
        "Give MCP hosts current context",
        "Preflight context excludes stale firm material by default",
        _narration(
            """
            Solomon's primary surface is MCP. Before a host assembles a prompt, it can call preflight context for the
            matter and client scope. Live positions are returned with currency metadata. Stale, superseded, retired,
            and contested positions are withheld from normal reuse, while the host can still call currency, why,
            impact, and audit tools to explain the decision. The vendor-integration scenario uses a deterministic mock
            host to show the important behavior: after a dependency changes, stale firm text is not injected into the
            draft.
            """
        ),
        "docs/assets/vendor-integration-demo.gif",
    ),
    Chapter(
        "Keep an audit trail without copying content",
        "Hash-chained metadata supports reconstruction and review",
        _narration(
            """
            Solomon records metadata-only audit evidence for important events: provenance, verification, boundary
            decisions, endpoint choices, primitive-plan hashes, dependency impact, and audit-pack exports. The journal
            is hash chained and can be verified before export. An audit pack gives a reviewer the evidence needed to
            understand why Solomon treated a position as current or review-required at a point in time. That evidence
            supports governance and investigation, but it is not a compliance certificate and it does not prove that a
            lawyer's substantive conclusion was correct.
            """
        ),
        "docs/assets/console/audit-pack.png",
    ),
    Chapter(
        "Report the impact to partners",
        "Currency reports turn events into a review queue",
        _narration(
            """
            A currency report groups movements such as stale positions, supersessions, retirements, and contradictions
            for a firm, practice area, or matter. It identifies the item, the triggering authority or dependency,
            current state, verification status, and downstream impact. The report is designed to make a review
            conversation concrete: what moved, what client work might be affected, and who must re-verify it? It does
            not replace a firm's matter management process or decide materiality on its own.
            """
        ),
        "docs/assets/console/verification-desk.png",
    ),
    Chapter(
        "Exercise realistic scenarios",
        "Vendor, Big Law, in-house GC, and boutique workflows",
        _narration(
            """
            The repository includes deterministic scenarios that exercise the same workflow at different operating
            scales. A fictional vendor host omits stale text before drafting. A Singapore Big Law scenario marks seven
            dependent banking memos for review after a recorded authority change. An in-house GC scenario stales twelve
            NDA clauses and keeps them out of a Copilot-like preflight result. A boutique scenario shows a sparse
            dependency graph and local Compose console path. They are demonstrations of currency controls, not
            statements of current law or endorsements by any named vendor or firm.
            """
        ),
        "docs/assets/vendor-integration-demo.gif",
    ),
    Chapter(
        "Use Solomon as a control plane",
        "Flag uncertainty, preserve evidence, keep lawyers in control",
        _narration(
            """
            Solomon's value is disciplined reuse. It helps a firm make current context available, flag a moved
            dependency, preserve the path to evidence, and route human verification where it belongs. The system
            deliberately leaves legal judgement, professional responsibility, deployment approvals, confidentiality
            analysis, retention, and client instructions with the firm and its lawyers. To explore further, install the
            MCP server, run the stale-house-view scenario, inspect the curator console, and review the technical
            whitepaper, boundary checklist, and known limitations linked from the repository documentation.
            """
        ),
        "docs/assets/console/dependency-review.png",
    ),
)


def _font(size: int) -> ImageFont.FreeTypeFont | ImageFont.ImageFont:
    for path in ("/System/Library/Fonts/Supplemental/Arial.ttf", "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf"):
        if Path(path).exists():
            return ImageFont.truetype(path, size)
    return ImageFont.load_default()


def _run(args: list[str]) -> None:
    subprocess.run(args, check=True)  # noqa: S603  # nosec B603


def _duration(path: Path, ffprobe: str) -> float:
    completed = subprocess.run(  # noqa: S603  # nosec B603
        [ffprobe, "-v", "error", "-show_entries", "format=duration", "-of", "default=nk=1:nw=1", str(path)],
        check=True,
        capture_output=True,
        text=True,
    )
    return float(completed.stdout.strip())


def _lines(text: str, width: int) -> list[str]:
    words = text.split()
    lines: list[str] = []
    current = ""
    for word in words:
        candidate = f"{current} {word}".strip()
        if len(candidate) > width and current:
            lines.append(current)
            current = word
        else:
            current = candidate
    if current:
        lines.append(current)
    return lines


def _asset(path: Path) -> Image.Image:
    if path.suffix == ".svg":
        icon = Image.new("RGB", (540, 540), "#0f172a")
        draw = ImageDraw.Draw(icon)
        draw.ellipse((105, 105, 435, 435), fill="#0ea5e9")
        draw.ellipse((165, 165, 375, 375), fill="#e0f2fe")
        draw.line((270, 190, 270, 350), fill="#0f172a", width=18)
        draw.line((190, 270, 350, 270), fill="#0f172a", width=18)
        return icon
    image = Image.open(path)
    image.seek(0)
    return image.convert("RGB")


def _slide(chapter: Chapter, destination: Path) -> None:
    image = Image.new("RGB", FRAME_SIZE, "#071426")
    draw = ImageDraw.Draw(image)
    title_font = _font(42)
    caption_font = _font(27)
    label_font = _font(20)
    body_font = _font(18)
    draw.rectangle((0, 0, FRAME_SIZE[0], 86), fill="#0f243f")
    draw.text((48, 27), "SOLOMON · FIVE-MINUTE TOUR", fill="#bae6fd", font=label_font)
    draw.rounded_rectangle((42, 126, 600, 662), radius=20, fill="#102b4c")
    draw.rounded_rectangle((642, 126, 1238, 662), radius=20, fill="#0b1f36")
    y = 166
    for line in _lines(chapter.title, 24):
        draw.text((82, y), line, fill="#f8fafc", font=title_font)
        y += 54
    y += 22
    for line in _lines(chapter.caption, 38):
        draw.text((82, y), line, fill="#7dd3fc", font=caption_font)
        y += 39
    y += 28
    for line in _lines(chapter.narration, 48):
        draw.text((82, y), line, fill="#dbeafe", font=body_font)
        y += 25
    asset = ImageOps.contain(_asset(ROOT / chapter.asset), (530, 430), Image.Resampling.LANCZOS)
    x = 642 + (596 - asset.width) // 2
    y = 126 + (536 - asset.height) // 2
    image.paste(asset, (x, y))
    image.save(destination)


def _timestamp(value: float) -> str:
    milliseconds = round(value * 1000)
    hours, remainder = divmod(milliseconds, 3_600_000)
    minutes, remainder = divmod(remainder, 60_000)
    seconds, milliseconds = divmod(remainder, 1000)
    return f"{hours:02}:{minutes:02}:{seconds:02}.{milliseconds:03}"


def _captions(chapters: list[Chapter], durations: list[float], destination: Path) -> None:
    offset = 0.0
    cues = ["WEBVTT", ""]
    for index, (chapter, duration) in enumerate(zip(chapters, durations, strict=True), start=1):
        cues.extend(
            (
                str(index),
                f"{_timestamp(offset)} --> {_timestamp(offset + duration)}",
                chapter.title,
                chapter.caption,
                "",
            )
        )
        offset += duration
    destination.write_text("\n".join(cues), encoding="utf-8")


def render(output: Path, captions: Path, *, voice: str, rate: int) -> float:
    output.parent.mkdir(parents=True, exist_ok=True)
    captions.parent.mkdir(parents=True, exist_ok=True)
    say = _executable("say")
    ffmpeg = _executable("ffmpeg")
    ffprobe = _executable("ffprobe")
    with tempfile.TemporaryDirectory(prefix="solomon-tour-") as raw:
        work = Path(raw)
        segments: list[Path] = []
        durations: list[float] = []
        for index, chapter in enumerate(CHAPTERS, start=1):
            slide = work / f"{index:02}.png"
            text = work / f"{index:02}.txt"
            audio = work / f"{index:02}.aiff"
            segment = work / f"{index:02}.mp4"
            _slide(chapter, slide)
            text.write_text(chapter.narration, encoding="utf-8")
            _run([say, "-v", voice, "-r", str(rate), "-f", str(text), "-o", str(audio)])
            _run(
                [
                    ffmpeg,
                    "-y",
                    "-loglevel",
                    "error",
                    "-loop",
                    "1",
                    "-framerate",
                    "30",
                    "-i",
                    str(slide),
                    "-i",
                    str(audio),
                    "-c:v",
                    "libx264",
                    "-crf",
                    "22",
                    "-tune",
                    "stillimage",
                    "-pix_fmt",
                    "yuv420p",
                    "-c:a",
                    "aac",
                    "-b:a",
                    "128k",
                    "-shortest",
                    str(segment),
                ]
            )
            segments.append(segment)
            durations.append(_duration(segment, ffprobe))
        manifest = work / "segments.txt"
        manifest.write_text("".join(f"file '{segment}'\n" for segment in segments), encoding="utf-8")
        _run(
            [
                ffmpeg,
                "-y",
                "-loglevel",
                "error",
                "-f",
                "concat",
                "-safe",
                "0",
                "-i",
                str(manifest),
                "-c",
                "copy",
                "-movflags",
                "+faststart",
                str(output),
            ]
        )
        _captions(list(CHAPTERS), durations, captions)
        return sum(durations)


def main() -> int:
    parser = argparse.ArgumentParser(description="Render Solomon's narrated five-minute tour.")
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--captions", type=Path, default=DEFAULT_CAPTIONS)
    parser.add_argument("--voice", default="Samantha")
    parser.add_argument("--rate", type=int, default=242)
    args = parser.parse_args()
    duration = render(args.output, args.captions, voice=args.voice, rate=args.rate)
    print(f"{args.output}: {duration:.1f}s")
    print(args.captions)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
