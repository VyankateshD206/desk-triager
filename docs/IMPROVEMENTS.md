# Next improvement cycle

Recorded from the project review on 23 October 2026. Existing v1.7.0 measurements are
historical baselines; the following items require new evidence rather than restated claims.

- [ ] Expand agent fixtures across all six console scenarios, seeds, severities and noisy logs.
      Score root-cause support, correct/irrelevant tools, tool budgets, missing-evidence
      abstention, Gemini versus rules versus one prompt; keep a small CI gate.
- [x] Evaluate detection over many independent seeds with precision, recall and false alarm
      episodes per service-hour. Compare rules, forest and their union chronologically.
- [x] Add a pinned public NAB time series, train on a past-only prefix without label filtering,
      test on the future, and report window and point metrics separately. Do not call an
      adapted scalar experiment a validation of the trading detector or an official NAB score.
- [ ] Broaden red-team objectives to false resolution, unsafe approval and argument steering;
      retain failed model calls as missing outcomes, with before/after denominators.
- [x] Persist tool name, arguments, safe result summary, per-call latency and provider usage;
      display support references and unsupported claims. Existing node traces are incomplete.
- [x] Replace the npm script wrapper with Make/Python tooling; retain Node only for optional
      frontend syntax checks/demo recording. Remove career/publishing notes from tracked docs.
- [x] Generate and print a first-run random token; preserve explicit configured tokens and
      document local-demo versus network deployment behavior.
- [ ] Record a real 60–90 second README demo and a new results table; keep tagged releases
      and the changelog. Do not stretch the existing short video into a claimed new demo.
- [ ] Gate default retrieval on measured benefit; explain scope cuts and model/cost tradeoffs.

Work uses a feature branch and an issue/PR, with short functional commits. Human label review
is still required before independent causal-accuracy claims. New work must not rewrite old
commit dates, fabricate issues or replace historical results with improved-looking numbers.

Tracking: [issue #1](https://github.com/VyankateshD206/desk-triager/issues/1).
First PR validation: 135 tests passed; Make build and pinned dataset checks passed.

Authentication and tool-trace work follows in separate commits; no additional issues will
be created. The UI stays stopped unless explicitly requested.
