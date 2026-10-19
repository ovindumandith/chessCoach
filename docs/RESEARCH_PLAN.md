# Research Plan

## Research question

Does evidence-backed, longitudinal student modelling produce better personalized chess coaching than (A) plain engine reports and (B) simple rule-based feedback?

## Systems compared

These all use the same game evidence.

| ID | System |
|---|---|
| A | Stockfish analysis only: critical moves, best lines, no personalization |
| B | Rule-based weakness profile with templated recommendations |
| C | Evidence-grounded student model with LLM-generated coaching |

## Sub-studies

1. **Taxonomy and classifier validity.**
   - Coaches annotate a benchmark of positions from several students using written guidelines.
   - Report precision, recall and macro-F1 for critical-move detection, tactical motifs and skill labels.
   - Report inter-annotator agreement (Cohen's κ) wherever two annotators overlap.
2. **History needed.** How do profile stability and agreement with coach judgement change as games per student go from 5 to 10, 20 and 50?
3. **Coaching quality.**
   - Blinded coaches rate outputs from A, B and C on chess correctness, evidence traceability, clarity, personalization relevance and exercise relevance (Likert scale plus pairwise preference).
   - Factual correctness is checked automatically by the validator.
4. **Learning effect (pilot).**
   - Compare exercise accuracy before and after on **unseen** positions.
   - Compare how often the targeted error type recurs in games played after the intervention.
   - With 10–30 students this counts as pilot evidence only.

## Metrics

- Classification: precision, recall, macro-F1, and calibration (reliability diagram, ECE) only where confidences are presented as probabilities.
- Coaching: validator pass rate, fabricated-reference rate, coach ratings, latency, tokens, and cost per lesson.
- Learning: change in exercise accuracy, and change in recurrence rate per 100 relevant opportunities.

## Data hygiene

- Splits are done **by student and by game**. Positions from one game never appear in both train and test.
- Studies that predict the future use temporal splits. Profiles are built only from games before the cutoff.
- Held-out games are never used as exercise sources.
- Every experiment records:
  - dataset version and game IDs
  - split
  - engine version and config
  - taxonomy and classifier versions
  - profile settings
  - prompt version and model ID
  - seeds
  - code revision (git SHA)
  - date
- Experiment configs live in `config/experiments/` and results in `data/experiments/`, which is not committed.

## Ethics

- Get consent from students, and from guardians if they are minors.
- Ratings are pseudonymized before analysis.
- Nothing is published without aggregation.
