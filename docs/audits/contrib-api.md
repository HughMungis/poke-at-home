- **Lines 2961 and 572–573 — Game selection is ignored when assigning trusted evaluation work.** `eval-next` accepts `X-Train-Game`, but `_contrib_next_job()` always selects the default game. Results are subsequently stored under the header-selected game at line 3000.
  
  **Trigger:** Send authenticated `GET /api/train/eval-next` with `X-Train-Game` set to a valid non-default game. Evaluate the returned default-game checkpoint, then submit it to `POST /api/train/eval-result` with the same header. The default-game score is stored in the other game's history. If checkpoint basenames coincide, it is attributed to that game's unrelated checkpoint.

- **Lines 2998 and 3073–3086 — Accepted upload names and stored result names can identify different checkpoints.** Uploads permit filenames longer than 120 characters, while result submission silently truncates them to 120 characters. Distinct uploaded checkpoints can therefore acquire the same scoring identity.
  
  **Trigger:** Let `P` be 116 `a` characters followed by `.zip`—exactly 120 characters. Upload distinct checkpoints named `P` and `P + "b.zip"` using authenticated `POST /api/train/upload`. Submit an evaluation for the second filename. Its stored checkpoint name becomes `P`, attributing its score to the first checkpoint.

- **Lines 3016–3020 — Repeated result submissions count the same evaluation multiple times.** Every submission appends a new entry; there is no evaluation identifier or replay check. An ordinary retry after a lost response duplicates scoring evidence.
  
  **Trigger:** Send authenticated `POST /api/train/eval-result` with `{"checkpoint":"model.zip","runs":1,"budget_min":60,"per_run":[{"badges":1}]}`. Repeat the identical request five times. The history contains five copies of one run, which can satisfy the stated five-run promotion bar without five independent evaluations.
