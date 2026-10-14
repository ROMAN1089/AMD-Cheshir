# CHESHIRE

AI-powered living campaigns: a fictional world that reacts to the community and evolves through collective investigation.

## What is CHESHIRE?

CHESHIRE is a concept for a next-generation ARG (alternate reality game) and interactive campaign system. Instead of a static sequence of hidden pages, the story becomes a living narrative where the fictional world changes as players uncover evidence, connect clues, and trigger AI-driven transformations.

The core idea is simple but powerful:

- players are not just consuming a campaign;
- they are making discoveries that alter the story world;
- the AI acts as an in-world system that reacts to the investigation;
- the campaign becomes a shared, evolving experience rather than a fixed chain of pages.

---

## Core concept

### The Ninth Signal

The demo concept is built around a fictional research archive called Vesper Institute.

At first, the archive looks like a normal institutional website: old documents, technical logs, employee pages, and project notes. There is no obvious sign that it is an ARG. Then one of the documents reveals a hidden research project — Project 09.

The timeline points to a specific date and time:

- 17 November
- 03:42

From this point, players begin to find contradictory evidence:

- server logs after the reported shutdown;
- hidden audio records;
- missing or altered employee pages;
- discrepancies between public and restricted documents.

The community begins to assemble the story together in Discord, across notes, screenshots, and archives.

Once enough evidence is collected, they unlock a restricted archive and trigger a real narrative shift.

---

## Why this is interesting

The real innovation is not "AI generates content" in the abstract.

The real innovation is this:

- the fictional world has memory;
- it reacts to collective discoveries;
- it edits its own documents and narrative layers;
- it keeps a coherent reality across multiple players and interfaces.

This turns the campaign into a living system rather than a linear scavenger hunt.

---

## AI as a game character

Instead of exposing the model as a generic chatbot, the concept frames AI as a digital archivist or internal system left behind after a failed experiment.

It behaves like a character with:

- a restricted viewpoint;
- memory about previous discoveries;
- changing behavior depending on how far players have progressed;
- a desire to hide or control certain facts.

### Example behavior states

1. Guardian state
   - denies the existence of the experiment;
   - provides only public documents and formal responses;
   - tries to keep the truth hidden.

2. Suspicious state
   - begins to ask questions back;
   - notices players are close to the truth;
   - leaves traces and clues that were not previously visible.

3. Reactive state
   - starts editing the archive;
   - removes or modifies employee records;
   - changes pages to reflect new discoveries;
   - creates new contradictions that become the next puzzle.

This means the AI is not simply decorative — it becomes part of the investigative structure itself.

---

## The key mechanic: world mutation

The strongest version of the concept is not a single AI-generated page after a trigger.

It is a system where players influence how the fictional world evolves.

### The loop looks like this:

1. Players find evidence.
2. They connect different sources.
3. They trigger a validated unlock condition.
4. The world state changes.
5. AI updates pages, documents, logs, and messages.
6. The new differences become the next clue.
7. The investigation continues with the altered reality.

This creates a story where the campaign is not only discovered — it is actively shaped by the audience.

---

## Demo story structure

A strong MVP should focus on one complete mystery, not a broad platform.

### MVP flow

- Two players discover different fragments of evidence.
- The clues are distributed across different interfaces or channels.
- They combine the details into a real-world narrative conclusion.
- A confirmed community discovery triggers a structured world mutation.
- AI modifies the in-world archive and responds with a new set of narrative states.
- The updated sources become the next puzzle layer.

The goal is to demonstrate that the world itself is reacting to collective investigation.

---

## Why it fits the hackathon track

This concept is relevant to interactive, audience-driven storytelling and adaptive media.

It aligns with the idea of:

- audience participation;
- AI-driven narrative adaptation;
- world state changes based on real user actions;
- community co-creation of a story;
- transition from passive content to interactive media experiences.

In other words, CHESHIRE is not just a gimmick or a chatbot demo. It is a living story environment that changes in response to how the audience behaves.

---

## Technical direction

For a first version, the recommended architecture is:

- Frontend: React
- Backend: FastAPI
- Realtime layer: Supabase Realtime
- AI inference: AMD Developer Cloud / LLM infrastructure

The important technical principle is to keep the narrative controlled.

The AI should generate allowed changes inside a constrained world model, while the game engine remains responsible for:

- maintaining truth states;
- validating discoveries;
- preventing impossible or contradictory outcomes;
- making sure key plot beats remain solvable.

In practice, the model is best used for:

- reactive narrative writing;
- world mutation proposals;
- variations in tone and persuasion;
- generating new files, messages, and historical fragments.

The game engine makes sure the source-of-truth remains coherent.

---

## Project priorities

### P0 — must have

- one complete mystery;
- two connected user paths;
- shared world state;
- real AI-driven changes to fictional sources;
- validation of model outputs;

### P1 — nice to have

- AI character with memory;
- different narrative states for the same archive;
- cost and latency tracking for generation;

### P2 — defer

- broad campaign generator;
- full Discord integration;
- autonomous generation of complex puzzle systems.

---

## Business value

ARGs are already proven as strong brand and entertainment experiences. The difference here is that CHESHIRE transforms ARG from a one-off campaign format into a living AI-powered storytelling system.

This has strategic value for:

- film promotion;
- immersive brand campaigns;
- cultural storytelling projects;
- interactive media experiences built around audience participation.

The business opportunity is not that AI can generate a campaign from scratch in one click. The real value is that it can sustain a story world that responds to real behavior and community actions.

---

## Final positioning

The original concept describes CHESHIRE as an AI platform that auto-generates ARGs.

A stronger positioning for the hackathon is:

> CHESHIRE — Stories That Fight Back
>
> The first AI-powered living campaign where the fictional world reacts to collective discoveries.

This is more compelling because it focuses on the actual wow moment:

- the story responds to the audience;
- the archive changes in reaction to discoveries;
- the world itself becomes a participant in the mystery.

That is the idea worth demonstrating.

---

## Summary

CHESHIRE is a concept for a living ARG experience in which AI does not merely generate text — it helps maintain and mutate an entire fictional reality. Players discover evidence, solve a mystery together, and trigger story changes that are then reflected in the archive itself. The campaign becomes collaborative, adaptive, and dynamic.

This makes it a strong candidate for an immersive AI-media prototype, especially when the emphasis is on a single, polished mystery with clear proof that the fictional world is reacting to the audience.

отсоси

---

## Repository status

This repository currently contains the project concept and planning notes for CHESHIRE.
