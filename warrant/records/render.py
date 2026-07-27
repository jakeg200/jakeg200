"""The record as one page a person can read.

No dashboard, no charts. A reader should be able to answer, in under a minute: what can
this person do unaided, how many times have they shown it, when, and can I go and look
at the working myself.
"""

from __future__ import annotations

from typing import Any

from jinja2 import Environment

TEMPLATE = """<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Capability record — {{ record.learner.handle }}</title>
<style>
  :root { color-scheme: light dark; --line: #d9d9d6; --muted: #6b6b66; --bg: #fbfbf9;
          --fg: #17171a; --secure: #1c6b3f; --emerging: #8a5a12; --none: #6b6b66; }
  @media (prefers-color-scheme: dark) {
    :root { --line:#33332f; --muted:#9a9a94; --bg:#131315; --fg:#eceae4;
            --secure:#5fbc86; --emerging:#d6a44a; --none:#8a8a84; }
  }
  body { margin: 0 auto; padding: 3rem 1.25rem 5rem; max-width: 46rem; background: var(--bg);
         color: var(--fg); font: 16px/1.6 ui-serif, Georgia, "Times New Roman", serif; }
  h1 { font-size: 1.5rem; margin: 0 0 .25rem; letter-spacing: -.01em; }
  .sub { color: var(--muted); font-size: .9rem; margin: 0 0 2.5rem; }
  .claim { border-top: 1px solid var(--line); padding: 1.25rem 0; }
  .claim h2 { font-size: 1.05rem; margin: 0 0 .3rem; font-weight: 600; }
  .code { font: .75rem ui-monospace, SFMono-Regular, Menlo, monospace; color: var(--muted); }
  .level { font-size: .8rem; text-transform: uppercase; letter-spacing: .08em; font-weight: 700; }
  .level.secure { color: var(--secure); }
  .level.emerging { color: var(--emerging); }
  .level.not_evidenced { color: var(--none); }
  .counts { color: var(--muted); font-size: .9rem; margin: .35rem 0 .6rem; }
  ul { margin: .4rem 0 0; padding-left: 1.1rem; }
  li { font-size: .9rem; margin: .2rem 0; }
  a { color: inherit; }
  .assisted { color: var(--muted); font-style: italic; }
  footer { border-top: 1px solid var(--line); margin-top: 2.5rem; padding-top: 1.25rem;
           color: var(--muted); font-size: .8rem; }
  code.sig { word-break: break-all; font-size: .7rem; }
</style>
</head>
<body>
<h1>{{ record.learner.handle }}</h1>
<p class="sub">Capability record &middot; generated {{ record.generated_at }}</p>

{% for claim in record.claims %}
<section class="claim">
  <h2>{{ claim.skill_name }} <span class="code">{{ claim.skill_code }}</span></h2>
  <div class="level {{ claim.level }}">{{ claim.level.replace('_', ' ') }}</div>
  <p class="counts">
    {{ claim.unaided_demonstrations }} unaided demonstration{{ '' if
    claim.unaided_demonstrations == 1 else 's' }}{% if claim.assisted_demonstrations %},
    <span class="assisted">{{ claim.assisted_demonstrations }} assisted
    (does not count towards the level)</span>{% endif %}{% if claim.last_evidence_at %},
    most recently {{ claim.last_evidence_at }}{% endif %}.
  </p>
  {% if claim.evidence %}
  <ul>
    {% for item in claim.evidence %}
    <li><a href="{{ item.href }}">{{ item.statement }}</a>
        &mdash; {{ item.submitted_at }} ({{ item.mode }})</li>
    {% endfor %}
  </ul>
  {% endif %}
</section>
{% endfor %}

<footer>
  <p>{{ record.notes }}</p>
  <p>Issued by <strong>{{ record.signature.issuer }}</strong>, held by the learner.
     Signed with {{ record.signature.algorithm }}
     ({{ record.signature.key_kind }} key).</p>
  <p>Public key <code class="sig">{{ record.signature.public_key }}</code></p>
</footer>
</body>
</html>
"""

_env = Environment(autoescape=True)


def render_record(record: dict[str, Any]) -> str:
    return _env.from_string(TEMPLATE).render(record=record)
