# Compliance Checklist

Reviewed July 19, 2026. This is a conservative product checklist, not legal advice.
Qualified Maryland counsel should determine applicability to the actual business model.

## Controls required before any outreach

- [ ] Human approved the exact recipient, channel, content, and claimed role.
- [ ] Identity, affiliation, authority, and capital claims are accurate and documented.
- [ ] Lawful contact source and retrieval date are recorded.
- [ ] Internal do-not-contact, channel opt-out, and suppression records were checked.
- [ ] National/state DNC applicability was reviewed for the number and call purpose.
- [ ] No automated dialing, prerecorded/artificial voice, automatic text, or blasting.
- [ ] Caller/email identity is accurate; no spoofing or deceptive subject line.
- [ ] Communication makes no distress, appraisal, guaranteed-price, or closing claim.
- [ ] “No” and any reasonable opt-out are recorded immediately.
- [ ] Follow-up has permission, an owner, and a date.
- [ ] Licensed broker/attorney review is obtained where the activity may be brokerage.

## Federal sources and counsel questions

**FCC / TCPA**

- FCC consumer guidance:
  https://www.fcc.gov/consumers/guides/stop-unwanted-robocalls-and-texts
- FCC enforcement overview:
  https://www.fcc.gov/enforcement/topics/unwanted-communications

Ask counsel how TCPA rules apply to manually dialed calls, mobile numbers, texts,
artificial/prerecorded voice, consent revocation, reassigned numbers, and mixed
business/personal lines. The product must not automate calls or texts in this MVP.

**FTC Telemarketing Sales Rule / National Do Not Call**

- TSR compliance guide:
  https://www.ftc.gov/business-guidance/resources/complying-telemarketing-sales-rule
- DNC questions:
  https://www.ftc.gov/business-guidance/resources/qa-telemarketers-sellers-about-dnc-provisions-tsr-0

Most genuine business-to-business calls have different treatment, but the exact
recipient, purpose, campaign, and state law matter. Do not encode an exemption as a
product conclusion. Maintain internal suppression regardless.

**CAN-SPAM**

- FTC business guide:
  https://www.ftc.gov/business-guidance/resources/can-spam-act-compliance-guide-business

Counsel should review whether a message is commercial. For commercial email, use
accurate headers and subjects, identify advertising where required, include a valid
postal address and clear opt-out, honor opt-outs promptly, and monitor partners.
CAN-SPAM has no general B2B exception.

## Maryland sources and counsel questions

**Telephone solicitation**

- Commercial Law §14-4502:
  https://mgaleg.maryland.gov/mgawebsite/Laws/StatuteText?article=gcl&section=14-4502

Ask counsel whether acquisition outreach is a “telephone solicitation,” whether any
B2B or isolated-transaction exception applies, and which consent, time-of-day,
frequency, identification, and recordkeeping requirements govern. Use the conservative
8 a.m.–8 p.m. local window and never exceed three attempts in 24 hours even before the
legal analysis is complete.

**Privacy and security**

- Maryland OAG privacy resources / MODPA:
  https://oag.maryland.gov/resources-info/Pages/data-privacy.aspx
- Maryland PIPA business guidance:
  https://oag.maryland.gov/i-need-to/Pages/Guidelines-for-Businesses-to-Comply-with-the-Maryland-Personal-Information-Protection-Act.aspx

Ask counsel whether thresholds/exemptions apply and how access, correction, deletion,
opt-out, minimization, retention, security, processor, and breach duties apply. Collect
only necessary professional contact and research data; do not infer sensitive traits.

**Real-estate licensing and compensation**

- Business Occupations and Professions §17-604:
  https://mgaleg.maryland.gov/mgawebsite/Laws/StatuteText?article=gbo&section=17-604
- Brokerage conduct provisions:
  https://mgaleg.maryland.gov/mgawebsite/Laws/StatuteText?article=gbo&section=17-322

Ask Maryland real-estate counsel what research, introductions, referrals, negotiation,
advertising, transaction-based compensation, or acting for another constitutes licensed
brokerage. Do not accept or promise brokerage compensation to an unlicensed person.

## Product gate

The application has no send, dial, text, or mail action. Milestone 4 can record a manual
outbound activity only after an identified human approves the contact and active
suppression/opt-out checks pass. Suppression values are stored as one-way hashes,
matching approvals are revoked, and there is no routine unsuppress command. Follow-up
output is visibility only; it does not create or dispatch external tasks.

Property briefs use source-reported facts and an honest, permission-based opener. They
repeat uncertainty, resident-agent, distress, appraisal, authority, and opt-out warnings.
The underwriting command treats every supplied number as an assumption and labels the
result “not an appraisal.”

The optional Streamlit dashboard is localhost-only and read-only. It can preview briefs
and calculate in-memory underwriting scenarios, but it cannot approve contacts, remove
suppressions, mutate CRM records, or send communications. Public hosting is out of scope.
