Below is a **phase‐by‐phase** breakdown of **what information each role (Developer, Owners, Speculators) sees** (or does **not** see) during the T-H experiment. Keep in mind that most actions involve only the **Developer** and **Owners** declaring their land values, whereas **Speculators** primarily observe declared values and trade either land or tax shares.

---

## 1. **Phase: “Presentation”**

- **All Players**  
  - See the **land layout** (who is Developer, who are Owners, where each property is located).  
  - See the **range** (minimum/maximum) of possible land values for each role (Owners and Developer) under both “No Project” and “Project.”  
  - Know **their own role** (Developer, one of the 5 Owners, or one of the Speculators).  
  - See a **timer** (how long this phase lasts).

- **Developer and Owners**  
  - **Privately** see their own **actual (real) property values** for “No Project” and “Project.”  
  - No one else sees these private draws.

- **Speculators**  
  - **Do not** see any specific land values or private values for Owners/Developer at this point; only see the global range of possible values for each role (e.g., Owner’s land can be between X and Y).

---

## 2. **Phase: “Declaration”**

- **Developer and Owners**  
  - Must each submit **two** declarations:  
    1. A declared value if **No Project** is ultimately chosen.  
    2. A declared value if **Project** is ultimately chosen.  
  - See a **prompt** with two input fields (one for “No Project,” one for “Project”) and a **tax calculator** showing how much tax (1% in this phase) they would pay if that outcome is chosen.  
  - See a **“value percentile”** indicator for each declaration they enter, telling them (privately) what fraction of the possible range is below their declared number. (For example, if you declare 120 when the possible range is 0–200, your percentile might be ~60% if 120 is above 60% of the range.)

- **Speculators**  
  - Do **not** declare anything.  
  - Do **not** see the Developer/Owners’ private land values or the actual declarations during this phase.  

- **Outcome of This Phase**  
  - The computer sums all **No Project** declarations (Developer + 5 Owners) and all **Project** declarations. The higher total determines which scenario is chosen (No Project vs. Project).  
  - All players **learn** which scenario won (Project or No Project) **after** this phase ends, but **not** the exact numeric declarations of the other players.

---

## 3. **Phase: “Speculation” (First Land‐Buying Opportunity)**

- **All Players**  
  - Now **know** which scenario (“Project” or “No Project”) was chosen.

- **Speculators**  
  - **See** for each plot (Developer’s and each Owner’s):  
    - The **declared value** relevant to the **chosen** scenario (only one of the two declarations now matters).  
    - The **value percentile** of that declaration (e.g., “Declared value is at the 70th percentile of possible real values”).  
  - **May buy** a plot at the declared price (the chosen scenario’s declaration).  
  - **Do not** see the *actual* real value, only the declared value and its percentile.

- **Developer and Owners**  
  - Know which scenario is chosen.  
  - See if **speculators** choose to buy their land. They will receive the purchase price immediately if bought.  
  - Typically **do not** see other Owners’ or Developer’s exact declarations (only their own). The interface does *not* reveal others’ numeric declarations to them, but it does reveal whether or not a speculator purchased a given property.

---

## 4. **Phase: “Market” (Trading Tax Shares)**

- **All Players** (Developer, Owners, Speculators) can trade **tax shares** in an open market. Everyone sees:

  1. **Public Signal** of the share’s likely final value (based on *initial* declarations, assuming they were accurate).  
  2. **Their Own Private Signal**: A noisy (±5%) estimate of the *true* share value if everyone declared their real values.  
  3. **Bid/Ask Lists**: Offers to buy (“bids”) and offers to sell (“asks”), plus the **price** associated with each.  
  4. **Market History**: Recent trades, the **median price** of the last seven trades, total time remaining, etc.  
  5. **Their Own** current **cash** balance and number of **tax shares** owned.

- **Developer** starts with 30 shares, each Owner with 6 shares, and each Speculator with 5 shares.

---

## 5. **Phase: “Final Declaration”**

- **Developer and Owners**  
  - Must enter a single **final declaration** for their property under the **already‐chosen** scenario (Project or No Project).  
  - See their own **real value** again (privately).  
  - See their **initial** declaration from Phase 2 (for reference) and can adjust it.  
  - A calculator shows them how much **33% tax** they will pay on whatever final value they declare.  
  - They see the **value percentile** of their new declaration (similar to the initial phase).  

- **Speculators**  
  - **Do not** participate in final declarations.  
  - Do **not** yet see these new final declarations. They see them only in the *next* phase (Final Speculation).

---

## 6. **Phase: “Final Speculation” (Second Land‐Buying Opportunity)**

- **Speculators**  
  - Now see for each plot (Developer’s or an Owner’s):  
    - The **final declared value** under the chosen scenario.  
    - The new **value percentile** (relative to the possible range).  
  - May decide to **buy** a plot at that **final declared value**. If they do, the original owner immediately receives that amount.  
  - Speculators either profit or lose half the difference between the *real* value and the *declared* value.

- **Developer and Owners**  
  - Do not see each other’s final numeric declarations in detail (the interface only shows each player’s own property details); however, they *will* see if speculators buy their land.

---

## 7. **Phase: “Results”**

- **All Players**  
  - See the **final outcome** for the round, including:  
    - Which scenario was chosen (already known).  
    - The **total tax revenue** (from 1% initial + 33% final declarations).  
    - How many **tax shares** they ended with and the **dividend** per share (tax revenue / 100).  
    - Their **speculation gains or losses** (if they bought/sold land).  
    - Their **net payoff** for the round (land value + speculation outcome + share dividends − taxes, etc.).  
  - After the Results screen, a new round begins (until all 6 rounds are completed).

---

### Summary Table of Key Information Flows by Phase

| **Phase**              | **Developer**                                                   | **Owners**                                                                            | **Speculators**                                                                                                        |
|------------------------|----------------------------------------------------------------|----------------------------------------------------------------------------------------|------------------------------------------------------------------------------------------------------------------------|
| **Presentation**       | Sees own real values (Project/No Project) + global ranges.      | Each sees own real values (Project/No Project) + global ranges.                       | Sees global ranges only (no private values).                                                                          |
| **Declaration**        | Declares 2 values (No Project / Project). Sees own real values. | Declares 2 values (No Project / Project). Sees own real values.                       | No declarations; does not see others’ declarations or real values yet.                                                |
| **Speculation** (1)    | Knows chosen scenario, sees if a speculator buys their land.     | Knows chosen scenario, sees if a speculator buys their land.                           | Sees **chosen** scenario’s declared value for each property + percentile. May buy land at declared price.             |
| **Market** (Tax Shares)| Public signal (same for all), private signal, current bids/asks.| Same info (public & private signals, market trades, their own shares/cash).           | Same info (public & private signals, market trades, their own shares/cash).                                           |
| **Final Declaration**  | Declares final value (chosen scenario). Sees own real value.     | Declares final value (chosen scenario). Sees own real value.                          | Does not see final declarations yet; does nothing in this phase.                                                      |
| **Final Speculation**  | Sees if any speculator buys land at final declared price.        | Sees if any speculator buys land at final declared price.                             | Sees final declared value (+ percentile) for each property. Can buy if under‐declared (or skip if over‐declared).      |
| **Results**            | Sees final payoffs, taxes, share dividends, speculation outcomes.| Sees final payoffs, taxes, share dividends, speculation outcomes.                     | Sees final payoffs, taxes, share dividends, speculation outcomes (own profits/losses and overall summary for the round).|

---

#### Important Notes

1. **Owners and Developer never see each other’s private real values**.  
2. **Owners and Developer do *not* generally see each other’s declarations** (either the numeric values or the exact percentile) in real time; they only see whether the **sum** of declarations caused Project or No Project to win, and they see if speculators purchased their property.  
3. **Speculators** see **declared values and percentiles** only for the scenario that ends up chosen, and only during the Speculation phases (initial and final). They never see anyone’s *true* land values.  
4. During **Market (tax shares)**, *everyone* sees the same **public signal**, has their own unique **private signal**, and can see the real‐time trades (bids/asks) posted by others.  
5. In the **Results** screen, *everyone* sees a summary of how much tax was collected, how many shares each person ended with, the share’s final dividend, and each player’s net earnings for that round.

These visibility rules create strategic uncertainty and drive the core incentives to **misreport** (inflating or deflating declarations) versus **speculate** on properties or tax shares in hopes of profiting from under‐ or over‐valuation.
