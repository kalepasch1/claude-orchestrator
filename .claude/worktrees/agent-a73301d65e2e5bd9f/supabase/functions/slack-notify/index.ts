// slack-notify - posts a pending approval to Slack with Approve/Deny buttons.
// Trigger it with a Supabase Database Webhook on INSERT into `approvals`
// (Dashboard -> Database -> Webhooks -> call this function). Or call it from the runner.
//
// Secrets to set (Dashboard -> Edge Functions -> Secrets):
//   SLACK_BOT_TOKEN   (xoxb-...)   SLACK_CHANNEL  (e.g. #orchestrator)
// SUPABASE_URL + SUPABASE_SERVICE_ROLE_KEY are provided automatically.
import { serve } from "https://deno.land/std@0.224.0/http/server.ts";

serve(async (req) => {
  const body = await req.json().catch(() => ({}));
  const a = body.record ?? body; // Supabase webhook sends {type,record,...}; or pass an approval directly
  if (!a || a.status && a.status !== "pending") return new Response("skip", { status: 200 });

  const fields = [
    a.why && `*Why:* ${a.why}`, a.value && `*Value:* ${a.value}`,
    a.risk && `*Risk:* ${a.risk}`, a.command && "`" + a.command + "`",
  ].filter(Boolean).join("\n");

  const blocks = [
    { type: "section", text: { type: "mrkdwn",
      text: `*${a.kind?.toUpperCase() ?? "APPROVAL"} — ${a.title}*\n${a.project ?? ""}\n${fields}` } },
    { type: "actions", elements: [
      { type: "button", style: "primary", text: { type: "plain_text", text: "Approve" },
        action_id: "approve", value: a.id },
      { type: "button", style: "danger", text: { type: "plain_text", text: "Deny" },
        action_id: "deny", value: a.id },
    ] },
  ];

  const r = await fetch("https://slack.com/api/chat.postMessage", {
    method: "POST",
    headers: { "Content-Type": "application/json",
               Authorization: `Bearer ${Deno.env.get("SLACK_BOT_TOKEN")}` },
    body: JSON.stringify({ channel: Deno.env.get("SLACK_CHANNEL") ?? "#orchestrator", blocks }),
  });
  return new Response(await r.text(), { status: 200 });
});
