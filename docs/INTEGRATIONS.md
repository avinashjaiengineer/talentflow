# Email, calendar, Teams, and AI calls

TalentFlow can email candidates from Outlook, book interviews in Outlook with a Teams link, and phone candidates with an AI calling agent. Every integration is **off by default**: out of the box everything works inside TalentFlow, and nothing reaches a candidate until you connect a provider.

| Feature | Default (nothing leaves TalentFlow) | Connected |
|---|---|---|
| **Email** | "Send" records the email in TalentFlow; you send it yourself | Sent from your Outlook mailbox (Microsoft 365) |
| **Calendar** | Slots are proposed in working hours; bookings are recorded only | Slots avoid interviewers' busy times; the interview is booked in Outlook with a **Teams link**, and invitations go out automatically |
| **Calls** | **Simulated**: you type the candidate's replies and the AI answers exactly as it would on a real call | Real phone calls through **Twilio** |

People stay in control: an agent drafts every email and prepares every call, but **nothing is sent or dialed until a recruiter clicks Send or Call**.

---

## How the AI calling agent works

Three call types, each started from the candidate's panel:

| Call | When | What the agent does | What you get |
|---|---|---|---|
| **Pre-screen** | After you advance a candidate | Confirms interest; asks about 1–2 requirements (prioritizing gaps from screening), notice period, and salary expectations | Transcript, summary, notice period, salary, concerns |
| **Scheduling** | After interview slots are proposed | Offers the slots and books the one the candidate picks | The interview is booked: Teams meeting and invitations when the calendar is connected |
| **Reminder** | After the interview is booked | Calls 24 hours before (configurable) to confirm attendance | Confirmed, or "asked to reschedule" |

**Built-in safeguards:**
- **The agent discloses it's an AI** in the first sentence and says the call is recorded, then asks whether it's a good time. If the candidate says no, the call ends politely.
- If the candidate says **"stop calling"** or "not interested", they're marked **Do not call** and TalentFlow blocks future calls. You can also set this by hand in the Talent pool.
- If they ask for a person, the agent ends the call and flags it for a recruiter.
- The agent **never** asks about protected characteristics (age, family, health, religion, nationality, and so on), gives feedback, or makes promises.
- What the candidate says is treated as information, never as instructions, so "ignore your rules" doesn't work on a call either.
- One active call per candidate. Calls are capped at 24 turns.
- Every call is logged with its full transcript and the name of the person who requested it.

**Try it now without a phone:** with the default simulated mode, open an advanced candidate, click **Pre-screen call**, and reply as the candidate in the chat box. It's the same agent a real call would use.

---

## Microsoft 365: Outlook email, calendar, and Teams

You need a Microsoft 365 tenant, admin rights to grant permissions, and a mailbox for recruiting, such as `recruiting@yourcompany.com`.

### 1. Register an app in Microsoft Entra ID
1. Go to [entra.microsoft.com](https://entra.microsoft.com) → **Identity → Applications → App registrations → New registration**.
2. Name it `TalentFlow`. Choose **Accounts in this organizational directory only**. No redirect URI is needed. Click **Register**.
3. Copy the **Application (client) ID** and **Directory (tenant) ID** from the Overview page.

### 2. Create a client secret
**Certificates & secrets → New client secret**. Pick an expiry and copy the secret **Value** right away; it's shown only once. Put a reminder in your calendar to rotate it before it expires.

### 3. Grant permissions, limited to the mailboxes TalentFlow needs

TalentFlow needs two Microsoft Graph application permissions:

| Permission | Why |
|---|---|
| `Mail.Send` | Send outreach and invitation emails |
| `Calendars.ReadWrite` | Read interviewers' free/busy and create interview events with Teams links |

**Choose one of these two approaches:**

**Option A: scoped with RBAC for Applications (recommended).** TalentFlow can only touch the mailboxes you list. This is Microsoft's current way to restrict app access to Exchange; it replaces the older application access policies.

> **Don't** add these permissions under **API permissions** in Entra. Permissions granted there apply to every mailbox and are *added to* the scoped ones, which would cancel the restriction.

In [Exchange Online PowerShell](https://learn.microsoft.com/powershell/exchange/connect-to-exchange-online-powershell), as an Exchange admin:

```powershell
# 1. A group holding the recruiting mailbox and every interviewer (direct members only)
New-DistributionGroup -Name "TalentFlow Mailboxes" -Type Security `
  -Members recruiting@yourcompany.com, lead@yourcompany.com
$dn = (Get-Group "TalentFlow Mailboxes").DistinguishedName

# 2. A management scope matching that group
New-ManagementScope -Name "TalentFlow Mailboxes" -RecipientRestrictionFilter "MemberOfGroup -eq '$dn'"

# 3. Point Exchange at the app. Use the IDs from Entra → *Enterprise applications* → TalentFlow
#    (not the App registrations page, which shows a different Object ID).
New-ServicePrincipal -AppId <application-client-id> -ObjectId <enterprise-app-object-id> -DisplayName "TalentFlow"

# 4. Grant the two roles, scoped to the group
New-ManagementRoleAssignment -App <enterprise-app-object-id> -Role "Application Mail.Send" -CustomResourceScope "TalentFlow Mailboxes"
New-ManagementRoleAssignment -App <enterprise-app-object-id> -Role "Application Calendars.ReadWrite" -CustomResourceScope "TalentFlow Mailboxes"

# 5. Check: InScope should be True for the recruiting mailbox
Test-ServicePrincipalAuthorization -Identity <enterprise-app-object-id> -Resource recruiting@yourcompany.com
```

Changes can take 30 minutes to 2 hours to take effect. Add new interviewers to the group so TalentFlow can read their free/busy.

**Option B: tenant-wide (quick test tenants only).** In the app registration, go to **API permissions → Add a permission → Microsoft Graph → Application permissions**, add `Mail.Send` and `Calendars.ReadWrite`, and click **Grant admin consent**. This lets the app send as, and edit the calendar of, **any** user in the tenant, so don't use it in a real organization.

### 4. Configure TalentFlow
In `.env` (or `deploy/.env.production`):

```bash
EMAIL_PROVIDER=graph
CALENDAR_PROVIDER=graph
MS_TENANT_ID=<directory-tenant-id>
MS_CLIENT_ID=<application-client-id>
MS_CLIENT_SECRET=<secret-value>
MS_SENDER=recruiting@yourcompany.com   # sends email and organizes interviews
TIMEZONE=Asia/Kolkata                  # interview hours are proposed in this zone
```

Restart or redeploy. The sidebar should show **Email: Outlook** and **Calendar: Outlook + Teams**.

### 5. Add interviewers to jobs
When creating a job, list the **interviewers' emails**. TalentFlow then proposes only times when all of them are free, and invites them to the Teams meeting along with the candidate.

**How booking works:** when a slot is chosen (by a recruiter clicking it, or by the scheduling call), TalentFlow creates the event in `MS_SENDER`'s calendar with a Teams meeting. **Outlook emails the invitation**, with the join link, to the candidate and interviewers. The Teams link also appears on the candidate in TalentFlow.

---

## Twilio: real AI phone calls

You need a Twilio account, a phone number that can call your candidates' countries, **HTTPS** for TalentFlow (a domain; see [DEPLOYMENT.md](DEPLOYMENT.md#https)), and an Anthropic API key.

### 1. Set up Twilio
1. Sign up at [twilio.com](https://www.twilio.com) and upgrade from trial. Trial accounts can only call verified numbers and play a trial message.
2. **Phone Numbers → Buy a number** with **Voice** capability.
3. **Voice → Settings → Geo permissions**: enable only the countries you'll call.
4. Copy the **Account SID** and **Auth Token** from the console dashboard.

### 2. Configure TalentFlow

```bash
VOICE_PROVIDER=twilio
TWILIO_ACCOUNT_SID=AC...
TWILIO_AUTH_TOKEN=...
TWILIO_FROM_NUMBER=+14155550100
PUBLIC_BASE_URL=https://talent.yourcompany.com   # must be https; Twilio connects back over wss://
VOICE_LANGUAGE=en-US
MODEL_CALLER=claude-haiku-4-5                    # optional: fastest replies on live calls
```

Redeploy. The sidebar should show **Calls: Twilio**.

### 3. Add phone numbers to candidates
Resumes often include a phone number, which is extracted automatically. Otherwise use **Talent pool → candidate → Edit contact details**. Use international format, for example `+919812345678`.

**How a call flows:**
1. A recruiter clicks **Call**, and the worker asks Twilio to dial.
2. When the candidate answers, Twilio speaks the greeting and streams the conversation to TalentFlow at `/api/voice/relay/…`. Twilio turns speech into text, Claude decides the reply, and Twilio speaks it.
3. When the call ends, the transcript is summarized and any booking or reminder result is applied.

**Security:** Twilio's status webhooks are checked against your Auth Token signature, and each call's audio stream uses a one-time secret token.

**Latency:** replies need to come back in about 1–2 seconds to feel natural. Calls use low effort by default. For the snappiest conversation, set `MODEL_CALLER=claude-haiku-4-5`, and test in simulated mode first.

---

## Costs

| Item | Approximate cost |
|---|---|
| Microsoft 365 | Included in your existing licenses |
| Twilio outbound calls | ~$0.01–$0.10 per minute depending on country, plus ~$1–$15/month per number |
| Twilio ConversationRelay (speech) | Per-minute pricing; see Twilio's pricing page |
| Claude per call | A 5-minute pre-screen is ~10–15 turns: roughly $0.05–$0.30 on Opus at low effort, less with Haiku |

## Legal checklist before calling real candidates

- **Consent to be called.** In the US, the TCPA restricts automated calls to mobile numbers without prior consent. Get consent in your application form (for example, "I agree to receive calls, including AI-assisted calls, about my application").
- **Recording consent.** Some US states and many countries require all parties to consent to recording. The greeting announces recording, and the candidate can decline.
- **AI disclosure.** Several jurisdictions require disclosing AI in hiring and in phone calls. The greeting does this. Check your local rules, for example the EU AI Act, NYC Local Law 144, and the Illinois AI Video Interview Act.
- **Calling hours and do-not-call lists.** Only call during reasonable local hours. Respect opt-outs; TalentFlow does this automatically when the candidate asks.
- **Data retention.** Transcripts contain personal data. Delete candidates you no longer need.

This checklist isn't legal advice. Have your counsel review your setup before calling at scale.

## Troubleshooting

| Symptom | Fix |
|---|---|
| "Microsoft 365 is not configured: set …" | A required `MS_*` setting is missing |
| "Microsoft 365 sign-in failed (401)" | Wrong tenant, client ID, or secret, or the secret has expired |
| "Microsoft Graph error 403" | The mailbox isn't in the "TalentFlow Mailboxes" scope (or, with option B, admin consent wasn't granted). Scoped changes can take up to 2 hours. |
| No free interview slots | Interviewers are fully booked for two weeks, or `WORKING_HOURS_START`/`WORKING_HOURS_END` are too narrow |
| "PUBLIC_BASE_URL must be https://" | Set up a domain and HTTPS first; Twilio needs `wss://` |
| Call status "no answer" | The candidate didn't pick up within 30 seconds. Try again later or send an email. |
| Long pauses on calls | Set `MODEL_CALLER=claude-haiku-4-5` |
