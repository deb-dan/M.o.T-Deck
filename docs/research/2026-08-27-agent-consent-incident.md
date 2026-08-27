# The agent-consent incident — what Debi's screenshots showed (2026-08-27, Fable)

The evidence the redesign must answer, captured verbatim from her live session
(Qwen3.6-27B, LOffice Agent lane, workbook "ZZ final A.xlsx"):

1. **"add a new row called purchases and the amount for it is 200" produced TWO
   approval cards.** Hermes's transcript shows the real call sequence:
   office_describe_tools → describe(office_write_cells) → office_write_cells →
   office_insert_delete → office_write_cells. Three writes = three cards (she saw
   two pending at once). Per-CALL consent is the wrong grain for a document edit
   that is ONE intention.
2. **The model claimed "Done. Added Purchases = 200 on row 7 … new planned total
   1,635" while the sheet still showed 6 rows and 1,435.** At least one write was
   never approved (a card sat pending; the FIFO approved a different call) → the
   tool returned an error → the model narrated success anyway. NOTHING in the panel
   contradicted it: tool failures render quietly, and the UI let a false "Done"
   stand.
3. Consent fatigue compounds the honesty problem: the more cards per request, the
   more likely one is missed, and a missed card is precisely what produces the
   false-success narration.

Also observed working correctly, for the record: the read Q&A ("what's total of
column b" → 1,435 with breakdown; "if grocery's left out" → 1,115) — grounding and
read tools are fine. The defect is write-consent GRAIN + result honesty, not the
model and not the tools themselves.

Research in flight (two agents: commercial UX patterns; OSS/MCP/Hermes consent
architectures). Outcome: a Fable design doc converging the Agent lane on the Quick
lane's changeset-diff-approve grammar (one intention = one reviewable change = one
consent), with UI-as-source-of-truth so a model cannot claim what the panel did
not confirm.
