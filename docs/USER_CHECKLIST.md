# ScrapTrust: end-user checklist (non-technical users)

Written 2026-11-17 after walking through the app as an end user on a computer and a phone (375 px), and checking it
against published guidance: Nielsen's 10 usability heuristics, WCAG 2.2 AA, AI-assistant UX practice (clear limits,
starting examples, specific errors, a way to reach a person) and field-app practice (gloves, sunlight, one hand, weak signal).

Legend: **DONE** already in the app · **DONE NOW** fixed in this pass · **CAN DO** worth doing, not blocking ·
**MUST DO** needed before the 50,000-user rollout (still open).

## 1. First-time user ("I've never used this. What do I do?")
| Need | Status |
|---|---|
| Home screen says what to do in one look | **DONE NOW**: 3-step welcome card (closable, remembered) |
| Starting buttons for the main job (black mass), not technical topics | **DONE NOW**: "Check a black-mass reading" (fills an example to edit), "Read a photo of the XRF screen", "Compare bags & make a report", "What can you do?" |
| Message box hint shows what to type | **DONE NOW**: "Type XRF numbers (e.g. Ni 31.8 Co 9.1) or ask a question…" |
| "What can you do?" answer leads with black mass, in plain words | **DONE NOW** |
| Help page: how-to, can / cannot, FAQ, safety, privacy, who to ask | **DONE NOW**: Help in the side menu; contact set with `SUPPORT_CONTACT` in `.env` |
| No technical choices forced on users | **DONE NOW**: AI-model picker hidden when there is only one engine; engine renamed "Built-in (private)" |
| Short video or guided tour | **CAN DO** |

## 2. Understanding the answer ("Is my black mass good?")
| Need | Status |
|---|---|
| Plain verdict first: battery type, main metals, how sure, what to do next | **DONE NOW**: "In short: This looks like NMC black mass…, most likely NMC622 (medium confidence)…" |
| No jargon in the main answer; details available on request | **DONE NOW**: kNN, scores and method moved into a "How this was worked out" fold-out |
| Numbers rounded to what people use | **DONE NOW**: 1 decimal (2 below 1 %); answer-checker still verifies every number |
| Element names spelled out | **DONE NOW**: "Ni (nickel)" |
| Every number labelled measured vs estimated (project rule) | **DONE**: OBSERVED / INFERRED kept in column headers and explained in plain words |
| Lithium clearly "calculated, not measured" | **DONE** |
| Clear "confirm with a lab before you buy, sell or price" | **DONE NOW**: in every black-mass answer and under the message box |
| Spoken summary in hands-free mode | **DONE** |
| A grade / pass-fail against the company's buying spec | **CAN DO**: needs ACE's spec limits (ask the business; never invent them) |
| Values in other units (kg per tonne, per bag) | **CAN DO** |

## 3. When something goes wrong
| Need | Status |
|---|---|
| Errors in plain words that say what to do | **DONE NOW**: separate messages for no internet, slow answer, too many messages, server busy, signed out, file too big, storage full |
| "Try again" without retyping | **DONE NOW**: Try again button re-sends the same message and files |
| Stop a slow answer | **DONE NOW**: Stop button while waiting |
| Warning when the phone/PC is offline | **DONE NOW**: banner "You're offline…" |
| Gibberish or off-topic gets suggestions, not a refusal | **DONE NOW** |
| Photo of the gun screen unreadable: tell people how to retake it | **DONE NOW**: hold straight, avoid glare, fill the frame, or type the values |
| Numbers read from a photo must be checked by the user | **DONE**: and now in bold |
| Answer-checker flags untraceable numbers | **DONE** |
| Report a wrong answer | **DONE**: thumbs up/down with note |
| Queue messages while offline and send later | **CAN DO** (needs an offline-capable app shell, PWA) |

## 4. Field worker on a phone (gloves, sunlight, one hand)
| Need | Status |
|---|---|
| Buttons big enough for gloves (≥ 44 px) | **DONE NOW**: message-box, menu and library buttons 44 px on phones; audit went from 11 undersized controls to 0 |
| Camera straight from the app | **DONE**: "Take a photo" |
| Voice input and hands-free conversation | **DONE**; Talk moved into the layout on phones so it never covers text |
| Readable in sunlight (contrast) | **DONE**: automated contrast check found no text below 4.5:1 |
| Works on a slow connection | **CAN DO**: compress photos before upload, show upload progress |
| Install as an app icon on the phone (PWA) | **CAN DO** |
| Bigger text option | **CAN DO** (browser zoom works today) |

## 5. Accessibility (WCAG 2.2 AA basics)
| Need | Status |
|---|---|
| Visible keyboard focus everywhere | **DONE NOW**: global focus outline + focus ring on the message box |
| Respect "reduce motion" | **DONE NOW** |
| Buttons have names for screen readers | **DONE**: audit found no unnamed visible controls |
| Page language set | **DONE** (`lang="en"`) |
| Full screen-reader test (NVDA / VoiceOver) | **MUST DO** before rollout: needs a person with the tools |
| Dark / high-contrast theme | **CAN DO** |

## 6. Finding past work (Library)
| Need | Status |
|---|---|
| Everything kept, searchable, filter by type | **DONE** |
| Rename, pin, open, back to the conversation | **DONE** |
| Download as text, PDF or the original file | **DONE** |
| Remove an item | **DONE NOW**: Remove button with a confirmation (the admin record stays) |
| Download all my data at once | **CAN DO** |

## 7. Trust and privacy
| Need | Status |
|---|---|
| Users told their inputs are saved and used to improve the system | **DONE NOW**: line on the home screen + Help page |
| Users told what the tool cannot do | **DONE NOW**: Help "cannot" list + "Things I can't do" in the intro |
| A way to reach a person | **DONE NOW**: Help page (set `SUPPORT_CONTACT`) |
| Terms of use / privacy notice approved by ACE legal, accepted at first sign-in | **MUST DO** (company decision; text not invented here) |
| No data sent to outside AI services | **DONE**: offline-only, by manager decision |

## 8. People who do not read English well
| Need | Status |
|---|---|
| Interface and answers in local languages (e.g. Hindi, Kannada, Tamil) | **CAN DO**: the plain-language wording is ready for translation; needs translators to check terms |
| Voice in local languages | **CAN DO**: the speech model can transcribe other languages |

## 9. Supervisors and admins
| Need | Status |
|---|---|
| See all activity by day / month / year, search, export | **DONE** (Records, admin only) |
| Add lab results so the model learns | **DONE** |
| Turn login back on before rollout | **MUST DO**: paused by request; remove `AUTH_MODE=disabled_local_dev` |
| Delete `TEST_ACCOUNTS.csv` before go-live | **MUST DO** |
| Real-user test session (5–8 people from the yard and lab) using `docs/TESTING_SESSION.md` | **MUST DO**: automated checks cannot replace watching real users |

## Sources
- Nielsen Norman Group, 10 usability heuristics: https://www.nngroup.com/articles/ten-usabilityheuristics/
- WebAIM WCAG 2.2 checklist: https://webaim.org/standards/wcag/wcag22
- Cornell WCAG 2 AA checklist: https://accessibility.cornell.edu/information-technology/web-accessibility/wcag-2-aa-checklist
- AI chatbot UX practice: https://mindtheproduct.com/deep-dive-ux-best-practices-for-ai-chatbots , https://orangeloops.com/2025/07/9-ux-patterns-to-build-trustworthy-ai-assistants/
- Software for people who work outside: https://blog.apario.net/on-writing-software-for-people-who-work-outside , https://www.thedroidsonroids.com/blog/mobile-apps-for-industrial-field-teams
