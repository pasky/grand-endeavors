# Five Grand Endeavors

Tracking humanity's progress in five grand endeavors --- our biggest ongoing R&D projects:

* Robots (and Automation overall)
* Rockets (and Space overall)
* Fusion (and Energy overall)
* Cancer (and Healthspan overall)
* Climate (and Environment overall)

The initial purpose of this project is using AI to automatically compose a regular trustworthy report to "the Board of Humanity" about major progress in these areas.

**Status:** Experimental draft.
* [x] We have a draft version of the endeavors definition and reporting structure. *(We expect to still iterate on it significantly based on early experience and feedback.)*
* [ ] *(work in progress)* We are piloting the reporting structure on a summary 2025 report.
* [ ] *(work in progress)* We are building an automatic report drafting harness.
* [ ] We have the weekly report cadence running.
* [ ] We have a reference list of sources to follow for each endeavor.
* [ ] We have a publishing infrastructure set up (most likely Substack and automated Twitter account).
* [ ] We have a drafting / feedback infrastructure for early expert reviews and errata.


### Manifesto

Science has a communication problem. It reports isolated discoveries (with applications often more of an afterthought), not progress towards the big outcomes. Thus, every week, we publish a newsletter updating humanity on the progress of science towards such outcomes — just as a company would report its progress to its board.

Scientific research is valuable even to its own end, but is largely expected to be the engine of material abundance. We track the needle on five Grand Endeavors that humanity has pursued for all its existence and that will also determine the quality of life for the next 100 years.

Each of the endeavors has a KPI assigned, as well as some key milestones and open challenges we need to solve. All of these may update and evolve over time, and are on purpose somewhat opinionated — they capture the current consensus rather than all perspectives. If the top experts' consensus shifts, we will shift. And we will report also on major progress of alternative approaches in each given area.

## Robots and Automation

Humans have been looking to automate their lives in one way or another for most of their existence. From early domesticated animals to microwave ovens and freighter ships, automation adds a huge multiplier on human labor — we can either do more with our time, or spend less time working. The current frontier is automating intelligence — the software (AI) and the hardware (robots).

### Software

**KPI:** 80-percentile METR task length equivalent (Human-hours)

**Milestone Countdown:**
*   **The Linux Kernel Patch:** An AI-submitted large (10k+ lines diff) patch to the Linux Kernel (or equivalent critical infra) is accepted by maintainers.
*   **The Nature Author:** An AI-generated research paper is accepted by a top-tier journal (Nature/Science) with AI credited as primary author.
*   **The $10M Solopreneur:** A single-person company reaches $10M ARR, proving AI capacity for complex economic agency.

**Major Open Challenges** (assuming "LLMs are enough" hypothesis)
*   **Reliability:** Reducing hallucinations and error compounding in long chains of reasoning.
*   **Agency:** Robust goal decomposition and self-correction over long time horizons.
*   **Continuous Learning:** Universal mechanism for rapidly adjusting long-term behavior based on past experiences.
*   **Novelty:** Consistently producing original connections beyond interpolations of existing knowledge.

### Hardware

**KPI:** Largest Active Commercial Fleet of General-Purpose Humanoids (Single Site)

**Milestone Countdown:**
*   **Robotaxi Saturation:** Autonomous robotaxis outnumber human-driven taxis in a major metropolitan area (L5 Transport Solved).
*   **The "Wozniak" Test:** Robot enters a random, previously unseen home and successfully makes a cup of coffee.
*   **The "Fukushima" Test:** Robot autonomously navigates a disaster zone and performs a critical repair (valve/switch) within human time limits.
*   **The "Blue Collar" Shift:** General purpose robot completes a full 8-hour shift in a real workplace (Construction, Factory, Logistics) working collaboratively alongside humans.

**Major Open Challenges:**
*   **Dexterous Manipulation:** Human-level hands requiring dense tactile sensing, compliant actuators, and real-time control across 10,000+ object types including deformables.
*   **Generalization:** Few-shot skill acquisition, robust task transfer across environments, recovery from unexpected failures, and long-horizon replanning without human intervention.
*   **Power/Efficiency/Cost:** Extending 1-2 hour runtimes to full 8-hour shifts via battery breakthroughs or radical actuator efficiency gains, at commercially viable price points.

## Rockets and Space

What child hasn't looked at the starry sky in wonder? The universe promises many worlds humanity could spread to — removing some eggs from the "one basket", a new age of discovery, making all raw materials cheap, and vast opportunities for community independence. And if nothing else, transport by orbital flights is the next best thing to teleportation, allowing you to reach the opposite side of the globe in 90 minutes.

**KPI:** Cost to LEO ($/kg)

**Milestone Countdown:**
*   **"The Deluge":** 100,000 tonnes delivered to orbit in a single year — the threshold to enable Mars colonization.
*   **"The Homestead":** Permanent crewed base operates 1+ year using local resources (Moon or Mars).
*   **"The Export":** Product manufactured in space is sold commercially on Earth (beyond novelty items).

**Major Open Challenges:**
*   **Radiation Shielding:** Protecting crew from cosmic and solar radiation during months-long deep space transits.
*   **Closed-Loop Life Support:** Years-long operation without resupply from Earth.
*   **ISRU at Scale:** Production-level extraction of fuel, oxygen, and materials from planetary resources.

## Fusion and Energy

Energy is the key limiting factor of the material world. It does not have to be. If all electricity bills go to zero, how does that change our lives, from heating (homes, iron or saltwater) to food, to travel, to compute? There are many short-term fixes, but the long-term approach is unlikely to be anything but nuclear fusion (and superconductors make everything easier).

**KPI:** Worldwide average electricity cost ($/MWh)

**Milestone Countdown:**
*   **"The First Watt":** First commercial fusion plant delivers sustained electricity to a public grid.
*   **"Grid Parity":** Fusion Levelized Cost Of Electricity falls below $100/MWh, competitive with gas.

**Tech Tree:**
*   **D-T Fusion** (easiest ignition, but 14 MeV neutrons + tritium breeding required)
    *   *General challenges:* tritium breeding (TBR>1) and neutron-resistant materials at scale
    *   *Magnetic confinement* (CFS, ITER, Zap Energy) — challenges: plasma stability, heat exhaust, materials survival
    *   *Inertial confinement* (NIF, First Light) — challenges: rep-rate (need 10 Hz), target cost ($50k→$0.10), driver efficiency
*   **Aneutronic Fusion** (D-He3, p-B11 — no neutrons/tritium, but 10× hotter, lower cross-section)
    *   Helion (D-He3, 2028 target), TAE (p-B11, early 2030s)
    *   Challenge: net gain at 1+ billion °C
*   **Deep Geothermal** (most viable mid-term fusion alternative)
    *   Quaise, GA Drilling — millimeter-wave/plasma drilling to 10-20 km

## Cancer and Healthspan

Some people long for immortality, others would just prefer not to die (or live a low-quality life) *yet*. The biggest symbol for fixing this is our journey to cure cancer, but the fight against other diseases such as Alzheimer's (or potential pandemics), as well as perfected early diagnostics, are just as important. And to achieve not just plain longevity, but long healthy lifespan, eventually we need to move further — to evolve our biology, not just fight off diseases.

**KPI:** Median country Healthy Life Expectancy (HALE) at birth (years) — currently ~72y (WHO 2021)

**Milestone Countdown:**
*   **Taming Cancer:** 80% of all solid tumor cases reach 10-year survival — metastatic cancer becomes a chronic, manageable condition.
*   **Precise Screening:** >50% of major non-communicable diseases (cancer, cardiovascular, metabolic, neurodegeneration) caught pre-symptomatic.
*   **Unbroken Mind:** Dementia prevalence (CDR ≥1) after age 80 falls below 5%.
*   **The Long Middle Age:** Validated interventions reverse ≥10 years of biological age (epigenetic clocks + functional biomarkers), with corresponding reductions in age-related disease incidence.

**Major Open Challenges:**
*   **Causal Model of Aging:** We lack a unified, predictive model explaining how molecular aging processes cause specific diseases — and which interventions safely extend healthspan without tradeoffs.
*   **Predictive Biomarkers:** Identifying reliable molecular signatures that detect disease years before symptoms across cancer, cardiovascular, metabolic, and neurodegenerative conditions — with sufficient specificity to avoid overwhelming healthcare with false positives.
*   **Safe In-Vivo Rejuvenation:** Resetting adult human cells via reprogramming, senolytics, or regeneration without inducing cancer, fibrosis, or loss of cell identity.
*   **Programmable Immunity:** Continuously monitoring and reprogramming the immune system over decades to prevent cancer, infections, and autoimmunity without breaking tolerance.
*   **Brain Preservation:** Maintaining cognition and identity for 100+ year lifespans despite protein aggregates, vascular damage, and neuron loss — repair at scale, not just slowing decline.

## Climate and Environment

This endeavor is unlike the other four, as it is about fixing the past rather than improving the future. A hundred years ago, we would have been talking about terraforming Sahara and Antarctica, but humanity messed up the Earth. Many historic civilizations fell to climate change, and we now have to clean up our mess if we are to survive into a better future.

**KPI:** Atmospheric CO₂ concentration (ppm) and 10-year trend (ppm/year)

**Milestone Countdown:**
*   **"The Bend":** Year of peak global greenhouse gas emissions is definitively behind us.
*   **"The Balance":** Global net anthropogenic greenhouse gas emissions reach approximately zero.
*   **"The Ceiling":** Peak warming held below +2°C.

**Major Open Challenges:**
*   **Net-Zero Transition:** Balancing carbon flows across energy, industry, agriculture, and transport — through both emissions reduction and enhanced biological/geological uptake.
*   **Permanent Removal:** Capturing and storing billions of tons of CO₂ per year durably at viable cost.
*   **Sunlight Management:** Developing and safely governing solar radiation management complementing the other two challenges.

## Supplemental

### The Knowledge Beyond

A great enabler for the future is deep understanding of our universe and the ability to manipulate it on a fine scale. Paradigm-breaking technologies like quantum computing and nanomachines, as well as new theoretical research, may not impact any of the great endeavors directly, but they will reframe everything in the long run.

### Society and Cohesion

As humanity progresses in its great endeavors, many challenges await our society. To survive into the future, we must pass the great filters — avoid wiping ourselves out with weapons of mass destruction, align our robots (align with *what*?) and learn to coexist with them (a new alien intelligence), as well as keep humans in some relationships with one another and the physical world. Meanwhile, trust is breaking, alienation and polarization are growing, and simulacra are getting more attractive than the real world. But society can adapt — 40 years ago, "open source" wasn't really a concept, but we fought off massive corporate capture and it now underpins vast areas of technology and knowledge (think: Wikipedia). What are the next philosophy, sociology, and social technologies best serving humanity's future?
