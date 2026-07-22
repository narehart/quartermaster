<!-- Quartermaster certified output-tuning block, v1.
     Provenance: this EXACT text was the treatment in the certified experiment
     (bench/docs/PREREG_POWERED_TUNED.md; finding F9): n=150 on SWE-bench Live,
     cost-per-solved ratio 0.66 (95% CI 0.55-0.77), resolve rate identical
     (24.0% vs 24.0%). Pairs with MAX_THINKING_TOKENS=8000.
     Do not edit without re-benching - the text IS the technique. -->

# Working style for this repository

- Be maximally concise. No preamble, no narration of what you are about to
  do, no summaries of what you just did. Never restate file contents you
  just read.
- Read the MINIMUM needed: use grep/targeted searches first; read full files
  only for the file you are about to edit. Batch independent
  reads/greps/searches into a single message wherever possible.
- Make the smallest change that fixes the root cause. Prefer surgical edits
  over rewrites. Do not refactor, reformat, or improve unrelated code.
- Do not re-read files you have already seen unless they changed.
- When done, stop immediately. Do not write a closing summary.
