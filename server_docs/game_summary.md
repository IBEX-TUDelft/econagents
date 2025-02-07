**Summary of the Experiment (T-H)**

In this experiment, each participant is assigned one of three possible roles—**Developer**, **Owner**, or **Speculator**—and keeps that role throughout all 6 rounds (the first round being a practice round). The key objective is to decide whether a **Project** will be developed and to handle related taxes, property declarations, and speculation.

Below is an overview of each step in a round (excluding the practice round):

---

### 1. **Roles and Setup**

- **Developer (1 person)**: Owns the plot of land where the Project may be built.  
- **Owners (5 people)**: Own various plots of land that can be affected (negatively) by the Project.  
- **Speculators (up to 6 people)**: Do not own land initially but can profit (or lose) by buying undervalued (or overvalued) land from Owners/Developer.  
- **Tax Shares**:  
  - The Developer starts with 30 shares, each Owner with 6 shares, and each Speculator with 5 shares (for a total of 90 shares in the market).  
  - A share’s value depends on the total tax revenue collected in the round.

- **Payoffs**: One of the final 5 (non-practice) rounds is picked at random to determine each participant’s cash payment, after converting their “points” into Euros via role-specific exchange rates.

---

### 2. **Phase: “Presentation”**

1. You see a map of the land, your role (Developer/Owner/Speculator), and the range of possible **real values** of each plot (with or without the Project).  
2. If you are an **Owner** or the **Developer**, you see your own private real-value draws for both the “No Project” scenario and the “Project” scenario.  
3. Speculators do **not** see these private values but will later see participants’ **declared** values.

---

### 3. **Phase: “Declaration”**

1. **Owners and the Developer** each submit two declared values for their land:
   - **Declaration if “No Project”** is chosen.  
   - **Declaration if “Project”** is chosen.

2. **Choosing the Scenario**:  
   - The computer **sums** all “No Project” declarations and all “Project” declarations.  
   - Whichever total is **higher** determines whether the Project happens or not.  
   - For example, if the sum of the declared “Project” values is higher, the Project is implemented; otherwise, “No Project” is chosen.

3. **Initial Tax Payment (1%)**:  
   - Owners and the Developer pay **1% tax** on **their declared value** for whichever scenario is chosen.  
   - (No tax is paid on the scenario that is *not* chosen.)

4. **Value Percentile**:  
   - As Owners/Developer enter declarations, the system shows what percentile that declaration is within the possible range (e.g., if it’s in the 70th percentile, it’s higher than 70% of all possible values).  
   - This percentile is visible to Speculators later.

---

### 4. **Phase: “Speculation” (First Round of Buying Land)**

1. **Speculators** see:  
   - The **chosen scenario** (Project or No Project).  
   - Each plot’s **declared value** (for the chosen scenario).  
   - The **value percentile** (how high/low that declaration is relative to possible real values).

2. **Buying Land**:  
   - A Speculator can choose to buy one or more plots at the *declared price*.  
   - The original landowner (Developer or Owner) immediately receives the sale proceeds.  
   - At the end of the round, the land automatically reverts to its original owner at a price equal to the **average** of:
     - The owner’s **real value**  
     - The **declared value**  
   - **Profit/Loss for Speculator**: Gains (or loses) half the difference between the real value and the declared value.  
   - **Cost to Original Owner**: They lose half of the difference (if any) between real value and declared value if the declared value was below the real value. Conversely, the Speculator loses if the declared value was higher than the real value.

3. Speculators can also **opt not to buy** to avoid risk (earning 0 from speculation).

---

### 5. **Phase: “Market” (Trading Tax Shares)**

1. **All players** (Developer, Owners, Speculators) can trade the **tax shares** in an open market.  
2. The **value** of each share depends on the **total final tax** collected later.  
3. **Public Signal**: Everyone sees a public (approximate) forecast of each share’s value, based on initial declarations (assuming they were “real”).  
4. **Private Signal**: Each player also receives a *personal* noisy signal about the share value.  
5. **Bids/Asks**: Players can post “asks” (offers to sell at a certain price) or “bids” (offers to buy at a certain price), and they can accept or remove offers in real time.  
6. This trading lasts for **4.5 minutes**.

---

### 6. **Phase: “Final Declaration”**

1. The Developer and Owners again declare the **value** of their land under the **chosen** scenario (Project or No Project).  
2. This time, they pay a **33% tax** on whatever final value they declare.  
3. The final declared value can be different from the initial declaration.  
4. The Speculators see these new declarations in the next phase.

---

### 7. **Phase: “Final Speculation” (Second Round of Buying Land)**

1. Similar to the earlier speculation phase, **Speculators** can buy plots at the **final declared price** for the chosen scenario.  
2. The same automatic resale mechanism applies (speculator gains or loses half the difference between the real value and the final declared value).

---

### 8. **Phase: “Results”**

1. The experiment calculates **final payoffs** for the round:
   - **Property Values** (for Owners/Developer, with or without the Project), minus any speculation losses or plus speculation gains.  
   - **Tax Payment** (1% of the initial declaration + 33% of the final declaration, whichever scenario was chosen).  
   - **Speculators’** gains/losses from buying/selling land.  
   - **Tax Share Dividends**: Each share you hold is worth 1/100 of the **total tax revenue** collected from all declarations.  
2. After viewing the results, a new round begins until all 6 rounds are completed.  
3. One of the final 5 rounds is chosen at random for actual payment in cash.

---

### 9. **Final Payment**

- After the last round, you see your **total points** and the **Euro amount** (converted via your role-specific exchange rate).  
- A **show-up fee** is added to your final payment.  
- You fill out a final receipt with your payment token before collecting your payment.

---

### Key Takeaways

1. **Which Scenario Is Chosen?**  
   Determined entirely by the **sum of declarations** (“No Project” vs. “Project”) from the Developer and Owners.

2. **Taxes:**  
   - **1%** tax on initial declaration (only for the chosen scenario).  
   - **33%** tax on final declaration (again, only for the chosen scenario).

3. **Speculation:**  
   - Occurs **twice** (after the initial declaration and after the final declaration).  
   - Speculators profit if they buy land that turns out to be **undervalued** by its owner’s declaration (and vice versa).

4. **Tax Shares:**  
   - All participants start with some number of shares.  
   - Shares pay dividends based on **total tax** collected from final declarations.  
   - The share-trading market allows players to buy or sell shares at prices determined by supply and demand, guided by public and private signals.

By combining **declarations, taxation, speculation,** and **share trading,** this experiment explores how participants strategize about property values and tax liabilities, and how speculators attempt to profit from discrepancies in declarations.
