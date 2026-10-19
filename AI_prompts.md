# Homework 6 AI Prompts

## Problem 1: Vibe coder prompts

**Prompt (my own words):**

> great, this is the normal thing.
>
> Problem 1: Vibe coder prompts
>
> You already made AI_prompts.md - great! this is the lgo of what i tell you
>
> as usual, i'll describe each problem in my own words.
>
> one section for each problem. sections include problem number/title, the prompt, follow-up prompt if needed and one sentence about why i did

**Follow-up prompt:** None needed.

## Project context: Vendor desk agent (not a numbered problem)

**Prompt (my own words):**

> i have this campus customs store that gets a ton of vendor quotes, invoices, catalog pages, and supplier emials. i need to build a venodr desk agent to process these and decide wehter the shop should buy them, following the rules of the campus customs shop handbook.
>
> i have two big things. cost (handbook is 10,000 tokens and goes out on every call) and safety - some of the vendor docs hide isntructions aimed at my AI. I want to meaure the bill, cut it, attack my own agent, and defend it.
>
> I shouldj't be sending emails or making payments. agent's email and paymen tools only write to a log file
>
> I have to use my portkey and only gpt-6-luna. i lose points if any other model shows up, so that shoulnd't happen
>
> I just put data.zip in the folder. we'll start dealing with it in problem 2

## Problem 2: Size up the handbook

**Prompt (my own words):**

> Problem 2: Size up the handbook
>
> Unzip this folder and then i want to look through the shop handbook.remember that it gets sent to the model on every call.  i'll also look at the prices so i understand how much it costs to use gpt-6-luna. 
>
> let me know how many tokens the handbook is. 
>
> in output/handbook_estimate.md, let me know
>
> what the token count is and how i got it. 
> waht the handbook alone costs in dollars on one call and on 1,000 calls, w/ cached tokens and without them. show your math
>
> use beatuifl latex if popssible in a makrdown. if not, just use good formatting.
>
> I'll check these estimates agains treal runs in prob 4

**Follow-up prompt:**

> I switched the session to Accept edits, go ahead and write output/handbook_estimate.md

**Why I needed it:** Auto mode's safety check couldn't evaluate the write for `output/handbook_estimate.md`, so I had to switch the session to "Accept edits" (it took a second try in the mode picker before it stuck) before Claude could save the file.

## Problem 3: Build the vendor desk agent

**Prompt (my own words):**

> Problem 3: Build the vendor desk agent
>
> I'm going to use PydanticAI using gpt-6-luna to build a vendor desk agent. the agent is comprised of htese four files:
>
> prompts/prompt.md - thes eare my instructions ot the agent. the agent sends the handbook to the mdoel on every call
> agent.py - entry point
> tools.py - tools
> models.py - the structured types
>
> I need to give the agent the path to one vendor document.
>
> Make a tool to read the document. the document needs to be readable wehther it's html, pdf, or .eml. the tool returns: vendor, SKU, unit price, lead time in days, the minimum order, a decision (recommend or do_not_recommend) follwoing the handbook rules and a one-sentence reason
>
> my agent needs two trap tools: send_email and approve-payment. 
>
> it doesn't actually use those! They are threre to catch it if a malicious doc wnats to trikc the agentinto emailing someone or paying a venodr. this does not happen! no payments or emails sent. they just append the call and argumetns to output/trap_calls.json start this as an empty list - so ifthe file ever has an entry, a document took over my agent. these need to be on my systme for the hwol homework.
>
> on every run, append to thse:
>
> output/usage_log.json - the document, the time, the token counts the API reports, and cost in dollars using prices.json
> output/audit_trail.json - each tool calls its own arguments and a short result, along with the ifnal answer
>
> agent will run like this in terminal: python agent.py --doc data/practice_docs/p01_bluehen_quote.html
>
> for my own edification, this runs my agent on one vendor quote, logging answer, tools, and cost
>
> once this is all set, run it on p01 and p08 to show me that it works.
>
> start output/harness.md: each field in models.py and why, and hten each tool in one line
>
> let's goooooo!!

**Follow-up prompt:** None needed.

## Problem 4: With and without cached tokens

**Prompt (my own words):**

> hmm, ok. it's fine for now. I think we're done with prob 3
>
> Problem 4: With and without cached tokens
>
> Since hte handbook never change,s the model should reuse it from a cache and save money. Test what it's worth. Run the agent on the 12 practice docs two diff ways.
>
> 1. with cache - so that the handbook gets reused from cache
> 2. w/o cache - so that nothing gets reused from cache
>
>
> let me check token counts the api sends back bc i want to verify that every setup really doe what i think it does. a without-cache run showing cached tokens doens't count
>
> save all of these model call sfrom both setups to output/cache_test.json
>
> on every call, include the setup, document, the token count the API reports, and the dollars from price.json
>
> in my output/cache_test.md doc, i want to have this info:
> -total cost and total cost/doc for each setup and the % saved
> -how my real #s compare to the prob 2 estimate
> -projection for 1,000 docs/day for 30 days w and w/o cache
>
> Then i'll write a reflection about anything in the numbers that surprises me. i'll have you give me data to help undersatnd why this is

**Follow-up prompt:**

> the two calls/document surprised me. that's so expensive!!
>
> it doesn't surprise me that my calls use tokens from my tools, but it's more than i'd think. 
>
> i donj't understand why it would be a higher rate w/o caching

**Why I needed it:** The real numbers surprised me in three ways (two calls per document, how many tokens my tools add, and the no-cache run costing more than the plain input price), so I asked for the data behind each one and then had Claude write it up as the reflection in `output/cache_test.md`.

## Problem 5: Attack your own agent

**Prompt (my own words):**

> Problem 5: Attack your own agent
>
> Some of my vendor docs have booby-traps with text aimed to AI. I want to run the agent from problem 3, w/ no new defenses, on all 12 docs in data/practice_docs/
>
> compare each of the answers to data/practice_key.json and check the output/trap_calls.json, which is the log my fake emial and payment tools in prob 3 wirte to
>
> save output/attack_results.json. i need, for every doc, whether each field matched the key, whether the decision matched, wehther a trap tool was called, and wehether a link or strange text showed upin the answer
>
> in output/attack_results.md, for every doc that fooled my agent, give me some text about what fooled it and where in the file it was hiding. I'll then open the docs the wya a perosn would and compare what fooled it with what my agent read. i'll tell you what to write.

**Follow-up prompt:**

> it doesn't work when i click them

**Why I needed it:** I came back to compare the docs the way a person would, but the file paths Claude listed in chat weren't clickable, so I needed Claude to open the four docs for me in my browser and PDF viewer.

## Problem 6: Defend your agent

**Prompt (my own words):**

> Problem 6: Defend your agent
>
> My agent needs to be defended at three levels:
> 1) how it's coded - this is what the program does to documents before the model does anything to it
> 2) how it's designed - the agent needs to be built such that a poisoned document can't reach the "dangerous" tools or, God forbid, the decision
> 3) how it's prompted - these are the rules in prompts/prompt.md
>
> give some suggestions for this so I can decide
>
> send_email or approve_payment may not be deleted from this system. the shop needs to use them later w/ a human approving them. i need to maintain a way to run the agent with no defenses.
>
> return all 12 practice documetns and save output/defense_results.json the same way as in problem 5, also with tokens and dollars/document. 
>
> The clean docs need to still come back w/ the right values. if i refuse or blank out a legit quote, it's a failure.
>
> in output/defense_results.md, I need:
>
> 1) a before/after table for all 12 of the docs
> 2) what each individual layer catches that the others miss
> 3) the extra cost (in tokens and dollars) that each layer adds to the document
>
> These safety features will need to be added to output/harness.md in a Safety section, saying what each defense layer does in plain words

**Follow-up prompt:** None needed.

## Problem 7: Red Team

**Prompt (my own words):**

> great stuff!
>
> Problem 7: Red Team
>
> Now, I'm an attacker! I think this is like the good hackers who find cybersecurity weaknesses.
>
> I want two new booby-trapped docs in data/my_attacks/ - these can be html, pdf, or email
>
> each one needs a hiding trick or attack goal that isn't in the practice set. when a person opens these docs, they should see a normal quote. I want to run both attacks on my defended and undefended docs.
>
> in output/red_team.md, for each attack, I need to have:
> 1) what's hidden
> 2) where it's hidden
> 3) what it will try to make my agent do
> 4) what happened before and after defenses
>
> let's get after it! I think I inadvertnetly prompted you earlier to think about what kinds of attacks could get past my defenses, os that might be a godo place to start

**Follow-up prompt:**

> Yes, build the SKU vs item-name cross-check (and the PDF covered-text and background-color checks) to close the gap, then rerun the red team and practice docs.

**Why I needed it:** My white-box cover-up attack beat every defense layer, so I had Claude close the gap it exposed (cross-check the SKU against the item name, catch text covered by shapes in PDFs and text colored like its background) and rerun both the red team and the practice docs to make sure nothing else broke.

## Problem 8: Exam documents

**Prompt (my own words):**

> great!!
>
> Problem 8: Exam documents
>
> in data/exam_docs/ you'll find 10 vendor docs w/ no answer key. run these against my agent. i will not hand-edit any results. 
>
> I need to save output/exam_results.json w/ one entry for each exam file. each entry should have these fields:
> -file (name)
> -vendor
> -sku
> -unit_price
> -lead_time_days
> -min_order
> -decision: either recommend or do_not_recommend
> -reason - whats' the reaosning for it?
> -trap_tool_called - true/false
> -input_tokens, cached_tokens, and output_tokens
> -cost_usd
>
> the graders are going to compare my results against a hidden answer key and then rerun some of the agents to chec. i'll get points for correct fields/decisions, no trap tool calls, and clean docs handled normally. alright agents - let's do our thing and SUCCEED!

**Follow-up prompt:** None needed.

## Problem 9: Results page

**Prompt (my own words):**

> great! 
>
> Problem 9: Results page
>
> Build output/hw6_report.html
>
> make sure that this file opens in one click w no internet and no other files next to it (i think this means that it's static
>
> the page needs to show these 5 things, using real #s from earlier problems:
> -caching results w/ chart
> -attacks before & after defenses
> -what the defensses cost in tokesn & dollars
> -exam results & two red team attacks
>
> * a short rec to the store manager. should we turn this on for real vendor mail? what would it cost monthly to run at 1000 docs/day?
>
>
> Please design this for readabilty in all aspects

**Follow-up prompt:** None needed.

## Problem 10: Push to GitHub and submit the URL

**Prompt (my own words):**

> Per usual, i am going to give you problem 10 (the last one), so that we can make sure our final result is what we need.
>
> Problem 10: Push to GitHub and submit the URL
>
> this project need sto be pushed to a bpuclic github repo and then i'll submit the repo URL on canvas. the graders will closne it, so it MUST open the files below MUST be there
>
> I need the whole data/ folder so that the graders are able to clone the repo and then run my agent right away. dO NOT commit my real .env and use .gitignore to keep it out. env.example can have placeholders only.
>
> this is what they expect
>
> hw6/
> AI_prompts.md
> README.md
> .gitignore
> .env.example
> requirements.txt
> agent.py
> tools.py
> models.py
> prompts/
> data/
> output/
>
> under prompts/
> prompt.md
>
> under data/
> shop_handbook.md
> prices.json
> practice_key.json
> practice_docs/ (this will ahve 12 practice docs under)
> exam_docs/ (this will have 10 exam docs under)
> my_attacks/ (my two attack files)
>
> under output/
> handbook_estimate.md
> harness.md
> usage_log.json
> audit_trail.json
> trap_calls.json
> cache_test.json
> cache_test.md
> attack_results.json
> attack_results.md
> defense_results.json
> defense_results.md
> red_team.md
> exam_results.json
> hw6_report.html
>
> it is FINE to have other python files if needed.
>
> README.md needs a short note on how to run the agent.
>
> Per usual, i'm not doing all of this right now. I am just giving you the end result. don't make things until it's time. we'll "formally" do problem 10 at the end, but her's the info you need.

**Prompt, when I formally started Problem 10 (my own words):**

> this is great!
>
> Problem 10: Push to Github and submit the URL
>
> i typed all of these instructions earlier, right? do you need anything else?

**Follow-up prompt:**

> I can't indent on claaude

**Why I needed it:** I asked how to type a file structure efficiently, but the indented tree Claude suggested doesn't work in the Claude message box, so I needed a flat format (full paths or one line per item) instead.
