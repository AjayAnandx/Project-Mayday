- Prefer claims from the paper's own Methods, Results and Discussion over its Introduction or Related Work. When a paper states someone else's finding, set "entity" to who found it.
- For each claim about a study's result, add a "study" object (omit fields you cannot read in the text):
  {"design": "meta_analysis|systematic_review|rct|quasi_experiment|observational|benchmark|simulation|survey|qualitative|case_study|theory|other",
   "sample_n": "number of participants/items/runs", "population": "who or what was studied",
   "intervention": "treatment / method tested", "comparator": "baseline or control",
   "dataset": "dataset or benchmark name", "outcome": "what was measured",
   "effect": {"metric": "e.g. accuracy, odds ratio, BLEU, elasticity", "value": "12.4", "ci": "95% CI 10.1-14.7"},
   "p_value": "0.003", "limitations": "limitations the authors state"}
- Every number you put in "study" (sample_n, effect value, CI, p-value) must appear in the quote you give for that claim. Choose a quote that contains the numbers, or leave those fields out.
- Classify the design from what the paper did, not from what it cites.
