"""
Slack integration for RedCouncil.

Deliberately reuses `council_graph` from app/graph.py directly rather than
calling the HTTP API — same engine, different presentation layer, exactly
like the web portal. This is the pattern to follow for any future channel
(e.g. Teams, email digest): wrap the graph, don't fork the logic.

Flow:
  1. A user runs `/redcouncil <decision text>` in Slack.
  2. We post one message immediately ("Convening the council...") and then
     edit that same message in place as agents complete, using chat.update —
     so the channel doesn't get spammed with 12 separate messages per run.
  3. The final edit renders the full verdict as Slack Block Kit, with the
     rubber-stamp verdict (approved / conditions / blocked) as the most
     visually prominent element, mirroring the web portal's signature moment.

Run locally with Socket Mode (no public URL needed):
    python -m app.integrations.slack_bot

For production, mount a `/slack/events` route on the same FastAPI app
instead of Socket Mode — see the commented alternative at the bottom of this
file.
"""

from __future__ import annotations

import logging

from slack_bolt.async_app import AsyncApp
from slack_bolt.adapter.socket_mode.async_handler import AsyncSocketModeHandler

from app.config import settings
from app.graph import council_graph
from app.models import DecisionInput, VulnerabilityReport

logger = logging.getLogger("redcouncil.slack")

slack_app = AsyncApp(token=settings.slack_bot_token, signing_secret=settings.slack_signing_secret)

_STAMP_BY_RECOMMENDATION = {
    "approved": ("✅ APPROVED", "#2E7D32"),
    "approved_with_conditions": ("⚠️ APPROVED — WITH CONDITIONS", "#B8860B"),
    "blocked": ("⛔ BLOCKED", "#B71C1C"),
}


@slack_app.command("/redcouncil")
async def handle_redcouncil_command(ack, respond, command, client):
    await ack()
    decision_text = command["text"].strip()

    if len(decision_text) < 10:
        await respond("Give the council something to review — e.g. `/redcouncil launch a $49/mo tier with no free trial`")
        return

    posted = await client.chat_postMessage(
        channel=command["channel_id"],
        text="🏛️ Convening the council...",
        blocks=_status_blocks(decision_text, {}),
    )
    channel, ts = posted["channel"], posted["ts"]

    decision_input = DecisionInput(decision_text=decision_text)
    initial_state = {"decision_id": ts, "decision": decision_input, "events": []}

    agent_status: dict[str, str] = {role: "idle" for role in ["growth", "risk", "legal", "tech_debt", "customer"]}
    last_emitted = 0
    final_state = None

    try:
        async for state in council_graph.astream(initial_state, stream_mode="values"):
            events = state.get("events", [])
            for event in events[last_emitted:]:
                _apply_event_to_status(agent_status, event)
            last_emitted = len(events)
            final_state = state

            # Throttle edits to avoid Slack rate limits — only re-render on
            # the events that actually change what's visible.
            if events and events[-1]["type"] in {"agent_completed", "conflict_detected", "round_2_started", "synthesis_started"}:
                await client.chat_update(
                    channel=channel, ts=ts, text="🏛️ Council in session...",
                    blocks=_status_blocks(decision_text, agent_status),
                )

        report: VulnerabilityReport | None = final_state.get("report") if final_state else None
        if report is None:
            raise RuntimeError("Graph completed without a report")

        await client.chat_update(
            channel=channel, ts=ts, text="🏛️ Council verdict is in.",
            blocks=_report_blocks(report),
        )

    except Exception as exc:  # noqa: BLE001
        logger.exception("Slack council run failed")
        await client.chat_update(
            channel=channel, ts=ts,
            text="The council hit an error.",
            blocks=[{"type": "section", "text": {"type": "mrkdwn", "text": f"⚠️ The council hit an error: `{exc}`"}}],
        )


def _apply_event_to_status(agent_status: dict[str, str], event: dict) -> None:
    payload = event.get("payload", {})
    if event["type"] == "agent_started":
        agent_status[payload["agent"]] = f"thinking (round {payload['round']})"
    elif event["type"] == "agent_completed":
        agent_status[payload["agent"]] = f"done (round {payload['round']})"


def _status_blocks(decision_text: str, agent_status: dict[str, str]) -> list[dict]:
    lines = [f"*{role.replace('_', ' ').title()}:* {status}" for role, status in agent_status.items()] or ["Seating the council..."]
    return [
        {"type": "header", "text": {"type": "plain_text", "text": "🏛️ RedCouncil is reviewing this decision"}},
        {"type": "section", "text": {"type": "mrkdwn", "text": f"*Decision:*\n> {decision_text}"}},
        {"type": "divider"},
        {"type": "section", "text": {"type": "mrkdwn", "text": "\n".join(lines)}},
    ]


def _report_blocks(report: VulnerabilityReport) -> list[dict]:
    stamp_text, _color = _STAMP_BY_RECOMMENDATION.get(report.overall_recommendation, ("VERDICT", "#666"))

    blocks: list[dict] = [
        {"type": "header", "text": {"type": "plain_text", "text": f"🏛️ Council Verdict: {stamp_text}"}},
        {"type": "section", "text": {"type": "mrkdwn", "text": f"*Decision:*\n> {report.decision_text}"}},
        {"type": "divider"},
    ]

    for vuln in sorted(report.vulnerabilities, key=lambda v: v.severity_score, reverse=True):
        consensus_emoji = {"agreement": "🤝", "contested": "⚔️", "unresolved": "❓"}.get(vuln.consensus, "")
        positions = "\n".join(f"   • *{role}:* {pos}" for role, pos in vuln.agent_positions.items())
        blocks.append(
            {
                "type": "section",
                "text": {
                    "type": "mrkdwn",
                    "text": (
                        f"*{vuln.title}* — severity {vuln.severity_score}/10 {consensus_emoji} {vuln.consensus}\n"
                        f"{vuln.synthesis}\n{positions}"
                    ),
                },
            }
        )

    if report.conditions:
        blocks.append(
            {"type": "section", "text": {"type": "mrkdwn", "text": "*Conditions:*\n" + "\n".join(f"• {c}" for c in report.conditions)}}
        )

    blocks.append(
        {
            "type": "context",
            "elements": [
                {"type": "mrkdwn", "text": f"Resolved in {report.total_latency_ms / 1000:.1f}s across 5 agents, 2 rounds."}
            ],
        }
    )
    return blocks


async def start_socket_mode() -> None:
    handler = AsyncSocketModeHandler(slack_app, settings.slack_app_token)
    await handler.start_async()


if __name__ == "__main__":
    import asyncio

    asyncio.run(start_socket_mode())


# --- Production alternative: mount on the FastAPI app instead of Socket Mode ---
#
# from slack_bolt.adapter.fastapi.async_handler import AsyncSlackRequestHandler
# from app.main import app as fastapi_app
#
# slack_handler = AsyncSlackRequestHandler(slack_app)
#
# @fastapi_app.post("/slack/events")
# async def slack_events(req: Request):
#     return await slack_handler.handle(req)
