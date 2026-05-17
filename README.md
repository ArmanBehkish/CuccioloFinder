# CuccioloFinder

<!-- §1 (hero) — to be written last -->

## What it is

Adoptable dogs across Italy are listed shelter by shelter on individual
websites, in Italian. Anyone hoping to find one has to comb through many
shelter sites, opening lots of pages on each. Every site has its own layout,
its own categories, and its own opinion on what information is worth showing.
Most of the dogs are mixed-breed and have no breed information anyway.

CuccioloFinder gathers those listings into one place and translates them
into English. Where shelters bury useful information in free-text
descriptions (age, weight, vaccinations, whether a dog gets along with cats
or children), it pulls those out and sorts every dog into the same
plain-English categories so they can actually be compared side by side. When
there's enough to go on, it also suggests what each dog's breed might be
from its photo and its described behaviour. The current build covers five
shelters in and around Torino; the approach is general and would extend to
many more.

You can browse with the filters you'd expect (size, age, breed,
compatibility, recently posted, …), describe your ideal dog in plain English
and let the site work the filters out for you, or open a dashboard with
aggregated statistics over the whole dataset: what each shelter covers, how
breeds and ages are distributed, how long dogs tend to wait for adoption,
and where the data is incomplete. Every dog links back to its original
shelter. Adoptions happen there, not here.

## What you can do

- **Browse every adoptable dog** the system currently knows about and
  filter on the axes adopters actually care about: size, age, gender,
  fur, weight, medical status, compatibility with kids / cats / other
  dogs, breed (both what the shelter wrote and what the AI guessed from
  the photos), how recently the dog was listed, and how long it has
  been waiting in shelter.

- **Describe your ideal dog in plain English** ("a calm older mid-sized
  dog good with cats") and let the Smart Search page extract the
  filters for you. It shows what the AI understood, so you can correct
  course if it misread.

- **Open any dog's profile** for all the photos, every field the shelter
  published (translated to English), two independent AI breed guesses
  (one from the photos, one from the described behaviour), and a link
  back to the original listing for adoption.

- **Open the Statistics dashboard** to see what the dataset looks like
  in aggregate: shelter coverage, breed and age distributions, wait
  times by age and gender, compatibility frequencies, and where the
  data is patchy.

- **All of the above works on a phone.**

## How it's built

The dataset is rebuilt on a schedule by a worker container running a
three-stage pipeline. An always-on API container serves the result to a
single-page React frontend.

```
   Worker container (runs on a schedule):
   ┌────────────────────────────────────────────────────┐
   │  Shelters → Scrape → Enrich → SQLite database      │
   └────────────────────────────────────────────────────┘
                                          │
                                          ▼
                                 ┌─────────────────────┐
                                 │   API   (FastAPI)   │
                                 │   always running    │
                                 └─────────────────────┘
                                          │
                                          ▼
                                 ┌─────────────────────┐
                                 │   React frontend    │
                                 │   single-page app   │
                                 └─────────────────────┘
```

**Scrapers.** One Scrapy spider per shelter, with headless-browser support
for the sites that render listings client-side. When a shelter recycles a
URL to a different physical dog (rare but real), the change in photo set
tips us off and the old row is preserved rather than overwritten.

**Enrichment.** Three stages run in order: translation, field extraction
from free-text descriptions, and breed inference. Each stage only
re-processes what actually changed since the last run, using sentinel values
that distinguish "tried and found nothing" from "never tried" so LLM calls
aren't repeated for dogs whose descriptions genuinely lack the information.
Any LLM workload can be served by a local Mistral 7B or one of two hosted
Llama-3.3-70B providers, chosen independently per stage.

**Database.** SQLite. Every scraped field has up to three sources stored
side by side (the original Italian, an English translation of the structured
field, and a value pulled by an LLM from the description), so the display
can prefer the structured value but fall back when the shelter never
published it.

**API.** FastAPI, with the values that drive dropdowns and the dashboard
precomputed in memory and refreshed by the worker after each run. The
natural-language search endpoint has its own provider dispatcher: when one
hosted LLM returns nothing usable, it retries against the other before
giving up.

**Frontend.** Single-page React app that reads from the API and renders
everything client-side, including the whole statistics dashboard. Detailed
in §7.

## The AI side

Four workloads pass through the AI layer: translating Italian into English,
extracting structured fields out of free-text descriptions, estimating
breeds, and parsing natural-language search queries. Each LLM workload can
be served independently by a local Mistral 7B (running on CPU inside the
API container) or by one of two hosted Llama-3.3-70B providers. The three
are interchangeable per workload, so operators can mix and match: free-tier
hosted for bulk translation, paid hosted for latency-sensitive search, local
for fully offline runs. When a hosted call fails and a local model is
loaded, the system falls back to it automatically.

### Translation

A small static dictionary handles the predictable Italian-to-English
vocabulary (sizes, sexes, yes/no medical fields, common compatibility tags)
instantly and reliably, falling through to an LLM only for what it doesn't
recognise. Long free-text descriptions skip the dictionary and go straight
to the LLM. The output token budget is scaled to the input length, which
sidesteps a failure mode autoregressive models share: given too much runway
after a short input, they paraphrase their own translation back to
themselves until the buffer fills.

### Pulling structure out of free text

A typical shelter description mentions some of: age, weight, size, fur,
microchip status, sterilisation, vaccinations, deworming, and which kinds
of housemates the dog gets along (or doesn't) with. None of it is in a
fixed place. One LLM call per field per dog handles the extraction,
deliberately not combined, because a single bad response that derails one
field then can't poison the rest. When an extraction succeeds and returns
"no signal", the system records a sentinel value rather than leaving the
column null, so subsequent runs don't re-spend LLM calls on descriptions
that will never say what colour the dog is.

### Breed estimation, two signals

Most of the dogs in the dataset are mixed-breed, so the goal here is not
to assign a definitive breed (that question doesn't have an answer) but
to give an adopter two reasonable hints from two independent signals and
let them decide. The two are kept separate on the page, never blended
into a single confidence number, because they measure different things
(the image model's softmax probability versus the behavioural model's
coverage of the dog's available dimensions). Averaging them would be
lying to the reader.

#### Image classification

The image side runs each dog's photos through a Vision Transformer
fine-tuned for dog breed classification. Top three predictions per photo
are pooled across all of the dog's images, with each breed taking its
best-seen probability. Before scoring, raw labels are filtered against an
AKC mapping so the noise inherited from the model's original training set
(labels like "black", "flat", "dingo") is dropped and the next valid
candidate moves up.

#### Behavioural similarity

The behavioural side scores the dog against every breed in the AKC
catalogue across seven dimensions: three structural (size, fur, weight)
and four behavioural (energy level, trainability, demeanour, temperament).
Structural dimensions come from the shelter listing; behavioural
dimensions are pulled from the description by the same LLM extraction
stage above. Each dimension contributes a similarity that respects its
own algebra (ordinal for sizes, where small is closer to medium than to
giant; set-based for temperament traits; exact-match for the rest),
weighted by how informative the dimension is over the AKC catalogue. A
dimension that splits the catalogue evenly gets weight; one where most
breeds share a value contributes almost nothing. Dogs missing too many
dimensions are not scored at all, because guessing from too little signal
is worse than declining to guess.

This scorer replaced an earlier sentence-embedding version whose cosine
scores collapsed to a narrow band for nearly every dog. §9 has the story.

### Natural-language search

Smart-search lets the visitor describe a dog in plain English and have
the page work out which filters to apply. The query goes to an LLM with a
system prompt built per-request from the live database: the allowed-breed
list is whatever breeds actually exist on currently-listed dogs, the
compatibility tags are whatever the dataset actually uses. The LLM's
output is then gated against the same lists used to render the prompt, so
it can't propose a value no dog has. If the configured hosted provider
returns an empty response (a real failure mode on certain phrasings of
certain prompts), the dispatcher transparently retries against the other
provider before surfacing a "no preferences extracted" result.

## The frontend

A single-page React app built with Vite, mobile-first throughout (sidebar
collapses to a hamburger drawer on phones). Six pages cover the surface:
home, structured filter search, natural-language search, a six-tab
statistics dashboard, a dog detail page, and a contact form.

A few details worth noting:

- The statistics dashboard fetches its data once on load and renders all
  six tabs client-side from the same rows. Tab switches make zero network
  calls.
- When the worker is rebuilding the database, the API surfaces that and
  the frontend explains it to the visitor instead of silently failing or
  showing stale results.
- Fields on the dog detail page that came from the LLM-extraction path
  rather than the structured one are tagged with a small "From DESC"
  marker, so adopters can tell what the shelter wrote and what we
  inferred.
- The breed autocomplete on the filter-and-search page is rebuilt from
  whatever breeds currently exist in the database, so it can't suggest
  something no dog has. Date filters that don't apply to the
  currently-selected shelter are auto-disabled with a tooltip explaining
  why.

## Running it in production

### Deployment

Everything that powers the live site runs on a single small VPS at the
bottom of the hosting provider's price list. Inside, two Docker
containers (the always-on API and a scheduled worker) are orchestrated
with Docker Compose, which gives them a private network so the worker
can talk to the API without ever touching the public proxy. Nginx fronts
both for SSL and routing. SQLite lives on a host-mounted volume that
survives container restarts. The Python image pins CPU-only PyTorch
wheels, so model dependencies stay slim instead of dragging in CUDA
libraries the VPS has no GPU to run.

### CI/CD

GitHub Actions handles deploys on push to main: the workflow logs into
the VPS, pulls the latest code, and rebuilds the affected containers. A
separate workflow runs security scans on every push to catch common
vulnerability patterns before they ship.

### Security

A few things hardened beyond defaults:

- Internal routes blocked at the proxy
- Per-IP rate limits, strict on the LLM-backed endpoint
- CORS scoped to the production origin
- Honeypot plus hCaptcha on the contact form

## Experiments and lessons learned

A few of the choices in the codebase landed where they did after at least
one failed attempt. The ones worth recording:

- **Breed similarity used to be an embedding problem.** The first
  behavioural breed scorer built a profile string per dog and per breed,
  embedded both with `all-MiniLM-L6-v2`, and ranked by cosine similarity.
  The output was unusable: nearly every (dog, breed) pair scored above
  0.95, the rankings carried no real information, and there was no
  honest way to threshold. Replaced with the typed-similarity scorer
  described in §6: per-dimension similarity functions chosen to match
  each dimension's algebra (ordinal, nominal, set), weighted by how
  informative the dimension is over the AKC catalogue. Scores now spread
  across the full [0, 1] range and the top-ranked breed actually carries
  signal.

- **OOM kills taught the worker to chunk and back off.** Sending a long
  Italian description in one shot to local Mistral OOM-killed the API
  container on the 8 GB VPS. The fix has three parts: descriptions are
  split at sentence boundaries into chunks of around 800 characters
  before being sent; the output token budget is scaled to input length
  so the model can't paraphrase itself to fill empty runway; and the
  worker retries failed chunks with backoff to cover the container's
  restart window. Same pattern, no more crashes.

- **Two more LLM backends arrived as the limits of the first became
  obvious.** The project started Mistral-only as a "no API key required"
  design. Local CPU inference and 8 GB of RAM made the bulk-translation
  step painfully slow, so a hosted Llama-3.3-70B path through Groq was
  added. Groq's free tier has request-per-day caps that get tight on
  per-row workloads, so OpenRouter (paid, same model family, no
  throttling at our scale) was added next. Each of the three workloads
  picks its own backend, so the operator can put free-tier hosted on the
  bulk job, paid hosted on the latency-sensitive search, and local on
  the rest.

- **Sentinel writes stopped the worker from re-asking the same
  questions.** Early on, an LLM extraction that returned "no signal"
  left the column NULL, so the next nightly run asked the same question
  about the same description and got the same null. Across hundreds of
  LLM calls per nightly run, that was a lot of avoidable cost. Now a
  successful "no signal" call writes an empty-string sentinel, which the
  next run treats as "already tried, skip"; only genuinely changed
  fields trigger a fresh call.

- **Smart search's breed prompt is built from real data.** Letting the
  LLM emit any breed name produced occasional candidates that sounded
  plausible but didn't match any actual dog in the dataset, which
  silently broke the SQL filter. The allowed-breed list is now derived
  from whatever breeds currently appear in the data (shelter claims plus
  image-classifier hits), passed into the LLM prompt verbatim, and the
  same list is used to validate the LLM's output before the database is
  queried. Prompt and validator can't drift because they read from the
  same source.

## Tech stack

| Layer | Stack |
|-------|-------|
| **Backend** | Python · FastAPI · SQLAlchemy · SQLite · Scrapy (+ Playwright) · Pydantic · pytest |
| **Frontend** | React 18 · Vite · React Router · React Bootstrap · recharts · @nivo/heatmap |
| **AI / ML** | Mistral 7B (via `llama-cpp-python`) · Llama 3.3 70B (Groq, OpenRouter) · Vision Transformer · PyTorch (CPU) · HF Transformers |
| **Infrastructure** | Docker · Docker Compose · Nginx · Hetzner Cloud · GitHub Actions · Certbot · Ubuntu |

## Roadmap and links

### What's next

- Adding More shelters, beyond the five currently in Piemonte.
- Better image-classification models for breed detection: Stronger vision models or fine tuning one for breed detection.

### Links

- **Live Website:** [armanb.dev/cucciolofinder](https://armanb.dev/cucciolofinder)
- **Author:** Arman Behkish
- **License:** AGPL-3.0
- **Support running costs:** [ko-fi.com/cucciolofinder](https://ko-fi.com/cucciolofinder)

<!-- remaining sections to be added as we approve them:
     §3 See it live (screenshots)
     §1 Hero (tagline + badges)
-->
